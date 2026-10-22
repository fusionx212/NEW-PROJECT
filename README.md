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

**Deep-zoom nebula videos that land on a name**
- Each video opens on a whole nebula that looks like a Hubble or JWST image: glowing filaments in hydrogen, oxygen and sulphur colours, dark dust lit at the edges by young stars, and stars with diffraction spikes.
- The camera then makes one slow, continuous Ken Burns dive, 48 times closer, into a single star. New filaments and dust keep appearing as it goes deeper, and stars stream past for a sense of flight.
- The star grows from a pinprick into a radiant star, then bursts into hundreds of glowing particles that fly into place and spell the person's name, with a caption such as "Born 16 July 1994 · London".
- Every name grows its own nebula: the same name always gives the same picture, so "Maya's nebula" is truly hers. See `output/name-gallery/eight-names.jpg`.
- Use them as the centrepiece of a birth, birthday, wedding or memorial gift, for YouTube sleep channels, or as Reels and TikTok teasers.

**Personalised bedtime story gift packs** (the main Etsy product, see `docs/GIFT-SHOP.md`)
- A bedtime story where the child is the hero: their own star calls them, their favourite animal becomes a companion made of starlight, and they travel to their own nebula. Birthday stories give one wish per year of age, and the star reads out a message from whoever gave the gift.
- With a birth date and town, the story uses the real sky of the night they were born.
- Each pack has the narrated story, the deep-zoom video landing on their name, an illustrated 8 x 8 inch storybook PDF with their birth-night sky chart, and a nebula certificate, zipped and ready to deliver.

**A matching product range from the same order**
- A nursery name print, a space birthday party kit (invitation, thank-you card, cupcake toppers, favour tags, name banner), a colouring page, a bedtime routine chart and a phone wallpaper, all in the child's own nebula.
- Lifestyle listing photos rendered in code: a framed print on a nursery wall, an invitation flat lay, a storybook on a tablet, a video on a phone.

## Samples in this repo

| Folder | What it is |
|---|---|
| `output/nightly/boulder/` | One full week for Boulder, Colorado, 21 to 27 October 2026, with MP3s, scripts, look-up cards, cover art and a podcast `feed.xml` |
| `output/keepsakes/sample-birth/` | London, 16 July 1994: the night "Maya" was born, with Maya's nebula video |
| `output/name-gallery/eight-names.jpg` | Eight names, eight nebulae |
| `output/stories/sample-isla/` | A full gift pack for "Isla", turning five, with a starlight bunny and her real birth-night sky |
| `docs/listing/` | Etsy listing images and lifestyle photos made from that pack |
| `output/products/sample-isla/` | Isla's matching printables and listing photos |
| `output/voice-test/` | Voice comparison clips; H became the house voice |
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
pip install -r requirements.txt     # also needs ffmpeg installed (apt install ffmpeg / brew install ffmpeg)
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
python -m skysoftly video --audio letter.mp3 --out maya.mp4 --title "Maya" --nebula-name "Maya" \
    --star-name "Maya" --star-caption "Born 2 May 2024 · Leeds" --zoom 48

# A personalised bedtime story gift pack
python -m skysoftly story --name "Isla" --pronoun she --age 5 --animal bunny --colour purple \
    --from "Grandma and Grandpa" --message "Happy fifth birthday, darling." \
    --born 2021-05-02 --city Leeds --country GB --video

# Scripts and charts only, in seconds
python -m skysoftly nightly --city Paris --country FR --days 7 --no-audio
```

Options: `--voice` picks the narrator. The default, `softly`, blends the quiet Nicole voice with Emma and speaks with a British accent, with warm close-mic processing. Other presets are `nicole`, `emma` and `heart`, and any Kokoro voice id works too. Occasions are `birth`, `wedding`, `memorial`, `meeting` and `custom`.

Rendering speed on a 4-core CPU is roughly 2 to 3 minutes of audio work per episode, plus about 5 minutes of video work per minute of 720p video, and roughly three times that for 1080x1920 vertical. A month of episodes for one city takes about an hour, unattended.

## How it works

| Module | Job |
|---|---|
| `skysoftly/engine.py` | Real sky for a place and moment: Sun and twilight, Moon phase and position, planets, named stars, the constellation overhead, meteor showers, equinoxes and solstices. Uses PyEphem and a bundled star catalogue, so it needs no network. |
| `skysoftly/script.py` | Turns facts into calm, speakable scripts. Times are spoken as people say them ("twenty to eight in the evening"), and phrasing rotates by date so a week never repeats. |
| `skysoftly/render.py` + `tools/audio_kit.py` | Kokoro TTS with timed pauses, a synthesized ambient bed and sting, then ffmpeg loudness mastering to podcast spec (-16 LUFS). |
| `skysoftly/chart.py` | All-sky star charts, the kids' look-up card, keepsake PDF and podcast cover art. |
| `skysoftly/feed.py` | Podcast RSS feed with Apple Podcasts tags. |
| `skysoftly/nebula.py` | Photoreal nebula stills: domain-warped fractal noise, ridged filaments per emission line, rim-lit dust, an astronomy-style asinh stretch, and a star layer with diffraction spikes. |
| `skysoftly/story.py` | Personalised bedtime stories with pronouns, age-based wishes, a companion animal, the giver's message and real birth-night sky facts. |
| `skysoftly/storybook.py` | The illustrated storybook PDF, birth-night sky page and nebula certificate. |
| `skysoftly/products.py` | The printables: nursery print, party kit, colouring page, bedtime chart and wallpaper. |
| `skysoftly/mockups.py` | Lifestyle listing photos rendered from scratch, no stock photos needed. |
| `skysoftly/scenes.py` | Illustrated story scenes: bedroom window, planets and starlight animal silhouettes. |
| `skysoftly/zoom.py` | Deep zoom: nested detail levels that keep brightness and colour separate and hold the same tonal range at every depth, a star catalogue drawn crisp at any zoom, and the name's particle targets. |
| `skysoftly/video.py` | The dive itself: eased exponential zoom, slow rotation, level cross-fades, fly-through stars, the growing star, the particle burst into the name, title cards, and ffmpeg encoding. |

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
