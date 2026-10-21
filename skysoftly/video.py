"""Moving-nebula video: a slow camera drift through a photoreal procedural nebula, muxed with the audio.

One detailed nebula still is generated per name (see nebula.py). The camera then glides and zooms through
it, with the star layer moving on its own path for parallax, a gentle glow that follows the narrator's voice,
and title and end cards. This is how real space videos are made from Hubble and JWST stills.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .nebula import STYLES, make_nebula, style_for

FPS = 24
PALETTES = list(STYLES)                       # hubble, natural, jwst, violet
_LEGACY = {"teal": "natural", "rose": "jwst", "ocean": "hubble"}


def name_style(name: str) -> tuple[int, str]:
    """Every name gets its own nebula: the same name always gives the same picture."""
    return style_for(name)


def voice_envelope(audio: Path, n_frames: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", "12000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    hop = 12000 // FPS
    n = min(n_frames, len(x) // hop)
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1)) if n else np.zeros(0)
    env = np.zeros(n_frames, dtype=np.float32)
    level = 0.0
    for i in range(n):
        level += (0.15 if rms[i] > level else 0.03) * (rms[i] - level)
        env[i] = level
    peak = np.percentile(env[:n], 98) if n else 1
    return np.clip(env / (peak + 1e-9), 0, 1)


def _font(size: int, serif: bool = True):
    from matplotlib import font_manager
    return ImageFont.truetype(font_manager.findfont("DejaVu Serif" if serif else "DejaVu Sans"), size)


def _text_layer(w: int, h: int, lines: list[tuple[str, int, bool, tuple]], y_centre: float) -> np.ndarray:
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
    for (t, _s, _serif, rgb), f, hh in zip(lines, fonts, heights):
        tw = d.textlength(t, font=f)
        for dx, dy in ((0, 2), (2, 0), (0, -2), (-2, 0), (2, 2), (-2, -2)):
            d.text(((w - tw) / 2 + dx, y + dy - f.getbbox(t)[1]), t, font=f, fill=(3, 5, 15, 150))
        d.text(((w - tw) / 2, y - f.getbbox(t)[1]), t, font=f, fill=tuple(int(c * 255) for c in rgb) + (255,))
        y += hh + gap
    return np.asarray(img, dtype=np.float32) / 255.0


def _fade(t: float, start: float, end: float, ramp: float = 1.5) -> float:
    if t < start or t > end:
        return 0.0
    return min(1.0, (t - start) / ramp, (end - t) / ramp)


def _affine(ux, uy, s, th, W, H):
    a, b = s * math.cos(th), -s * math.sin(th)
    d, e = s * math.sin(th), s * math.cos(th)
    return (a, b, ux - (a * W / 2 + b * H / 2), d, e, uy - (d * W / 2 + e * H / 2))


def make_video(audio: Path, out: Path, *, title: str, subtitle: str = "", end_line: str = "Goodnight.",
               seed: int = 1, palette: str | None = None, size: tuple[int, int] = (1280, 720),
               crf: int = 21, preset: str = "medium", max_seconds: float | None = None, still_px: int | None = None) -> Path:
    W, H = size
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)],
                               capture_output=True, text=True, check=True).stdout.strip())
    if max_seconds:
        dur = min(dur, max_seconds)
    n_frames = int(math.ceil(dur * FPS))
    style = _LEGACY.get(palette, palette) or PALETTES[seed % len(PALETTES)]
    n = still_px or (2048 if max(W, H) <= 1280 else 3072)

    gas, stars = make_nebula(seed, style, n)
    gas_im = Image.fromarray((gas ** (1 / 1.1) * 255).astype(np.uint8))
    star_im = Image.fromarray((stars * 255).astype(np.uint8))
    env = voice_envelope(audio, n_frames)

    # Camera path: start wide, glide towards a point near the bright core, with a slow turn
    rng = np.random.default_rng(seed ^ 0x5EED)
    frac0, frac1 = 0.85, 0.5                       # visible fraction of the still, start and end
    from PIL import ImageFilter
    def densest(blur):
        m = np.asarray(gas_im.convert("L").resize((128, 128)).filter(ImageFilter.GaussianBlur(blur)), dtype=np.float32)
        m[:16], m[-16:], m[:, :16], m[:, -16:] = 0, 0, 0, 0     # keep the camera away from the edges
        yy, xx = np.unravel_index(np.argmax(m), m.shape)
        return np.array([xx + 0.5, yy + 0.5]) / 128 * n
    target = densest(8)                            # the richest patch of glowing gas, where the camera ends
    start = 0.5 * densest(22) + 0.5 * np.array([n / 2, n / 2])
    th0, th1 = rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05) + rng.choice([-1, 1]) * 0.06

    base = min(H, W * 1.2)
    title_rgba = _text_layer(W, H, [(title, int(base * 0.075), True, (0.96, 0.80, 0.50))] +
                             ([(subtitle, int(base * 0.035), False, (0.92, 0.94, 0.98))] if subtitle else []), 0.5)
    end_rgba = _text_layer(W, H, [(end_line, int(base * 0.06), True, (0.96, 0.80, 0.50)),
                                  ("Tonight's Sky, Softly", int(base * 0.03), False, (0.78, 0.82, 0.95))], 0.5)

    out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-t", f"{dur:.2f}", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE)

    for i in range(n_frames):
        t = i / FPS
        p = t / max(dur, 1)
        ease = p * p * (3 - 2 * p)                 # smoothstep: gentle start and finish
        frac = frac0 + (frac1 - frac0) * ease
        c = start + (target - start) * ease
        th = th0 + (th1 - th0) * ease
        s_gas = frac * n / max(W, H)
        half = 0.5 * frac * n * 1.06
        c = np.clip(c, half, n - half)
        g = gas_im.transform((W, H), Image.AFFINE, _affine(c[0], c[1], s_gas, th, W, H), resample=Image.BICUBIC)
        # stars sit "in front": they zoom a little more and drift a little further, giving depth
        frac_s = frac0 + (frac1 - frac0) * ease * 1.25
        cs = np.clip(start + (target - start) * ease * 1.15, 0.5 * frac_s * n * 1.06, n - 0.5 * frac_s * n * 1.06)
        st = star_im.transform((W, H), Image.AFFINE, _affine(cs[0], cs[1], frac_s * n / max(W, H), th * 1.1, W, H),
                               resample=Image.BILINEAR)
        e = float(env[i])
        a = np.asarray(g, dtype=np.float32) * (0.94 + 0.1 * e)
        b = np.asarray(st, dtype=np.float32)
        frame = 255 - (255 - a) * (255 - b) / 255          # screen blend, as in astro composites
        for rgba, al in ((title_rgba, _fade(t, 0.5, 8.0)), (end_rgba, _fade(t, max(dur - 7.0, 9.0), dur + 1.5, ramp=2.0))):
            if al > 0:
                m = rgba[..., 3:4] * al
                frame = frame * (1 - m) + rgba[..., :3] * 255 * m
        ff.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out
