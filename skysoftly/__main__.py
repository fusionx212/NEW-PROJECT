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
            if a.video:
                from .video import make_video
                ph = sky["moon"]["extra"]["phase"]
                make_video(mp3, ep / "episode.mp4", title="Tonight's Sky, Softly",
                           subtitle=f"{place.name} · {day.strftime('%A %d %B %Y')} · {ph if ph.endswith('Moon') else ph + ' Moon'}",
                           seed=day.toordinal(), size=_size(a.video_size))
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


def _size(s: str) -> tuple[int, int]:
    w, h = s.lower().split("x")
    return int(w), int(h)


def cmd_video(a):
    from .video import make_video, name_style
    seed, palette = a.seed, a.palette
    if a.nebula_name:
        seed, auto = name_style(a.nebula_name)
        palette = palette or auto
    out = make_video(Path(a.audio), Path(a.out), title=a.title, subtitle=a.subtitle or "", end_line=a.end_line,
                     seed=seed, palette=palette, size=_size(a.video_size), star_name=a.star_name,
                     star_caption=a.star_caption or "", zoom=a.zoom)
    print("Done:", out)


CAPTIONS = {"birth": "Born {date} · {place}", "wedding": "Married {date} · {place}", "memorial": "Remembered · {date} · {place}",
            "meeting": "Met {date} · {place}", "custom": "{date} · {place}"}

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
                   root_hz=87.3, seed=11)
        print(f"  audio {d:.0f}s")
        if a.video:
            from .video import make_video, name_style
            seed, palette = name_style(a.name)
            make_video(out / "letter-from-the-sky.mp3", out / "letter-from-the-sky.mp4", title=headline,
                       subtitle=f"{place.name} · {when.strftime('%d %B %Y')}", end_line="With love, from the sky.",
                       seed=seed, palette=palette, size=_size(a.video_size),
                       star_name=a.name, star_caption=CAPTIONS[a.occasion].format(date=when.strftime('%d %B %Y').lstrip('0'), place=place.name))
            print("  video", out / "letter-from-the-sky.mp4")
    print("Done:", out)


def cmd_story(a):
    """A complete personalised gift pack: narrated story, deep-zoom video, storybook PDF and certificate."""
    import zipfile
    from .nebula import make_nebula, style_for
    from .script import words
    from .story import StoryOrder, make_story, story_title, style_for_colour
    from .storybook import make_storybook
    from .zoom import build_levels, pick_star_spot
    order = StoryOrder(name=a.name, pronoun=a.pronoun, age=a.age, animal=a.animal, colour=a.colour,
                       giver=a.giver, message=a.message, occasion="birthday" if a.age else "bedtime")
    sky, born, place_name = None, None, None
    if a.born:
        born = dt.date.fromisoformat(a.born)
        place = _place(a)
        place_name = place.name
        sky = sky_for(place, born, dt.time.fromisoformat(a.born_time))
    title = story_title(order)
    text, tags = make_story(order, sky, born, with_scenes=True)
    out = Path(a.out or f"output/stories/{_slugify(a.name)}")
    out.mkdir(parents=True, exist_ok=True)
    _write_script(out / "story.md", title, text)
    style = style_for_colour(a.colour)
    seed = style_for(a.name)[0]
    caption = f"{a.name}'s Nebula" + (f" · {words(a.age).capitalize()} today" if a.age else "")
    print("  storybook")
    gas, _ = make_nebula(seed, style, 2048)
    levels = build_levels(gas, pick_star_spot(gas), 7, seed, log=lambda *x: None)
    files = make_storybook(out / "storybook.pdf", title=title, name=a.name, script=text, levels=levels,
                           giver=a.giver, message=a.message, sky=sky, born=born, place=place_name, caption=caption)
    if not a.no_audio:
        from .render import render
        print("  narration")
        d = render(text, out / "story.mp3", voice=a.voice, title=title, album="Tonight's Sky, Softly: Bedtime Stories",
                   root_hz=87.3, seed=seed % 97, timing_json=out / "story.timing.json")
        from .storyvideo import write_chapters
        write_chapters(out / "story.timing.json", tags, out / "chapters.json")
        print(f"  audio {d / 60:.1f} min")
        files.append(out / "story.mp3")
        if a.video:
            print("  video")
            if a.video_style == "zoom":
                from .video import make_video
                make_video(out / "story.mp3", out / "story.mp4", title=title, subtitle="A bedtime story", seed=seed,
                           palette=style, size=_size(a.video_size), star_name=a.name, star_caption=caption)
            else:
                from .storyvideo import render_story_video
                render_story_video(out / "story.mp3", out / "story.timing.json", tags, out / "story.mp4", seed=seed,
                                   style=style, name=a.name, animal=a.animal.lower(), caption=caption, title=title,
                                   sky=sky, giver_message=a.message, size=_size(a.video_size))
            files.append(out / "story.mp4")
    (out / "How to enjoy your gift.txt").write_text(
        f"{title}\n\n"
        "Inside this pack:\n"
        "  story.mp3          the bedtime story, read slowly and softly. Play it at lights-out.\n"
        "  story.mp4          the same story with a slow journey into the child's own nebula, landing on their name.\n"
        "  storybook.pdf      the illustrated storybook to read together or print at home (8 x 8 inches).\n"
        "  certificate.jpg    the nebula certificate, ready to print and frame.\n"
        "  cover.jpg          the book cover, nice for sharing.\n\n"
        "The narration uses a synthetic voice. Every sky detail in the story is computed from the real sky.\n")
    files.append(out / "How to enjoy your gift.txt")
    with zipfile.ZipFile(out / f"{_slugify(a.name)}-gift-pack.zip", "w", zipfile.ZIP_STORED) as z:
        for f in files:
            if Path(f).exists():
                z.write(f, Path(f).name)
    print("Done:", out)


def cmd_products(a):
    """Printables and listing photos from one order: nursery print, party kit, colouring page, bedtime chart, wallpaper."""
    from PIL import Image
    from .mockups import flat_lay, nursery_wall, phone_on_table
    from .nebula import make_nebula, style_for
    from .products import Order, make_all
    from .story import style_for_colour
    from .zoom import build_levels, pick_star_spot
    sky, born, place_name = None, None, None
    if a.born:
        born = dt.date.fromisoformat(a.born)
        place = _place(a)
        place_name = place.name
        sky = sky_for(place, born, dt.time.fromisoformat(a.born_time))
    seed = style_for(a.name)[0]
    gas, _ = make_nebula(seed, style_for_colour(a.colour), 2048)
    levels = build_levels(gas, pick_star_spot(gas), 5, seed, log=lambda *x: None)
    out = Path(a.out or f"output/products/{_slugify(a.name)}")
    o = Order(a.name, a.age, a.animal, born, place_name, a.party, a.rsvp, sky)
    made = make_all(o, levels, out)
    for k, v in made.items():
        print(f"  {k}: {len(v)} file(s)")
    if a.mockups:
        ph = out / "listing-photos"; ph.mkdir(exist_ok=True)
        nursery_wall(Image.open(made["nursery print"][0])).save(ph / "nursery-wall.jpg", quality=90)
        flat_lay(Image.open(made["party kit"][0])).save(ph / "invitation-flatlay.jpg", quality=90)
        phone_on_table(Image.open(made["wallpaper"][0])).save(ph / "wallpaper-phone.jpg", quality=90)
        print("  listing photos:", ph)
    print("Done:", out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skysoftly", description="Tonight's Sky, Softly: real-sky bedtime audio and keepsakes.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("nightly", "keepsake"):
        p = sub.add_parser(name)
        p.add_argument("--city"); p.add_argument("--country", help="ISO country code, e.g. US, GB")
        p.add_argument("--lat", type=float); p.add_argument("--lon", type=float); p.add_argument("--tz")
        p.add_argument("--place-name", help="How the narrator should name the place")
        p.add_argument("--voice", default="softly", help="softly (default: quiet British), nicole, heart, emma, or any Kokoro voice id")
        p.add_argument("--out"); p.add_argument("--no-audio", action="store_true", help="Scripts and charts only (fast)")
        p.add_argument("--video", action="store_true", help="Also render a moving-nebula MP4 for each audio file")
        p.add_argument("--video-size", default="1280x720", help="e.g. 1280x720, 1920x1080, or 1080x1920 for Reels/TikTok")
    n = sub.choices["nightly"]
    n.add_argument("--start", default=dt.date.today().isoformat()); n.add_argument("--days", type=int, default=7)
    n.add_argument("--base-url", help="Public URL where the folder will be hosted; writes feed.xml")
    k = sub.choices["keepsake"]
    k.add_argument("--date", required=True); k.add_argument("--time", default="21:00")
    k.add_argument("--occasion", choices=list(HEADLINES), default="birth")
    k.add_argument("--name", required=True, help="e.g. 'Maya', or 'Sam and Alex' for a wedding")
    v = sub.add_parser("video", help="Moving-nebula video for any audio file")
    v.add_argument("--audio", required=True); v.add_argument("--out", required=True)
    v.add_argument("--title", default="Tonight's Sky, Softly"); v.add_argument("--subtitle")
    v.add_argument("--end-line", default="Goodnight."); v.add_argument("--seed", type=int, default=1)
    v.add_argument("--nebula-name", help="Grow a unique nebula from a name (same name, same nebula, every time)")
    v.add_argument("--star-name", help="Land the zoom on a star that bursts into this name")
    v.add_argument("--star-caption", help="Small line under the name, e.g. 'Born 2 May 2024 · Leeds'")
    v.add_argument("--zoom", type=float, default=48.0, help="How far the camera zooms in (default 48x)")
    v.add_argument("--palette", choices=["hubble", "natural", "jwst", "violet"], help="Colour style; default comes from the name or seed")
    v.add_argument("--video-size", default="1280x720")
    st = sub.add_parser("story", help="Personalised bedtime story gift pack")
    st.add_argument("--name", required=True); st.add_argument("--pronoun", choices=["she", "he", "they"], default="they")
    st.add_argument("--age", type=int, help="Makes it a birthday story with one wish per year")
    st.add_argument("--animal", default="fox", help="Their favourite animal becomes a starlight companion")
    st.add_argument("--colour", default="purple", help="Favourite colour picks the nebula's colours")
    st.add_argument("--from", dest="giver", help="Who the gift is from, e.g. 'Grandma and Grandpa'")
    st.add_argument("--message", help="A short message the star reads out")
    st.add_argument("--born", help="Birth date (YYYY-MM-DD) to weave in the real sky of that night")
    st.add_argument("--born-time", default="21:00")
    st.add_argument("--city"); st.add_argument("--country"); st.add_argument("--lat", type=float); st.add_argument("--lon", type=float)
    st.add_argument("--tz"); st.add_argument("--place-name")
    st.add_argument("--voice", default="softly"); st.add_argument("--out")
    st.add_argument("--no-audio", action="store_true"); st.add_argument("--video", action="store_true")
    st.add_argument("--video-size", default="1280x720")
    st.add_argument("--video-style", choices=["animated", "zoom"], default="animated",
                    help="animated: illustrated scenes that follow the story (default); zoom: the deep nebula dive")
    pr = sub.add_parser("products", help="Printables from one order: nursery print, party kit, colouring, chart, wallpaper")
    pr.add_argument("--name", required=True); pr.add_argument("--age", type=int); pr.add_argument("--animal", default="fox")
    pr.add_argument("--colour", default="purple"); pr.add_argument("--born"); pr.add_argument("--born-time", default="21:00")
    pr.add_argument("--city"); pr.add_argument("--country"); pr.add_argument("--lat", type=float); pr.add_argument("--lon", type=float)
    pr.add_argument("--tz"); pr.add_argument("--place-name")
    pr.add_argument("--party", help="Party details, lines separated by |, e.g. 'Saturday 2 May | 2pm to 4pm | Leeds Community Hall'")
    pr.add_argument("--rsvp", help="e.g. 'to Sarah on 07700 900123'")
    pr.add_argument("--mockups", action="store_true", help="Also render lifestyle listing photos")
    pr.add_argument("--out")
    a = ap.parse_args(argv)
    {"nightly": cmd_nightly, "keepsake": cmd_keepsake, "video": cmd_video, "story": cmd_story, "products": cmd_products}[a.cmd](a)


if __name__ == "__main__":
    main()
