"""YouTube publishing for the Little Lantern channel: login, metadata, thumbnails, a schedule queue and uploads.

    python -m skysoftly.youtube login
    python -m skysoftly.youtube queue add output/nightly/boulder/2026-10-25/episode.mp4
    python -m skysoftly.youtube queue list
    python -m skysoftly.youtube upload --next          (or --all-due, or --dry-run)
    python -m skysoftly.youtube plan --weeks 4 --city Boulder

The channel is meant to publish a few calm, long, varied videos a week, not a flood of near-identical
ones: YouTube does not monetise mass-produced, repetitive content. The tool caps uploads per run, warns
about near-duplicate titles and short videos, and `plan` mixes nightly episodes with long sleep videos.

API reference notes (checked 2026-10-22)
----------------------------------------
How these were checked: the docs pages themselves could not be fetched from this build machine
(WebFetch could not resolve developers.google.com), so each fact below comes from web-search
excerpts of the official pages. Where the excerpts disagreed or were silent, the fact is marked
UNVERIFIED. Re-check them against the live pages before relying on them.

OAuth 2.0 for installed (desktop) apps
  https://developers.google.com/identity/protocols/oauth2/native-app
  https://developers.google.com/youtube/v3/guides/auth/installed-apps
  * Desktop apps are public clients. They open the system browser and receive the code on a
    loopback redirect, http://127.0.0.1:PORT (or http://[::1]:PORT). Any free port works for a
    "Desktop app" client; the port does not need registering.
  * PKCE: code_verifier is 43 to 128 characters from [A-Za-z0-9-._~]. code_challenge is
    BASE64URL(SHA256(verifier)) with code_challenge_method=S256 (recommended).
  * Authorisation endpoint: https://accounts.google.com/o/oauth2/v2/auth (HTTPS only).
  * Token endpoint https://oauth2.googleapis.com/token. This was NOT seen in a search excerpt;
    it comes from memory and from the "token_uri" field of the downloaded client JSON, which
    this module prefers.
  * access_type=offline returns a refresh token. prompt=consent makes Google issue one again
    on re-login.
  * Consent screen in "Testing" status: refresh tokens expire 7 days after consent.
    https://support.google.com/cloud/answer/15549945

Scopes
  https://www.googleapis.com/auth/youtube.upload is accepted by videos.insert and also by
  thumbnails.set, so it is the only scope requested.
  https://developers.google.com/youtube/v3/docs/videos/insert
  https://developers.google.com/youtube/v3/docs/thumbnails/set

Resumable upload
  https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
  * Start: POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=...
    with the JSON resource and the headers X-Upload-Content-Length and X-Upload-Content-Type.
    The session URL comes back in the Location header. These are the documented headers, but
    the exact header names were NOT shown in a search excerpt; they are from memory.
  * Send bytes with PUT and "Content-Range: bytes FIRST-LAST/TOTAL". A 308 (Resume Incomplete)
    answer means more is needed; its Range header ("bytes=0-N", zero-indexed) says what was
    stored, and no Range means nothing was stored. 200 or 201 returns the video resource.
  * Status check after an interruption: an empty PUT with "Content-Range: bytes */TOTAL". If the
    308 answer carries Retry-After, wait that long. Sessions expire after a while; 404 or 410
    means start a new session.
  * Chunks other than the last must be a multiple of 256 KiB. This is stated by Google's
    resumable-upload guide (https://cloud.google.com/storage/docs/performing-resumable-uploads)
    and the Google API client libraries, not seen on the YouTube page itself. The guide
    recommends at least 8 MiB.
  * Retry 500, 502, 503 and 504, and dropped connections, with exponential backoff.

Video resource (https://developers.google.com/youtube/v3/docs/videos)
  * snippet.title: up to 100 characters, no "<" or ">".
  * snippet.description: up to 5000 BYTES of UTF-8, no "<" or ">".
  * snippet.tags[]: 500 characters in total. The commas between tags count, and a tag that
    contains a space counts as if quoted (+2 characters).
  * snippet.categoryId: a string. The IDs used here (1 Film & Animation, 22 People & Blogs,
    27 Education) are UNVERIFIED for every region; videoCategories.list?regionCode=.. lists them.
  * status.privacyStatus: "private", "public" or "unlisted".
  * status.publishAt: an ISO 8601 time for a scheduled release. It only works while
    privacyStatus is "private".
  * status.selfDeclaredMadeForKids: the uploader's made-for-kids (COPPA) declaration.
  * status.containsSyntheticMedia: EXISTS (revision history, 30 October 2024). It is set with
    videos.insert or videos.update, and marks "realistic altered or synthetic content".
    https://developers.google.com/youtube/v3/revision_history

Upload restrictions and quota
  * Videos uploaded from an unverified API project created after 28 July 2020 are locked to
    private until the project passes a YouTube API compliance audit (videos.insert page).
  * Default project quota: 10,000 units a day, reset at midnight Pacific Time.
  * The cost of videos.insert has changed. It used to be about 1,600 units. The revision history
    reports a cut to about 100 units (4 December 2025), and then a move into its own
    "video uploads" quota bucket; third-party guides describe that bucket as about 100 calls a
    day at 1 unit each. These figures are UNVERIFIED: check the project's Quotas page in Google
    Cloud Console.
  * thumbnails.set: about 50 units. The search excerpts disagreed on its maximum image size (2 MB
    in older copies, 50 MB after a reported September 2026 change), so thumbnails are kept under
    2 MB, which is safe either way. Custom thumbnails also need a verified channel (phone
    verification); that part is from YouTube Help and UNVERIFIED here.
  * Chapters (YouTube Help, not the API; UNVERIFIED here): the first timestamp must be 0:00,
    there must be at least three, and each must be at least 10 seconds long.

Secrets: tokens and the client secret live in ~/.config/skysoftly with mode 600. They are never
printed or logged, and never written under the project folder. Resumable session URLs authorise
uploads, so they are kept there too, not in output/youtube/queue.json.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import difflib
import hashlib
import http.server
import json
import os
import random
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# --------------------------------------------------------------------------------------------- constants

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
REVOKE_URI = "https://oauth2.googleapis.com/revoke"
UPLOAD_URI = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_URI = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"

TITLE_MAX = 100            # characters
DESCRIPTION_MAX = 5000     # UTF-8 bytes
TAGS_MAX = 500             # characters, commas and quotes included
CHUNK_UNIT = 256 * 1024    # every chunk but the last must be a multiple of this
DEFAULT_CHUNK = 32 * CHUNK_UNIT   # 8 MiB
RETRY_STATUSES = {500, 502, 503, 504}
MAX_RETRIES = 10
THUMB_SIZE = (1280, 720)
THUMB_MAX_BYTES = 2 * 1024 * 1024
GOLD = (245, 205, 130)     # #F5CD82
BRAND = "Little Lantern"                       # the YouTube channel; the Etsy shop is "Tonight's Sky, Softly"

# Approximate and UNVERIFIED (see the header): a guide for the user, not something the code relies on.
QUOTA = {"daily_default": 10_000, "videos.insert": 100, "thumbnails.set": 50}

DEFAULT_CONFIG = {
    "client_secret": "~/.config/skysoftly/youtube_client_secret.json",
    "shop_url": "",
    "timezone": "Europe/London",
    "publish_time": "19:00",
    "publish_days": ["Mon", "Wed", "Fri", "Sun"],
    "upload_lead_hours": 72,
    "max_uploads_per_run": 2,
    "category": {"nightly": "27", "story": "1", "sleep": "22"},
    "made_for_kids": {"nightly": True, "story": True, "sleep": False},
    "contains_synthetic_media": True,
    "default_language": "en",
    "fictional_characters": ["Luna"],
    "chunk_size": DEFAULT_CHUNK,
}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_sleep = time.sleep        # patched in tests


class YouTubeError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------------- config

def config_dir() -> Path:
    return Path(os.environ.get("SKYSOFTLY_CONFIG_DIR", "~/.config/skysoftly")).expanduser()


def token_path() -> Path:
    return config_dir() / "youtube_token.json"


def sessions_path() -> Path:
    return config_dir() / "youtube_sessions.json"


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    p = config_dir() / "youtube.json"
    if p.exists():
        user = json.loads(p.read_text())
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    if int(cfg["chunk_size"]) % CHUNK_UNIT:
        raise YouTubeError(f"chunk_size must be a multiple of {CHUNK_UNIT} bytes (256 KiB)")
    return cfg


def _write_private(path: Path, data: dict):
    """Write JSON readable only by this user (mode 600), atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


# --------------------------------------------------------------------------------------------- OAuth

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def make_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for S256 PKCE."""
    verifier = _b64url(secrets.token_bytes(64))          # 86 characters, all unreserved
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def load_client_secret(path: str | Path | None = None) -> dict:
    p = Path(path or load_config()["client_secret"]).expanduser()
    if not p.exists():
        raise YouTubeError(f"No OAuth client file at {p}. Download it from Google Cloud Console "
                           "(see docs/YOUTUBE-SETUP.md) or pass --client-secret.")
    data = json.loads(p.read_text())
    if "installed" not in data:
        kind = next(iter(data), "unknown")
        raise YouTubeError(f"That client file is a '{kind}' client. Create a 'Desktop app' OAuth client.")
    c = data["installed"]
    return {"client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
            "auth_uri": c.get("auth_uri", AUTH_URI), "token_uri": c.get("token_uri", TOKEN_URI)}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def authorization_url(client: dict, redirect_uri: str, challenge: str, state: str) -> str:
    q = {"client_id": client["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
         "scope": " ".join(SCOPES), "code_challenge": challenge, "code_challenge_method": "S256",
         "state": state, "access_type": "offline", "prompt": "consent"}
    return client["auth_uri"] + "?" + urllib.parse.urlencode(q)


def _token_request(client: dict, data: dict) -> dict:
    if client.get("client_secret"):
        data["client_secret"] = client["client_secret"]
    data["client_id"] = client["client_id"]
    r = requests.request("POST", client["token_uri"], data=data, timeout=30)
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200:
        # Only the error code and description: never the request, which holds secrets.
        err = body.get("error", r.status_code)
        hint = ""
        if err == "invalid_grant":
            hint = (" The saved login has expired or was revoked. Run `python -m skysoftly.youtube login` "
                    "again. (Apps left in 'Testing' status lose their login every 7 days.)")
        raise YouTubeError(f"Google token endpoint said {err}: {body.get('error_description', '')}{hint}")
    return body


def _store_token(body: dict, previous: dict | None = None) -> dict:
    tok = {"access_token": body["access_token"],
           "refresh_token": body.get("refresh_token") or (previous or {}).get("refresh_token"),
           "expires_at": time.time() + float(body.get("expires_in", 3600)),
           "scope": body.get("scope", (previous or {}).get("scope", " ".join(SCOPES))),
           "token_type": body.get("token_type", "Bearer")}
    _write_private(token_path(), tok)
    return tok


def exchange_code(client: dict, code: str, verifier: str, redirect_uri: str) -> dict:
    body = _token_request(client, {"code": code, "code_verifier": verifier, "redirect_uri": redirect_uri,
                                   "grant_type": "authorization_code"})
    if not body.get("refresh_token"):
        print("Warning: Google did not send a refresh token, so you will need to log in again in an hour.")
    return _store_token(body)


def refresh(client: dict, tok: dict) -> dict:
    if not tok.get("refresh_token"):
        raise YouTubeError("No refresh token saved. Run `python -m skysoftly.youtube login`.")
    body = _token_request(client, {"refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    return _store_token(body, previous=tok)


def access_token(client: dict | None = None, force_refresh: bool = False) -> str:
    """A valid access token, refreshing it automatically when it is within a minute of expiry."""
    p = token_path()
    if not p.exists():
        raise YouTubeError("Not logged in. Run `python -m skysoftly.youtube login` first.")
    tok = json.loads(p.read_text())
    if force_refresh or tok.get("expires_at", 0) - 60 < time.time():
        tok = refresh(client or load_client_secret(), tok)
    return tok["access_token"]


def login(client_secret: str | None = None, open_browser: bool = True, timeout: float = 300) -> dict:
    client = load_client_secret(client_secret)
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(24)
    port = free_port()
    redirect_uri = f"http://127.0.0.1:{port}"
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" not in q and "error" not in q:
                self.send_response(404); self.end_headers(); return
            result.update({k: v[0] for k, v in q.items()})
            ok = "code" in q and q.get("state", [""])[0] == state
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = ("Signed in. You can close this tab and go back to the terminal." if ok
                   else "Sign-in did not complete. Go back to the terminal for details.")
            self.wfile.write(f"<html><body style='font-family:serif;background:#0b1430;color:#f5cd82;"
                             f"padding:3em'><h2>{BRAND}</h2><p>{msg}</p></body></html>".encode())

        def log_message(self, *a):   # keep the code out of the terminal
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    url = authorization_url(client, redirect_uri, challenge, state)
    print("Opening your browser to sign in to Google. If it does not open, paste this link into it:\n")
    print("  " + url + "\n")
    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    deadline = time.time() + timeout
    while not result and time.time() < deadline:
        server.handle_request()
    server.server_close()
    if not result:
        raise YouTubeError("Timed out waiting for the Google sign-in.")
    if "error" in result:
        raise YouTubeError(f"Google sign-in was not completed: {result['error']}")
    if result.get("state") != state:
        raise YouTubeError("Sign-in reply did not match this request (state mismatch); try again.")
    tok = exchange_code(client, result["code"], verifier, redirect_uri)
    print(f"Logged in. Token saved to {token_path()} (readable only by you).")
    return tok


# --------------------------------------------------------------------------------------------- media helpers

def probe_duration(video: Path) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", str(video)], capture_output=True, text=True, check=True)
        return float(out.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return 0.0


def fingerprint(video: Path) -> str:
    """Stable id for a video file: size plus hashes of its first and last MiB (fast on big files)."""
    size = video.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with open(video, "rb") as f:
        h.update(f.read(1 << 20))
        if size > 1 << 20:
            f.seek(max(0, size - (1 << 20)))
            h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


def _clock(seconds: float) -> str:
    s = int(round(seconds))
    h, m, s = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _length_phrase(seconds: float) -> str:
    if seconds >= 55 * 60:
        h = round(seconds / 3600 * 2) / 2
        return f"{h:g} Hour" if h == 1 else f"{h:g} Hours"
    return f"{max(1, round(seconds / 60))} Minutes"


# --------------------------------------------------------------------------------------------- metadata limits

def clean_text(s: str) -> str:
    """Angle brackets are not allowed in titles or descriptions."""
    return s.replace("<", "‹").replace(">", "›")


def fit_title(title: str) -> str:
    t = re.sub(r"\s+", " ", clean_text(title)).strip()
    if len(t) <= TITLE_MAX:
        return t
    cut = t[:TITLE_MAX - 1]
    if " " in cut[60:]:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,.:;|·-") + "…"


def _truncate_bytes(s: str, limit: int) -> str:
    b = s.encode("utf-8")
    if len(b) <= limit:
        return s
    cut = b[:max(0, limit - len("…".encode()))].decode("utf-8", "ignore")
    nl = cut.rfind("\n")
    if nl > len(cut) * 0.6:
        cut = cut[:nl]
    elif " " in cut[int(len(cut) * 0.8):]:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip() + "…"


def fit_description(body: str, tail: str = "") -> str:
    """Join body and tail within 5000 UTF-8 bytes. The tail (shop link, disclosure) is never cut."""
    body, tail = clean_text(body).strip(), clean_text(tail).strip()
    sep = "\n\n" if body and tail else ""
    room = DESCRIPTION_MAX - len((sep + tail).encode("utf-8"))
    if room < 0:
        return _truncate_bytes(tail, DESCRIPTION_MAX)
    return _truncate_bytes(body, room) + sep + tail


def tags_length(tags: list[str]) -> int:
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(0, len(tags) - 1)


def fit_tags(tags: list[str]) -> list[str]:
    """Drop duplicates and empty tags, then keep tags in order while the total stays within 500."""
    out, seen = [], set()
    for t in tags:
        t = re.sub(r"[<>,\"]", "", t)
        t = re.sub(r"\s+", " ", t).strip()
        if not t or t.lower() in seen or len(t) > 100:
            continue
        if tags_length(out + [t]) > TAGS_MAX:
            continue
        out.append(t); seen.add(t.lower())
    return out


# --------------------------------------------------------------------------------------------- metadata builder

SCENE_TITLES = {
    "settle": "Settling in", "settling": "Settling in", "breathe": "Settling in", "bedroom": "Settling in",
    "intro": "Settling in", "star": "The star at the window", "window": "The star at the window",
    "companion": "A friend made of starlight", "animal": "A friend made of starlight",
    "moonbeam": "The moonbeam ride", "ride": "The moonbeam ride", "planets": "Past the planets",
    "nebula": "Into the nebula", "zoom": "Into the nebula", "wishes": "The wishes", "message": "A message",
    "home": "Floating home", "countdown": "Counting down the stars", "goodnight": "Goodnight",
    "secret": "A secret to keep", "outro": "Goodnight",
}

INTROS = {
    "nightly": ["Settle in, dim the lights, and let's look out of the window together.",
                "A quiet few minutes with tonight's real sky, then rest.",
                "Get cosy. Tonight we look up at the real sky over {city}, slowly and softly."],
    "story": ["A slow, gentle bedtime story to listen to with the lights down low.",
              "Snuggle down for a soft story under the stars.",
              "A calm story for sleepy eyes, told slowly, with soft music and starlight."],
    "sleep": ["A slow drift through deep space to help you unwind and fall asleep.",
              "Let your eyes go soft. Nothing to do but breathe and drift.",
              "A long, quiet journey through a glowing nebula for rest, sleep or study."],
}

TAGS = {
    "base": ["sleep", "bedtime", "relaxing", "calm", "Little Lantern", "night sky", "stars"],
    "nightly": ["bedtime story for kids", "astronomy for kids", "moon phase tonight", "stargazing",
                "sleep meditation for kids", "what's in the sky tonight"],
    "story": ["bedtime story", "sleep story for kids", "kids bedtime story", "calm story", "story for sleep"],
    "sleep": ["sleep video", "space ambience", "nebula", "deep space", "relaxing space video",
              "sleep music", "deep sleep"],
}


def _pick(options: list[str], key: str) -> str:
    return options[int(hashlib.sha1(key.encode()).hexdigest(), 16) % len(options)]


def detect_kind(video: Path) -> str:
    d = video.parent
    if (d / "episode.json").exists():
        return "nightly"
    if (d / "story.md").exists():
        return "story"
    return "sleep"


def load_chapters(video: Path, duration: float) -> list[tuple[float, str]]:
    """Read a timing file next to the video and return chapters valid for YouTube, or []."""
    d = video.parent
    for name in (f"{video.stem}.chapters.json", f"{video.stem}.timing.json", "chapters.json", "timing.json",
                 "segments.json"):
        p = d / name
        if p.exists():
            break
    else:
        return []
    try:
        data = json.loads(p.read_text())
    except ValueError:
        return []
    if isinstance(data, dict):
        data = next((data[k] for k in ("chapters", "segments", "paragraphs", "scenes") if k in data), [])
    raw = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        start = next((item[k] for k in ("start", "start_s", "t", "time", "at") if k in item), None)
        label = next((item[k] for k in ("title", "label", "chapter", "scene", "name") if k in item), None)
        if start is None or not label:
            continue
        label = str(label)
        label = SCENE_TITLES.get(label.lower(), label.replace("_", " ").replace("-", " ").strip().capitalize())
        raw.append((float(start), label))
    raw.sort()
    merged: list[tuple[float, str]] = []
    for start, label in raw:
        if merged and merged[-1][1] == label:
            continue
        if merged and start - merged[-1][0] < 10:      # each chapter must be at least 10 s long
            continue
        merged.append((start, label))
    if merged:
        merged[0] = (0.0, merged[0][1])
    if duration and merged and duration - merged[-1][0] < 10:
        merged.pop()
    return merged if len(merged) >= 3 else []


def _fmt_local(iso: str) -> str:
    t = dt.datetime.fromisoformat(iso)
    return t.strftime("%I:%M %p").lstrip("0").lower()


def _nightly_meta(video: Path, cfg: dict) -> dict:
    d = video.parent
    ep = json.loads((d / "episode.json").read_text())
    sky = json.loads((d / "sky.json").read_text()) if (d / "sky.json").exists() else {}
    city = sky.get("place", {}).get("name") or ep.get("title", "").split(":")[0] or "your town"
    date = dt.date.fromisoformat(ep.get("date") or sky["date"])
    nice_date = f"{date.strftime('%A')} {date.day} {date.strftime('%B')}"
    moon = sky.get("moon", {}).get("extra", {})
    up = [p["name"] for p in sky.get("planets", []) if p.get("status") == "up"]
    zen = sky.get("zenith_constellation")
    meteors = [m["name"] for m in sky.get("meteors_active", [])]
    # The headline is whatever is special tonight, so titles differ from night to night.
    if meteors:
        hook = f"{meteors[0]} Shooting Stars"
    elif moon.get("phase") in ("Full Moon",) or (moon.get("illumination", 0) > 97):
        hook = "A Full Moon"
    elif up:
        hook = f"{' and '.join(up[:2])} Are Up"
    elif zen:
        hook = f"{zen} Overhead"
    else:
        hook = f"A {moon.get('phase', 'Quiet')} Moon"
    title = f"{city} Tonight, {nice_date}: {hook} | Calm Sky Bedtime Story"
    if len(title) > TITLE_MAX:
        title = f"{city}, {date.day} {date.strftime('%b')}: {hook} | Sky Bedtime Story"
    lines = [_pick(INTROS["nightly"], title).format(city=city), "",
             f"The real sky over {city} on {nice_date}, read slowly for winding down at bedtime."]
    facts = []
    if moon:
        facts.append(f"• The Moon: {moon.get('phase', '').lower()}, {round(moon.get('illumination', 0))}% lit")
    if up:
        facts.append(f"• Planets up this evening: {', '.join(up)}")
    if zen:
        facts.append(f"• Overhead: {zen}")
    if meteors:
        facts.append(f"• Meteor shower: {', '.join(meteors)}")
    if sky.get("look_time"):
        facts.append(f"• Best time to look out of the window: about {_fmt_local(sky['look_time'])}")
    if facts:
        lines += ["", "Tonight's sky:"] + facts
    lines += ["", "If it's cloudy, the stars are still there above the clouds."]
    tags = TAGS["nightly"] + [city, f"{city} night sky", f"{city} stars tonight", f"night sky {nice_date}"]
    tags += [f"{p} tonight" for p in up] + ([zen] if zen else []) + meteors
    tz = sky.get("place", {}).get("tz")
    return {"title": title, "body": "\n".join(lines), "tags": tags, "city": city, "date": date.isoformat(),
            "tz": tz, "thumb_text": f"{city}\n{date.strftime('%A')} {date.day} {date.strftime('%B')}",
            "disclosure_extra": f"Sky positions are real, calculated for {city} on {nice_date}."}


def story_hero(md: str) -> str | None:
    m = re.search(r"This is a story for ([A-Z][\w'-]+)", md) or re.search(r"^#\s*([A-Z][\w'-]+)\b", md, re.M)
    return m.group(1) if m else None


def _story_meta(video: Path, cfg: dict) -> dict:
    md = (video.parent / "story.md").read_text()
    m = re.search(r"^#\s*(.+)$", md, re.M)
    story_title = m.group(1).strip() if m else video.stem.replace("-", " ").title()
    paras = [p.strip() for p in re.split(r"\n\s*\n", md) if p.strip() and not p.lstrip().startswith("#")]
    teaser = paras[0] if paras else ""
    teaser = re.split(r"(?<=[.!?])\s+", teaser)
    teaser = " ".join(teaser[1:3]) if len(teaser) > 2 else " ".join(teaser)
    hero = story_hero(md)
    title = f"{story_title} | Calm Bedtime Story for Kids"
    lines = [_pick(INTROS["story"], title), ""]
    if teaser:
        lines += [teaser, ""]
    lines += ["Dim the lights, get comfy, and let the story do the rest."]
    tags = TAGS["story"] + ([f"{hero} bedtime story"] if hero else []) + ["starlight", "moon story"]
    return {"title": title, "body": "\n".join(lines), "tags": tags, "hero": hero, "thumb_text": story_title,
            "disclosure_extra": (f"{hero} is a made-up character." if hero else "All characters are made up.")}


def _sleep_meta(video: Path, cfg: dict, duration: float) -> dict:
    name = re.sub(r"[-_]+", " ", video.stem).strip().title() or "Nebula"
    length = _length_phrase(duration) if duration else ""
    title = f"{name}{' · ' + length if length else ''} of Deep Space for Sleep | Calm Nebula Journey"
    lines = [_pick(INTROS["sleep"], title), "",
             "A slow camera drifts into a glowing nebula, past newborn stars and soft dust, all generated "
             "for this channel. Turn the brightness down, put it on a screen across the room, and rest."]
    return {"title": title, "body": "\n".join(lines), "tags": TAGS["sleep"] + [name],
            "thumb_text": name, "disclosure_extra": "The nebula is a generated artwork, not a telescope photo."}


def build_metadata(video: str | Path, cfg: dict | None = None, kind: str | None = None,
                   made_for_kids: bool | None = None) -> dict:
    """Title, description, tags, category and flags for one video, within YouTube's limits."""
    cfg = cfg or load_config()
    video = Path(video)
    kind = kind or detect_kind(video)
    duration = probe_duration(video) if video.exists() else 0.0
    meta = {"nightly": lambda: _nightly_meta(video, cfg), "story": lambda: _story_meta(video, cfg),
            "sleep": lambda: _sleep_meta(video, cfg, duration)}[kind]()
    override = video.with_suffix(".youtube.json")
    if override.exists():                 # optional hand-written title/description/tags
        meta.update(json.loads(override.read_text()))
    body = meta["body"]
    chapters = load_chapters(video, duration)
    if chapters:
        body += "\n\nChapters\n" + "\n".join(f"{_clock(s)} {label}" for s, label in chapters)
    tail = []
    if cfg.get("shop_url"):
        tail.append(f"Personalised bedtime stories and star gifts: {cfg['shop_url']}")
    tail.append("About this video: the narration is a synthetic (computer-generated) voice. "
                + meta.get("disclosure_extra", ""))
    tail.append(f"{BRAND}: a soft light for bedtime. Calm stories and the real night sky.")
    kids = cfg["made_for_kids"].get(kind, False) if made_for_kids is None else made_for_kids
    return {"kind": kind, "title": fit_title(meta["title"]),
            "description": fit_description(body, "\n".join(t.strip() for t in tail)),
            "tags": fit_tags(TAGS["base"] + meta["tags"]),
            "category_id": str(cfg["category"].get(kind, "22")),
            "made_for_kids": bool(kids), "contains_synthetic_media": bool(cfg.get("contains_synthetic_media", True)),
            "duration_s": round(duration, 1), "chapters": len(chapters),
            "thumb_text": meta.get("thumb_text", meta["title"]), "hero": meta.get("hero"),
            "date": meta.get("date"), "tz": meta.get("tz")}


def video_resource(item: dict, cfg: dict) -> dict:
    status = {"privacyStatus": item.get("privacy", "private"),
              "selfDeclaredMadeForKids": bool(item["made_for_kids"]),
              "containsSyntheticMedia": bool(item.get("contains_synthetic_media", True))}
    publish_at = item.get("publish_at")
    if publish_at:
        when = dt.datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
        if when > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=15):
            status["privacyStatus"] = "private"     # publishAt only works on private videos
            status["publishAt"] = when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lang = cfg.get("default_language", "en")
    return {"snippet": {"title": fit_title(item["title"]), "description": fit_description(item["description"]),
                        "tags": fit_tags(item.get("tags", [])), "categoryId": str(item["category_id"]),
                        "defaultLanguage": lang, "defaultAudioLanguage": lang},
            "status": status}


# --------------------------------------------------------------------------------------------- thumbnail

def font(size: int, serif: bool = True, italic: bool = False, bold: bool = False):
    """DejaVu via matplotlib's font manager, matching skysoftly.products.font."""
    from matplotlib import font_manager
    from PIL import ImageFont
    prop = font_manager.FontProperties(family="DejaVu Serif" if serif else "DejaVu Sans",
                                       style="italic" if italic else "normal", weight="bold" if bold else "normal")
    return ImageFont.truetype(font_manager.findfont(prop), size)


def grab_frame(video: Path, at: float | None, out: Path) -> bool:
    dur = probe_duration(video)
    t = at if at is not None else dur * 0.35
    if dur and t >= dur:
        t = dur * 0.5
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", str(video),
                        "-frames:v", "1", str(out)], capture_output=True)
    return r.returncode == 0 and out.exists() and out.stat().st_size > 0


def _wrap(d, text: str, f, max_w: int) -> list[str]:
    lines = []
    for para in text.split("\n"):
        cur = ""
        for w in para.split():
            trial = (cur + " " + w).strip()
            if d.textlength(trial, font=f) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
    return lines


def make_thumbnail(video: str | Path, text: str, out: str | Path, at: float | None = None) -> Path:
    """1280x720 JPEG under 2 MB: a video frame, darkened, with large gold serif text in a dark outline."""
    import numpy as np
    from PIL import Image, ImageDraw

    video, out = Path(video), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    W, H = THUMB_SIZE
    with tempfile.TemporaryDirectory() as td:
        frame = Path(td) / "frame.png"
        if grab_frame(video, at, frame):
            im = Image.open(frame).convert("RGB")
            s = max(W / im.width, H / im.height)
            im = im.resize((max(W, round(im.width * s)), max(H, round(im.height * s))), Image.LANCZOS)
            x, y = (im.width - W) // 2, (im.height - H) // 2
            im = im.crop((x, y, x + W, y + H))
        else:                              # no frame: a plain night-blue gradient
            g = np.linspace(0, 1, H)[:, None, None]
            im = Image.fromarray((np.array([11, 20, 48]) * (1 - g) + np.array([40, 45, 80]) * g)
                                 .repeat(W, axis=1).astype("uint8"))
    # Darken: an overall dim plus a gradient that deepens towards the bottom, where the text sits.
    a = np.asarray(im).astype(np.float32)
    ramp = np.linspace(0.85, 0.30, H, dtype=np.float32)[:, None, None]
    a = a * ramp + np.array([6, 10, 28], np.float32) * (1 - ramp)
    im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    d = ImageDraw.Draw(im)
    text = text.strip() or BRAND
    size, max_w = 132, W - 160
    while True:
        f = font(size, bold=True)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if "\n" not in text or size < 96:       # keep the author's line breaks while the text is large
            lines = _wrap(d, text, f, max_w)
        line_h = int(size * 1.12)
        if (len(lines) <= 3 and all(d.textlength(l, font=f) <= max_w for l in lines)
                and line_h * len(lines) <= H * 0.55) or size <= 40:
            break
        size = int(size * 0.92)
    y = H - 90 - line_h * len(lines)
    stroke = max(3, size // 14)
    for line in lines:
        w = d.textlength(line, font=f)
        d.text(((W - w) / 2, y), line, font=f, fill=GOLD, stroke_width=stroke, stroke_fill=(8, 10, 24))
        y += line_h
    small = font(34, italic=True)
    w = d.textlength(BRAND, font=small)
    d.text(((W - w) / 2, H - 70), BRAND, font=small, fill=(238, 240, 250), stroke_width=2,
           stroke_fill=(8, 10, 24))
    for q in (92, 85, 75, 65, 50):
        im.save(out, "JPEG", quality=q, optimize=True, progressive=True)
        if out.stat().st_size < THUMB_MAX_BYTES:
            break
    return out


# --------------------------------------------------------------------------------------------- HTTP and upload

def _error_message(r) -> str:
    try:
        e = r.json().get("error", {})
        if isinstance(e, dict):
            reasons = ",".join(x.get("reason", "") for x in e.get("errors", []))
            return f"HTTP {r.status_code} {e.get('message', '')} {('(' + reasons + ')') if reasons else ''}".strip()
        return f"HTTP {r.status_code} {e}"
    except ValueError:
        return f"HTTP {r.status_code}"


def _backoff(attempt: int, retry_after: str | None = None):
    if retry_after and retry_after.isdigit():
        _sleep(int(retry_after)); return
    _sleep(min(64.0, 2 ** attempt) + random.random())


class Api:
    """Authorised calls: refreshes on 401 once, retries 5xx and dropped connections with backoff."""

    def __init__(self, client: dict | None = None):
        self.client = client
        self._token = None

    def token(self, force: bool = False) -> str:
        if self._token is None or force:
            self._token = access_token(self.client, force_refresh=force)
        return self._token

    def request(self, method: str, url: str, headers: dict | None = None, retry: bool = True, **kw):
        refreshed = False
        for attempt in range(MAX_RETRIES + 1):
            h = dict(headers or {}, Authorization=f"Bearer {self.token()}")
            try:
                r = requests.request(method, url, headers=h, timeout=kw.pop("timeout", 120), **kw)
            except (requests.ConnectionError, requests.Timeout):
                if not retry or attempt == MAX_RETRIES:
                    raise
                _backoff(attempt); continue
            if r.status_code == 401 and not refreshed:
                self.token(force=True); refreshed = True; continue
            if r.status_code in RETRY_STATUSES and retry and attempt < MAX_RETRIES:
                _backoff(attempt, r.headers.get("Retry-After")); continue
            return r
        return r


def _load_sessions() -> dict:
    p = sessions_path()
    return json.loads(p.read_text()) if p.exists() else {}


def _save_session(key: str, value: dict | None):
    s = _load_sessions()
    if value is None:
        s.pop(key, None)
    else:
        s[key] = value
    _write_private(sessions_path(), s)


def _parse_range(r) -> int:
    """Bytes the server holds, from a 308 Range header like 'bytes=0-999'. No header means 0."""
    rng = r.headers.get("Range")
    if not rng:
        return 0
    m = re.search(r"(\d+)-(\d+)", rng)
    return int(m.group(2)) + 1 if m else 0


def start_session(api: Api, resource: dict, size: int, mime: str = "video/*") -> str:
    url = UPLOAD_URI + "?" + urllib.parse.urlencode({"uploadType": "resumable", "part": "snippet,status"})
    r = api.request("POST", url, json=resource, headers={
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": mime})
    if r.status_code != 200 or not r.headers.get("Location"):
        raise YouTubeError("Could not start the upload: " + _error_message(r))
    return r.headers["Location"]


def query_offset(api: Api, session_url: str, size: int):
    """Ask how much of an interrupted upload arrived. Returns (offset, finished_resource_or_None),
    or (None, None) when the session has expired."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = api.request("PUT", session_url, data=b"", retry=False,
                            headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"})
        except (requests.ConnectionError, requests.Timeout):
            _backoff(attempt); continue
        if r.status_code in (200, 201):
            return size, r.json()
        if r.status_code == 308:
            if r.headers.get("Retry-After"):
                _backoff(attempt, r.headers.get("Retry-After"))
            return _parse_range(r), None
        if r.status_code in (404, 410):
            return None, None
        if r.status_code in RETRY_STATUSES:
            _backoff(attempt); continue
        raise YouTubeError("Could not check the upload: " + _error_message(r))
    raise YouTubeError("Gave up checking the upload after repeated server errors.")


def resumable_upload(api: Api, video: Path, resource: dict, key: str, chunk_size: int = DEFAULT_CHUNK,
                     progress=print) -> dict:
    """Upload with the resumable protocol. The session URL is saved under `key` before any bytes are sent,
    so a crash or Ctrl-C can resume where it stopped instead of uploading again."""
    if chunk_size % CHUNK_UNIT:
        raise YouTubeError("chunk_size must be a multiple of 256 KiB")
    size = video.stat().st_size
    saved = _load_sessions().get(key)
    offset, session_url = 0, None
    if saved and saved.get("size") == size:
        session_url = saved["url"]
        offset, done = query_offset(api, session_url, size)
        if done:
            _save_session(key, None)
            return done
        if offset is None:
            session_url, offset = None, 0
        else:
            progress(f"  resuming at {offset / size:.0%}")
    if session_url is None:
        session_url = start_session(api, resource, size)
        _save_session(key, {"url": session_url, "size": size, "started": time.time()})
    failures = 0
    with open(video, "rb") as f:
        while True:
            f.seek(offset)
            chunk = f.read(chunk_size)
            last = offset + len(chunk) - 1
            try:
                r = api.request("PUT", session_url, data=chunk, retry=False, headers={
                    "Content-Length": str(len(chunk)), "Content-Range": f"bytes {offset}-{last}/{size}"})
            except (requests.ConnectionError, requests.Timeout):
                r = None
            if r is not None and r.status_code in (200, 201):
                _save_session(key, None)
                return r.json()
            if r is not None and r.status_code == 308:
                offset, failures = _parse_range(r), 0
                progress(f"  uploaded {offset / size:.0%}")
                continue
            if r is not None and r.status_code not in RETRY_STATUSES:
                if r.status_code in (404, 410):
                    _save_session(key, None)
                raise YouTubeError("Upload failed: " + _error_message(r))
            failures += 1
            if failures > MAX_RETRIES:
                raise YouTubeError("Upload kept failing; run the same command again later to resume.")
            _backoff(failures - 1, r.headers.get("Retry-After") if r is not None else None)
            new_offset, done = query_offset(api, session_url, size)
            if done:
                _save_session(key, None)
                return done
            if new_offset is None:
                _save_session(key, None)
                raise YouTubeError("The upload session expired; run the command again to start afresh.")
            offset = new_offset


def set_thumbnail(api: Api, video_id: str, thumb: Path) -> dict:
    url = THUMBNAIL_URI + "?" + urllib.parse.urlencode({"videoId": video_id, "uploadType": "media"})
    r = api.request("POST", url, data=thumb.read_bytes(), headers={"Content-Type": "image/jpeg"})
    if r.status_code != 200:
        raise YouTubeError("Thumbnail not set: " + _error_message(r))
    return r.json()


# --------------------------------------------------------------------------------------------- queue

def queue_path() -> Path:
    return Path(os.environ.get("SKYSOFTLY_YT_QUEUE", "output/youtube/queue.json"))


def load_queue(path: Path | None = None) -> list[dict]:
    p = path or queue_path()
    return json.loads(p.read_text()) if p.exists() else []


def save_queue(items: list[dict], path: Path | None = None):
    _write_json(path or queue_path(), items)


def _parse_when(s: str, tz: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=ZoneInfo(tz))
    return t.astimezone(dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slots(cfg: dict, start: dt.datetime, count: int, days: list[str] | None = None, tz: str | None = None):
    """The next `count` publishing slots (fixed evening time on the configured weekdays) after `start`."""
    zone = ZoneInfo(tz or cfg["timezone"])
    hh, mm = (int(x) for x in cfg["publish_time"].split(":"))
    want = {DAY_NAMES.index(d[:3].title()) for d in (days or cfg["publish_days"])}
    day = start.astimezone(zone).date()
    out = []
    while len(out) < count:
        if day.weekday() in want:
            t = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=zone)
            if t > start:
                out.append(t.astimezone(dt.timezone.utc))
        day += dt.timedelta(days=1)
    return out


def default_publish_at(cfg: dict, meta: dict, taken: set[str], now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now(dt.timezone.utc)
    earliest = now + dt.timedelta(hours=float(cfg["upload_lead_hours"]))
    if meta["kind"] == "nightly" and meta.get("date"):
        # A nightly episode belongs to its own evening, published at the usual time in its city.
        zone = ZoneInfo(meta.get("tz") or cfg["timezone"])
        hh, mm = (int(x) for x in cfg["publish_time"].split(":"))
        d = dt.date.fromisoformat(meta["date"])
        t = dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=zone).astimezone(dt.timezone.utc)
        if t > now:
            return t
        print(f"  warning: this episode describes the sky on {meta['date']}, which has passed.")
    zone = ZoneInfo(cfg["timezone"])
    for t in slots(cfg, earliest, 200):
        if t.astimezone(zone).date().isoformat() not in taken:
            return t
    return earliest


def _local_day(iso: str, zone: ZoneInfo) -> str:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(zone).date().isoformat()


def _norm_title(t: str) -> str:
    t = t.lower().split("|")[0]
    t = re.sub(r"\d+|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may"
               r"|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec",
               " ", t)
    return re.sub(r"[^a-z]+", " ", t).strip()


def near_duplicates(titles: list[str], threshold: float = 0.85) -> list[tuple[str, str, float]]:
    """Pairs of titles that read almost the same once dates and numbers are ignored."""
    out = []
    norm = [_norm_title(t) for t in titles]
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            r = difflib.SequenceMatcher(None, norm[i], norm[j]).ratio()
            if r >= threshold:
                out.append((titles[i], titles[j], round(r, 2)))
    return out


def queue_add(video: str | Path, publish_at: str | None = None, kids: bool | None = None, privacy: str = "private",
              kind: str | None = None, thumb_at: float | None = None, confirm_fictional: bool = False,
              cfg: dict | None = None, path: Path | None = None) -> dict:
    cfg = cfg or load_config()
    video = Path(video).resolve()
    if not video.exists():
        raise YouTubeError(f"No such video: {video}")
    items = load_queue(path)
    fp = fingerprint(video)
    for it in items:
        if it["id"] == fp:
            print(f"Already queued as {fp} ({it['status']}): {it['title']}")
            return it
    if {"keepsakes", "products"} & set(video.parts) and not confirm_fictional:
        raise YouTubeError("This looks like a customer keepsake or product video. Never upload a customer's "
                           "personalised video without their written permission. Pass --confirm-fictional "
                           "if it is a made-up sample or you have that permission.")
    meta = build_metadata(video, cfg, kind=kind, made_for_kids=kids)
    if meta["kind"] == "story":
        allowed = {c.lower() for c in cfg.get("fictional_characters", [])}
        if (meta.get("hero") or "").lower() not in allowed and not confirm_fictional:
            raise YouTubeError(
                f"This story's hero is '{meta.get('hero')}', who is not in fictional_characters {sorted(allowed)}. "
                "YouTube stories must use a made-up character, never a customer's child. If this really is "
                "fictional, add the name to the config or pass --confirm-fictional.")
    zone = ZoneInfo(cfg["timezone"])
    taken = {_local_day(it["publish_at"], zone) for it in items if it.get("publish_at")}
    if publish_at:
        when = _parse_when(publish_at, cfg["timezone"])
    elif privacy == "private":
        when = default_publish_at(cfg, meta, taken)
    else:
        when = None
    qdir = (path or queue_path()).parent
    thumb = make_thumbnail(video, meta["thumb_text"], qdir / "thumbnails" / f"{fp}.jpg", at=thumb_at)
    item = {"id": fp, "video": str(video), "kind": meta["kind"], "title": meta["title"],
            "description": meta["description"], "tags": meta["tags"], "category_id": meta["category_id"],
            "made_for_kids": meta["made_for_kids"], "contains_synthetic_media": meta["contains_synthetic_media"],
            "privacy": privacy, "publish_at": _iso(when) if when else None, "thumbnail": str(thumb.resolve()),
            "duration_s": meta["duration_s"], "status": "queued", "video_id": None, "thumbnail_set": False,
            "added_at": _iso(dt.datetime.now(dt.timezone.utc)), "uploaded_at": None, "error": None}
    for a, b, r in near_duplicates([item["title"]] + [it["title"] for it in items]):
        if item["title"] in (a, b):
            print(f"  warning: title is {r:.0%} like an existing one: {b if a == item['title'] else a}")
    if meta["kind"] == "sleep" and meta["duration_s"] and meta["duration_s"] < 20 * 60:
        print("  note: long sleep videos (an hour or more) suit this channel better than short ones.")
    items.append(item)
    save_queue(items, path)
    return item


def _due(item: dict, cfg: dict, now: dt.datetime) -> bool:
    if item.get("status") == "uploaded":
        return not item.get("thumbnail_set")
    if not item.get("publish_at"):
        return True
    when = dt.datetime.fromisoformat(item["publish_at"].replace("Z", "+00:00"))
    return when - dt.timedelta(hours=float(cfg["upload_lead_hours"])) <= now


def upload_item(item: dict, cfg: dict, api: Api | None, items: list[dict], path: Path | None = None,
                dry_run: bool = False) -> dict:
    resource = video_resource(item, cfg)
    if dry_run:
        print(json.dumps(resource, indent=1, ensure_ascii=False))
        return item
    if item.get("publish_at") and "publishAt" not in resource["status"]:
        print(f"  warning: publish time {item['publish_at']} has passed, so this uploads as {item['privacy']}.")
    if item.get("status") != "uploaded":
        item["status"], item["error"] = "uploading", None
        save_queue(items, path)
        try:
            res = resumable_upload(api, Path(item["video"]), resource, key=item["id"],
                                   chunk_size=int(cfg["chunk_size"]))
        except Exception as e:  # noqa: BLE001 - recorded, then re-raised
            item["status"], item["error"] = "interrupted", str(e)
            save_queue(items, path)
            raise
        item.update(status="uploaded", video_id=res.get("id"),
                    upload_status=res.get("status", {}).get("uploadStatus"),
                    privacy_returned=res.get("status", {}).get("privacyStatus"),
                    uploaded_at=_iso(dt.datetime.now(dt.timezone.utc)))
        save_queue(items, path)
        print(f"  uploaded: https://youtu.be/{item['video_id']}")
        if item.get("publish_at") and item.get("privacy_returned") == "private" and "publishAt" in resource["status"]:
            print("  scheduled for", item["publish_at"])
    if item.get("video_id") and not item.get("thumbnail_set") and item.get("thumbnail"):
        try:
            set_thumbnail(api, item["video_id"], Path(item["thumbnail"]))
            item["thumbnail_set"], item["error"] = True, None
        except YouTubeError as e:
            item["error"] = str(e)
            print("  " + str(e) + " (it will be retried next run; custom thumbnails need a verified channel)")
        save_queue(items, path)
    return item


def upload(next_only: bool = False, all_due: bool = False, item_id: str | None = None, dry_run: bool = False,
           max_count: int | None = None, cfg: dict | None = None, path: Path | None = None,
           api: Api | None = None) -> list[dict]:
    cfg = cfg or load_config()
    items = load_queue(path)
    now = dt.datetime.now(dt.timezone.utc)
    pending = [it for it in items if it.get("status") != "uploaded" or not it.get("thumbnail_set")]
    pending.sort(key=lambda it: it.get("publish_at") or "")
    if item_id:
        pending = [it for it in pending if it["id"] == item_id]
    elif all_due:
        pending = [it for it in pending if _due(it, cfg, now)]
    elif next_only:
        pending = pending[:1]
    else:
        raise YouTubeError("Say which: --next, --all-due or --id ID.")
    limit = max_count or int(cfg["max_uploads_per_run"])
    # Finishing a thumbnail costs little, so only new uploads count towards the per-run cap.
    todo, n = [], 0
    for it in pending:
        if it.get("status") != "uploaded":
            if n >= limit:
                print(f"Stopping at {limit} uploads this run (max_uploads_per_run); the rest wait for next time.")
                break
            n += 1
        todo.append(it)
    if not todo:
        print("Nothing to upload.")
        return []
    if api is None and not dry_run:
        api = Api(load_client_secret(cfg["client_secret"]))
    done = []
    for it in todo:
        print(f"{it['id']}  {it['title']}")
        done.append(upload_item(it, cfg, api, items, path, dry_run=dry_run))
    return done


# --------------------------------------------------------------------------------------------- plan

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _long_videos(root: Path, cfg: dict) -> list[Path]:
    """Candidate long sleep videos: MP4s outside nightly and customer folders."""
    vids = []
    for p in sorted(root.rglob("*.mp4")):
        rel = p.relative_to(root).parts
        if rel and rel[0] in ("nightly", "youtube", "keepsakes", "products"):
            continue
        if rel and rel[0] == "stories":
            md = p.parent / "story.md"
            hero = story_hero(md.read_text()) if md.exists() else None
            if (hero or "").lower() not in {c.lower() for c in cfg.get("fictional_characters", [])}:
                continue        # a customer's story: never on YouTube
        vids.append(p)
    return vids


def plan(weeks: int, city: str, per_week: int = 4, cfg: dict | None = None, root: Path = Path("output"),
         out_dir: Path | None = None, start: dt.datetime | None = None) -> dict:
    cfg = cfg or load_config()
    per_week = max(1, min(int(per_week), 7))
    days = list(cfg["publish_days"])[:per_week] if per_week <= len(cfg["publish_days"]) else DAY_NAMES[:per_week]
    city_dir = root / "nightly" / _slug(city)
    tz = cfg["timezone"]
    sky_files = sorted(city_dir.glob("*/sky.json"))
    if sky_files:
        tz = json.loads(sky_files[0].read_text()).get("place", {}).get("tz") or tz
    start = start or dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=float(cfg["upload_lead_hours"]))
    queued = load_queue()
    queued_videos = {it["video"] for it in queued}
    long_pool = [p for p in _long_videos(root, cfg) if str(p.resolve()) not in queued_videos]
    entries, warnings = [], []
    for i, t in enumerate(slots(cfg, start, weeks * per_week, days=days, tz=tz)):
        local = t.astimezone(ZoneInfo(tz))
        # Alternate: nightly, long sleep video, nightly, long sleep video... no more than half are nightly.
        kind = "nightly" if i % 2 == 0 else "long"
        e = {"publish_at": _iso(t), "local": local.strftime("%a %d %b %Y %H:%M"), "kind": kind}
        if kind == "nightly":
            ep = city_dir / local.date().isoformat()
            vid = ep / "episode.mp4"
            e["video"] = str(vid)
            if str(vid.resolve()) in queued_videos:
                e.update(ready=True, queued=True, command="already queued",
                         title=next(it["title"] for it in queued if it["video"] == str(vid.resolve())))
            elif vid.exists():
                e["title"] = build_metadata(vid, cfg, kind="nightly")["title"]
                e["ready"] = True
                e["command"] = f"python -m skysoftly.youtube queue add {vid}"
            else:
                e["ready"] = False
                e["command"] = (f"python -m skysoftly nightly --city {city!r} --start {local.date()} --days 1 "
                                f"--video")
        else:
            if long_pool:
                vid = long_pool.pop(0)
                e.update(video=str(vid), ready=True, title=build_metadata(vid, cfg)["title"],
                         command=f"python -m skysoftly.youtube queue add {vid} --publish-at {_iso(t)}")
            else:
                e.update(ready=False, title=None,
                         command="render a new long sleep video (an hour of nebula drift, or a Luna story)")
        entries.append(e)
    titles = [e["title"] for e in entries if e.get("title") and not e.get("queued")] + [it["title"] for it in queued]
    for a, b, r in near_duplicates(titles):
        warnings.append(f"near-duplicate titles ({r:.0%}): '{a}' / '{b}'")
    if per_week > 4:
        warnings.append("more than 4 a week leans towards 'mass-produced' content; fewer, longer videos do better")
    nightly_short = [e for e in entries if e["kind"] == "nightly"]
    if nightly_short:
        warnings.append("nightly episodes are about 4 minutes long; keep them to half the schedule or less and "
                        "give the other slots to long videos")
    result = {"city": city, "weeks": weeks, "per_week": per_week, "timezone": tz, "entries": entries,
              "warnings": warnings}
    out_dir = out_dir or queue_path().parent
    _write_json(out_dir / "plan.json", result)
    md = [f"# YouTube plan: {city}, {weeks} weeks", "", f"{per_week} a week at {cfg['publish_time']} ({tz}).", "",
          "| When | Kind | Ready | Title or next step |", "|---|---|---|---|"]
    for e in entries:
        md.append(f"| {e['local']} | {e['kind']} | {'yes' if e['ready'] else 'no'} | "
                  f"{(e.get('title') or e['command']).replace('|', '/')} |")
    if warnings:
        md += ["", "## Warnings", ""] + [f"- {w}" for w in warnings]
    (out_dir / "plan.md").write_text("\n".join(md) + "\n")
    return result


# --------------------------------------------------------------------------------------------- CLI

def _print_queue(items: list[dict]):
    if not items:
        print("The queue is empty.")
        return
    for it in sorted(items, key=lambda i: i.get("publish_at") or ""):
        flags = ("kids" if it["made_for_kids"] else "not-kids") + (" thumb" if it.get("thumbnail_set") else "")
        vid = f" https://youtu.be/{it['video_id']}" if it.get("video_id") else ""
        print(f"{it['id']}  {it['status']:<11} {it.get('publish_at') or 'unscheduled':<20} "
              f"{it['kind']:<7} {flags:<14} {it['title']}{vid}")
        if it.get("error"):
            print(f"{'':18}last error: {it['error']}")


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(prog="python -m skysoftly.youtube", description="Publish to YouTube.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("login", help="sign in with Google in your browser")
    p.add_argument("--client-secret", help="path to the downloaded Desktop OAuth client JSON")
    p.add_argument("--no-browser", action="store_true", help="only print the sign-in link")
    sub.add_parser("logout", help="revoke and delete the saved login")
    sub.add_parser("status", help="show login, config and queue status (never prints secrets)")
    p = sub.add_parser("config", help="write a starter config file")
    p.add_argument("--init", action="store_true")

    q = sub.add_parser("queue", help="add to or list the upload queue")
    qs = q.add_subparsers(dest="qcmd", required=True)
    a = qs.add_parser("add")
    a.add_argument("video")
    a.add_argument("--publish-at", help="ISO time, e.g. 2026-11-02T19:00 (config timezone if no offset)")
    a.add_argument("--kids", dest="kids", action="store_true", default=None, help="mark as made for kids")
    a.add_argument("--no-kids", dest="kids", action="store_false", help="mark as not made for kids")
    a.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    a.add_argument("--kind", choices=["nightly", "story", "sleep"])
    a.add_argument("--thumb-at", type=float, help="seconds into the video for the thumbnail frame")
    a.add_argument("--confirm-fictional", action="store_true",
                   help="confirm a story's hero is a made-up character, not a customer")
    qs.add_parser("list")
    r = qs.add_parser("remove")
    r.add_argument("id")

    u = sub.add_parser("upload", help="upload queued videos")
    g = u.add_mutually_exclusive_group(required=True)
    g.add_argument("--next", action="store_true", help="the earliest queued video")
    g.add_argument("--all-due", action="store_true", help="everything due within upload_lead_hours")
    g.add_argument("--id")
    u.add_argument("--max", type=int, help="override max_uploads_per_run")
    u.add_argument("--dry-run", action="store_true", help="show what would be sent; no network")

    pl = sub.add_parser("plan", help="suggest a schedule without uploading")
    pl.add_argument("--weeks", type=int, default=4)
    pl.add_argument("--city", required=True)
    pl.add_argument("--per-week", type=int, default=4, help="videos a week (3 or 4 recommended)")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "login":
            login(a.client_secret, open_browser=not a.no_browser)
        elif a.cmd == "logout":
            p = token_path()
            if p.exists():
                tok = json.loads(p.read_text())
                try:
                    requests.request("POST", REVOKE_URI, data={"token": tok.get("refresh_token") or
                                                               tok.get("access_token")}, timeout=30)
                except requests.RequestException:
                    print("Could not reach Google to revoke; deleting the local token anyway.")
                p.unlink()
            print("Logged out.")
        elif a.cmd == "status":
            cfg = load_config()
            p = token_path()
            if p.exists():
                tok = json.loads(p.read_text())
                mins = (tok.get("expires_at", 0) - time.time()) / 60
                print(f"Logged in ({'refresh token saved' if tok.get('refresh_token') else 'no refresh token'}; "
                      f"access token {'valid for %d min' % mins if mins > 0 else 'will refresh on next use'}).")
            else:
                print("Not logged in.")
            cs = Path(cfg["client_secret"]).expanduser()
            print(f"Client file: {cs} ({'found' if cs.exists() else 'missing'})")
            print(f"Shop link: {cfg['shop_url'] or '(not set: add shop_url to ' + str(config_dir() / 'youtube.json') + ')'}")
            items = load_queue()
            print(f"Queue: {len(items)} items, {sum(i['status'] == 'uploaded' for i in items)} uploaded.")
            print(f"Rough quota (unverified, check Cloud Console): upload ~{QUOTA['videos.insert']}, "
                  f"thumbnail ~{QUOTA['thumbnails.set']} of {QUOTA['daily_default']} units a day.")
        elif a.cmd == "config":
            p = config_dir() / "youtube.json"
            if p.exists():
                print(f"{p} already exists:")
                print(p.read_text())
            elif a.init:
                _write_private(p, DEFAULT_CONFIG)
                print(f"Wrote {p}. Set shop_url and timezone in it.")
            else:
                print(json.dumps(DEFAULT_CONFIG, indent=1))
                print(f"\n(run with --init to write this to {p})")
        elif a.cmd == "queue":
            if a.qcmd == "add":
                it = queue_add(a.video, a.publish_at, a.kids, a.privacy, a.kind, a.thumb_at, a.confirm_fictional)
                print(f"Queued {it['id']}: {it['title']}\n  publish {it['publish_at'] or 'unscheduled'}, "
                      f"{'made for kids' if it['made_for_kids'] else 'not made for kids'}, "
                      f"thumbnail {it['thumbnail']}")
            elif a.qcmd == "list":
                _print_queue(load_queue())
            elif a.qcmd == "remove":
                items = load_queue()
                keep = [i for i in items if i["id"] != a.id or i["status"] == "uploaded"]
                if len(keep) == len(items):
                    print("Nothing removed (unknown id, or already uploaded).")
                else:
                    save_queue(keep); _save_session(a.id, None)
                    print("Removed.")
        elif a.cmd == "upload":
            upload(next_only=a.next, all_due=a.all_due, item_id=a.id, dry_run=a.dry_run, max_count=a.max)
        elif a.cmd == "plan":
            res = plan(a.weeks, a.city, a.per_week)
            for e in res["entries"]:
                print(f"{e['local']}  {e['kind']:<7} {'ready' if e['ready'] else 'TODO ':<5}  "
                      f"{e.get('title') or e['command']}")
            for w in res["warnings"]:
                print("warning:", w)
            print(f"\nWritten to {queue_path().parent / 'plan.md'} (nothing was uploaded).")
    except YouTubeError as e:
        print("Error:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
