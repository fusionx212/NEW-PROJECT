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
    out = make_video(wav, tmp_path / "v.mp4", title="Test", subtitle="Sub", seed=2, size=(320, 180))
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True, check=True).stdout.split()
    assert sorted(probe) == ["audio", "video"]


def test_name_style_is_stable_and_varied():
    from skysoftly.video import name_style
    assert name_style("Maya") == name_style(" maya ")
    assert len({name_style(n) for n in ["Maya", "Leo", "Amara", "Noah", "Isla", "Oliver"]}) == 6
