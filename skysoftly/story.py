"""Personalised bedtime stories: the child travels to their own nebula on a real night sky.

Everything that can be true is true. If the order includes a birth date and place, the story uses the real
sky of the night the child was born: the Moon's phase, the planets that were up, the constellation overhead
and a star whose light set off before they were born. Wording varies by name so two children with the same
order details still get different stories.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import random
from dataclasses import dataclass

from .catalog import CONSTELLATION_STORIES
from .script import ordinal, words, year_words, spoken_date

PRONOUNS = {
    "she": {"they": "she", "them": "her", "their": "her", "was": "was", "is": "is", "has": "has", "they're": "she's"},
    "he": {"they": "he", "them": "him", "their": "his", "was": "was", "is": "is", "has": "has", "they're": "he's"},
    "they": {"they": "they", "them": "them", "their": "their", "was": "were", "is": "are", "has": "have", "they're": "they're"},
}

COLOURS = {  # favourite colour -> nebula style, and how the narrator describes it
    "violet": ("violet", "purple and lilac and the softest blue"),
    "natural": ("natural", "rose pink and sea green"),
    "jwst": ("jwst", "honey gold and amber and pale blue"),
    "hubble": ("hubble", "emerald and gold and sky blue"),
}
COLOUR_WORDS = {
    "purple": "violet", "lilac": "violet", "lavender": "violet", "violet": "violet",
    "pink": "natural", "red": "natural", "rose": "natural",
    "orange": "jwst", "gold": "jwst", "yellow": "jwst", "brown": "jwst",
    "green": "hubble", "blue": "hubble", "teal": "hubble", "turquoise": "hubble",
}

WISHES = [
    "a wish for kindness, so that you always find a friend, and always are one",
    "a wish for courage, the quiet kind that lets you try new things",
    "a wish for laughter, the sort that makes your tummy ache in the best way",
    "a wish for curiosity, so that you never stop asking why",
    "a wish for cosy days, warm socks and hot chocolate",
    "a wish for adventures, big ones and little ones",
    "a wish for love, more than all the stars put together",
    "a wish for sweet dreams, every single night",
]


@dataclass
class StoryOrder:
    name: str
    pronoun: str = "they"
    age: int | None = None            # birthday stories count wishes with this
    animal: str = "fox"
    colour: str = "purple"
    giver: str | None = None          # e.g. "Grandma and Grandpa"
    message: str | None = None        # a short line from the giver, read near the end
    occasion: str = "birthday"        # birthday | bedtime


def style_for_colour(colour: str) -> str:
    return COLOUR_WORDS.get(colour.strip().lower(), "violet")


def _rng(*k):
    return random.Random(int(hashlib.sha256("|".join(map(str, k)).encode()).hexdigest()[:12], 16))


def _a(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def story_title(o: StoryOrder) -> str:
    return f"{o.name} and the Star That Knew {PRONOUNS[o.pronoun]['their'].capitalize()} Name"


def make_story(o: StoryOrder, sky: dict | None = None, born: dt.date | None = None) -> str:
    """Returns a narration script with [pause N] markers, roughly seven to nine minutes at bedtime pace."""
    P = PRONOUNS.get(o.pronoun, PRONOUNS["they"])
    N = o.name
    rng = _rng(N, o.age, o.animal, o.colour)
    style = style_for_colour(o.colour)
    colours = COLOURS[style][1]
    animal = o.animal.strip().lower() or "fox"
    S = []

    # 1. Settling in
    if o.occasion == "birthday" and o.age:
        S.append(f"This is a story for {N}. [pause 1] It was the night after {N}'s {ordinal(o.age)} birthday. "
                 f"The cake was eaten, the wrapping paper was folded away, and the house had gone soft and quiet.")
    else:
        S.append(f"This is a story for {N}. [pause 1] It was a quiet night, and the house had gone soft and still.")
    S.append(f"{N} was snuggled up in bed. [pause 1] So let's get cosy too. "
             "Let your shoulders sink into the pillow. [pause 2] Breathe in slowly, [pause 3] and breathe out. [pause 3] "
             "One more time. In, [pause 3] and out. [pause 3]")

    # 2. The star at the window
    star_line = rng.choice([
        f"Outside the window, one star was twinkling more brightly than all the others. It blinked once, then twice, as if it were waving.",
        f"Outside the window, a single star began to glow, brighter and brighter, until it was looking straight at {N}.",
    ])
    S.append(f"{star_line} [pause 1] \"Hello, {N},\" whispered the star, in a voice like a tiny silver bell. "
             f"\"I've been waiting for you.\"")
    if sky and born:
        zc = sky.get("zenith_constellation")
        phase = sky["moon"]["extra"]["phase"].lower()
        S.append(f"\"I was there on the night you were born,\" said the star. \"It was {spoken_date(born)}, {year_words(born.year)}. "
                 + (f"The Moon was {phase if phase.endswith('moon') else 'a ' + phase + ' moon'} that night, " if phase else "")
                 + (f"and I was shining right above you, in the stars of {zc}. " if zc else "")
                 + f"I've been watching over you ever since.\"")
    else:
        S.append(f"\"I've been shining above your home for a very long time,\" said the star. \"Ever since you were tiny. "
                 f"I know your name, {N}, and tonight I want to show you something special.\"")

    # 3. The companion and the moonbeam
    S.append(f"Then something padded softly across the windowsill. [pause 1] It was {_a(animal)}, a little {animal} made "
             f"entirely of starlight, glowing gently, with eyes like two tiny moons. [pause 1] "
             f"\"I'm here to keep you company,\" said the {animal}. \"Hold on to me, and don't worry. We'll be back before you know it.\"")
    S.append(f"A moonbeam slid down through the window, as smooth and silver as a ribbon. {N} and the starlight {animal} "
             f"climbed onto it, and it lifted them up, [pause 1] up past the rooftops, [pause 1] up past the clouds, "
             f"[pause 1] up into the deep, quiet blue of the night.")

    # 4. The journey, using real planets when we have them
    planets = [p["name"] for p in (sky or {}).get("planets", []) if p["status"] in ("up", "rises_later")]
    sights = {
        "Mercury": "little Mercury, hurrying round the Sun as fast as it could",
        "Venus": "Venus, shining so brightly that it lit up their faces",
        "Mars": "rusty red Mars, with its tall sleepy volcanoes",
        "Jupiter": "giant Jupiter, striped like a sweet, with its great red storm spinning slowly",
        "Saturn": "Saturn, wearing its rings like a sparkly hula hoop",
    }
    if planets:
        seen = [sights[p] for p in planets[:3]]
        S.append(f"They floated past the planets that had been out on the night {N} was born. "
                 + ". [pause 1] ".join(s[0].upper() + s[1:] for s in seen) + ". [pause 1] "
                 + f"The {animal} waved a glowing paw at each one, and each one seemed to glow back.")
    else:
        S.append(f"They floated past the Moon, [pause 1] past Saturn wearing its rings like a sparkly hula hoop, "
                 f"[pause 1] past giant Jupiter, striped like a sweet. The {animal} waved a glowing paw at each one.")

    # 5. Arriving at their nebula
    S.append(f"And then, ahead of them, the darkness began to glow. [pause 1] Great soft clouds of {colours} "
             f"stretched further than {N} could see, curling and drifting like steam from a warm drink. [pause 1] "
             f"\"This is your nebula,\" said the star. \"{N}'s Nebula. It's a place where new stars are born, "
             f"just like you were born. No one else in the whole universe has one quite like it.\"")
    S.append(f"{N} reached out a hand, and the cloud felt like the softest blanket in the world. [pause 2] "
             f"Tiny new stars were blinking awake inside it, [pause 1] one, [pause 1] and then another, [pause 1] "
             f"and then another, like fireflies on a summer evening.")

    # 6. Wishes (birthday) or a gift (bedtime)
    if o.occasion == "birthday" and o.age:
        n_w = max(1, min(o.age, 7))
        S.append(f"\"We have a birthday present for you,\" said the star. \"{words(n_w).capitalize()} "
                 f"{'wish' if n_w == 1 else 'wishes'}, one for every year"
                 + (", and a few to spare" if o.age > 7 else "") + ".\" [pause 1]")
        pool = WISHES[:]
        rng.shuffle(pool)
        lines = []
        for i in range(n_w):
            lines.append(f"The {ordinal(i + 1)} little star floated down and whispered {pool[i % len(pool)]}.")
        S.append(" [pause 1] ".join(lines))
        S.append(f"Each wish landed on {N} as softly as a snowflake, and stayed.")
    else:
        pool = WISHES[:]
        rng.shuffle(pool)
        S.append(f"\"We have a present for you,\" said the star. [pause 1] Three little stars floated down. "
                 f"The first whispered {pool[0]}. [pause 1] The second whispered {pool[1]}. [pause 1] "
                 f"And the third whispered {pool[2]}.")

    # 7. A message from the giver
    if o.giver:
        msg = o.message.strip() if o.message else f"We love you to the stars and back."
        S.append(f"Then the star said, \"Someone asked me to give you a message. It's from {o.giver}.\" [pause 1] "
                 f"And in a voice as soft as a hug, the star said: [pause 1] \"{msg}\" [pause 2]")

    # 8. Wind down and home
    S.append(f"By now, {N}'s eyes were getting heavy. [pause 1] The starlight {animal} gave a great big yawn. "
             f"\"Time to go home,\" it said. [pause 1] The moonbeam curled around them like a scarf, and down they "
             f"floated, [pause 2] slowly, [pause 2] slowly, [pause 2] past the planets, [pause 2] past the clouds, "
             f"[pause 2] all the way back to {N}'s warm, cosy bed.")
    S.append(f"Let's count the stars down together, nice and slowly. [pause 1] Ten. [pause 2] Nine. [pause 2] Eight. [pause 2] "
             f"Seven. [pause 2] Six. [pause 2] Five. [pause 2] Four. [pause 2] Three. [pause 2] Two. [pause 2] One. [pause 3]")
    S.append(f"The starlight {animal} curled up at the end of the bed, glowing softly, [pause 1] and slowly faded "
             f"into a faint shimmer that only {N} would ever know was there. [pause 2] "
             f"And outside the window, {N}'s star kept watch, [pause 1] twinkling gently, [pause 1] the way it always had, "
             f"and the way it always will.")
    if sky and sky.get("stars"):
        st = sky["stars"][0]
        if st.get("light_years") and born and st["light_years"] < 1500:
            left = born.year - st["light_years"]
            S.append(f"Here's a secret to keep. [pause 1] On the night you were born, the star called {st['name']} was shining above you. "
                     f"The light from it had set off around {year_words(left)}, and travelled all that way, just to reach you.")
    S.append(f"Goodnight, {N}. [pause 2] Sweet dreams. [pause 2] Your star is watching over you.")
    return "\n\n".join(S)
