"""Photoreal procedural nebula stills, styled after narrowband Hubble/JWST imagery.

Pipeline: domain-warped fractal noise -> ridged filaments for three emission lines (H-alpha, OIII, SII)
-> sharp-edged dust with rim lighting from a central star cluster -> asinh stretch like astro processing
-> a separate star layer with diffraction spikes (so the video can parallax it against the gas).
"""
from __future__ import annotations

import hashlib

import numpy as np
from PIL import Image, ImageFilter

STYLES = {
    # channel colours for (H-alpha, OIII, SII, dust rim) in linear RGB
    "hubble":  {"H": (0.55, 0.85, 0.35), "O": (0.15, 0.55, 1.00), "S": (1.00, 0.55, 0.15), "rim": (1.0, 0.75, 0.45)},
    "natural": {"H": (1.00, 0.22, 0.32), "O": (0.20, 0.80, 0.85), "S": (0.85, 0.20, 0.45), "rim": (1.0, 0.55, 0.50)},
    "jwst":    {"H": (1.00, 0.55, 0.25), "O": (0.35, 0.60, 1.00), "S": (0.75, 0.35, 0.20), "rim": (1.0, 0.80, 0.55)},
    "violet":  {"H": (0.85, 0.30, 0.80), "O": (0.30, 0.55, 1.00), "S": (1.00, 0.45, 0.55), "rim": (1.0, 0.75, 0.85)},
}


def style_for(name: str) -> tuple[int, str]:
    h = hashlib.sha256(name.strip().lower().encode()).digest()
    return int.from_bytes(h[:6], "big"), list(STYLES)[h[6] % len(STYLES)]


def _noise(rng, n, beta):
    f = np.fft.fftfreq(n)
    fx, fy = np.meshgrid(f, f)
    k = np.sqrt(fx ** 2 + fy ** 2); k[0, 0] = 1
    spec = (rng.normal(size=(n, n)) + 1j * rng.normal(size=(n, n))) / k ** (beta / 2)
    spec[0, 0] = 0
    x = np.real(np.fft.ifft2(spec)).astype(np.float32)
    return (x - x.mean()) / (x.std() + 1e-9)


def _warp(field, wx, wy, amount):
    n = field.shape[0]
    gy, gx = np.mgrid[0:n, 0:n].astype(np.float32)
    x = gx + amount * wx; y = gy + amount * wy
    x0 = np.floor(x).astype(np.int32); y0 = np.floor(y).astype(np.int32)
    fx = x - x0; fy = y - y0
    x0 %= n; y0 %= n; x1 = (x0 + 1) % n; y1 = (y0 + 1) % n
    a = field[y0, x0] * (1 - fx) + field[y0, x1] * fx
    b = field[y1, x0] * (1 - fx) + field[y1, x1] * fx
    return a * (1 - fy) + b * fy


def _ridged(x, sharp=3.0):
    return (1 - np.tanh(np.abs(x) * 1.2)) ** sharp


def _blur(a, r):
    """Gaussian blur via the FFT (wraps at the edges, which suits tileable fields)."""
    if r <= 0:
        return a
    h, w = a.shape
    fy = np.fft.fftfreq(h)[:, None]; fx = np.fft.rfftfreq(w)[None, :]
    g = np.exp(-2 * (np.pi * r) ** 2 * (fx ** 2 + fy ** 2))
    return np.fft.irfft2(np.fft.rfft2(a) * g, s=a.shape).astype(np.float32)


def _norm(a, lo=1, hi=99.7):
    l, h = np.percentile(a, (lo, hi))
    return np.clip((a - l) / (h - l + 1e-9), 0, 1)


def make_nebula(seed: int, style: str = "hubble", n: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Returns (gas_rgb, stars_rgb) as float32 arrays in 0..1, both n x n x 3."""
    rng = np.random.default_rng(seed)
    st = {k: np.array(v, dtype=np.float32) for k, v in STYLES[style].items()}
    gy, gx = np.mgrid[0:n, 0:n].astype(np.float32) / n
    cx, cy = rng.uniform(0.4, 0.6, 2)  # the young star cluster that lights the cloud

    # Large-scale envelope: where the cloud is, with a cavity blown out around the cluster
    env = _norm(_noise(rng, n, 4.6))
    r = np.sqrt((gx - cx) ** 2 + (gy - cy) ** 2)
    cavity = np.clip(r / 0.16, 0, 1) ** 1.5
    env = np.clip(env * 1.5 - 0.35, 0, 1) ** 1.3 * (0.3 + 0.7 * cavity) * np.clip(1.25 - r * 1.6, 0, 1) ** 1.5

    # Domain warp fields (two levels) for wispy, turbulent filaments
    w1x, w1y = _noise(rng, n, 4.0), _noise(rng, n, 4.0)
    w2x, w2y = _noise(rng, n, 3.4), _noise(rng, n, 3.4)

    def filaments(beta, sharp, amt):
        f = _noise(rng, n, beta)
        f = _warp(f, w1x, w1y, amt * n / 2048)
        f = _warp(f, w2x, w2y, amt * 0.4 * n / 2048)
        fine = _noise(rng, n, beta - 0.6)
        fine = _warp(fine, w1x, w1y, amt * 0.7 * n / 2048)
        return _norm(_ridged(f, sharp) * 0.7 + _ridged(fine, sharp + 1) * 0.45 + 0.25 * _norm(f))

    Ha = filaments(3.3, 2.5, 60) * env
    O3 = filaments(3.6, 1.6, 40) * np.clip(1.4 - r * 3.0, 0, 1) * env ** 0.6   # oxygen glows hotter, nearer the stars
    S2 = filaments(3.0, 3.5, 75) * env * cavity                                 # sulphur traces the outer shocked edges

    # Dust: smooth dark clouds and pillars with crisp edges, rim-lit only where they face the cluster
    d = _blur(_noise(rng, n, 4.2), 1.5 * n / 2048)
    d = _warp(d, w1x, w1y, 45 * n / 2048)
    d = _warp(d, w2x, w2y, 18 * n / 2048)
    dust = np.clip((d - 0.7) * 2.2, 0, 1) ** 0.7 * np.clip(cavity * 1.3, 0, 1) * np.clip(env * 2.5, 0, 1)
    soft = _blur(dust, 0.8 * n / 2048)
    edge_y, edge_x = np.gradient(soft)
    tox, toy = (cx - gx), (cy - gy)
    dist = np.sqrt(tox ** 2 + toy ** 2) + 1e-6
    facing = np.clip(-(edge_x * tox + edge_y * toy) / dist * n / 60, 0, 1)
    band_ = np.clip(soft * (1 - soft) * 4, 0, 1) ** 2          # only the thin boundary of the dust
    rim = _blur(facing * band_, 0.7 * n / 2048) * np.exp(-r / 0.2)
    gas = (st["H"] * Ha[..., None] * 1.0 + st["O"] * O3[..., None] * 0.9 + st["S"] * S2[..., None] * 0.75)
    gas += _blur_rgb(gas, 22 * n / 2048) * 0.5      # diffuse glow under the filaments
    gas *= (1 - 0.95 * dust[..., None])
    gas += st["rim"] * rim[..., None] * 0.7
    core = np.exp(-r ** 2 / 0.02) * 0.18 + np.exp(-r ** 2 / 0.003) * 0.12
    gas += (st["O"] * 0.6 + 0.4)[None, None] * core[..., None] * (1 - dust[..., None]) * O3[..., None].clip(0.3, 1)
    gas = np.arcsinh(gas * 4) / np.arcsinh(4)        # astro-style stretch
    gas = _saturate(gas, 1.15) * 0.9
    gas *= np.clip(1.25 - 0.9 * ((gx - 0.5) ** 2 + (gy - 0.5) ** 2) * 2, 0.35, 1)[..., None]

    stars = make_stars(rng, n, cx, cy, dust)
    return np.clip(gas, 0, 1).astype(np.float32), stars


def _blur_rgb(a, r):
    return np.stack([_blur(a[..., c], r) for c in range(3)], -1)


def _saturate(rgb, s):
    lum = rgb.mean(-1, keepdims=True)
    return lum + (rgb - lum) * s


def _star_colour(rng, k):
    t = rng.uniform(0, 1, k)
    return np.stack([np.clip(0.75 + 0.35 * t, 0, 1), np.clip(0.8 + 0.1 * t, 0, 1), np.clip(1.15 - 0.45 * t, 0, 1)], 1)


def make_stars(rng, n, cx, cy, dust) -> np.ndarray:
    img = np.zeros((n, n, 3), dtype=np.float32)
    scale = n / 2048
    # field stars, dimmed behind dust
    k = int(16000 * scale ** 2)
    xs = rng.integers(0, n, k); ys = rng.integers(0, n, k)
    b = (rng.pareto(2.0, k).astype(np.float32) * 0.3 + 0.04) * (1 - 0.9 * dust[ys, xs])
    np.add.at(img, (ys, xs), b[:, None] * _star_colour(rng, k))
    # young cluster around the centre
    k2 = int(500 * scale ** 2)
    xs2 = np.clip(rng.normal(cx * n, 0.05 * n, k2), 0, n - 1).astype(int)
    ys2 = np.clip(rng.normal(cy * n, 0.05 * n, k2), 0, n - 1).astype(int)
    b2 = rng.pareto(1.8, k2).astype(np.float32) * 0.35
    np.add.at(img, (ys2, xs2), b2[:, None] * _star_colour(rng, k2) * np.array([0.85, 0.9, 1.1]))
    img = _blur_rgb(img, 0.7 * scale) * 2.2 + img * 0.5
    # a few bright stars with halos and diffraction spikes
    spikes = np.zeros((n, n), dtype=np.float32)
    halo = np.zeros((n, n), dtype=np.float32)
    nb = rng.integers(10, 18)
    bx = np.concatenate([rng.integers(0, n, nb), np.clip(rng.normal(cx * n, 0.04 * n, 6), 0, n - 1).astype(int)])
    by = np.concatenate([rng.integers(0, n, nb), np.clip(rng.normal(cy * n, 0.04 * n, 6), 0, n - 1).astype(int)])
    bb = np.concatenate([rng.uniform(0.3, 1.0, nb), rng.uniform(0.6, 1.2, 6)])
    L = int(130 * scale)
    t = np.arange(-L, L + 1)
    fall = np.exp(-np.abs(t) / (L / 4)).astype(np.float32)
    for x, y, s in zip(bx, by, bb):
        for dx, dy in ((1, 0), (0, 1)):   # four-point spikes like Hubble
            xx = x + t * dx; yy = y + t * dy
            ok = (xx >= 0) & (xx < n) & (yy >= 0) & (yy < n)
            np.add.at(spikes, (yy[ok], xx[ok]), fall[ok] * s * 0.9)
        halo[y, x] += s * 40
    halo = _blur(halo, 3.0 * scale) + _blur(halo, 12 * scale) * 0.4
    spikes = _blur(spikes, 0.6 * scale)
    img += (spikes + halo)[..., None] * np.array([0.95, 0.97, 1.0], dtype=np.float32)
    return np.clip(img, 0, 1)


def preview(seed, style, path, n=1536):
    gas, stars = make_nebula(seed, style, n)
    rgb = 1 - (1 - gas) * (1 - stars)    # screen blend
    Image.fromarray((np.clip(rgb, 0, 1) ** (1 / 1.1) * 255).astype(np.uint8)).save(path)
