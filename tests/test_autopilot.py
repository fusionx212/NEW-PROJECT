import datetime as dt
import json
import types

import pytest

from skysoftly import autopilot as ap


@pytest.fixture(autouse=True)
def cfgdir(tmp_path, monkeypatch):
    monkeypatch.setenv("SKYSOFTLY_CONFIG_DIR", str(tmp_path))
    return tmp_path


class Runner:
    def __init__(self, rc=0, stdout=""):
        self.calls, self.rc, self.stdout = [], rc, stdout

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return types.SimpleNamespace(returncode=self.rc, stdout=self.stdout)


def test_etsy_skipped_until_signed_in(cfgdir):
    r = Runner()
    assert ap.step_etsy(ap.load_config(), r).startswith("skipped")
    (cfgdir / "etsy.json").write_text("{}"); (cfgdir / "etsy_token.json").write_text("{}")
    assert ap.step_etsy(ap.load_config(), r) == "ok"
    cmd = r.calls[-1][0]
    assert cmd[1:4] == ["-m", "skysoftly.etsy", "fetch"] and "--video" in cmd


def test_youtube_once_a_day_after_the_quiet_hour():
    cfg = ap.load_config()
    early = dt.datetime(2026, 11, 2, 0, 30, tzinfo=dt.timezone.utc)      # 00:30 London
    late = dt.datetime(2026, 11, 2, 3, 0, tzinfo=dt.timezone.utc)
    assert not ap.youtube_due(cfg, {}, early)
    assert ap.youtube_due(cfg, {}, late)
    assert not ap.youtube_due(cfg, {"youtube_day": "2026-11-02"}, late)


def test_luna_only_and_rotates():
    cfg = ap.load_config()
    a = ap.luna_args(cfg, dt.date(2026, 11, 2), ap.REPO / "x")
    assert a[a.index("--name") + 1] == "Luna"
    b = ap.luna_args(cfg, dt.date(2026, 11, 3), ap.REPO / "x")
    assert a[a.index("--colour") + 1] != b[b.index("--colour") + 1]


def test_youtube_renders_missing_then_queues_and_uploads(monkeypatch):
    now = dt.datetime(2026, 11, 2, 3, 0, tzinfo=dt.timezone.utc)
    calls = {"plan": 0, "queued": []}

    def plan(weeks, city, per_week=4):
        calls["plan"] += 1
        ready = calls["plan"] > 1
        return {"timezone": "Europe/London", "entries": [
            {"publish_at": "2026-11-04T19:00:00Z", "kind": "nightly", "ready": ready, "video": "n.mp4"},
            {"publish_at": "2026-11-06T19:00:00Z", "kind": "long", "ready": ready, "video": "l.mp4" if ready else None},
            {"publish_at": "2026-12-20T19:00:00Z", "kind": "nightly", "ready": False, "video": "far.mp4"},
        ]}

    class YTErr(Exception):
        pass
    yt = types.SimpleNamespace(plan=plan, YouTubeError=YTErr,
                               queue_add=lambda v, publish_at=None: calls["queued"].append((v, publish_at)))
    monkeypatch.setattr(ap, "youtube_ready", lambda *a: True)
    r = Runner()
    out = ap.step_youtube(ap.load_config(), now, r, yt=yt)
    cmds = [c[0][2:] for c in r.calls]
    assert cmds[0][:2] == ["skysoftly", "nightly"] and "2026-11-04" in cmds[0]
    assert cmds[1][:2] == ["skysoftly", "story"] and "Luna" in cmds[1]
    assert not any("2026-12-20" in " ".join(c) for c in cmds)          # beyond the render horizon
    assert cmds[-1] == ["skysoftly.youtube", "upload", "--all-due"]
    assert [q[0] for q in calls["queued"]] == ["n.mp4", "l.mp4"]
    assert "2 rendered, 2 queued" in out


def test_once_records_state_and_skips_when_locked(cfgdir):
    r = Runner()
    res = ap.once(dt.datetime(2026, 11, 2, 0, 30, tzinfo=dt.timezone.utc), runner=r)
    assert res["etsy"].startswith("skipped")
    assert json.loads((cfgdir / "autopilot-state.json").read_text())["last"]["etsy"] == res["etsy"]
    with ap.single_run(cfgdir / "autopilot.lock") as got:
        assert got
        assert ap.once(runner=r) == {"skipped": True}


def test_install_cron_replaces_old_line(monkeypatch):
    r = Runner(stdout="0 1 * * * other job\n*/5 * * * * old  # com.littlelantern.autopilot\n")
    ap.install(10, system="Linux", runner=r)
    written = r.calls[-1][1]["input"]
    assert "other job" in written and "old  #" not in written
    assert "*/10 * * * *" in written and "skysoftly.autopilot once" in written


def test_install_mac_and_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(ap.Path, "home", classmethod(lambda cls: tmp_path))
    r = Runner()
    ap.install(10, system="Darwin", runner=r)
    plist = (tmp_path / "Library/LaunchAgents/com.littlelantern.autopilot.plist").read_text()
    assert "<integer>600</integer>" in plist and "skysoftly.autopilot" in plist
    ap.install(15, system="Windows", runner=r)
    assert r.calls[-1][0][:2] == ["schtasks", "/Create"] and "15" in r.calls[-1][0]
