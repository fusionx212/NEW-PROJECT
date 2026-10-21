"""Turn sky facts into calm, speakable scripts. `[pause N]` marks N seconds of silence."""
from __future__ import annotations

import datetime as dt
import hashlib
import random

from .catalog import KID_FACTS, PLANET_NOTES, STAR_NOTES, CONSTELLATION_STORIES, GENERIC_CONSTELLATION

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
        "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
ORD = {1: "first", 2: "second", 3: "third", 5: "fifth", 8: "eighth", 9: "ninth", 12: "twelfth"}


def words(n: int) -> str:
    n = int(n)
    if n < 0:
        return "minus " + words(-n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else "-" + ONES[n % 10])
    if n < 1000:
        return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " and " + words(n % 100))
    if n < 1_000_000:
        return words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else (" and " if n % 1000 < 100 else " ") + words(n % 1000))
    return str(n)


def ordinal(n: int) -> str:
    if n in ORD:
        return ORD[n]
    if n < 20:
        return words(n) + "th"
    if n % 10 == 0:
        return TENS[n // 10][:-1] + "ieth"
    return TENS[n // 10] + "-" + ordinal(n % 10)


def year_words(y: int) -> str:
    if 2000 <= y < 2010:
        return "two thousand" + ("" if y == 2000 else " and " + words(y - 2000))
    if y < 1000:
        return words(y)
    hi, lo = divmod(y, 100)
    return words(hi) + " " + ("hundred" if lo == 0 else ("oh " + words(lo) if lo < 10 else words(lo)))


def spoken_date(d: dt.date) -> str:
    return f"{d.strftime('%A')}, the {ordinal(d.day)} of {d.strftime('%B')}"


def spoken_time(t: dt.datetime, approx: bool = True) -> str:
    """'twenty to eight in the evening'. Rounded to five minutes, which is how people say times out loud."""
    m = int(round((t.hour * 60 + t.minute) / 5) * 5) if approx else t.hour * 60 + t.minute
    h, mi = divmod(m % 1440, 60)
    part = ("at night" if h >= 21 or h < 4 else "in the evening" if h >= 17 else "in the afternoon" if h >= 12 else "in the morning")
    if h == 0 and mi == 0:
        return "midnight"
    if h == 12 and mi == 0:
        return "midday"
    def h12(x):
        x %= 12
        return "twelve" if x == 0 else words(x)
    if mi == 0:
        core = f"{h12(h)} o'clock"
    elif mi == 15:
        core = f"quarter past {h12(h)}"
    elif mi == 30:
        core = f"half past {h12(h)}"
    elif mi == 45:
        core = f"quarter to {h12(h + 1)}"
    elif mi < 30:
        core = f"{words(mi)} past {h12(h)}"
    else:
        core = f"{words(60 - mi)} to {h12(h + 1)}"
    nh = (h + 1) % 24 if mi > 30 else h
    if nh == 0 and mi > 30:
        part = "at night"
    return f"{core} {part}"


def direction(az: float) -> str:
    names = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
    return names[int(((az % 360) + 22.5) // 45) % 8]


def height(alt: float) -> str:
    if alt < 12:
        return "low down"
    if alt < 30:
        return "a little way up"
    if alt < 55:
        return "high up"
    if alt < 75:
        return "very high"
    return "almost straight overhead"


def brightness(mag: float) -> str:
    if mag < -3:
        return "dazzling"
    if mag < -1:
        return "very bright"
    if mag < 0.8:
        return "bright"
    if mag < 2:
        return "easy to see"
    return "quite faint"


def fraction_words(pct: float) -> str:
    tenths = int(round(pct / 10))
    if tenths <= 0:
        return "barely lit at all"
    if tenths >= 10:
        return "completely lit"
    if tenths == 5:
        return "half lit"
    return f"{words(tenths)} tenths lit"


def light_when(ly: int | None, year: int) -> str | None:
    if not ly:
        return None
    if ly > 1500:
        return "Its light has been travelling towards you for thousands of years"
    left = year - ly
    if left > 1900:
        return f"The light you see tonight left it around {year_words(left)}, and has been travelling ever since"
    return f"The light you see tonight set off around the year {year_words(left)}"


def _stable(*keys) -> int:
    return int(hashlib.sha256("|".join(map(str, keys)).encode()).hexdigest()[:12], 16)


def where(alt: float, az: float) -> str:
    """'high up in the south-east', or just 'almost straight overhead'."""
    h = height(alt)
    return h if alt >= 75 else f"{h} in the {direction(az)}"


def _rng(*keys) -> random.Random:
    h = hashlib.sha256("|".join(map(str, keys)).encode()).hexdigest()
    return random.Random(int(h[:16], 16))


def _t(iso: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(iso) if iso else None


OPENINGS = [
    "Good evening. This is Tonight's Sky, Softly, for {city}.",
    "Hello, and good evening. You're listening to Tonight's Sky, Softly. Tonight's sky is over {city}.",
    "Good evening, {city}. This is Tonight's Sky, Softly.",
    "Hello again. It's evening in {city}, and this is Tonight's Sky, Softly.",
]
SETTLE = [
    "Get yourself comfortable. Tonight, we're going to look out of the window together, and then we're going to rest.",
    "Snuggle down. In a few minutes we'll peek at the real sky above your home, and then it will be time to sleep.",
    "Settle in. Let's find out what is shining above your roof tonight.",
    "Make yourself cosy. The sky has been getting ready for you all day.",
]
BREATHS = [
    "Let's take one slow breath in, [pause 3] and let it out. [pause 3] And one more. In, [pause 3] and out. [pause 3]",
    "Breathe in slowly, like you're smelling a flower. [pause 3] And breathe out, like you're cooling a cup of cocoa. [pause 3]",
    "Let your shoulders drop. [pause 2] Breathe in, [pause 3] and breathe out. [pause 3]",
]
MOON_LINES = {
    "New Moon": ["The Moon is hiding tonight, almost exactly between us and the Sun. That makes this a good, dark night for stars."],
    "Waxing Crescent": ["It's a thin, smiling crescent, and it grows a little fatter every night this week.",
                        "Look closely, and you might see the dark part of the Moon glowing faintly. That's sunlight bouncing off the Earth, called earthshine."],
    "First Quarter": ["Half of it is lit, and the line down the middle is the best place for spotting craters with binoculars."],
    "Waxing Gibbous": ["It's more than half full now, and growing. Its brightness will wash out some of the fainter stars.",
                       "It's getting rounder every night, on its way to full."],
    "Full Moon": ["It's full tonight: a round, bright face, lit up all the way across.",
                  "It's a full moon, rising as the Sun sets, and staying up all night long."],
    "Waning Gibbous": ["It's just past full, and it rises a little later each night, so early evenings are getting darker."],
    "Last Quarter": ["Half of it is lit, but it won't climb into the sky until late tonight."],
    "Waning Crescent": ["It's a thin crescent that only appears in the early morning, just before the Sun."],
}
WINDOW = [
    "Now, if you can, look out of the window. [pause 2] Can you find {target}? [pause 6] Take your time. [pause 6]",
    "Here's tonight's little mission. Look out of the window and try to find {target}. [pause 8] If the clouds are in the way, that's all right. The sky is still there, shining above them. [pause 4]",
    "Let's peek outside. Look for {target}. [pause 8] Say goodnight to it if you'd like. [pause 4]",
]
CLOSINGS = [
    "That's the sky for tonight. The Earth will keep turning slowly while you sleep, and the stars will wheel quietly overhead. [pause 2] Goodnight, {city}. [pause 2] Sleep well.",
    "And that is tonight's sky. Everything up there will carry on shining, all night long, without making a sound. [pause 2] Goodnight. [pause 2] Clear skies.",
    "That's all for tonight. Close your eyes now. The sky will still be there tomorrow, a little bit different, and we'll look at it together again. [pause 2] Goodnight.",
    "Time to rest. Let the Moon and the stars keep watch for a while. [pause 2] Goodnight, and sweet dreams.",
]


def _planet_line(p: dict, rng: random.Random) -> str:
    note = rng.choice(PLANET_NOTES[p["name"]])
    if p["status"] == "up":
        return (f"{p['name']}. {brightness(p['mag']).capitalize()}. {where(p['alt'], p['az']).capitalize()}. "
                f"[pause 1] {p['name']} is {note}.")
    if p["status"] == "rises_later":
        return f"{p['name']}. Rising later tonight, in the east, at about {spoken_time(_t(p['rise']))}."
    return ""


def nightly_script(sky: dict, episode_no: int | None = None) -> str:
    city = sky["place"]["name"]
    day = dt.date.fromisoformat(sky["date"])
    rng = _rng(city, sky["date"])
    look = _t(sky["look_time"])
    sun, moon = sky["sun"], sky["moon"]
    mx = moon["extra"]
    P = []

    P.append(rng.choice(OPENINGS).format(city=city) + f" It is {spoken_date(day)}. [pause 1] " + rng.choice(SETTLE))
    P.append(rng.choice(BREATHS))

    # Sun
    s = []
    if sun["sunset"]:
        s.append(f"The Sun set this evening at {spoken_time(_t(sun['sunset']))}.")
    if sky["still_light_at_look"]:
        s.append("At this time of year the sky stays light very late, so tonight the stars and planets will be hard to see. "
                 "We'll still tell you where they are, so you can imagine them behind the pale sky.")
    elif sun["astronomical_dusk"]:
        s.append(f"The sky will be properly dark by {spoken_time(_t(sun['astronomical_dusk']))}.")
    ch = sun.get("day_length_change_week_min")
    if ch:
        if abs(ch) >= 3:
            s.append(f"Today's daylight was {words(abs(ch))} minutes {'shorter' if ch < 0 else 'longer'} than a week ago.")
    P.append(" ".join(s))

    # Moon, forecast-style
    phase = mx["phase"]
    m = [f"The Moon. [pause 1] {phase}. {fraction_words(mx['illumination']).capitalize()}."]
    if moon["status"] == "up":
        m.append(f"{where(moon['alt'], moon['az']).capitalize()}, in front of the stars of {moon['constellation']}.")
    elif moon["status"] == "rises_later" and moon["rise"]:
        m.append(f"Rising in the east at {spoken_time(_t(moon['rise']))}.")
    else:
        m.append("Below the horizon this evening.")
    m.append(rng.choice(MOON_LINES[phase]))
    if 0 < mx["days_to_full"] <= 7:
        n = int(round(mx["days_to_full"]))
        m.append(f"The next full moon is in {'one night' if n <= 1 else words(n) + ' nights'}. "
                 f"In the old almanacs it's called the {mx['next_full_name']}.")
    P.append(" ".join(m))

    # Planets
    up = [p for p in sky["planets"] if p["status"] in ("up", "rises_later")]
    morning = [p for p in sky["planets"] if p["status"] == "morning"]
    lines = ["The planets. [pause 1]"]
    if up:
        lines += [_planet_line(p, rng) for p in up]
    else:
        lines.append("No bright planets are up this evening. They are all on the far side of the sky, or hiding in the Sun's glare.")
    if morning:
        names = [p["name"] for p in morning]
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        lines.append(f"And for anyone awake before sunrise: {joined} will be shining in the morning sky.")
    for p in up:
        if p["status"] == "up" and moon["status"] == "up" and p["extra"]["moon_separation"] < 8:
            lines.append(f"Tonight {p['name']} is sitting close to the Moon. Look just beside it.")
            break
    P.append(" ".join(lines))

    # Stars: the brightest, plus two that rotate night to night
    pool = sky["stars"][:7]
    if len(pool) > 3:
        k = day.toordinal() % (len(pool) - 1)
        rest = pool[1:] + pool[1:]
        st = [pool[0]] + rest[k:k + 2]
    else:
        st = pool
    if st and not sky["still_light_at_look"]:
        lines = ["The stars."]
        for s_ in st:
            bits = [f"{s_['name']}. {where(s_['alt'], s_['az']).capitalize()}."]
            note = STAR_NOTES.get(s_["name"])
            if note:
                bits.append(f"It's {note}.")
            lw = light_when(s_["light_years"], day.year)
            if lw:
                bits.append(lw + ".")
            lines.append(" ".join(bits))
        P.append(" [pause 1] ".join(lines))
    zc = sky["zenith_constellation"]
    if zc:
        story = CONSTELLATION_STORIES.get(zc, GENERIC_CONSTELLATION.format(name=zc))
        P.append(f"Straight above your roof tonight is the constellation of {zc}. [pause 1] {story}")
        storied = [c for c in sky.get("high_constellations", []) if c["name"] != zc and c["name"] in CONSTELLATION_STORIES]
        if storied:
            c = storied[day.toordinal() % len(storied)]
            P.append(f"And {where(c['alt'], c['az'])} is {c['name']}. [pause 1] {CONSTELLATION_STORIES[c['name']]}")

    # Coming up
    cu = []
    for sh in sky["meteors_active"]:
        d = sh["days_to_peak"]
        if d == 0:
            when = "peaks tonight"
        elif d > 0:
            when = f"is building towards its peak in {words(d)} {'night' if d == 1 else 'nights'}"
        else:
            when = "is fading now, but still sending the odd shooting star"
        cu.append(f"The {sh['name']} meteor shower {when}. The shooting stars seem to fly out from {sh['radiant']}, "
                  "and the best time to look is late at night, from somewhere dark.")
    if not cu and sky["meteors_upcoming"]:
        u = sky["meteors_upcoming"]
        cu.append(f"Coming soon: the {u['name']} meteor shower starts in {words(u['days_to_start'])} days.")
    if sky["season"]:
        se = sky["season"]
        what = {"equinox": "the equinox, when day and night are almost exactly the same length",
                "solstice": ("the longest day of the year" if (se["month"] == 6) == (sky["place"]["lat"] >= 0) else "the shortest day of the year")}[se["kind"]]
        cu.append(("Today is " if se["days"] == 0 else f"In {words(se['days'])} {'day' if se['days'] == 1 else 'days'} it will be ") + what + ".")
    if cu:
        P.append("Coming up in the sky. [pause 1] " + " ".join(cu))

    # Kid fact (rotates by day of year so a week never repeats)
    fact = KID_FACTS[(day.toordinal() + _stable(city) % 7) % len(KID_FACTS)]
    P.append("Tonight's sky fact. [pause 1] " + fact)

    # Window moment
    targets = []
    if moon["status"] == "up":
        targets.append("the Moon")
    bright_up = sorted([p for p in sky["planets"] if p["status"] == "up"], key=lambda p: p["mag"])
    if bright_up:
        targets.append(f"{bright_up[0]['name']}, over in the {direction(bright_up[0]['az'])}")
    if st and not targets:
        targets.append(f"the star {st[0]['name']}, " + ("right overhead" if st[0]['alt'] >= 75 else f"over in the {direction(st[0]['az'])}"))
    target = " and ".join(targets) if targets else "one single star"
    P.append(rng.choice(WINDOW).format(target=target))

    # Shipping-forecast recap
    rec = []
    if moon["status"] == "up":
        rec.append(f"Moon, {phase.lower()}, {direction(moon['az'])}.")
    for p in bright_up[:3]:
        rec.append(f"{p['name']}, {direction(p['az'])}.")
    for s_ in st[:2]:
        rec.append(f"{s_['name']}, {'overhead' if s_['alt'] >= 75 else direction(s_['az'])}.")
    if rec:
        P.append("Here is tonight's sky once more, slowly. [pause 2] " + " [pause 1] ".join(rec) + " [pause 2]")

    P.append(rng.choice(CLOSINGS).format(city=city))
    return "\n\n".join(x for x in P if x.strip())


OCCASIONS = {
    "birth": "the night {name} was born",
    "wedding": "the night {name} were married",
    "memorial": "a night we remember {name}",
    "meeting": "the night {name} first met",
    "custom": "{name}",
}


def keepsake_script(sky: dict, occasion: str, name: str, when: dt.datetime) -> str:
    place = sky["place"]["name"]
    day = when.date()
    rng = _rng("keepsake", place, sky["date"], name)
    moon, mx = sky["moon"], sky["moon"]["extra"]
    label = OCCASIONS.get(occasion, OCCASIONS["custom"]).format(name=name)
    P = []
    P.append(f"This is a letter from the sky. [pause 1] It's about one night: {spoken_date(day)}, {year_words(day.year)}, in {place}. "
             f"[pause 1] It was {label}.")
    P.append("Nobody photographs the sky on nights like that. Everyone is looking somewhere else. "
             "So here is what was happening above you, worked out from the movements of the Earth, the Moon and the planets.")
    s = []
    if sky["sun"]["sunset"]:
        s.append(f"The Sun had set at {spoken_time(_t(sky['sun']['sunset']))}.")
    if sky["still_light_at_look"]:
        s.append("It was one of those nights when the sky never quite gets dark.")
    elif sky["sun"]["astronomical_dusk"]:
        s.append(f"By {spoken_time(_t(sky['sun']['astronomical_dusk']))} the last of the twilight had gone.")
    P.append(" ".join(s))

    ph = mx["phase"].lower()
    m = [f"The Moon was {'a ' + ph if ph in ('new moon', 'full moon', 'first quarter', 'last quarter') else ph}, {fraction_words(mx['illumination'])}."]
    if moon["status"] == "up":
        m.append(f"It hung {where(moon['alt'], moon['az'])}, in front of the stars of {moon['constellation']}.")
    elif moon["status"] == "rises_later" and moon["rise"]:
        m.append(f"It hadn't risen yet. It would come up in the east at {spoken_time(_t(moon['rise']))}.")
    else:
        m.append("It was below the horizon, which left the sky darker and the stars brighter.")
    if mx["phase"] == "Full Moon":
        m.append(f"It was the {sky['moon']['extra']['next_full_name'] if mx['days_to_full'] < 2 else 'full moon'}.")
    P.append(" ".join(m))

    up = sorted([p for p in sky["planets"] if p["status"] == "up"], key=lambda p: p["mag"])
    if up:
        bits = [f"{p['name']} was {where(p['alt'], p['az'])}" for p in up]
        P.append("The planets were out too. " + ". ".join(bits) + ". " +
                 (f"{up[0]['name']} was the brightest of them: {rng.choice(PLANET_NOTES[up[0]['name']])}." if len(up) > 1
                  else f"{up[0]['name']} is {rng.choice(PLANET_NOTES[up[0]['name']])}."))
    close = [p for p in up if moon["status"] == "up" and p["extra"]["moon_separation"] < 8]
    if close:
        P.append(f"That night {close[0]['name']} sat right beside the Moon, as if keeping it company.")
    later = [p["name"] for p in sky["planets"] if p["status"] in ("rises_later", "morning")]
    if later:
        P.append(f"Before dawn, {', '.join(later[:-1]) + ' and ' + later[-1] if len(later) > 1 else later[0]} would rise as well.")

    st = sky["stars"][:3]
    if st:
        lines = []
        for s_ in st:
            lw = None
            if s_["light_years"] and s_["light_years"] < 1500:
                left = day.year - s_["light_years"]
                lw = (f"the light from {s_['name']} that shone on {place} that night had left the star around {year_words(left)}"
                      if left > 0 else None)
            lines.append(f"{s_['name']} was {where(s_['alt'], s_['az'])}" + (f". {lw[0].upper() + lw[1:]}" if lw else ""))
        P.append("Among the stars, " + ". [pause 1] ".join(lines) + ".")
    zc = sky["zenith_constellation"]
    if zc:
        P.append(f"Directly overhead was the constellation of {zc}. " + CONSTELLATION_STORIES.get(zc, GENERIC_CONSTELLATION.format(name=zc)))
    for sh in sky["meteors_active"]:
        P.append(f"And the {sh['name']} meteor shower was active, so now and then a shooting star crossed the dark.")
        break
    if sky["season"] and sky["season"]["days"] == 0:
        P.append(f"It was the day of the {sky['season']['kind']}.")

    P.append("[pause 2] The sky will never be arranged in exactly this way again. The Moon, the planets and the turning Earth will not line up like this "
             "for thousands of years.")
    if st:
        P.append(f"But every year, around {day.strftime('%B')}, the same stars come back to the same places in the evening sky. "
                 f"So when you look up and find {st[0]['name']}, you are looking at the sky of that night. [pause 2]")
    P.append("With love, from the sky.")
    return "\n\n".join(x for x in P if x.strip())
