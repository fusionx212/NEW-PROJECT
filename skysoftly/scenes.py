"""Illustrated story scenes, drawn procedurally: the bedroom window, the starlight animal, the planets.

Everything is vector-like shapes and glow composited in numpy, so it renders on any computer with no
artwork licences. These are the building blocks for animated story videos.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .zoom import _spike_stamp, _stamp, sprinkle_stars

# Starlight animals as constellations: star positions (x, y in a unit box) and the lines between them.
ANIMALS = {
    "bunny": ([(0.30, 0.05), (0.36, 0.30), (0.45, 0.04), (0.47, 0.30), (0.44, 0.42), (0.38, 0.48),
               (0.50, 0.56), (0.66, 0.52), (0.80, 0.60), (0.86, 0.78), (0.76, 0.92), (0.55, 0.92),
               (0.45, 0.86), (0.92, 0.62)],
              [(0, 1), (2, 3), (1, 4), (3, 4), (4, 5), (4, 6), (6, 7), (7, 8), (8, 9), (9, 10), (10, 11),
               (11, 12), (12, 6), (8, 13)]),
    "fox": ([(0.18, 0.18), (0.24, 0.34), (0.32, 0.20), (0.30, 0.40), (0.14, 0.46), (0.42, 0.50), (0.62, 0.48),
             (0.78, 0.56), (0.70, 0.78), (0.48, 0.78), (0.44, 0.94), (0.72, 0.94), (0.92, 0.42), (0.98, 0.20)],
            [(0, 1), (2, 1), (1, 4), (2, 3), (3, 4), (3, 5), (5, 6), (6, 7), (7, 8), (8, 9), (9, 5), (9, 10),
             (8, 11), (7, 12), (12, 13)]),
    "cat": ([(0.20, 0.10), (0.26, 0.28), (0.36, 0.12), (0.38, 0.30), (0.30, 0.42), (0.40, 0.55), (0.66, 0.55),
             (0.80, 0.70), (0.74, 0.92), (0.44, 0.92), (0.88, 0.40), (0.84, 0.18)],
            [(0, 1), (2, 3), (1, 3), (1, 4), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 9), (9, 5), (7, 10), (10, 11)]),
}
ANIMALS["dog"] = ANIMALS["fox"]; ANIMALS["kitten"] = ANIMALS["cat"]; ANIMALS["rabbit"] = ANIMALS["bunny"]


# Cute silhouettes from ellipses and polygons in a unit box: ("e", x0, y0, x1, y1) or ("p", [(x, y), ...]).
SHAPES = {
    "bunny": [("e", 0.30, 0.50, 0.78, 0.95), ("e", 0.18, 0.36, 0.48, 0.64), ("e", 0.20, 0.00, 0.31, 0.44),
              ("e", 0.31, 0.02, 0.42, 0.44), ("e", 0.72, 0.68, 0.86, 0.82)],
    "fox": [("e", 0.30, 0.48, 0.76, 0.86), ("e", 0.12, 0.30, 0.44, 0.60), ("p", [(0.14, 0.38), (0.18, 0.14), (0.28, 0.32)]),
            ("p", [(0.28, 0.32), (0.38, 0.12), (0.42, 0.36)]), ("p", [(0.14, 0.48), (0.02, 0.56), (0.18, 0.58)]),
            ("e", 0.62, 0.40, 1.00, 0.70), ("e", 0.34, 0.80, 0.42, 0.98), ("e", 0.62, 0.80, 0.70, 0.98)],
    "cat": [("e", 0.32, 0.48, 0.76, 0.90), ("e", 0.16, 0.28, 0.46, 0.58), ("p", [(0.17, 0.36), (0.20, 0.12), (0.30, 0.30)]),
            ("p", [(0.32, 0.30), (0.42, 0.12), (0.45, 0.36)]), ("e", 0.70, 0.30, 0.80, 0.78)],
    "bear": [("e", 0.26, 0.42, 0.82, 0.96), ("e", 0.18, 0.18, 0.54, 0.54), ("e", 0.16, 0.12, 0.28, 0.26), ("e", 0.44, 0.12, 0.56, 0.26)],
    "owl": [("e", 0.28, 0.20, 0.72, 0.95), ("p", [(0.30, 0.26), (0.32, 0.08), (0.42, 0.22)]), ("p", [(0.58, 0.22), (0.68, 0.08), (0.70, 0.26)])],
    "elephant": [("e", 0.30, 0.36, 0.90, 0.84), ("e", 0.10, 0.26, 0.42, 0.60), ("e", 0.02, 0.50, 0.14, 0.95),
                 ("e", 0.26, 0.26, 0.48, 0.58), ("e", 0.40, 0.76, 0.52, 0.98), ("e", 0.70, 0.76, 0.82, 0.98)],
}
SHAPES["rabbit"] = SHAPES["bunny"]; SHAPES["kitten"] = SHAPES["cat"]; SHAPES["dog"] = SHAPES["fox"]
SHAPES["teddy"] = SHAPES["bear"]
EYES = {"bunny": (0.27, 0.48), "fox": (0.24, 0.43), "cat": (0.25, 0.42), "bear": (0.30, 0.34), "owl": (0.40, 0.40),
        "elephant": (0.22, 0.40)}


def animal_mask(animal: str, size: int) -> np.ndarray:
    m = Image.new("L", (size, size), 0); d = ImageDraw.Draw(m)
    for sh in SHAPES.get(animal, SHAPES["fox"]):
        if sh[0] == "e":
            d.ellipse([sh[1] * size, sh[2] * size, sh[3] * size, sh[4] * size], fill=255)
        else:
            d.polygon([(x * size, y * size) for x, y in sh[1]], fill=255)
    return np.asarray(m.filter(ImageFilter.GaussianBlur(size / 120)), dtype=np.float32) / 255


def starlight_silhouette(frame: np.ndarray, animal: str, cx: float, cy: float, size: float, t: float = 0.0,
                         colour=(255, 232, 200), seed: int = 0, alpha: float = 1.0) -> None:
    """The companion as a glowing silhouette: a bright rim, a soft inner glow full of sparkles, and moon eyes."""
    sz = int(size)
    m = animal_mask(animal if animal in SHAPES else "fox", sz)
    inner = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(max(3, (sz // 60) | 1))),
                       dtype=np.float32) / 255
    rim = np.clip(m - inner, 0, 1)
    rng = np.random.default_rng(seed)
    sp = np.zeros_like(m)
    k = sz * 2
    xs, ys = rng.integers(0, sz, k), rng.integers(0, sz, k)
    tw = 0.5 + 0.5 * np.sin(t * 3 + rng.uniform(0, 6.28, k))
    np.add.at(sp, (ys, xs), tw)
    sp *= inner
    body = rim * 1.0 + inner * 0.16 + sp * 0.9
    glow = np.asarray(Image.fromarray((np.clip(body, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(sz / 40)),
                      dtype=np.float32) / 255
    lum = np.clip(body + glow * 0.9, 0, 1.6) * (0.9 + 0.1 * math.sin(t * 1.6)) * alpha
    rgb = lum[..., None] * np.array(colour, dtype=np.float32)
    H, W = frame.shape[:2]
    x0, y0 = int(cx - sz / 2), int(cy - sz / 2)
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x0 + sz), min(H, y0 + sz)
    if xa < xb and ya < yb:
        frame[ya:yb, xa:xb] += rgb[ya - y0:yb - y0, xa - x0:xb - x0]
    ex, ey = EYES.get(animal, (0.25, 0.42))
    st = _spike_stamp(max(5, sz // 30))
    _stamp(frame, x0 + ex * sz, y0 + ey * sz, st, np.array([255, 250, 235]) * alpha)


def _glow(a: np.ndarray, r: float, k: float) -> np.ndarray:
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return a + np.asarray(im.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32) * k


def starlight_animal(frame: np.ndarray, animal: str, cx: float, cy: float, size: float, t: float = 0.0,
                     colour=(255, 236, 200)) -> None:
    """Draws the companion as a glowing constellation, gently breathing."""
    pts, lines = ANIMALS.get(animal, ANIMALS["fox"])
    H, W = frame.shape[:2]
    breathe = 1 + 0.02 * math.sin(t * 1.6)
    P = [(cx + (x - 0.5) * size * breathe, cy + (y - 0.5) * size * breathe) for x, y in pts]
    layer = Image.new("RGB", (W, H)); d = ImageDraw.Draw(layer)
    for a, b in lines:
        d.line([P[a], P[b]], fill=tuple(int(c * 0.45) for c in colour), width=max(2, int(size / 140)))
    arr = np.asarray(layer, dtype=np.float32)
    arr = _glow(arr, size / 60, 1.2)
    frame += arr
    st = _spike_stamp(max(6, int(size / 22)))
    for i, (x, y) in enumerate(P):
        tw = 0.8 + 0.2 * math.sin(t * 2.1 + i * 1.7)
        _stamp(frame, x, y, st, np.array(colour, dtype=np.float32) * tw)


def planet(frame: np.ndarray, kind: str, cx: float, cy: float, r: float, light=(-0.6, -0.5)) -> None:
    """A shaded planet sprite: Jupiter's bands, Mars' rust, Saturn with its rings."""
    H, W = frame.shape[:2]
    R = int(r * (2.4 if kind == "Saturn" else 1.05))
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1].astype(np.float32)
    nx, ny = xx / r, yy / r
    inside = nx ** 2 + ny ** 2 <= 1
    nz = np.sqrt(np.clip(1 - nx ** 2 - ny ** 2, 0, 1))
    lx, ly = light
    lz = math.sqrt(max(0.0, 1 - lx ** 2 - ly ** 2))
    shade = np.clip(nx * lx + ny * ly + nz * lz, 0, 1) ** 0.8
    if kind == "Jupiter":
        band = 0.5 + 0.5 * np.sin(ny * 13 + 0.6 * np.sin(nx * 4))
        base = np.stack([0.85 + 0.1 * band, 0.68 + 0.12 * band, 0.5 + 0.1 * band], -1)
    elif kind == "Mars":
        base = np.stack([0.78 + 0 * nx, 0.38 + 0.05 * np.sin(nx * 7) * np.cos(ny * 5), 0.24 + 0 * nx], -1)
    elif kind == "Saturn":
        band = 0.5 + 0.5 * np.sin(ny * 9)
        base = np.stack([0.9 + 0.05 * band, 0.8 + 0.05 * band, 0.58 + 0.05 * band], -1)
    else:
        base = np.stack([0.8 + 0 * nx, 0.8 + 0 * nx, 0.82 + 0 * nx], -1)
    sprite = base * shade[..., None] * inside[..., None]
    alpha = inside.astype(np.float32)
    if kind == "Saturn":
        tilt = 0.28
        ry_ = yy / (r * tilt)
        rr = np.sqrt((xx / r) ** 2 + ry_ ** 2)
        ring = ((rr > 1.35) & (rr < 2.25)).astype(np.float32) * (0.55 + 0.35 * np.sin(rr * 30))
        front = (ny > 0) | ~inside                     # rings pass in front of the lower half
        ring_rgb = np.stack([0.85 * ring, 0.78 * ring, 0.62 * ring], -1)
        sprite = np.where((front & (ring > 0))[..., None], sprite * 0.2 + ring_rgb, sprite)
        alpha = np.maximum(alpha, ring * front)
    x0, y0 = int(cx) - R, int(cy) - R
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x0 + 2 * R + 1), min(H, y0 + 2 * R + 1)
    if xa < xb and ya < yb:
        a = alpha[ya - y0:yb - y0, xa - x0:xb - x0, None]
        frame[ya:yb, xa:xb] = frame[ya:yb, xa:xb] * (1 - a) + sprite[ya - y0:yb - y0, xa - x0:xb - x0] * 255 * a


def bedroom_window(W: int, H: int, sky: Image.Image, star_glow: float = 1.0, seed: int = 0) -> np.ndarray:
    """A dim bedroom: arched window onto the night sky, curtains, the edge of a bed and a nightlight glow."""
    wall = np.zeros((H, W, 3), np.float32)
    gy = np.linspace(0, 1, H)[:, None, None]
    wall[:] = np.array([16, 22, 48]) * (0.6 + 0.4 * gy)
    # window opening with an arched top
    wx0, wx1, wy0, wy1 = int(W * 0.36), int(W * 0.64), int(H * 0.12), int(H * 0.72)
    mask = Image.new("L", (W, H), 0); dm = ImageDraw.Draw(mask)
    dm.rectangle((wx0, wy0 + (wx1 - wx0) // 2, wx1, wy1), fill=255)
    dm.ellipse((wx0, wy0, wx1, wy0 + (wx1 - wx0)), fill=255)
    skyimg = sprinkle_stars(sky.resize((W, H)), seed=seed, density=0.7)
    m = np.asarray(mask, dtype=np.float32)[..., None] / 255
    frame = wall * (1 - m) + np.asarray(skyimg, dtype=np.float32) * m
    # window frame and cross bars
    fr = Image.new("L", (W, H), 0); df = ImageDraw.Draw(fr)
    df.ellipse((wx0, wy0, wx1, wy0 + (wx1 - wx0)), outline=255, width=14)
    df.rectangle((wx0, wy0 + (wx1 - wx0) // 2, wx1, wy1), outline=255, width=14)
    df.line(((wx0 + wx1) // 2, wy0, (wx0 + wx1) // 2, wy1), fill=255, width=10)
    df.line((wx0, int(H * 0.47), wx1, int(H * 0.47)), fill=255, width=10)
    df.rectangle((wx0 - 40, wy1, wx1 + 40, wy1 + 22), fill=255)            # sill
    f = np.asarray(fr, dtype=np.float32)[..., None] / 255
    frame = frame * (1 - f) + np.array([34, 38, 66]) * f
    # curtains
    cu = Image.new("L", (W, H), 0); dc = ImageDraw.Draw(cu)
    dc.polygon([(wx0 - 300, 0), (wx0 + 30, 0), (wx0 + 70, int(H * 0.35)), (wx0 + 10, int(H * 0.8)), (wx0 - 320, int(H * 0.86))], fill=255)
    dc.polygon([(wx1 + 300, 0), (wx1 - 30, 0), (wx1 - 70, int(H * 0.35)), (wx1 - 10, int(H * 0.8)), (wx1 + 320, int(H * 0.86))], fill=255)
    c = np.asarray(cu.filter(ImageFilter.GaussianBlur(3)), dtype=np.float32)[..., None] / 255
    folds = 0.75 + 0.25 * np.sin(np.arange(W) / 18.0)[None, :, None]
    frame = frame * (1 - c) + np.array([44, 36, 80]) * folds * c
    # bed edge and blanket
    bed = Image.new("L", (W, H), 0); db = ImageDraw.Draw(bed)
    db.rounded_rectangle((-50, int(H * 0.8), int(W * 0.8), H + 60), radius=90, fill=255)
    b = np.asarray(bed.filter(ImageFilter.GaussianBlur(4)), dtype=np.float32)[..., None] / 255
    frame = frame * (1 - b) + np.array([52, 46, 92]) * b
    # nightlight glow, bottom right
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    frame += np.exp(-((xx - W * 0.9) ** 2 + (yy - H * 0.86) ** 2) / (2 * (W * 0.09) ** 2))[..., None] * np.array([120, 90, 50])
    # the star in the window
    st = _spike_stamp(int(W / 30))
    _stamp(frame, W * 0.55, H * 0.3, st, np.array([255, 240, 215]) * star_glow)
    return frame
