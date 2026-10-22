"""Offline tests for skysoftly.youtube: the HTTP layer is replaced by a fake, nothing touches Google."""
import base64
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import time
import urllib.parse

import pytest
import requests
from PIL import Image

from skysoftly import youtube as yt


# ----------------------------------------------------------------------------- fixtures

class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Config, token and queue all live in tmp_path; no real sleeping; no real network."""
    cfg_dir = tmp_path / "config"
    monkeypatch.setenv("SKYSOFTLY_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("SKYSOFTLY_YT_QUEUE", str(tmp_path / "out" / "youtube" / "queue.json"))
    monkeypatch.setattr(yt, "_sleep", lambda s: None)

    def no_network(*a, **k):
        raise AssertionError("unexpected network call")
    monkeypatch.setattr(requests, "request", no_network)
    cfg_dir.mkdir()
    (cfg_dir / "youtube_client_secret.json").write_text(json.dumps({"installed": {
        "client_id": "cid.apps.googleusercontent.com", "client_secret": "csecret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"]}}))
    (cfg_dir / "youtube.json").write_text(json.dumps({
        "client_secret": str(cfg_dir / "youtube_client_secret.json"),
        "shop_url": "https://example.com/shop", "timezone": "Europe/London"}))
    return tmp_path


def logged_in(expires_in=3600):
    yt._write_private(yt.token_path(), {"access_token": "AT-old", "refresh_token": "RT",
                                        "expires_at": time.time() + expires_in})


@pytest.fixture(scope="session")
def tiny_video(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    out = d / "drift.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
                    "-t", "2", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


def nightly_folder(root, date="2030-01-15", tiny=None):
    d = root / "nightly" / "boulder" / date
    d.mkdir(parents=True)
    (d / "episode.json").write_text(json.dumps({"slug": date, "date": date, "title": f"Boulder: {date}",
                                                "duration_s": 255, "summary": "Moon and Saturn"}))
    (d / "sky.json").write_text(json.dumps({
        "place": {"name": "Boulder", "tz": "America/Denver"}, "date": date, "look_time": f"{date}T19:30-07:00",
        "moon": {"extra": {"phase": "Waxing Gibbous", "illumination": 88.4}},
        "planets": [{"name": "Saturn", "status": "up"}, {"name": "Venus", "status": "hidden"}],
        "zenith_constellation": "Cygnus", "meteors_active": []}))
    if tiny:
        (d / "episode.mp4").write_bytes(tiny.read_bytes())
    return d


# ----------------------------------------------------------------------------- OAuth

def test_pkce_pair():
    v, c = yt.make_pkce()
    assert 43 <= len(v) <= 128 and re.fullmatch(r"[A-Za-z0-9._~-]+", v)
    expect = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert c == expect and "=" not in c
    assert yt.make_pkce()[0] != v


def test_authorization_url_and_loopback():
    client = yt.load_client_secret()
    port = yt.free_port()
    url = yt.authorization_url(client, f"http://127.0.0.1:{port}", "CHAL", "STATE")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["redirect_uri"] == [f"http://127.0.0.1:{port}"]
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"] == ["CHAL"]
    assert q["scope"] == ["https://www.googleapis.com/auth/youtube.upload"]
    assert q["access_type"] == ["offline"] and q["state"] == ["STATE"]


def test_web_client_rejected(isolated):
    p = isolated / "web.json"
    p.write_text(json.dumps({"web": {"client_id": "x"}}))
    with pytest.raises(yt.YouTubeError, match="Desktop app"):
        yt.load_client_secret(p)


def test_exchange_saves_token_mode_600(monkeypatch):
    seen = {}

    def fake(method, url, data=None, **k):
        seen.update(data)
        return FakeResponse(200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 3599})
    monkeypatch.setattr(requests, "request", fake)
    yt.exchange_code(yt.load_client_secret(), "CODE", "VERIFIER", "http://127.0.0.1:5555")
    assert seen["code_verifier"] == "VERIFIER" and seen["grant_type"] == "authorization_code"
    p = yt.token_path()
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert json.loads(p.read_text())["refresh_token"] == "RT"


def test_token_refresh_when_expired(monkeypatch):
    logged_in(expires_in=-10)
    calls = []

    def fake(method, url, data=None, **k):
        calls.append(data)
        return FakeResponse(200, {"access_token": "AT-new", "expires_in": 3600})   # no new refresh token
    monkeypatch.setattr(requests, "request", fake)
    assert yt.access_token() == "AT-new"
    assert calls[0]["grant_type"] == "refresh_token" and calls[0]["refresh_token"] == "RT"
    tok = json.loads(yt.token_path().read_text())
    assert tok["refresh_token"] == "RT" and tok["expires_at"] > time.time() + 3000
    assert yt.access_token() == "AT-new" and len(calls) == 1      # still valid: no second refresh


def test_refresh_invalid_grant_explains(monkeypatch):
    logged_in(expires_in=-10)
    monkeypatch.setattr(requests, "request",
                        lambda *a, **k: FakeResponse(400, {"error": "invalid_grant", "error_description": "x"}))
    with pytest.raises(yt.YouTubeError) as e:
        yt.access_token()
    assert "login" in str(e.value) and "RT" not in str(e.value)


def test_api_refreshes_on_401(monkeypatch):
    logged_in()
    seq = []

    def fake(method, url, headers=None, data=None, **k):
        if "oauth2" in url:
            return FakeResponse(200, {"access_token": "AT-fresh", "expires_in": 3600})
        seq.append(headers["Authorization"])
        return FakeResponse(401 if len(seq) == 1 else 200, {})
    monkeypatch.setattr(requests, "request", fake)
    r = yt.Api().request("GET", "https://www.googleapis.com/x")
    assert r.status_code == 200 and seq == ["Bearer AT-old", "Bearer AT-fresh"]


# ----------------------------------------------------------------------------- resumable upload

class FakeUploadServer:
    """Behaves like the resumable endpoint; can drop the connection or answer 503 on chosen chunks."""

    def __init__(self, size, drop_on=(), fail_503_on=()):
        self.size, self.received = size, bytearray()
        self.drop_on, self.fail_503_on = set(drop_on), set(fail_503_on)
        self.chunk_calls = 0
        self.inits = 0
        self.log = []

    def __call__(self, method, url, headers=None, data=None, json=None, **k):
        if "uploadType=resumable" in url and method == "POST":
            self.inits += 1
            self.resource = json
            assert headers["X-Upload-Content-Length"] == str(self.size)
            return FakeResponse(200, {}, {"Location": "https://upload.example/session/1"})
        assert url == "https://upload.example/session/1"
        cr = headers["Content-Range"]
        self.log.append(cr)
        if cr.startswith("bytes */"):
            return self._status()
        self.chunk_calls += 1
        m = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", cr)
        first, last, total = map(int, m.groups())
        assert first == len(self.received) and total == self.size and last - first + 1 == len(data)
        if last + 1 < total:
            assert len(data) % yt.CHUNK_UNIT == 0
        if self.chunk_calls in self.drop_on:
            self.received += data[: len(data) // 2 // yt.CHUNK_UNIT * yt.CHUNK_UNIT]   # partial, then drop
            raise requests.ConnectionError("connection reset")
        if self.chunk_calls in self.fail_503_on:
            return FakeResponse(503, {"error": {"message": "backend"}})
        self.received += data
        return self._status()

    def _status(self):
        if len(self.received) == self.size:
            return FakeResponse(201, {"id": "VID123", "status": {"uploadStatus": "uploaded",
                                                                "privacyStatus": "private"}})
        h = {"Range": f"bytes=0-{len(self.received) - 1}"} if self.received else {}
        return FakeResponse(308, None, h)


def big_file(tmp_path, n=5 * yt.CHUNK_UNIT + 1234):
    p = tmp_path / "big.mp4"
    p.write_bytes(os.urandom(n))
    return p


def test_resumable_upload_with_drop_and_503(isolated, monkeypatch):
    logged_in()
    f = big_file(isolated)
    srv = FakeUploadServer(f.stat().st_size, drop_on={2}, fail_503_on={4})
    monkeypatch.setattr(requests, "request", srv)
    res = yt.resumable_upload(yt.Api(), f, {"snippet": {}}, key="k1", chunk_size=2 * yt.CHUNK_UNIT,
                              progress=lambda *a: None)
    assert res["id"] == "VID123" and bytes(srv.received) == f.read_bytes()
    assert any(c.startswith("bytes */") for c in srv.log)       # asked where to resume
    assert srv.inits == 1 and "k1" not in yt._load_sessions()   # one session, cleaned up


def test_resume_after_crash_uses_saved_session(isolated, monkeypatch):
    logged_in()
    f = big_file(isolated)
    size = f.stat().st_size
    srv = FakeUploadServer(size)
    srv.received += f.read_bytes()[: 2 * yt.CHUNK_UNIT]          # an earlier run got this far
    yt._save_session("k2", {"url": "https://upload.example/session/1", "size": size})
    assert stat.S_IMODE(os.stat(yt.sessions_path()).st_mode) == 0o600
    monkeypatch.setattr(requests, "request", srv)
    res = yt.resumable_upload(yt.Api(), f, {}, key="k2", chunk_size=yt.CHUNK_UNIT, progress=lambda *a: None)
    assert res["id"] == "VID123" and srv.inits == 0 and bytes(srv.received) == f.read_bytes()
    assert srv.log[0] == f"bytes */{size}"


def test_chunk_size_must_be_256k_multiple(isolated):
    with pytest.raises(yt.YouTubeError):
        yt.resumable_upload(None, big_file(isolated), {}, key="x", chunk_size=100_000)


# ----------------------------------------------------------------------------- metadata

def test_title_description_tag_limits():
    t = yt.fit_title("A <very> long title " * 20)
    assert len(t) <= 100 and "<" not in t and ">" not in t and t.endswith("…")
    tail = "Narration is a synthetic voice. Shop: https://example.com"
    d = yt.fit_description("ナイト " * 3000, tail)       # 3-byte characters: bytes, not characters, count
    assert len(d.encode("utf-8")) <= 5000 and d.endswith(tail)
    tags = yt.fit_tags([f"sleep tag number {i}" for i in range(80)] + ["sleep tag number 1", "", "a<b>"])
    assert yt.tags_length(tags) <= 500 and len(tags) == len({t.lower() for t in tags})
    assert yt.tags_length(["a b", "c"]) == 5 + 1 + 1     # quotes around "a b", a comma, "c"


def test_nightly_metadata(isolated, tiny_video):
    d = nightly_folder(isolated / "out", tiny=tiny_video)
    m = yt.build_metadata(d / "episode.mp4", yt.load_config())
    assert m["kind"] == "nightly" and "Boulder" in m["title"] and len(m["title"]) <= 100
    assert "synthetic" in m["description"] and "https://example.com/shop" in m["description"]
    assert m["made_for_kids"] is True and m["category_id"] == "27" and m["contains_synthetic_media"] is True
    assert "Saturn" in m["description"] and yt.tags_length(m["tags"]) <= 500


def test_chapters_from_timing_and_kids_flag(isolated, tiny_video, monkeypatch):
    d = isolated / "out" / "stories" / "luna"
    d.mkdir(parents=True)
    (d / "story.md").write_text("# Luna and the Moonbeam\n\nThis is a story for Luna. The house was quiet.\n")
    v = d / "story.mp4"
    v.write_bytes(tiny_video.read_bytes())
    (d / "timing.json").write_text(json.dumps({"segments": [
        {"start": 1.2, "scene": "settle"}, {"start": 40, "scene": "star"}, {"start": 45, "scene": "companion"},
        {"start": 90, "scene": "moonbeam"}, {"start": 200, "scene": "goodnight"}]}))
    monkeypatch.setattr(yt, "probe_duration", lambda p: 300.0)
    m = yt.build_metadata(v, yt.load_config())
    assert m["kind"] == "story" and m["made_for_kids"] is True and m["hero"] == "Luna"
    assert "0:00 Settling in" in m["description"] and "1:30 The moonbeam ride" in m["description"]
    assert "0:45" not in m["description"]          # under 10 s after the previous chapter
    assert "made-up character" in m["description"]
    assert yt.build_metadata(v, yt.load_config(), made_for_kids=False)["made_for_kids"] is False


def test_video_resource_publish_at_forces_private():
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    item = {"title": "t", "description": "d", "tags": ["x"], "category_id": "22", "made_for_kids": False,
            "contains_synthetic_media": True, "privacy": "public", "publish_at": future}
    r = yt.video_resource(item, yt.load_config())
    assert r["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                           "containsSyntheticMedia": True, "publishAt": future}
    assert r["snippet"]["categoryId"] == "22"


# ----------------------------------------------------------------------------- thumbnail

def test_thumbnail_size(isolated, tiny_video):
    out = yt.make_thumbnail(tiny_video, "Boulder\nThursday 22 October", isolated / "t.jpg", at=1.0)
    im = Image.open(out)
    assert im.size == (1280, 720) and im.format == "JPEG" and out.stat().st_size < 2 * 1024 * 1024
    # bad time and missing video still give a valid thumbnail
    out2 = yt.make_thumbnail(isolated / "missing.mp4", "A very long title that has to wrap over lines " * 3,
                             isolated / "t2.jpg")
    assert Image.open(out2).size == (1280, 720)


# ----------------------------------------------------------------------------- queue

def test_queue_idempotent_and_upload_once(isolated, tiny_video, monkeypatch):
    d = nightly_folder(isolated / "out", tiny=tiny_video)
    v = d / "episode.mp4"
    a = yt.queue_add(v)
    b = yt.queue_add(v)                      # same file twice: one queue item
    items = yt.load_queue()
    assert a["id"] == b["id"] and len(items) == 1
    assert a["publish_at"] == "2030-01-16T02:00:00Z"     # 19:00 in Denver on the episode's own date
    assert Image.open(a["thumbnail"]).size == (1280, 720)
    assert "session" not in json.dumps(items)            # session URLs never stored in the project

    logged_in()
    srv = FakeUploadServer(v.stat().st_size)
    thumbs = []

    def fake(method, url, headers=None, data=None, json=None, **k):
        if "thumbnails/set" in url:
            thumbs.append(url)
            return FakeResponse(200, {"items": []})
        return srv(method, url, headers=headers, data=data, json=json)
    monkeypatch.setattr(requests, "request", fake)
    yt.upload(next_only=True)
    it = yt.load_queue()[0]
    assert it["status"] == "uploaded" and it["video_id"] == "VID123" and it["thumbnail_set"]
    assert srv.resource["status"]["publishAt"] == "2030-01-16T02:00:00Z"
    assert srv.resource["status"]["containsSyntheticMedia"] is True
    assert yt.upload(next_only=True) == [] and yt.upload(all_due=True) == []
    assert srv.inits == 1 and len(thumbs) == 1


def test_thumbnail_failure_retried_without_reupload(isolated, tiny_video, monkeypatch):
    d = nightly_folder(isolated / "out", tiny=tiny_video)
    yt.queue_add(d / "episode.mp4")
    logged_in()
    srv = FakeUploadServer((d / "episode.mp4").stat().st_size)
    thumb_status = [403]

    def fake(method, url, headers=None, data=None, json=None, **k):
        if "thumbnails/set" in url:
            return FakeResponse(thumb_status[0], {"error": {"message": "no", "errors": [{"reason": "forbidden"}]}})
        return srv(method, url, headers=headers, data=data, json=json)
    monkeypatch.setattr(requests, "request", fake)
    yt.upload(next_only=True)
    it = yt.load_queue()[0]
    assert it["status"] == "uploaded" and not it["thumbnail_set"] and "forbidden" in it["error"]
    thumb_status[0] = 200
    yt.upload(next_only=True)
    assert yt.load_queue()[0]["thumbnail_set"] and srv.inits == 1


def test_story_with_real_child_name_refused(isolated, tiny_video):
    d = isolated / "out" / "stories" / "isla"
    d.mkdir(parents=True)
    (d / "story.md").write_text("# Isla and the Star\n\nThis is a story for Isla.\n")
    (d / "story.mp4").write_bytes(tiny_video.read_bytes())
    with pytest.raises(yt.YouTubeError, match="made-up character"):
        yt.queue_add(d / "story.mp4")
    assert yt.load_queue() == []


def test_upload_cap_and_dry_run(isolated, tiny_video, monkeypatch, capsys):
    vids = []
    for i in range(4):
        v = isolated / f"nebula-{i}.mp4"
        v.write_bytes(tiny_video.read_bytes() + bytes([i]) * 10)
        vids.append(v)
        yt.queue_add(v, publish_at=f"2020-01-0{i + 1}T19:00")
    assert len(yt.load_queue()) == 4
    done = yt.upload(all_due=True, dry_run=True)
    assert len(done) == 2                                   # max_uploads_per_run
    assert "selfDeclaredMadeForKids" in capsys.readouterr().out


def test_plan_and_near_duplicates(isolated, tiny_video, monkeypatch):
    root = isolated / "out"
    start = dt.datetime(2030, 1, 13, 12, tzinfo=dt.timezone.utc)        # a Sunday
    nightly_folder(root, "2030-01-14", tiny=tiny_video)                  # Monday
    res = yt.plan(2, "Boulder", per_week=3, root=root, out_dir=root / "youtube", start=start)
    assert len(res["entries"]) == 6
    first = res["entries"][0]
    assert first["kind"] == "nightly" and first["ready"] and first["local"].startswith("Mon 14 Jan")
    assert sum(e["kind"] == "nightly" for e in res["entries"]) == 3
    assert (root / "youtube" / "plan.md").exists() and yt.load_queue() == []
    dups = yt.near_duplicates(["Boulder Tonight, Monday 14 January: Saturn Is Up | Calm",
                               "Boulder Tonight, Friday 18 January: Saturn Is Up | Calm",
                               "Into the Violet Nebula · 1 Hour"])
    assert len(dups) == 1


def test_keepsake_needs_confirmation(isolated, tiny_video):
    d = isolated / "out" / "keepsakes" / "maya"
    d.mkdir(parents=True)
    v = d / "letter.mp4"
    v.write_bytes(tiny_video.read_bytes())
    with pytest.raises(yt.YouTubeError, match="written permission"):
        yt.queue_add(v)
    assert yt.queue_add(v, confirm_fictional=True, kids=False)["made_for_kids"] is False
