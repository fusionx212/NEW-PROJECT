"""Fast tests: no TTS model needed."""
import datetime as dt
import re
import xml.dom.minidom

import pytest

from skysoftly.engine import Place, find_place, sky_for, radec_to_altaz
from skysoftly.script import nightly_script, keepsake_script, spoken_time, words, year_words, direction

BOULDER = Place("Boulder", 40.01499, -105.27055, "America/Denver", "US")
LONDON = Place("London", 51.50853, -0.12574, "Europe/London", "GB")
SYDNEY = Place("Sydney", -33.86785, 151.20732, "Australia/Sydney", "AU")


def test_words_and_times():
    assert words(21) == "twenty-one"
    assert words(1957) == "one thousand nine hundred and fifty-seven"
    assert year_words(1994) == "nineteen ninety-four"
    assert year_words(2001) == "two thousand and one"
    assert year_words(1905) == "nineteen oh five"
    assert spoken_time(dt.datetime(2026, 1, 1, 19, 42)) == "twenty to eight in the evening"
    assert spoken_time(dt.datetime(2026, 1, 1, 23, 58)) == "midnight"
    assert direction(135) == "south-east" and direction(359) == "north"


def test_city_lookup_offline():
    p = find_place("Boulder", "US")
    assert p.tz == "America/Denver" and abs(p.lat - 40.0) < 0.1


def test_full_moon_named_only_on_the_right_night():
    # Full moon: 2026-10-26 04:11 UTC = 25 Oct 22:11 in Boulder
    phases = {d: sky_for(BOULDER, dt.date(2026, 10, d))["moon"]["extra"]["phase"] for d in (24, 25, 26)}
    assert phases[25] == "Full Moon"
    assert phases[24] == "Waxing Gibbous" and phases[26] == "Waning Gibbous"


def test_positions_match_known_sky():
    s = sky_for(BOULDER, dt.date(2026, 10, 21))
    sat = next(p for p in s["planets"] if p["name"] == "Saturn")
    assert sat["status"] == "up" and 90 < sat["az"] < 130
    assert s["zenith_constellation"] == "Cygnus"
    assert any(m["name"] == "Orionids" and m["days_to_peak"] == 0 for m in s["meteors_active"])


def test_polaris_altitude_equals_latitude():
    # Polaris (J2000 RA 37.95, Dec 89.26) sits about the observer's latitude above the north horizon
    s = sky_for(LONDON, dt.date(2026, 1, 1))
    alt, az = radec_to_altaz(37.95, 89.26, s["lst_rad"], LONDON.lat)
    assert abs(alt - LONDON.lat) < 1.0 and (az < 3 or az > 357)


def test_solstice_same_day_and_hemisphere_wording():
    s = sky_for(LONDON, dt.date(2026, 6, 21))
    assert s["season"] == {"kind": "solstice", "date": "2026-06-21", "days": 0, "month": 6}
    assert s["still_light_at_look"] is True
    text = nightly_script(s)
    assert "longest day of the year" in text
    syd = sky_for(SYDNEY, dt.date(2026, 6, 21))
    assert "shortest day of the year" in nightly_script(syd)


@pytest.mark.parametrize("place,day", [(BOULDER, "2026-10-21"), (LONDON, "2026-06-21"), (SYDNEY, "2026-12-14")])
def test_scripts_are_clean(place, day):
    s = sky_for(place, dt.date.fromisoformat(day))
    for text in (nightly_script(s), keepsake_script(s, "birth", "Maya", dt.datetime.fromisoformat(day + "T21:00"))):
        assert "{" not in text and "}" not in text and "None" not in text
        spoken = re.sub(r"\[pause [\d.]+\]", "", text)
        assert not re.search(r"\d", spoken.replace("Rigil Kentaurus", "")), "digits should be spelled out for TTS"
        assert 250 < len(spoken.split()) < 1100


def test_week_has_no_identical_scripts():
    texts = {nightly_script(sky_for(BOULDER, dt.date(2026, 10, 21) + dt.timedelta(days=i))) for i in range(7)}
    assert len(texts) == 7


def test_card_and_feed(tmp_path):
    from skysoftly.chart import lookup_card
    from skysoftly.feed import build_feed
    import json
    s = sky_for(BOULDER, dt.date(2026, 10, 21))
    png, pdf = lookup_card(s, tmp_path / "ep" / "card")
    assert png.stat().st_size > 50_000 and pdf.stat().st_size > 10_000
    (tmp_path / "ep" / "episode.json").write_text(json.dumps(
        {"slug": "ep", "date": "2026-10-21", "title": "t & t", "audio": "episode.mp3", "bytes": 1, "duration_s": 300, "summary": "s"}))
    feed = build_feed(tmp_path, "https://example.com/x", "Boulder")
    xml.dom.minidom.parse(str(feed))


def test_video_short_clip(tmp_path):
    import subprocess
    import numpy as np
    from skysoftly.video import make_video
    wav = tmp_path / "a.wav"
    import soundfile as sf
    sf.write(wav, (0.1 * np.sin(np.linspace(0, 2000, 24000 * 2))).astype(np.float32), 24000)
    out = make_video(wav, tmp_path / "v.mp4", title="Test", subtitle="Sub", seed=2, size=(320, 180), still_px=512,
                     star_name="Maya", star_caption="Born today", log=lambda *a: None)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True, check=True).stdout.split()
    assert sorted(probe) == ["audio", "video"]


def test_name_style_is_stable_and_varied():
    from skysoftly.video import name_style
    assert name_style("Maya") == name_style(" maya ")
    assert len({name_style(n) for n in ["Maya", "Leo", "Amara", "Noah", "Isla", "Oliver"]}) == 6


def test_nebula_still_has_structure():
    import numpy as np
    from skysoftly.nebula import make_nebula
    gas, stars = make_nebula(7, "natural", 512)
    lum = gas.mean(-1)
    assert gas.shape == (512, 512, 3) and stars.shape == (512, 512, 3)
    assert (lum < 0.05).mean() > 0.15          # real dark sky around the cloud
    assert np.percentile(lum, 99) > 0.3        # and bright glowing gas
    assert stars.max() > 0.9                   # bright stars


def test_zoom_levels_hold_their_tone():
    import numpy as np
    from skysoftly.nebula import make_nebula
    from skysoftly.zoom import build_levels, pick_star_spot
    gas, _ = make_nebula(3, "jwst", 512)
    T = pick_star_spot(gas)
    assert 128 <= T[0] <= 384 and 128 <= T[1] <= 384
    lv = build_levels(gas, T, 5, 3, log=lambda *a: None)
    means = [np.asarray(im, dtype=np.float32).mean() for im in lv[1:]]
    stds = [np.asarray(im.convert("L"), dtype=np.float32).std() for im in lv[1:]]
    assert max(means) / min(means) < 1.6          # no drift to black or white as the zoom deepens
    assert min(stds) > 0.6 * max(stds)            # contrast holds at depth


def test_story_personalisation_and_real_sky():
    import re
    from skysoftly.story import StoryOrder, make_story, story_title
    born = dt.date(2021, 5, 2)
    sky = sky_for(LONDON, born, dt.time(21, 0))
    o = StoryOrder(name="Isla", pronoun="she", age=5, animal="bunny", colour="purple", giver="Grandma", message="We love you.")
    t = make_story(o, sky, born)
    assert story_title(o) == "Isla and the Star That Knew Her Name"
    spoken = re.sub(r"\[pause [\d.]+\]", "", t)
    assert "Five wishes" in t and "fifth birthday" in t
    assert "starlight bunny" in t and "It's from Grandma" in t and "We love you." in t
    assert "twenty twenty-one" in t and sky["zenith_constellation"] in t
    assert not re.search(r"\d", spoken)
    assert "{" not in t and "None" not in t
    plain = make_story(StoryOrder(name="Leo"), None, None)          # no birth details, no age, they/them
    assert "wishes" not in plain.split("present for you")[0] and "Leo" in plain


def test_storybook_pdf(tmp_path):
    from PIL import Image
    from skysoftly.story import StoryOrder, make_story, story_title
    from skysoftly.storybook import make_storybook
    levels = [Image.new("RGB", (512, 512), (40, 20, 70)) for _ in range(3)]
    o = StoryOrder(name="Leo", age=3)
    pdf, cover, cert = make_storybook(tmp_path / "book.pdf", title=story_title(o), name="Leo", script=make_story(o),
                                      levels=levels, giver="Mum", caption="Leo's Nebula")
    assert pdf.stat().st_size > 50_000 and cover.exists() and cert.exists()


def test_products_and_mockups(tmp_path):
    from PIL import Image
    from skysoftly.products import Order, make_all
    from skysoftly.mockups import nursery_wall, flat_lay
    levels = [Image.new("RGB", (512, 512), (50, 25, 80)) for _ in range(3)]
    o = Order("Leo", 3, "fox", dt.date(2023, 3, 1), "York", "Sunday 1 March | 2pm", "to Sam")
    made = make_all(o, levels, tmp_path)
    banner = [p for p in made["party kit"] if "banner" in p.name]
    assert len(banner) == len("HAPPY BIRTHDAY LEO")                  # one flag per letter and one star per space
    for group in made.values():
        for p in group:
            assert p.exists() and p.stat().st_size > 10_000
    inv = Image.open(made["party kit"][0])
    assert inv.size == (1500, 2100)                                   # 5 x 7 inches at 300 dpi
    assert nursery_wall(Image.open(made["nursery print"][0])).size == (2000, 2000)
    assert flat_lay(inv).size == (2000, 2000)


def test_story_scene_tags_and_chapters(tmp_path):
    import json
    from skysoftly.story import StoryOrder, make_story
    from skysoftly.storyvideo import write_chapters
    text, tags = make_story(StoryOrder(name="Isla", age=5, giver="Gran"), None, None, with_scenes=True)
    assert len(text.split("\n\n")) == len(tags)
    assert tags[0] == "settle" and tags[-1] == "goodnight" and "countdown" in tags and "wishes" in tags
    timing = {"paragraphs": [{"start": 3.0 + 10 * i, "end": 13.0 + 10 * i, "sentences": []} for i in range(len(tags))]}
    (tmp_path / "t.json").write_text(json.dumps(timing))
    ch = json.loads(write_chapters(tmp_path / "t.json", tags, tmp_path / "c.json").read_text())["chapters"]
    assert ch[0]["start"] == 0.0 and ch[-1]["title"] == "Goodnight"
    assert len(ch) == len([t for i, t in enumerate(tags) if i == 0 or tags[i - 1] != t])
