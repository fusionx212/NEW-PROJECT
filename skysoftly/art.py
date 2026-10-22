"""Illustrated story art made in Canva (skysoftly/art/).

Backgrounds are full 16:9 paintings. Glowing pieces (the starlight bunny, the moonbeam, the star, the moon
and the star field) were painted on black, so they are laid over a scene with a screen blend: black vanishes
and the light adds on top, the way real glow would.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .video import _affine

DIR = Path(__file__).parent / "art"

# Animals we have painted art for, and which file each pose uses.
ANIMAL_ART = {
    "bunny": {"sit": "bunny-sit", "leap": "bunny-leap", "sleep": "bunny-sleep"},
}
ANIMAL_ALIASES = {"rabbit": "bunny", "hare": "bunny", "bunny rabbit": "bunny"}

# Where things sit inside each background, as fractions of the painting.
BEDROOM = {"focus": (0.55, 0.33), "star": (0.64, 0.21), "moon": (0.45, 0.13), "sill": (0.56, 0.645),
           "bed": (0.24, 0.80), "window": (0.365, 0.02, 0.735, 0.61)}
# The moonbeam ribbon's path across its own image, bottom-left to top-right.
RIBBON_PATH = [(0.04, 0.93), (0.18, 0.74), (0.33, 0.66), (0.48, 0.55), (0.58, 0.42), (0.70, 0.30), (0.84, 0.24), (0.95, 0.07)]


def animal_key(animal: str) -> str | None:
    a = (animal or "").strip().lower()
    a = ANIMAL_ALIASES.get(a, a)
    return a if a in ANIMAL_ART else None


@lru_cache(maxsize=None)
def image(name: str) -> Image.Image:
    return Image.open(DIR / f"{name}.jpg").convert("RGB")


@lru_cache(maxsize=512)
def sprite(name: str, height: int, flip: bool = False) -> np.ndarray:
    """A glowing piece resized to a given height (cached in 4px steps)."""
    im = image(name)
    h = max(4, int(height))
    w = max(4, int(im.width * h / im.height))
    im = im.resize((w, h), Image.LANCZOS)
    if flip:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    return np.asarray(im, np.float32)


PLANETS = ("saturn", "jupiter", "mars", "venus", "mercury")


@lru_cache(maxsize=256)
def solid(name: str, height: int) -> np.ndarray:
    """A solid painted piece (a planet) with its alpha, resized to a height."""
    im = Image.open(DIR / f"{name}.png").convert("RGBA")
    h = max(4, int(height))
    im = im.resize((max(4, int(im.width * h / im.height)), h), Image.LANCZOS)
    return np.asarray(im, np.float32)


def over(frame: np.ndarray, spr: np.ndarray, cx: float, cy: float) -> None:
    """Lay a solid RGBA sprite over the frame in place, centred on (cx, cy)."""
    H, W = frame.shape[:2]
    h, w = spr.shape[:2]
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if xa >= xb or ya >= yb:
        return
    s = spr[ya - y0:yb - y0, xa - x0:xb - x0]
    a = s[..., 3:4] / 255.0
    frame[ya:yb, xa:xb] = frame[ya:yb, xa:xb] * (1 - a) + s[..., :3] * a


def screen(frame: np.ndarray, spr: np.ndarray, cx: float, cy: float, gain: float = 1.0, anchor: str = "centre") -> None:
    """Screen-blend a glowing sprite onto the frame in place. anchor='bottom' puts (cx, cy) at its base."""
    if gain <= 0.003:
        return
    H, W = frame.shape[:2]
    h, w = spr.shape[:2]
    x0 = int(round(cx - w / 2))
    y0 = int(round(cy - (h if anchor == "bottom" else h / 2)))
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if xa >= xb or ya >= yb:
        return
    s = np.minimum(spr[ya - y0:yb - y0, xa - x0:xb - x0] * gain, 255.0)
    region = frame[ya:yb, xa:xb]
    frame[ya:yb, xa:xb] = 255.0 - (255.0 - np.clip(region, 0, 255)) * (255.0 - s) / 255.0


def glow(frame: np.ndarray, spr: np.ndarray, cx: float, cy: float, gain: float = 1.0, anchor: str = "centre") -> None:
    """Lay a glowing figure over a bright scene: solid where it is bright, with a soft screen glow around it."""
    if gain <= 0.003:
        return
    H, W = frame.shape[:2]
    h, w = spr.shape[:2]
    x0 = int(round(cx - w / 2))
    y0 = int(round(cy - (h if anchor == "bottom" else h / 2)))
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if xa >= xb or ya >= yb:
        return
    s = spr[ya - y0:yb - y0, xa - x0:xb - x0]
    a = np.clip((s.max(2, keepdims=True) - 25) / 110, 0, 1) ** 0.8 * min(gain, 1.0)
    region = frame[ya:yb, xa:xb] * (1 - a) + s * a
    g = np.minimum(s * 0.45 * gain, 255.0)
    frame[ya:yb, xa:xb] = 255.0 - (255.0 - np.clip(region, 0, 255)) * (255.0 - g) / 255.0


def ken_burns(img: Image.Image, W: int, H: int, z: float, fx: float, fy: float, th: float = 0.0):
    """A W x H view into img, zoomed z times past 'cover', centred near (fx, fy) given as fractions.

    Returns (frame, to_screen) where to_screen(px, py) maps painting fractions to frame pixels."""
    bw, bh = img.size
    s = max(bw / W, bh / H) / z
    hx, hy = s * W / 2, s * H / 2
    cx = min(max(fx * bw, hx), bw - hx)
    cy = min(max(fy * bh, hy), bh - hy)
    f = np.asarray(img.transform((W, H), Image.AFFINE, _affine(cx, cy, s, th, W, H), resample=Image.BILINEAR), np.float32)

    def to_screen(px, py):
        return W / 2 + (px * bw - cx) / s, H / 2 + (py * bh - cy) / s
    return f, to_screen, 1 / s


def along(path, k: float):
    """Point and heading at fraction k (0..1) along a polyline."""
    seg = [math.dist(a, b) for a, b in zip(path, path[1:])]
    d = min(max(k, 0.0), 1.0) * sum(seg)
    for (a, b), L in zip(zip(path, path[1:]), seg):
        if d <= L or b == path[-1]:
            u = d / L if L else 0
            return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u), math.atan2(b[1] - a[1], b[0] - a[0])
        d -= L
    return path[-1], 0.0
