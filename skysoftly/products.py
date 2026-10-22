"""One order, a whole shop: printables generated from a child's nebula, name, animal and birth-night sky.

Every product shares the same look (their nebula, gold serif lettering, starlight animal) so they sell as
a set: nursery print, birthday party kit, colouring pages, bedtime chart and phone wallpaper.
"""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .scenes import animal_mask, planet, starlight_silhouette
from .script import ordinal, words
from .zoom import _stamp, big_star, sprinkle_stars

GOLD = (245, 205, 130)
CREAM = (250, 246, 236)
INK = (238, 240, 250)
NAVY = (11, 20, 48)
DEEP = (40, 45, 80)


def font(size: int, serif: bool = True, italic: bool = False, bold: bool = False):
    from matplotlib import font_manager
    prop = font_manager.FontProperties(family="DejaVu Serif" if serif else "DejaVu Sans",
                                       style="italic" if italic else "normal", weight="bold" if bold else "normal")
    return ImageFont.truetype(font_manager.findfont(prop), size)


def fit_font(d, text, max_w, size, **kw):
    f = font(size, **kw)
    while d.textlength(text, font=f) > max_w and size > 12:
        size = int(size * 0.93); f = font(size, **kw)
    return f


def centred(d, cx, y, text, f, fill, shadow=False):
    w = d.textlength(text, font=f)
    if shadow:
        for dx, dy in ((0, 4), (4, 0), (0, -4), (-4, 0), (3, 3)):
            d.text((cx - w / 2 + dx, y + dy), text, font=f, fill=(5, 8, 25))
    d.text((cx - w / 2, y), text, font=f, fill=fill)


def nebula_art(levels, w: int, h: int, depth: int = 0, seed: int = 0, stars: float = 1.0) -> Image.Image:
    im = levels[min(depth, len(levels) - 1)]
    n = im.size[0]
    aspect = w / h
    cw = int(n * 0.8) if aspect >= 1 else int(n * 0.8 * aspect)
    ch = int(cw / aspect)
    c = n // 2
    crop = im.crop((c - cw // 2, c - ch // 2, c + cw // 2, c + ch // 2)).resize((w, h), Image.LANCZOS)
    return sprinkle_stars(crop, seed=seed, density=stars) if stars else crop


class Order:
    def __init__(self, name, age=None, animal="fox", born: dt.date | None = None, place: str | None = None,
                 party: str | None = None, rsvp: str | None = None, sky: dict | None = None):
        self.name, self.age, self.animal, self.born, self.place = name, age, animal, born, place
        self.party, self.rsvp, self.sky = party, rsvp, sky


# ---------------- nursery print ----------------
def nursery_print(o: Order, levels, out: Path, w=2400, h=3000) -> Path:
    """8 x 10 inches at 300 dpi (scales cleanly to 16 x 20). Nebula, their star, name and birth details."""
    im = nebula_art(levels, w, h, depth=1, seed=11)
    a = np.asarray(im, dtype=np.float32)
    yy = np.linspace(0, 1, h)[:, None, None]
    a = a * (1 - 0.65 * np.clip((yy - 0.55) / 0.45, 0, 1))      # darken the lower part for lettering
    _stamp(a, w * 0.5, h * 0.33, big_star(int(w / 4)), np.array([255, 240, 210]) * 1.25)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    centred(d, w / 2, h * 0.62, o.name, fit_font(d, o.name, w * 0.8, 380), GOLD, shadow=True)
    line2 = f"{o.name}'s Nebula"
    centred(d, w / 2, h * 0.62 + 470, line2, font(90, italic=True), INK, shadow=True)
    if o.born:
        details = o.born.strftime("%d %B %Y").lstrip("0") + (f"  ·  {o.place}" if o.place else "")
        centred(d, w / 2, h * 0.62 + 640, details, font(70, serif=False), (200, 205, 230))
    if o.sky and o.sky.get("zenith_constellation"):
        centred(d, w / 2, h * 0.62 + 760, f"Born under {o.sky['zenith_constellation']}", font(62, serif=False, italic=True), (170, 180, 220))
    im.save(out, quality=95, dpi=(300, 300))
    return out


# ---------------- party kit ----------------
def _card(levels, w, h, seed):
    im = nebula_art(levels, w, h, depth=2, seed=seed, stars=0.8)
    a = np.asarray(im, dtype=np.float32) * 0.85
    return Image.fromarray(a.astype(np.uint8))


def invitation(o: Order, levels, out: Path, w=1500, h=2100) -> Path:
    """5 x 7 inch invitation."""
    im = _card(levels, w, h, 21)
    a = np.asarray(im, dtype=np.float32)
    planet(a, "Saturn", w * 0.78, h * 0.14, 90)
    planet(a, "Mars", w * 0.16, h * 0.86, 40)
    starlight_silhouette(a, o.animal, w * 0.2, h * 0.17, 300, t=0.4)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
    centred(d, w / 2, h * 0.3, "Blast off!", font(110, italic=True), INK, shadow=True)
    centred(d, w / 2, h * 0.38, "You're invited to", font(70, serif=False), INK, shadow=True)
    centred(d, w / 2, h * 0.43, f"{o.name}'s", fit_font(d, f"{o.name}'s", w * 0.85, 240), GOLD, shadow=True)
    age = f"{ordinal(o.age).capitalize()} Birthday" if o.age else "Birthday"
    centred(d, w / 2, h * 0.56, age, fit_font(d, age, w * 0.85, 130), GOLD, shadow=True)
    centred(d, w / 2, h * 0.66, "Space Party", font(90, italic=True), INK, shadow=True)
    y = h * 0.74
    for ln in (o.party or "Party date · time · place").split("|"):
        centred(d, w / 2, y, ln.strip(), fit_font(d, ln.strip(), w * 0.8, 62, serif=False), INK, shadow=True); y += 85
    if o.rsvp:
        centred(d, w / 2, y + 20, f"RSVP {o.rsvp}", font(52, serif=False, italic=True), (200, 205, 230), shadow=True)
    im.save(out, quality=95, dpi=(300, 300)); return out


def thank_you(o: Order, levels, out: Path, w=2100, h=1500) -> Path:
    im = _card(levels, w, h, 22)
    a = np.asarray(im, dtype=np.float32)
    starlight_silhouette(a, o.animal, w * 0.18, h * 0.5, 420, t=0.2)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
    centred(d, w * 0.6, h * 0.3, "Thank you", font(190, italic=True), GOLD, shadow=True)
    centred(d, w * 0.6, h * 0.52, "for making my birthday", font(70, serif=False), INK, shadow=True)
    centred(d, w * 0.6, h * 0.6, "out of this world!", font(70, serif=False), INK, shadow=True)
    centred(d, w * 0.6, h * 0.74, f"Love, {o.name}", font(90, italic=True), GOLD, shadow=True)
    im.save(out, quality=95, dpi=(300, 300)); return out


def cupcake_toppers(o: Order, levels, out: Path) -> Path:
    """A4 sheet (2480 x 3508) of twelve 2-inch circles: age, name, planets and their animal."""
    W, H = 2480, 3508
    sheet = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(sheet)
    r = 300
    designs = ["age", "name", "Saturn", "animal", "Jupiter", "star"] * 2
    for i, kind in enumerate(designs):
        cx = 420 + (i % 3) * 820; cy = 520 + (i // 3) * 820
        tile = _card(levels, 2 * r, 2 * r, 30 + i)
        a = np.asarray(tile, dtype=np.float32)
        td = None
        if kind in ("Saturn", "Jupiter"):
            planet(a, kind, r, r, r * (0.38 if kind == "Saturn" else 0.6))
        elif kind == "animal":
            starlight_silhouette(a, o.animal, r, r, int(r * 1.5), t=i)
        elif kind == "star":
            _stamp(a, r, r, big_star(int(r * 0.9)), np.array([255, 240, 210]) * 1.3)
        tile = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)); td = ImageDraw.Draw(tile)
        if kind == "age" and o.age:
            centred(td, r, r - 190, str(o.age), font(300, bold=True), GOLD, shadow=True)
        elif kind == "name" or (kind == "age" and not o.age):
            centred(td, r, r - 80, o.name, fit_font(td, o.name, 1.5 * r, 150), GOLD, shadow=True)
        mask = Image.new("L", (2 * r, 2 * r), 0); ImageDraw.Draw(mask).ellipse((0, 0, 2 * r, 2 * r), fill=255)
        sheet.paste(tile, (cx - r, cy - r), mask)
        d.ellipse((cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3), outline=(200, 200, 200), width=3)
    centred(d, W / 2, H - 140, "Print on card, cut out, and attach to cocktail sticks.", font(48, serif=False), (120, 120, 120))
    sheet.save(out, quality=95, dpi=(300, 300)); return out


def banner(o: Order, levels, out_dir: Path) -> list[Path]:
    """Pennant flags, one letter each: HAPPY BIRTHDAY NAME. Each is an A5 portrait pennant."""
    text = f"HAPPY BIRTHDAY {o.name.upper()}"
    outs = []
    W, H = 1748, 2480
    for i, ch in enumerate(text.replace(" ", "*")):
        flag = Image.new("RGB", (W, H), "white")
        tile = _card(levels, W, int(H * 0.9), 40 + i)
        mask = Image.new("L", (W, int(H * 0.9)), 0)
        ImageDraw.Draw(mask).polygon([(0, 0), (W, 0), (W, H * 0.62), (W / 2, H * 0.9), (0, H * 0.62)], fill=255)
        flag.paste(tile, (0, 0), mask)
        d = ImageDraw.Draw(flag)
        if ch == "*":
            a = np.asarray(flag, dtype=np.float32)
            _stamp(a, W / 2, H * 0.36, big_star(600), np.array([255, 240, 210]) * 1.3)
            flag = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(flag)
        else:
            centred(d, W / 2, H * 0.12, ch, font(900), GOLD, shadow=True)
        p = out_dir / f"banner-{i + 1:02d}.jpg"
        flag.save(p, quality=92, dpi=(300, 300)); outs.append(p)
    return outs


def favour_tags(o: Order, levels, out: Path) -> Path:
    W, H = 2480, 3508
    sheet = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(sheet)
    tw, th = 700, 1000
    for i in range(9):
        x = 140 + (i % 3) * 760; y = 160 + (i // 3) * 1080
        tag = _card(levels, tw, th, 60 + i); td = ImageDraw.Draw(tag)
        td.ellipse((tw / 2 - 30, 50, tw / 2 + 30, 110), fill="white")
        centred(td, tw / 2, th * 0.3, "Thanks for", font(70, italic=True), INK, shadow=True)
        centred(td, tw / 2, th * 0.4, "coming!", font(70, italic=True), INK, shadow=True)
        centred(td, tw / 2, th * 0.58, o.name, fit_font(td, o.name, tw * 0.85, 130), GOLD, shadow=True)
        sheet.paste(tag, (x, y))
    sheet.save(out, quality=95, dpi=(300, 300)); return out


# ---------------- colouring pages ----------------
def colouring_page(o: Order, out: Path) -> Path:
    """A4 line art: their animal riding a moonbeam past Saturn, with their name in outline letters."""
    W, H = 2480, 3508
    page = Image.new("L", (W, H), 255)
    m = (animal_mask(o.animal, 1400) > 0.5).astype(np.uint8) * 255
    mi = Image.fromarray(m)
    outer = np.asarray(mi.filter(ImageFilter.MaxFilter(13)), dtype=np.float32)
    inner = np.asarray(mi.filter(ImageFilter.MinFilter(3)), dtype=np.float32)
    edge = np.clip(outer - inner, 0, 255)
    a = np.asarray(page, dtype=np.float32)
    x0, y0 = 300, 1300
    a[y0:y0 + 1400, x0:x0 + 1400] -= edge
    page = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(page)
    # Saturn: back of the ring, the planet over it, then the front of the ring
    d.arc((1250, 640, 2350, 860), 180, 360, fill=0, width=10)
    d.ellipse((1500, 450, 2100, 1050), fill=255, outline=0, width=10)
    d.arc((1250, 640, 2350, 860), 0, 180, fill=0, width=10)
    # moonbeam
    pts = [(int(100 + t * 23), int(3100 - 900 * math.sin(t / 100 * math.pi / 2))) for t in range(101)]
    d.line(pts, fill=0, width=10); d.line([(x, y + 90) for x, y in pts], fill=0, width=10)
    # stars to colour
    rng = np.random.default_rng(5)
    for _ in range(14):
        cx, cy, r = rng.uniform(150, W - 150), rng.uniform(250, 1250), rng.uniform(50, 110)
        pts5 = [(cx + r * (1 if k % 2 == 0 else 0.45) * math.sin(k * math.pi / 5), cy - r * (1 if k % 2 == 0 else 0.45) * math.cos(k * math.pi / 5)) for k in range(10)]
        d.polygon(pts5, outline=0, width=8)
    # name in outline letters
    f = fit_font(d, o.name, W * 0.8, 520, bold=True)
    tw = d.textlength(o.name, font=f)
    d.text(((W - tw) / 2, 2950 - 320), o.name, font=f, fill=255, stroke_width=10, stroke_fill=0)
    page.convert("RGB").save(out, quality=95, dpi=(300, 300)); return out


def bedtime_chart(o: Order, levels, out: Path) -> Path:
    """A4 bedtime routine with tick boxes and their starlight animal."""
    W, H = 2480, 3508
    im = _card(levels, W, H, 70)
    a = np.asarray(im, dtype=np.float32) * 0.75
    starlight_silhouette(a, o.animal, W * 0.8, H * 0.9, 600, t=0.3)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
    centred(d, W / 2, 180, f"{o.name}'s Bedtime", fit_font(d, f"{o.name}'s Bedtime", W * 0.85, 190), GOLD, shadow=True)
    steps = ["Bath time", "Pyjamas on", "Brush teeth", "Choose a story", "Look out for my star", "Lights out, sweet dreams"]
    y = 620
    for s in steps:
        d.rounded_rectangle((260, y, 420, y + 160), radius=30, outline=GOLD, width=10)
        d.text((520, y + 30), s, font=font(100, serif=False), fill=INK)
        y += 420
    im.save(out, quality=95, dpi=(300, 300)); return out


def wallpaper(o: Order, levels, out: Path, w=1170, h=2532) -> Path:
    im = nebula_art(levels, w, h, depth=2, seed=80)
    a = np.asarray(im, dtype=np.float32)
    _stamp(a, w * 0.5, h * 0.6, big_star(int(w / 3)), np.array([255, 240, 210]) * 1.2)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
    centred(d, w / 2, h * 0.72, o.name, fit_font(d, o.name, w * 0.8, 200), GOLD, shadow=True)
    im.save(out, quality=93); return out


def make_all(o: Order, levels, out_dir: Path) -> dict[str, list[Path]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "party").mkdir(exist_ok=True); (out_dir / "party" / "banner").mkdir(exist_ok=True)
    return {
        "nursery print": [nursery_print(o, levels, out_dir / "nursery-print-8x10.jpg")],
        "party kit": [invitation(o, levels, out_dir / "party" / "invitation-5x7.jpg"),
                      thank_you(o, levels, out_dir / "party" / "thank-you-7x5.jpg"),
                      cupcake_toppers(o, levels, out_dir / "party" / "cupcake-toppers-A4.jpg"),
                      favour_tags(o, levels, out_dir / "party" / "favour-tags-A4.jpg"),
                      *banner(o, levels, out_dir / "party" / "banner")],
        "activities": [colouring_page(o, out_dir / "colouring-page-A4.jpg"),
                       bedtime_chart(o, levels, out_dir / "bedtime-chart-A4.jpg")],
        "wallpaper": [wallpaper(o, levels, out_dir / "phone-wallpaper.jpg")],
    }
