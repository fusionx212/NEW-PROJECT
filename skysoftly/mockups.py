"""Lifestyle listing photos, rendered from scratch: a nursery wall, a party flat lay, a tablet on a bed,
a phone on a table. Etsy buyers respond best to seeing the product in a home, and these need no stock
photos or mockup licences.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PX = 2000


def _noise(rng, h, w, scale):
    small = rng.normal(0, 1, (max(2, h // scale), max(2, w // scale))).astype(np.float32)
    return np.asarray(Image.fromarray(small).resize((w, h), Image.BICUBIC), dtype=np.float32)


def _light(h, w, cx, cy, spread, strength):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return 1 + strength * np.exp(-(((xx - cx) / w) ** 2 + ((yy - cy) / h) ** 2) / spread)


def _shadow_paste(base: Image.Image, item: Image.Image, xy, blur=28, offset=(18, 26), opacity=150, angle=0.0):
    item = item.convert("RGBA")
    if angle:
        item = item.rotate(angle, resample=Image.BICUBIC, expand=True)
    sh = Image.new("RGBA", (item.width + 4 * blur, item.height + 4 * blur), (0, 0, 0, 0))
    alpha = item.split()[3].point(lambda v: opacity if v > 0 else 0)
    sh.paste(Image.new("RGBA", item.size, (20, 15, 10, 255)), (2 * blur, 2 * blur), alpha)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(sh, (xy[0] - 2 * blur + offset[0], xy[1] - 2 * blur + offset[1]))
    base.alpha_composite(item, xy)


def _wood(rng, h, w, base=(176, 128, 86), plank=None, vertical=False):
    g = _noise(rng, h, w, 6)
    streak = _noise(rng, h, max(2, w // 60), 1) if not vertical else _noise(rng, max(2, h // 60), w, 1)
    streak = np.asarray(Image.fromarray(streak).resize((w, h), Image.BICUBIC), dtype=np.float32)
    v = 1 + 0.05 * g + 0.08 * streak
    img = np.ones((h, w, 3), np.float32) * np.array(base, np.float32) * v[..., None]
    if plank:
        for x in range(0, w if not vertical else h, plank):
            if vertical:
                img[x:x + 3] *= 0.75
            else:
                img[:, x:x + 3] *= 0.75
    return img


def framed(print_img: Image.Image, width: int, frame=(232, 222, 205), mat=True) -> Image.Image:
    """A thin light-oak frame with a white mat around the print."""
    pw = int(width * (0.78 if mat else 0.92))
    ph = int(pw * print_img.height / print_img.width)
    fb = int(width * 0.04)
    W = width; H = ph + (W - pw)
    im = Image.new("RGB", (W, H), frame)
    d = ImageDraw.Draw(im)
    for i in range(fb):  # bevel shading on the frame
        c = tuple(int(v * (0.82 + 0.18 * i / fb)) for v in frame)
        d.rectangle((i, i, W - 1 - i, H - 1 - i), outline=c)
    d.rectangle((fb, fb, W - fb, H - fb), fill=(248, 247, 243) if mat else (20, 20, 20))
    im.paste(print_img.resize((pw, ph), Image.LANCZOS), ((W - pw) // 2, (H - ph) // 2))
    d.rectangle(((W - pw) // 2 - 2, (H - ph) // 2 - 2, (W + pw) // 2 + 1, (H + ph) // 2 + 1), outline=(205, 200, 190), width=3)
    return im


def _plant(size, rng):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    pot = (int(size * 0.3), int(size * 0.68), int(size * 0.7), size - 2)
    d.rounded_rectangle(pot, radius=size // 18, fill=(214, 196, 172))
    for i in range(16):
        ang = rng.uniform(-2.3, -0.8); L = rng.uniform(0.25, 0.5) * size
        x0, y0 = size * 0.5, size * 0.7
        x1, y1 = x0 + math.cos(ang) * L, y0 + math.sin(ang) * L
        d.line((x0, y0, x1, y1), fill=(70, 100, 60), width=max(2, size // 120))
        g = tuple(int(c * rng.uniform(0.8, 1.1)) for c in (86, 128, 78))
        r = size * rng.uniform(0.05, 0.08)
        d.ellipse((x1 - r, y1 - r * 0.6, x1 + r, y1 + r * 0.6), fill=g)
    return im


def nursery_wall(print_img: Image.Image, seed: int = 1, wall=(222, 214, 200)) -> Image.Image:
    rng = np.random.default_rng(seed)
    H = W = PX
    floor_y = int(H * 0.8)
    wa = np.ones((H, W, 3), np.float32) * np.array(wall, np.float32)
    wa *= (1 + 0.025 * _noise(rng, H, W, 3))[..., None]
    wa *= _light(H, W, W * 0.15, H * 0.2, 0.35, 0.22)[..., None]          # window light from the left
    wa *= np.linspace(1.0, 0.82, W)[None, :, None]
    wa[floor_y:] = _wood(rng, H - floor_y, W, plank=170) * np.linspace(0.95, 0.7, H - floor_y)[:, None, None]
    wa[floor_y:floor_y + 8] *= 0.6                                        # skirting shadow
    base = Image.fromarray(np.clip(wa, 0, 255).astype(np.uint8)).convert("RGBA")
    fr = framed(print_img, int(W * 0.36))
    _shadow_paste(base, fr, ((W - fr.width) // 2, int(H * 0.12)))
    # cot rails, bottom right
    cot = Image.new("RGBA", (int(W * 0.55), int(H * 0.38)), (0, 0, 0, 0)); dc = ImageDraw.Draw(cot)
    cw, ch = cot.size
    dc.rounded_rectangle((0, 0, cw, int(ch * 0.08)), radius=20, fill=(245, 241, 233))
    for x in range(30, cw, 70):
        dc.rounded_rectangle((x, int(ch * 0.05), x + 26, ch), radius=12, fill=(240, 236, 228))
    dc.rounded_rectangle((0, int(ch * 0.05), 40, ch), radius=14, fill=(236, 231, 222))
    _shadow_paste(base, cot, (int(W * 0.5), int(H * 0.64)), blur=20, offset=(14, 10), opacity=110)
    _shadow_paste(base, _plant(int(W * 0.32), rng), (int(W * 0.02), int(H * 0.55)), blur=24, opacity=100)
    return base.convert("RGB")


def flat_lay(card: Image.Image, seed: int = 2) -> Image.Image:
    rng = np.random.default_rng(seed)
    table = _wood(rng, PX, PX, base=(196, 164, 128), plank=330)
    table *= _light(PX, PX, PX * 0.3, PX * 0.25, 0.5, 0.15)[..., None]
    base = Image.fromarray(np.clip(table, 0, 255).astype(np.uint8)).convert("RGBA")
    env = Image.new("RGBA", (int(PX * 0.5), int(PX * 0.62)), (214, 186, 150, 255))
    ImageDraw.Draw(env).polygon([(0, 0), (env.width, 0), (env.width // 2, int(env.height * 0.35))], fill=(200, 170, 134, 255))
    _shadow_paste(base, env, (int(PX * 0.42), int(PX * 0.2)), angle=-8)
    c = card.resize((int(PX * 0.45), int(PX * 0.45 * card.height / card.width)), Image.LANCZOS)
    _shadow_paste(base, c, (int(PX * 0.12), int(PX * 0.14)), angle=4)
    # eucalyptus sprig
    sp = Image.new("RGBA", (700, 700), (0, 0, 0, 0)); ds = ImageDraw.Draw(sp)
    ds.line((60, 640, 640, 60), fill=(110, 130, 110), width=6)
    for i in range(9):
        t = (i + 0.5) / 9; x, y = 60 + 580 * t, 640 - 580 * t
        side = 1 if i % 2 else -1
        r = 62 - i * 3
        leaf = Image.new("RGBA", (2 * r, int(2 * r * 0.75)), (0, 0, 0, 0))
        ImageDraw.Draw(leaf).ellipse((0, 0, 2 * r - 1, int(2 * r * 0.75) - 1), fill=(128 + i * 3, 158, 138, 255))
        leaf = leaf.rotate(45 + side * 30, expand=True)
        sp.alpha_composite(leaf, (int(x + side * 46 - leaf.width / 2), int(y + side * 46 - leaf.height / 2)))
    _shadow_paste(base, sp, (int(PX * 0.62), int(PX * 0.62)), blur=16, opacity=90)
    # gold star confetti
    dd = ImageDraw.Draw(base)
    for _ in range(26):
        cx, cy, r = rng.uniform(80, PX - 80), rng.uniform(80, PX - 80), rng.uniform(14, 30)
        a0 = rng.uniform(0, 1)
        pts = [(cx + r * (1 if k % 2 == 0 else 0.45) * math.sin(k * math.pi / 5 + a0), cy - r * (1 if k % 2 == 0 else 0.45) * math.cos(k * math.pi / 5 + a0)) for k in range(10)]
        dd.polygon(pts, fill=(222, 184, 92))
    return base.convert("RGB")


def device(screen: Image.Image, w: int, h: int, bezel: int, radius: int, fit: str = "cover") -> Image.Image:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=(24, 24, 28, 255))
    sw, sh = w - 2 * bezel, h - 2 * bezel
    s = screen.convert("RGB")
    if fit == "contain":                       # show the whole page, centred on the page's own background colour
        scale = min(sw / s.width, sh / s.height)
        s2 = s.resize((int(s.width * scale), int(s.height * scale)), Image.LANCZOS)
        bg = Image.new("RGB", (sw, sh), s.getpixel((s.width // 2, s.height - 5)))
        bg.paste(s2, ((sw - s2.width) // 2, (sh - s2.height) // 2)); s = bg
    else:
        scale = max(sw / s.width, sh / s.height)
        s = s.resize((int(s.width * scale) + 1, int(s.height * scale) + 1), Image.LANCZOS)
        s = s.crop(((s.width - sw) // 2, (s.height - sh) // 2, (s.width - sw) // 2 + sw, (s.height - sh) // 2 + sh))
    m = Image.new("L", (sw, sh), 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, sw - 1, sh - 1), radius=max(4, radius - bezel), fill=255)
    im.paste(s, (bezel, bezel), m)
    gl = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ImageDraw.Draw(gl).polygon([(0, 0), (int(w * 0.55), 0), (0, int(h * 0.5))], fill=(255, 255, 255, 18))
    im.alpha_composite(gl)
    return im


def tablet_on_bed(page: Image.Image, seed: int = 3) -> Image.Image:
    rng = np.random.default_rng(seed)
    cloth = np.ones((PX, PX, 3), np.float32) * np.array([214, 222, 232], np.float32)
    folds = _noise(rng, PX, PX, 160)
    cloth *= (1 + 0.06 * folds + 0.015 * _noise(rng, PX, PX, 2))[..., None]
    cloth *= _light(PX, PX, PX * 0.7, PX * 0.2, 0.6, 0.12)[..., None]
    base = Image.fromarray(np.clip(cloth, 0, 255).astype(np.uint8)).convert("RGBA")
    tab = device(page, int(PX * 0.62), int(PX * 0.62 * 1.3), 40, 60, fit="contain")
    _shadow_paste(base, tab, (int(PX * 0.18), int(PX * 0.12)), angle=-6, blur=34, opacity=140)
    return base.convert("RGB")


def phone_on_table(screen: Image.Image, seed: int = 4) -> Image.Image:
    rng = np.random.default_rng(seed)
    table = _wood(rng, PX, PX, base=(120, 86, 60), plank=400) * _light(PX, PX, PX * 0.5, PX * 0.3, 0.4, 0.25)[..., None]
    base = Image.fromarray(np.clip(table, 0, 255).astype(np.uint8)).convert("RGBA")
    ph = device(screen, int(PX * 0.42), int(PX * 0.42 * 2.1), 22, 70)
    _shadow_paste(base, ph, (int(PX * 0.29), int(PX * 0.06)), angle=3, blur=30)
    mug = Image.new("RGBA", (420, 420), (0, 0, 0, 0)); dm = ImageDraw.Draw(mug)
    dm.ellipse((10, 10, 410, 410), fill=(236, 230, 220, 255)); dm.ellipse((50, 50, 370, 370), fill=(120, 80, 50, 255))
    _shadow_paste(base, mug, (int(PX * 0.72), int(PX * 0.7)), blur=20)
    return base.convert("RGB")
