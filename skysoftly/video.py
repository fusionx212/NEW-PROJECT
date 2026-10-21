"""Slowly drifting procedural nebula video, gently pulsing with the narration, muxed with the episode audio.

Everything is generated: tileable fractal noise clouds, a twinkling star field with parallax,
a soft glow driven by the voice's loudness, title and end cards. No footage or stock assets.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 24
TILE = 1024

PALETTES = {
    # (deep cloud colour, bright cloud colour, emission colour, core glow colour)
    "violet": ((0.10, 0.05, 0.28), (0.45, 0.30, 0.85), (0.95, 0.35, 0.65), (1.00, 0.85, 0.70)),
    "teal":   ((0.02, 0.10, 0.22), (0.15, 0.55, 0.70), (0.55, 0.95, 0.80), (0.85, 0.95, 1.00)),
    "rose":   ((0.18, 0.04, 0.12), (0.80, 0.35, 0.45), (1.00, 0.75, 0.40), (1.00, 0.90, 0.75)),
    "ocean":  ((0.02, 0.04, 0.18), (0.20, 0.35, 0.85), (0.60, 0.40, 0.95), (0.80, 0.90, 1.00)),
}


def _fractal_tile(rng: np.random.Generator, beta: float) -> np.ndarray:
    """Tileable 1/f^beta noise via the FFT, normalised to 0..1."""
    f = np.fft.fftfreq(TILE)
    fx, fy = np.meshgrid(f, f)
    k = np.sqrt(fx ** 2 + fy ** 2)
    k[0, 0] = 1
    spec = (rng.normal(size=(TILE, TILE)) + 1j * rng.normal(size=(TILE, TILE))) / k ** (beta / 2)
    spec[0, 0] = 0
    n = np.real(np.fft.ifft2(spec))
    lo, hi = np.percentile(n, (1, 99.5))
    return np.clip((n - lo) / (hi - lo), 0, 1).astype(np.float32)


def _sample(tile: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Bilinear sample of a wrapping tile at float coordinates."""
    x0 = np.floor(x).astype(np.int32); y0 = np.floor(y).astype(np.int32)
    fx = (x - x0).astype(np.float32); fy = (y - y0).astype(np.float32)
    x0 %= TILE; y0 %= TILE
    x1 = (x0 + 1) % TILE; y1 = (y0 + 1) % TILE
    a = tile[y0, x0] * (1 - fx) + tile[y0, x1] * fx
    b = tile[y1, x0] * (1 - fx) + tile[y1, x1] * fx
    return a * (1 - fy) + b * fy


def voice_envelope(audio: Path, n_frames: int) -> np.ndarray:
    """Loudness per video frame, smoothed with a slow attack and release, scaled 0..1."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", "12000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    hop = 12000 // FPS
    n = min(n_frames, len(x) // hop)
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1))
    env = np.zeros(n_frames, dtype=np.float32)
    level = 0.0
    for i in range(n):
        a = 0.18 if rms[i] > level else 0.04
        level += a * (rms[i] - level)
        env[i] = level
    peak = np.percentile(env[:n], 98) if n else 1
    return np.clip(env / (peak + 1e-9), 0, 1)


def _font(size: int, serif: bool = True):
    from matplotlib import font_manager
    path = font_manager.findfont("DejaVu Serif" if serif else "DejaVu Sans")
    return ImageFont.truetype(path, size)


def _text_layer(w: int, h: int, lines: list[tuple[str, int, bool, tuple]], y_centre: float) -> np.ndarray:
    """RGBA text overlay as float32, lines are (text, size, serif, rgb)."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fonts = []
    for t, size, serif, _ in lines:
        f = _font(size, serif)
        while d.textlength(t, font=f) > w * 0.88 and size > 10:
            size = int(size * 0.92)
            f = _font(size, serif)
        fonts.append(f)
    heights = [f.getbbox(t)[3] - f.getbbox(t)[1] for (t, *_), f in zip(lines, fonts)]
    gap = int(h * 0.025)
    y = int(h * y_centre - (sum(heights) + gap * (len(lines) - 1)) / 2)
    for (t, s, serif, rgb), f, hh in zip(lines, fonts, heights):
        tw = d.textlength(t, font=f)
        for dx, dy in ((0, 2), (2, 0), (0, -2), (-2, 0)):  # soft dark halo for legibility
            d.text(((w - tw) / 2 + dx, y + dy - f.getbbox(t)[1]), t, font=f, fill=(5, 8, 25, 140))
        d.text(((w - tw) / 2, y - f.getbbox(t)[1]), t, font=f, fill=tuple(int(c * 255) for c in rgb) + (255,))
        y += hh + gap
    return np.asarray(img, dtype=np.float32) / 255.0


def _fade(t: float, start: float, end: float, ramp: float = 1.5) -> float:
    if t < start or t > end:
        return 0.0
    return min(1.0, (t - start) / ramp, (end - t) / ramp)


def make_video(audio: Path, out: Path, *, title: str, subtitle: str = "", end_line: str = "Goodnight.",
               seed: int = 1, palette: str | None = None, size: tuple[int, int] = (1280, 720),
               crf: int = 22, preset: str = "medium", max_seconds: float | None = None) -> Path:
    W, H = size
    lw, lh = (W // 3, H // 3)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)],
                               capture_output=True, text=True, check=True).stdout.strip())
    if max_seconds:
        dur = min(dur, max_seconds)
    n_frames = int(math.ceil(dur * FPS))
    rng = np.random.default_rng(seed)
    pal = PALETTES[palette or list(PALETTES)[seed % len(PALETTES)]]
    deep, bright, emit, core = (np.array(c, dtype=np.float32) for c in pal)

    big, mid, dust = _fractal_tile(rng, 4.4), _fractal_tile(rng, 3.6), _fractal_tile(rng, 2.9)
    env = voice_envelope(audio, n_frames)

    # Low-res sampling grid (the nebula is soft, so it is upscaled; stars are drawn at full res)
    gy, gx = np.mgrid[0:lh, 0:lw].astype(np.float32)
    cx, cy = lw / 2, lh / 2
    rx, ry = (gx - cx) / lw, (gy - cy) / lh
    r2 = rx ** 2 + (ry * lh / lw) ** 2
    vignette = np.clip(1.15 - 1.6 * r2, 0.25, 1)[..., None].astype(np.float32)
    core_mask = np.exp(-r2 / 0.05)[..., None].astype(np.float32)
    # composition: a soft diagonal band of nebula through the frame, off-centre like a real photo
    ox_, oy_ = rng.uniform(-0.15, 0.15), rng.uniform(-0.1, 0.1)
    tilt = rng.uniform(-0.6, 0.6)
    band = np.exp(-((ry - oy_) - tilt * (rx - ox_)) ** 2 / 0.06) * 0.7 + np.exp(-((rx - ox_) ** 2 + (ry - oy_) ** 2) / 0.12) * 0.6
    band = np.clip(band, 0, 1).astype(np.float32)

    # Stars: three parallax layers, each star twinkles at its own rate
    n_st = int(900 * W * H / (1280 * 720))
    sx = rng.uniform(0, W, n_st); sy = rng.uniform(0, H, n_st)
    sb = np.clip(rng.exponential(0.28, n_st), 0.06, 1.0).astype(np.float32)
    layer = rng.integers(0, 3, n_st); speed = np.array([0.15, 0.35, 0.7])[layer]
    tw_f = rng.uniform(0.08, 0.5, n_st); tw_p = rng.uniform(0, 2 * np.pi, n_st)
    tint = np.stack([np.ones(n_st), rng.uniform(0.85, 1, n_st), rng.uniform(0.85, 1.15, n_st)], 1).astype(np.float32)
    big_star = sb > 0.6
    k3 = np.array([[0.15, 0.5, 0.15], [0.5, 1.0, 0.5], [0.15, 0.5, 0.15]], dtype=np.float32)
    yy, xx = np.mgrid[-3:4, -3:4]
    k7 = (np.exp(-(xx ** 2 + yy ** 2) / 2.2) + 0.35 * np.exp(-(np.abs(xx) * 4 + yy ** 2 * 6)) +
          0.35 * np.exp(-(np.abs(yy) * 4 + xx ** 2 * 6))).astype(np.float32)
    k7 /= k7.max()

    base = min(H, W * 1.2)
    title_rgba = _text_layer(W, H, [(title, int(base * 0.075), True, (0.96, 0.78, 0.45))] +
                             ([(subtitle, int(base * 0.035), False, (0.9, 0.92, 0.98))] if subtitle else []), 0.5)
    end_rgba = _text_layer(W, H, [(end_line, int(base * 0.06), True, (0.96, 0.78, 0.45)),
                                  ("Tonight's Sky, Softly", int(base * 0.03), False, (0.75, 0.8, 0.95))], 0.5)
    grain = [rng.normal(0, 1.2, (H, W, 1)).astype(np.float32) for _ in range(6)]

    out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-t", f"{dur:.2f}", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE)

    ang0 = rng.uniform(0, 2 * np.pi)
    for i in range(n_frames):
        t = i / FPS
        e = float(env[i])
        # slow drift, gentle zoom-in and a hint of rotation
        zoom = 1.0 - 0.18 * (t / max(dur, 1))
        ang = ang0 + 0.02 * t / 60
        ca, sa = math.cos(ang), math.sin(ang)
        px, py = rx * zoom * 520, ry * zoom * 520 * lh / lw
        X = ca * px - sa * py; Y = sa * px + ca * py
        d1 = _sample(big, X + 7.0 * t + 100, Y + 2.5 * t + 300)
        d2 = _sample(mid, X * 1.6 - 4.0 * t + 500, Y * 1.6 + 3.0 * t + 50)
        d3 = _sample(dust, X * 2.4 + 2.0 * t, Y * 2.4 - 5.5 * t + 700)

        dens = d1 * 0.7 + d2 * 0.3
        cloud = np.clip((dens - 0.42 + 0.35 * band) * 1.9, 0, 1) ** 1.5 * (0.35 + 0.65 * band)
        cloud *= 0.45 + 0.75 * d2 * (0.6 + 0.6 * d3)
        hot = np.clip((d2 - 0.5) * 2.4, 0, 1) ** 1.6 * cloud
        lanes = np.clip((d3 - 0.52) * 2.6, 0, 1) ** 1.2 * 0.7 * np.clip(cloud * 2, 0, 1)
        img = (deep[None, None] * cloud[..., None] * 1.4
               + bright * (cloud ** 1.8)[..., None] * 0.8
               + emit * hot[..., None] * 0.9)
        img *= (1 - lanes[..., None])
        img += core * core_mask * (0.06 + 0.16 * e) * band[..., None]
        img *= vignette * (0.93 + 0.12 * e)
        img8 = Image.fromarray(np.clip(img * 255, 0, 255).astype(np.uint8))
        bloom = np.asarray(img8.filter(ImageFilter.GaussianBlur(radius=lw / 40)), dtype=np.float32) / 255
        img = img + bloom * 0.5
        img = 1 - np.exp(-img * 1.35)  # filmic shoulder: bright cores glow instead of clipping to white
        small = Image.fromarray(np.clip(img * 255, 0, 255).astype(np.uint8))
        frame = np.asarray(small.resize((W, H), Image.BICUBIC), dtype=np.float32)

        # stars
        sxp = ((sx - speed * 6.0 * t) % W).astype(np.int32)
        syp = ((sy - speed * 2.0 * t) % H).astype(np.int32)
        lum = sb * (0.72 + 0.28 * np.sin(2 * np.pi * tw_f * t + tw_p)) * 255
        star = np.zeros((H + 8, W + 8, 3), dtype=np.float32)
        for k, mask in ((k3, ~big_star), (k7, big_star)):
            r = k.shape[0] // 2
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    wgt = k[dy + r, dx + r]
                    if wgt < 0.05:
                        continue
                    np.add.at(star, (syp[mask] + dy + 4, sxp[mask] + dx + 4), (lum[mask, None] * wgt) * tint[mask])
        frame += star[4:H + 4, 4:W + 4]
        frame += grain[i % len(grain)]

        a_title = _fade(t, 0.5, 8.0)
        a_end = _fade(t, max(dur - 7.0, 9.0), dur + 1.5, ramp=2.0)
        for rgba, a in ((title_rgba, a_title), (end_rgba, a_end)):
            if a > 0:
                al = rgba[..., 3:4] * a
                frame = frame * (1 - al) + rgba[..., :3] * 255 * al
        ff.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out
