"""Deep Ken Burns zoom into a nebula, landing on one star that bursts into a person's name.

The zoom goes far beyond what one image can hold (64x by default), so the nebula is built as a stack of
nested levels. Level 0 is the full still. Each deeper level covers half the width of the one above, centred
on the person's star, and is made by upscaling that crop and painting in new fine filaments and dust, so the
picture keeps revealing detail instead of going soft. Levels cross-fade as the camera passes through.

Stars are never upscaled. They live in one catalogue in level-0 coordinates and are drawn as crisp points
every frame, with fainter populations fading in as the camera goes deeper, plus a 3D layer that streams
past the camera for a sense of flight.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .nebula import _noise, _norm, _ridged, _warp

LEVEL_FIT = 0.98       # a level is usable while the view covers at most this fraction of it


def _smooth(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def pick_star_spot(gas: np.ndarray) -> tuple[float, float]:
    """A place for the person's star: the densest glowing gas in the middle half of the still."""
    n = gas.shape[0]
    im = Image.fromarray((gas * 255).astype(np.uint8)).convert("L").resize((128, 128))
    m = np.asarray(im.filter(ImageFilter.GaussianBlur(5)), dtype=np.float32)
    mask = np.zeros_like(m); mask[40:88, 40:88] = 1
    yy, xx = np.unravel_index(np.argmax(m * mask), m.shape)
    return (xx + 0.5) / 128 * n, (yy + 0.5) / 128 * n


def _resize_f(a: np.ndarray, box, n: int) -> np.ndarray:
    """Crop and bicubic-resize a float field without quantising it."""
    im = Image.fromarray(a.astype(np.float32), mode="F")
    return np.asarray(im.crop(box).resize((n, n), Image.BICUBIC), dtype=np.float32)


def build_levels(gas: np.ndarray, T: tuple[float, float], n_levels: int, seed: int, log=print) -> list[Image.Image]:
    """Nested zoom levels. Brightness and colour are kept apart: each level adds new fine structure to the
    brightness, then remaps it to exactly the brightness distribution of the crop it came from, so exposure and
    contrast never drift however deep the zoom goes. Colour is carried down unchanged."""
    n = gas.shape[0]
    rng = np.random.default_rng(seed ^ 0xD00D)
    rgb0 = np.clip(gas, 0, 1) ** (1 / 1.1)
    lum = rgb0.mean(-1).astype(np.float32)
    chroma = (rgb0 / (lum[..., None] + 0.02)).astype(np.float32)
    levels = [Image.fromarray((rgb0 * 255).astype(np.uint8))]
    ref = None                                   # tonal reference: the first zoom level, which has rich contrast
    for L in range(1, n_levels):
        if L == 1:
            box = (int(T[0] - n / 4), int(T[1] - n / 4), int(T[0] + n / 4), int(T[1] + n / 4))
        else:
            box = (n // 4, n // 4, 3 * n // 4, 3 * n // 4)
        base = _resize_f(lum, box, n)
        chroma = np.stack([_resize_f(chroma[..., c], box, n) for c in range(3)], -1)
        cm = chroma.mean(-1, keepdims=True)
        chroma = cm + (chroma - cm) * 1.07                                # keep colour from fading with depth
        wx, wy = _noise(rng, n, 4.0), _noise(rng, n, 4.0)
        f = _warp(_noise(rng, n, 3.1), wx, wy, 40 * n / 2048)
        fil = _norm(_ridged(f, 2.6)) - 0.45                               # new fine filaments
        d = _warp(_noise(rng, n, 3.4), wx, wy, 30 * n / 2048)
        dust = np.clip((_norm(d) - 0.6) * 2.4, 0, 1) ** 0.8 * 0.7          # new dark knots and lanes
        where = np.clip(_blur_img(base, 6) * 3.0, 0, 1)
        new = base * (1 + 0.9 * fil * where) * (1 - dust * where)
        # histogram-match to the reference: same tonal range at every depth, new structure each time
        if ref is None:
            ref = np.sort(new.ravel())
        order = np.argsort(new.ravel(), kind="stable")
        matched = np.empty(new.size, dtype=np.float32)
        matched[order] = ref
        lum = matched.reshape(n, n)
        rgb = np.clip(chroma * (lum[..., None] + 0.02), 0, 1)
        levels.append(Image.fromarray((rgb * 255).astype(np.uint8)))
        log(f"    level {L} ready")
    return levels


def _blur_img(a, r):
    im = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32) / 255


class StarCatalogue:
    """Stars in level-0 pixel coordinates. Population L lives inside level L's region and fades in near zoom 2^L."""

    def __init__(self, n: int, T, n_levels: int, seed: int, per_level: int = 8000):
        rng = np.random.default_rng(seed ^ 0x57A2)
        xs, ys, bs, lv, cols = [], [], [], [], []
        for L in range(n_levels):
            side = n / 2 ** L
            cx, cy = (n / 2, n / 2) if L == 0 else T
            k = per_level
            x = rng.uniform(cx - side / 2, cx + side / 2, k); y = rng.uniform(cy - side / 2, cy + side / 2, k)
            # three loose star clusters per level, so the sky has clumps and voids like a real one
            for _ in range(3):
                ccx, ccy = rng.uniform(cx - side * 0.4, cx + side * 0.4), rng.uniform(cy - side * 0.4, cy + side * 0.4)
                m = k // 40
                idx = rng.choice(k, m, replace=False)
                x[idx] = rng.normal(ccx, side * 0.025, m); y[idx] = rng.normal(ccy, side * 0.025, m)
            xs.append(x); ys.append(y)
            bs.append(rng.pareto(2.0, k) * 0.24 + 0.05); lv.append(np.full(k, L))
            t = rng.uniform(0, 1, k)
            cols.append(np.stack([0.78 + 0.3 * t, 0.82 + 0.1 * t, 1.12 - 0.4 * t], 1))
        self.x = np.concatenate(xs); self.y = np.concatenate(ys); self.b = np.concatenate(bs).astype(np.float32)
        self.lv = np.concatenate(lv); self.col = np.clip(np.concatenate(cols), 0, 1.2).astype(np.float32)
        # keep the space right next to the person's star clear so it stands alone
        d = np.hypot(self.x - T[0], self.y - T[1]) * 2.0 ** self.lv
        self.b[d < n * 0.03] *= 0.15


def _spike_stamp(r: int) -> np.ndarray:
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    core = np.exp(-(xx ** 2 + yy ** 2) / 2.0)
    sp = np.exp(-np.abs(xx) / (r / 4)) * np.exp(-yy ** 2 / 0.6) + np.exp(-np.abs(yy) / (r / 4)) * np.exp(-xx ** 2 / 0.6)
    halo = np.exp(-(xx ** 2 + yy ** 2) / (2 * (r / 6) ** 2)) * 0.25
    s = core + 0.6 * sp + halo
    return (s / s.max()).astype(np.float32)


def _stamp(img, cx, cy, stamp, rgb):
    H, W = img.shape[:2]
    sh, sw = stamp.shape[:2]
    x0, y0 = int(round(cx)) - sw // 2, int(round(cy)) - sh // 2
    xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + sw, W), min(y0 + sh, H)
    if xa >= xb or ya >= yb:
        return
    img[ya:yb, xa:xb] += stamp[ya - y0:yb - y0, xa - x0:xb - x0, None] * rgb


def name_points(name: str, W: int, H: int, y_centre: float, font, max_points: int = 1600, seed: int = 0):
    """Sample points inside the glyphs of the name, used as particle destinations."""
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    tw = d.textlength(name, font=font)
    bb = font.getbbox(name)
    d.text(((W - tw) / 2, H * y_centre - (bb[3] + bb[1]) / 2), name, font=font, fill=255)
    m = np.asarray(img)
    ys, xs = np.nonzero(m > 128)
    rng = np.random.default_rng(seed)
    if len(xs) > max_points:
        idx = rng.choice(len(xs), max_points, replace=False)
        xs, ys = xs[idx], ys[idx]
    return xs.astype(np.float32), ys.astype(np.float32), np.asarray(img, dtype=np.float32) / 255


def make_wisps(n: int, seed: int, colour) -> Image.Image:
    """A translucent layer of fine gas wisps that drifts past the camera, in front of the nebula."""
    rng = np.random.default_rng(seed ^ 0x3171)
    wx, wy = _noise(rng, n, 4.2), _noise(rng, n, 4.2)
    f = _warp(_noise(rng, n, 3.3), wx, wy, 70 * n / 2048)
    w = _norm(_ridged(f, 3.2)) * _norm(_noise(rng, n, 4.6)) ** 1.5
    a = np.clip((w - 0.12) * 1.6, 0, 1) ** 1.4
    rgb = np.ones((n, n, 3), dtype=np.float32) * np.asarray(colour, dtype=np.float32)
    rgba = np.concatenate([rgb, a[..., None]], -1)
    return Image.fromarray((np.clip(rgba, 0, 1) * 255).astype(np.uint8), mode="RGBA")


def galaxy_sprite(rng, size: int) -> np.ndarray:
    """A small, tilted spiral-ish galaxy: bright core, soft elliptical disc, faint arms."""
    r = size
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    th = rng.uniform(0, np.pi); incl = rng.uniform(0.25, 0.8)
    xr = xx * np.cos(th) + yy * np.sin(th); yr = (-xx * np.sin(th) + yy * np.cos(th)) / incl
    rr = np.sqrt(xr ** 2 + yr ** 2) / r
    ang = np.arctan2(yr, xr)
    arms = 0.5 + 0.5 * np.cos(2 * ang - 6.0 * rr)
    disc = np.exp(-rr * 4.5) * (0.55 + 0.45 * arms)
    core = np.exp(-(rr * 9) ** 2)
    g = disc * 0.6 + core
    tint = np.array([1.0, 0.92, 0.8]) if rng.uniform() < 0.6 else np.array([0.8, 0.88, 1.0])
    return (g[..., None] * tint).astype(np.float32)


def sprinkle_stars(img: Image.Image, seed: int, density: float = 1.0) -> Image.Image:
    """Adds a natural star field with a few spiked bright stars to a still (for book pages and listings)."""
    rng = np.random.default_rng(seed)
    a = np.asarray(img, dtype=np.float32).copy()
    H, W = a.shape[:2]
    k = int(W * H / 900 * density)
    xs = rng.integers(1, W - 1, k); ys = rng.integers(1, H - 1, k)
    b = (rng.pareto(2.0, k) * 0.25 + 0.05).clip(0, 1.5) * 255
    for oy in (-1, 0, 1):
        for ox in (-1, 0, 1):
            w = 1.0 if ox == oy == 0 else (0.45 if ox == 0 or oy == 0 else 0.15)
            np.add.at(a, (ys + oy, xs + ox), (b * w)[:, None] * np.array([0.95, 0.97, 1.0]))
    st = _spike_stamp(int(W / 60))
    for _ in range(int(6 * density)):
        _stamp(a, rng.uniform(0, W), rng.uniform(0, H), st, np.array([255, 245, 230]) * rng.uniform(0.6, 1.0))
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def big_star(r: int) -> np.ndarray:
    """A hero star for prints: a real core, soft halo and diffraction spikes that scale with its size."""
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    rr2 = xx ** 2 + yy ** 2
    core = np.exp(-rr2 / (2 * (r / 22) ** 2))
    halo = np.exp(-rr2 / (2 * (r / 6) ** 2)) * 0.35 + np.exp(-rr2 / (2 * (r / 2.5) ** 2)) * 0.12
    w = max(1.0, r / 70)
    spikes = (np.exp(-np.abs(xx) / (r / 3.5)) * np.exp(-yy ** 2 / (2 * w ** 2))
              + np.exp(-np.abs(yy) / (r / 3.5)) * np.exp(-xx ** 2 / (2 * w ** 2))) * 0.7
    s = core + halo + spikes
    return (s / s.max()).astype(np.float32)
