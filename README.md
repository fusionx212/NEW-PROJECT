# Tonight's Sky, Softly

**A bedtime broadcast of the real sky over your own town, every night.** Plus a keepsake spin-off: a narrated "letter from the sky" for the night someone was born, married, or said goodbye.

Every space-themed sleep show today is fiction. This one is true, local and tonight. It tells a child where the Moon is from their window, which planets are up, which stars are overhead and how long their light has been travelling, then winds down in the slow cadence of the BBC Shipping Forecast over a soft synthesized pad.

Everything is generated offline with free tools. There are no paid APIs, no stock music and no licensed voices.

## What a buyer gets

**Nightly feed (per city)**
- A 4 to 5 minute episode every night: breathing, the Sun, the Moon "forecast", planets, three stars with light-travel times, the constellation overhead with a short story, meteor showers and seasons, one sky fact, a "look out of the window" moment, and a slow recap.
- A printable look-up card with tonight's real star chart and a tick-box checklist.

**Keepsake (made to order)**
- A 2 to 3 minute narrated letter describing exactly what the sky was doing over one place at one moment.
- A two-page A4 PDF: the star chart for that moment, plus the written letter.
- A personal hook nobody else offers: *"The light from Arcturus that shone on London that night had left the star around 1957."*

**Moving-nebula videos**
- Any episode or keepsake can also be rendered as an MP4 that looks like a Hubble or JWST image. Each video starts from one detailed nebula "photograph" made in code: glowing filaments in three narrowband colours (hydrogen, oxygen, sulphur), dark dust clouds lit at the edges by a young star cluster, and bright stars with diffraction spikes. A slow camera then glides and zooms through it, with the stars moving on their own layer for depth, and a soft glow that follows the narrator's voice.
- Every name grows its own nebula: the same name always gives the same clouds and colours, so "Maya's nebula" is truly hers. See `output/name-gallery/eight-names.jpg`.
- Use them for YouTube sleep channels, Reels and TikTok teasers, or as a nicer keepsake to send to family.

## Samples in this repo

| Folder | What it is |
|---|---|
| `output/nightly/boulder/` | One full week for Boulder, Colorado, 21 to 27 October 2026, with MP3s, scripts, look-up cards, cover art and a podcast `feed.xml` |
| `output/keepsakes/sample-birth/` | London, 16 July 1994: the night "Maya" was born, with Maya's nebula video |
| `output/name-gallery/eight-names.jpg` | Eight names, eight nebulae |
| `output/keepsakes/sample-wedding/` | Edinburgh, 15 June 2019: "Sam and Alex" |
| `output/keepsakes/sample-memorial/` | Sydney, 2 March 2024: "Grandad Joe" |

All names in the samples are fictional.

## Pricing and where to sell

| Product | Price | Channel |
|---|---|---|
| Nightly feed, one city | $2.99/month or $19.99/year | Substack paid podcast, Patreon or Ko-fi membership (all free to start, they take a cut of sales) |
| Keepsake | $19 (audio + chart + letter) | Etsy made-to-order digital listing, Gumroad or Payhip |
| Keepsake family set | $29 for three dates | Same |
| Keepsake with video | $29 (adds the nebula MP4) | Same |
| Classroom/library licence | $49/year per city | Direct, Gumroad |

Benchmarks the ideation research found: Koala Kids sleep-story bundles sell at $5.99 on Apple Podcasts, custom star-map prints sell from $5 to $32 on Etsy with thousands of listings, and none of them include audio.

## Run it

```bash
pip install -r requirements.txt
./tools/fetch_models.sh            # free Kokoro-82M TTS model (Apache-2.0), ~350 MB, CPU only

# A week of nightly episodes for any city with population > 15,000 (offline lookup)
python -m skysoftly nightly --city Boulder --country US --start 2026-10-21 --days 7 \
    --base-url https://YOUR-HOST/tonights-sky/boulder

# A keepsake
python -m skysoftly keepsake --city London --country GB --date 1994-07-16 --time 22:30 \
    --occasion birth --name "Maya"

# Any place by coordinates
python -m skysoftly keepsake --lat 36.17 --lon -115.14 --tz America/Los_Angeles \
    --place-name "Las Vegas" --date 2015-09-12 --time 21:30 --occasion wedding --name "Ana and Luis"

# Add --video to either command for a moving-nebula MP4 beside each MP3
python -m skysoftly keepsake --city London --country GB --date 1994-07-16 --time 22:30 \
    --occasion birth --name "Maya" --video --video-size 1080x1920   # vertical for Reels/TikTok

# Or turn any audio file into a nebula video
python -m skysoftly video --audio episode.mp3 --out episode.mp4 --subtitle "Boulder · Full Moon" \
    --palette jwst            # hubble, natural, jwst or violet
python -m skysoftly video --audio letter.mp3 --out maya.mp4 --title "Maya" --nebula-name "Maya"

# Scripts and charts only, in seconds
python -m skysoftly nightly --city Paris --country FR --days 7 --no-audio
```

Options: `--voice` picks any Kokoro voice (`af_heart` default, `bf_emma` or `bm_george` for British). Occasions are `birth`, `wedding`, `memorial`, `meeting` and `custom`.

Rendering speed on a 4-core CPU is roughly 2 to 3 minutes of audio work per episode, plus about 2 minutes of video work per minute of 720p video. A month of episodes for one city takes about an hour, unattended.

## How it works

| Module | Job |
|---|---|
| `skysoftly/engine.py` | Real sky for a place and moment: Sun and twilight, Moon phase and position, planets, named stars, the constellation overhead, meteor showers, equinoxes and solstices. Uses PyEphem and a bundled star catalogue, so it needs no network. |
| `skysoftly/script.py` | Turns facts into calm, speakable scripts. Times are spoken as people say them ("twenty to eight in the evening"), and phrasing rotates by date so a week never repeats. |
| `skysoftly/render.py` + `tools/audio_kit.py` | Kokoro TTS with timed pauses, a synthesized ambient bed and sting, then ffmpeg loudness mastering to podcast spec (-16 LUFS). |
| `skysoftly/chart.py` | All-sky star charts, the kids' look-up card, keepsake PDF and podcast cover art. |
| `skysoftly/feed.py` | Podcast RSS feed with Apple Podcasts tags. |
| `skysoftly/nebula.py` | Photoreal nebula stills: domain-warped fractal noise, ridged filaments per emission line, rim-lit dust, an astronomy-style asinh stretch, and a star layer with diffraction spikes. |
| `skysoftly/video.py` | Camera glide through the still with a parallax star layer, a voice-driven glow, title and end cards, encoded with ffmpeg and libx264. |

Tests run without the TTS model: `python -m pytest -q tests`.

## Launch checklist

1. **Keepsake first.** It earns per order and needs no audience. List on Etsy as a personalised digital download, using the sample chart as the main photo and a 30-second audio clip as the video. Etsy requires sellers to disclose AI involvement, so say plainly that narration uses a synthetic voice.
2. **Nightly feed second.** Pick one city with a strong parenting community. Publish the first week free on any podcast host, then switch to a paid Substack or Patreon feed.
3. **Grow by city.** Each new city is one command. Start with a few big English-speaking metros.
4. **Gifting seasons.** Mother's and Father's Day, Valentine's Day and Christmas for keepsakes; back-to-school and the clocks changing for the nightly feed.

## Honest risks

- **Night-to-night sameness.** The sky changes slowly. Rotation of stars, constellations, facts and phrasing helps, and the Moon changes nightly, but a month in one city will feel familiar. That is partly the point for a bedtime ritual.
- **Synthetic voice for an emotional keepsake.** Some buyers will not want it. The free sample and an honest listing are the mitigation. A seller can also record their own voice reading the generated letter.
- **No weather.** The script never claims the sky is clear, and says the sky is still there above the clouds.
- **Accuracy.** Positions are from standard ephemerides and checked by tests, but precession is ignored for star charts, which is well under a degree for dates between 1900 and 2100.

## Credits and licences

- Text-to-speech: [Kokoro-82M](https://github.com/thewh1teagle/kokoro-onnx), Apache-2.0.
- Star and constellation data: trimmed from [starplot-bigsky](https://github.com/steveberardi/starplot-bigsky) and [starplot-constellations](https://github.com/steveberardi/starplot-constellations) by Steve Berardi, MIT licence, derived from the Hipparcos and Tycho catalogues.
- City lookup: [geonamescache](https://pypi.org/project/geonamescache/), data from GeoNames (CC BY 4.0).
- Ephemeris: [PyEphem](https://rhodesmill.org/pyephem/), MIT-style licence.
- Music beds and stings are synthesized in code; no samples are used.
