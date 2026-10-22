"""Autopilot: runs the Etsy shop and the Little Lantern channel by itself on your computer.

    python -m skysoftly.autopilot config     write a starter config (~/.config/skysoftly/autopilot.json)
    python -m skysoftly.autopilot once       do one round now (what the scheduler runs)
    python -m skysoftly.autopilot install    run a round every 10 minutes from now on (Mac, Windows, Linux)
    python -m skysoftly.autopilot uninstall  stop the automatic runs
    python -m skysoftly.autopilot status     show what happened last

Each round:
  1. Etsy: checks for new paid orders and builds each gift pack (story, narration, video, storybook,
     certificate). Orders it can't read go to needs-review and you get an email.
  2. YouTube, once a day: plans the next two weeks, renders anything missing for the coming week
     (nightly sky episodes for your city, and Luna stories for the long slots), queues them, and
     uploads whatever is due. Videos go up private and publish themselves at their scheduled time.

YouTube only ever gets fictional heroes (Luna). Customer orders are never touched by the YouTube steps,
and the uploader refuses customer folders on its own as well.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shlex
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
LABEL = "com.littlelantern.autopilot"
TASK_NAME = "LittleLanternAutopilot"

DEFAULT = {
    "city": "London",
    "country": "GB",
    "timezone": "Europe/London",
    "every_minutes": 10,
    "etsy": True,
    "etsy_video": True,
    "youtube": True,
    "youtube_hour": 2,               # do the daily YouTube work from this local hour (quiet hours)
    "youtube_weeks": 2,
    "youtube_per_week": 4,
    "render_days_ahead": 7,
    "luna_animals": ["bunny"],       # add more as their Canva art is added to skysoftly/art
    "luna_colours": ["purple", "blue", "pink", "gold", "green"],
}


def config_dir() -> Path:
    return Path(os.environ.get("SKYSOFTLY_CONFIG_DIR") or Path.home() / ".config" / "skysoftly")


def load_config() -> dict:
    p = config_dir() / "autopilot.json"
    cfg = dict(DEFAULT)
    if p.exists():
        cfg.update(json.loads(p.read_text()))
    return cfg


def state_path() -> Path:
    return config_dir() / "autopilot-state.json"


def load_state() -> dict:
    p = state_path()
    return json.loads(p.read_text()) if p.exists() else {}


def save_state(st: dict):
    state_path().parent.mkdir(parents=True, exist_ok=True)
    state_path().write_text(json.dumps(st, indent=1))


def log(msg: str):
    line = f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}  {msg}"
    print(line, flush=True)


@contextmanager
def single_run(path: Path):
    """Only one round at a time: a slow video render must not be started twice."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        yield False
        return
    try:
        yield True
    finally:
        fh.close()


def py(*args: str) -> list[str]:
    return [sys.executable, "-m", *args]


def run(cmd: list[str], runner=subprocess.run) -> bool:
    log("  $ " + " ".join(shlex.quote(c) for c in cmd[2:]))
    r = runner(cmd, cwd=REPO)
    return getattr(r, "returncode", 0) == 0


# ------------------------------------------------------------------------------------------- steps

def etsy_ready() -> bool:
    d = config_dir()
    return ((d / "etsy.json").exists() or bool(os.environ.get("ETSY_KEYSTRING"))) and (d / "etsy_token.json").exists()


def youtube_ready(cfg_yt: dict | None = None) -> bool:
    from . import youtube as yt
    cfg_yt = cfg_yt or yt.load_config()
    return Path(cfg_yt["client_secret"]).expanduser().exists() and yt.token_path().exists()


def step_etsy(cfg: dict, runner=subprocess.run) -> str:
    if not cfg.get("etsy"):
        return "off"
    if not etsy_ready():
        return "skipped: not signed in (run: python -m skysoftly.etsy login)"
    cmd = py("skysoftly.etsy", "fetch") + (["--video"] if cfg.get("etsy_video") else [])
    return "ok" if run(cmd, runner) else "failed"


def youtube_due(cfg: dict, st: dict, now: dt.datetime) -> bool:
    local = now.astimezone(ZoneInfo(cfg["timezone"]))
    return st.get("youtube_day") != local.date().isoformat() and local.hour >= int(cfg["youtube_hour"])


def luna_args(cfg: dict, day: dt.date, out: Path) -> list[str]:
    animals, colours = cfg["luna_animals"] or ["bunny"], cfg["luna_colours"] or ["purple"]
    n = day.toordinal()
    return ["--name", "Luna", "--pronoun", "she", "--animal", animals[n % len(animals)],
            "--colour", colours[(n // len(animals)) % len(colours)], "--video", "--out", str(out)]


def step_youtube(cfg: dict, now: dt.datetime | None = None, runner=subprocess.run, yt=None) -> str:
    if yt is None:
        from . import youtube as yt
    if not cfg.get("youtube"):
        return "off"
    if not youtube_ready():
        return "skipped: not signed in (run: python -m skysoftly.youtube login)"
    now = now or dt.datetime.now(dt.timezone.utc)
    horizon = now + dt.timedelta(days=int(cfg["render_days_ahead"]))
    plan = yt.plan(int(cfg["youtube_weeks"]), cfg["city"], per_week=int(cfg["youtube_per_week"]))
    rendered = 0
    for e in plan["entries"]:
        when = dt.datetime.fromisoformat(e["publish_at"].replace("Z", "+00:00"))
        if e.get("ready") or when > horizon:
            continue
        day = when.astimezone(ZoneInfo(plan["timezone"])).date()
        if e["kind"] == "nightly":
            cmd = py("skysoftly", "nightly", "--city", cfg["city"], "--start", day.isoformat(), "--days", "1", "--video")
            if cfg.get("country"):
                cmd += ["--country", cfg["country"]]
        else:
            cmd = py("skysoftly", "story", *luna_args(cfg, day, REPO / "output" / "stories" / f"luna-{day.isoformat()}"))
        rendered += run(cmd, runner)
    # plan again now that new videos exist, then queue everything that is ready for its slot
    plan = yt.plan(int(cfg["youtube_weeks"]), cfg["city"], per_week=int(cfg["youtube_per_week"]))
    queued = 0
    for e in plan["entries"]:
        if e.get("ready") and not e.get("queued") and e.get("video"):
            try:
                yt.queue_add(e["video"], publish_at=e["publish_at"])
                queued += 1
            except yt.YouTubeError as err:
                log(f"  not queued: {err}")
    ok = run(py("skysoftly.youtube", "upload", "--all-due"), runner)
    return f"{'ok' if ok else 'upload failed'}: {rendered} rendered, {queued} queued"


def once(now: dt.datetime | None = None, runner=subprocess.run) -> dict:
    cfg = load_config()
    now = now or dt.datetime.now(dt.timezone.utc)
    with single_run(config_dir() / "autopilot.lock") as got:
        if not got:
            log("Another round is still running (probably rendering a video). Skipping this one.")
            return {"skipped": True}
        st = load_state()
        result = {"at": now.isoformat(timespec="seconds")}
        for name, fn in (("etsy", lambda: step_etsy(cfg, runner)),):
            try:
                result[name] = fn()
            except Exception:
                result[name] = "error"; log(traceback.format_exc())
        if youtube_due(cfg, st, now):
            try:
                result["youtube"] = step_youtube(cfg, now, runner)
                if not result["youtube"].startswith("skipped"):
                    st["youtube_day"] = now.astimezone(ZoneInfo(cfg["timezone"])).date().isoformat()
            except Exception:
                result["youtube"] = "error"; log(traceback.format_exc())
        st["last"] = result
        st.setdefault("history", []).append(result)
        st["history"] = st["history"][-50:]
        save_state(st)
        log("round: " + ", ".join(f"{k} {v}" for k, v in result.items() if k != "at"))
        return result


# ------------------------------------------------------------------------------------ scheduling

def log_file() -> Path:
    return REPO / "output" / "autopilot.log"


def cron_line(every: int) -> str:
    return (f"*/{every} * * * * cd {shlex.quote(str(REPO))} && {shlex.quote(sys.executable)} -m skysoftly.autopilot once "
            f">> {shlex.quote(str(log_file()))} 2>&1  # {LABEL}")


def launchd_plist(every: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{sys.executable}</string><string>-m</string><string>skysoftly.autopilot</string><string>once</string>
  </array>
  <key>WorkingDirectory</key><string>{REPO}</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StartInterval</key><integer>{every * 60}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{log_file()}</string>
  <key>StandardErrorPath</key><string>{log_file()}</string>
</dict></plist>
"""


def windows_cmd() -> str:
    return (f'@echo off\r\ncd /d "{REPO}"\r\n"{sys.executable}" -m skysoftly.autopilot once >> "{log_file()}" 2>&1\r\n')


def install(every: int | None = None, system: str | None = None, runner=subprocess.run) -> str:
    every = int(every or load_config()["every_minutes"])
    system = system or platform.system()
    log_file().parent.mkdir(parents=True, exist_ok=True)
    if system == "Darwin":
        p = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        p.parent.mkdir(parents=True, exist_ok=True)
        runner(["launchctl", "unload", str(p)], capture_output=True)
        p.write_text(launchd_plist(every))
        runner(["launchctl", "load", str(p)], check=True)
        return f"Installed: runs every {every} minutes while you're logged in ({p})."
    if system == "Windows":
        bat = config_dir() / "autopilot-run.cmd"
        bat.parent.mkdir(parents=True, exist_ok=True)
        bat.write_text(windows_cmd())
        runner(["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", str(every), "/TN", TASK_NAME, "/TR", f'"{bat}"'],
               check=True)
        return f"Installed: Task Scheduler runs '{TASK_NAME}' every {every} minutes."
    current = runner(["crontab", "-l"], capture_output=True, text=True)
    lines = [ln for ln in (current.stdout or "").splitlines() if LABEL not in ln]
    lines.append(cron_line(every))
    runner(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
    return f"Installed: cron runs every {every} minutes."


def uninstall(system: str | None = None, runner=subprocess.run) -> str:
    system = system or platform.system()
    if system == "Darwin":
        p = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        runner(["launchctl", "unload", str(p)], capture_output=True)
        p.unlink(missing_ok=True)
    elif system == "Windows":
        runner(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], capture_output=True)
    else:
        current = runner(["crontab", "-l"], capture_output=True, text=True)
        lines = [ln for ln in (current.stdout or "").splitlines() if LABEL not in ln]
        runner(["crontab", "-"], input="\n".join(lines) + ("\n" if lines else ""), text=True, check=True)
    return "Automatic runs stopped."


def status() -> str:
    st = load_state()
    out = [f"Etsy signed in: {'yes' if etsy_ready() else 'no'}"]
    try:
        out.append(f"YouTube signed in: {'yes' if youtube_ready() else 'no'}")
    except Exception as e:
        out.append(f"YouTube: {e}")
    out.append(f"Last YouTube day: {st.get('youtube_day', 'never')}")
    for r in st.get("history", [])[-10:]:
        out.append("  " + r.get("at", "?") + "  " + ", ".join(f"{k} {v}" for k, v in r.items() if k != "at"))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skysoftly.autopilot", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("config", help="write a starter config")
    sub.add_parser("once", help="do one round now")
    sub.add_parser("loop", help="keep running rounds in this window (Ctrl+C to stop)")
    i = sub.add_parser("install", help="run automatically from now on")
    i.add_argument("--every", type=int, help="minutes between rounds (default from config: 10)")
    sub.add_parser("uninstall", help="stop running automatically")
    sub.add_parser("status", help="show the last rounds")
    a = ap.parse_args(argv)
    if a.cmd == "config":
        p = config_dir() / "autopilot.json"
        if p.exists():
            print(f"Already exists: {p}")
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(DEFAULT, indent=1) + "\n")
            print(f"Wrote {p}. Set your city, country and timezone there.")
    elif a.cmd == "once":
        once()
    elif a.cmd == "loop":
        every = int(load_config()["every_minutes"])
        try:
            while True:
                once()
                time.sleep(every * 60)
        except KeyboardInterrupt:
            print("\nStopped.")
    elif a.cmd == "install":
        print(install(a.every))
        print(f"Log: {log_file()}   Check with: python -m skysoftly.autopilot status")
    elif a.cmd == "uninstall":
        print(uninstall())
    elif a.cmd == "status":
        print(status())


if __name__ == "__main__":
    main()
