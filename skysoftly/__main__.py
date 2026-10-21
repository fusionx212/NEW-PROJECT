"""Command line: `python -m skysoftly nightly ...` and `python -m skysoftly keepsake ...`."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from .engine import Place, find_place, sky_for


def _place(a) -> Place:
    if a.lat is not None and a.lon is not None:
        if not a.tz:
            raise SystemExit("--tz is required with --lat/--lon (e.g. Europe/London)")
        return Place(a.place_name or f"{a.lat:.2f}, {a.lon:.2f}", a.lat, a.lon, a.tz, a.country or "")
    if not a.city:
        raise SystemExit("Give --city (and optionally --country) or --lat --lon --tz")
    p = find_place(a.city, a.country)
    if a.place_name:
        p.name = a.place_name
    return p


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _write_script(path: Path, title: str, text: str):
    clean = re.sub(r"\s*\[pause [\d.]+\]\s*", " ", text)
    path.write_text(f"# {title}\n\n" + "\n\n".join(p.strip() for p in clean.split("\n\n")) + "\n")


def cmd_nightly(a):
    from .script import nightly_script
    from .chart import lookup_card, cover_art
    place = _place(a)
    start = dt.date.fromisoformat(a.start)
    out = Path(a.out or f"output/nightly/{_slugify(place.name)}")
    out.mkdir(parents=True, exist_ok=True)
    for i in range(a.days):
        day = start + dt.timedelta(days=i)
        sky = sky_for(place, day)
        text = nightly_script(sky)
        slug = day.isoformat()
        ep = out / slug
        ep.mkdir(exist_ok=True)
        title = f"{place.name}: {day.strftime('%A %d %B %Y')}"
        (ep / "sky.json").write_text(json.dumps(sky, indent=1))
        _write_script(ep / "script.md", f"Tonight's Sky, Softly. {title}", text)
        lookup_card(sky, ep / "lookup-card")
        meta = {"slug": slug, "date": slug, "title": title, "audio": "episode.mp3", "bytes": 0, "duration_s": 0,
                "summary": _summary(sky)}
        if not a.no_audio:
            from .render import render
            mp3 = ep / "episode.mp3"
            meta["duration_s"] = round(render(text, mp3, voice=a.voice, title=title, album=f"Tonight's Sky, Softly: {place.name}",
                                              seed=day.toordinal() % 97, root_hz=[98.0, 110.0, 87.3, 103.8][day.toordinal() % 4]), 1)
            meta["bytes"] = mp3.stat().st_size
        (ep / "episode.json").write_text(json.dumps(meta, indent=1))
        print(f"  {slug}  {meta['duration_s']:>6.0f}s  {meta['summary']}")
    cover_art(sky_for(place, start), out / "cover.png", place.name)
    if a.base_url:
        from .feed import build_feed
        print("  feed:", build_feed(out, a.base_url, place.name))
    print("Done:", out)


def _summary(sky: dict) -> str:
    ph = sky["moon"]["extra"]["phase"]
    bits = [ph if ph.endswith("Moon") else f"{ph} Moon"]
    up = [p["name"] for p in sky["planets"] if p["status"] == "up"]
    if up:
        bits.append(", ".join(up) + (" up" if len(up) > 1 else " is up"))
    if sky["zenith_constellation"]:
        bits.append(f"{sky['zenith_constellation']} overhead")
    if sky["meteors_active"]:
        bits.append(f"{sky['meteors_active'][0]['name']} meteor shower")
    return "; ".join(bits) + "."


HEADLINES = {"birth": "The night {name} was born", "wedding": "The night {name} were married",
             "memorial": "Remembering {name}", "meeting": "The night {name} met", "custom": "{name}"}


def cmd_keepsake(a):
    from .script import keepsake_script
    from .chart import keepsake_page
    place = _place(a)
    when = dt.datetime.combine(dt.date.fromisoformat(a.date), dt.time.fromisoformat(a.time))
    sky = sky_for(place, when.date(), when.time())
    text = keepsake_script(sky, a.occasion, a.name, when)
    headline = HEADLINES[a.occasion].format(name=a.name)
    out = Path(a.out or f"output/keepsakes/{_slugify(a.name)}-{a.date}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "sky.json").write_text(json.dumps(sky, indent=1))
    _write_script(out / "letter.md", headline, text)
    keepsake_page(sky, out / "sky-chart-and-letter", headline, text, when)
    if not a.no_audio:
        from .render import render
        d = render(text, out / "letter-from-the-sky.mp3", voice=a.voice, title=headline, album="A letter from the sky",
                   root_hz=87.3, seed=11, speed=0.85)
        print(f"  audio {d:.0f}s")
    print("Done:", out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skysoftly", description="Tonight's Sky, Softly: real-sky bedtime audio and keepsakes.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("nightly", "keepsake"):
        p = sub.add_parser(name)
        p.add_argument("--city"); p.add_argument("--country", help="ISO country code, e.g. US, GB")
        p.add_argument("--lat", type=float); p.add_argument("--lon", type=float); p.add_argument("--tz")
        p.add_argument("--place-name", help="How the narrator should name the place")
        p.add_argument("--voice", default="af_heart", help="Kokoro voice, e.g. af_heart, bf_emma, bm_george")
        p.add_argument("--out"); p.add_argument("--no-audio", action="store_true", help="Scripts and charts only (fast)")
    n = sub.choices["nightly"]
    n.add_argument("--start", default=dt.date.today().isoformat()); n.add_argument("--days", type=int, default=7)
    n.add_argument("--base-url", help="Public URL where the folder will be hosted; writes feed.xml")
    k = sub.choices["keepsake"]
    k.add_argument("--date", required=True); k.add_argument("--time", default="21:00")
    k.add_argument("--occasion", choices=list(HEADLINES), default="birth")
    k.add_argument("--name", required=True, help="e.g. 'Maya', or 'Sam and Alex' for a wedding")
    a = ap.parse_args(argv)
    {"nightly": cmd_nightly, "keepsake": cmd_keepsake}[a.cmd](a)


if __name__ == "__main__":
    main()
