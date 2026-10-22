"""Moving-nebula video: a deep, slow Ken Burns zoom through a photoreal nebula, landing on one star.

One detailed nebula is generated per name (see nebula.py). The camera zooms 48x into it through nested
detail levels (see zoom.py), with crisp stars, a fly-through star layer and a glow that follows the
narrator's voice. With a name, the final star bursts into particles that spell that name.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

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
               crf: int = 21, preset: str = "medium", max_seconds: float | None = None, still_px: int | None = None,
               star_name: str | None = None, star_caption: str = "", zoom: float = 48.0, log=print) -> Path:
    """Deep Ken Burns zoom into the nebula, landing on one star. With star_name, the star bursts into that name."""
    from .zoom import (LEVEL_FIT, StarCatalogue, _smooth, _spike_stamp, _stamp, build_levels, name_points, pick_star_spot)
    W, H = size
    L_ = max(W, H)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)],
                               capture_output=True, text=True, check=True).stdout.strip())
    if max_seconds:
        dur = min(dur, max_seconds)
    n_frames = int(math.ceil(dur * FPS))
    style = _LEGACY.get(palette, palette) or PALETTES[seed % len(PALETTES)]
    n = still_px or (2048 if L_ <= 1280 else 3072)

    log("  painting the nebula")
    gas, _stars = make_nebula(seed, style, n)
    T = pick_star_spot(gas)
    f0 = 0.85
    n_levels = int(math.ceil(math.log2(zoom / f0 * LEVEL_FIT))) + 1
    levels = build_levels(gas, T, n_levels, seed, log=log)
    cat = StarCatalogue(n, T, n_levels, seed)
    env = voice_envelope(audio, n_frames)
    rng = np.random.default_rng(seed ^ 0x5EED)

    # timeline: zoom across most of the piece, land with ~20 s to spare for the name
    t_land = max(min(dur - 20.0, dur * 0.82), dur * 0.6)
    th0, th1 = rng.uniform(-0.04, 0.04), rng.uniform(0.06, 0.12) * rng.choice([-1, 1])
    C0 = np.array([n / 2, n / 2]); Tv = np.array(T)

    def cam(t):
        u = min(max(t / t_land, 0.0), 1.0)
        e = u * u * u * (u * (u * 6 - 15) + 10)            # smootherstep: slow start, slow landing
        z = math.exp(math.log(zoom) * e)
        C = Tv + (C0 - Tv) / z ** 1.5
        th = th0 + (th1 - th0) * e
        return z, C, th

    # fly-through stars
    m3 = 450
    fx, fy = rng.uniform(-1, 1, m3), rng.uniform(-1, 1, m3)
    fz = rng.uniform(0.1, 1.0, m3); fb = rng.uniform(0.3, 1.0, m3)

    # text layers
    base = min(H, W * 1.2)
    title_rgba = _text_layer(W, H, [(title, int(base * 0.075), True, (0.96, 0.80, 0.50))] +
                             ([(subtitle, int(base * 0.035), False, (0.92, 0.94, 0.98))] if subtitle else []), 0.5)
    name_y = 0.72
    if star_name:
        fsize = int(base * 0.15)
        f = _font(fsize)
        probe = ImageDraw.Draw(Image.new("L", (10, 10)))
        while probe.textlength(star_name, font=f) > W * 0.86 and fsize > 12:
            fsize = int(fsize * 0.92); f = _font(fsize)
        px, py, _mask = name_points(star_name, W, H, name_y, f, seed=seed)
        name_rgba = _text_layer(W, H, [(star_name, fsize, True, (1.0, 0.86, 0.58))], name_y)
        glow = Image.fromarray((name_rgba[..., 3] * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(base * 0.02))
        name_glow = np.asarray(glow, dtype=np.float32)[..., None] / 255 * np.array([1.0, 0.75, 0.4], dtype=np.float32)
        cap_rgba = _text_layer(W, H, [(star_caption, int(base * 0.034), False, (0.9, 0.92, 0.98))], name_y + 0.1) if star_caption else None
        k_p = len(px)
        p_delay = rng.uniform(0, 0.9, k_p); p_len = rng.uniform(2.4, 3.6, k_p)
        p_arc = rng.normal(0, base * 0.12, k_p); p_tw = rng.uniform(0, 6.28, k_p)
    end_rgba = _text_layer(W, H, [(end_line, int(base * 0.06), True, (0.96, 0.80, 0.50)),
                                  ("Tonight's Sky, Softly", int(base * 0.03), False, (0.78, 0.82, 0.95))], 0.72)
    spike_small = _spike_stamp(10)
    k3 = np.array([[0.2, 0.55, 0.2], [0.55, 1.0, 0.55], [0.2, 0.55, 0.2]], dtype=np.float32)

    out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-t", f"{dur:.2f}", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE)
    log(f"  rendering {n_frames} frames, {len(levels)} zoom levels, {zoom:.0f}x")

    def render_level(L, z, C, th):
        s0 = f0 * n / z / L_
        if L == 0:
            u = C.copy(); s = s0
        else:
            u = (C - Tv) * 2 ** L + n / 2; s = s0 * 2 ** L
        hx = 0.5 * s * (W * abs(math.cos(th)) + H * abs(math.sin(th)))
        hy = 0.5 * s * (W * abs(math.sin(th)) + H * abs(math.cos(th)))
        u = np.array([min(max(u[0], hx), n - hx), min(max(u[1], hy), n - hy)])
        im = levels[L].transform((W, H), Image.AFFINE, _affine(u[0], u[1], s, th, W, H), resample=Image.BICUBIC)
        return np.asarray(im, dtype=np.float32)

    prev_logz = 0.0
    for i in range(n_frames):
        t = i / FPS
        z, C, th = cam(t)
        e = float(env[i])
        # --- gas: deepest usable level, blended with the one above it
        width0 = f0 / z
        best = 0
        for L in range(1, len(levels)):
            if width0 * 2 ** L <= LEVEL_FIT:
                best = L
        if best == 0:
            frame = render_level(0, z, C, th)
        else:
            a = float(_smooth((LEVEL_FIT - width0 * 2 ** best) / (LEVEL_FIT - 0.62)))
            frame = render_level(best, z, C, th) * a + render_level(best - 1, z, C, th) * (1 - a) if a < 0.999 else render_level(best, z, C, th)
        frame *= (0.94 + 0.1 * e)

        # --- catalogue stars as crisp points
        s0 = f0 * n / z / L_
        ct, st_ = math.cos(-th), math.sin(-th)
        dx, dy = (cat.x - C[0]) / s0, (cat.y - C[1]) / s0
        qx = W / 2 + ct * dx - st_ * dy; qy = H / 2 + st_ * dx + ct * dy
        vis = np.where(cat.lv == 0, 1.0, _smooth((z - 2.0 ** cat.lv * 0.45) / (2.0 ** cat.lv * 0.6)))
        ok = (qx >= 1) & (qx < W - 1) & (qy >= 1) & (qy < H - 1) & (vis > 0.01)
        bx, by = qx[ok].astype(np.int32), qy[ok].astype(np.int32)
        val = (cat.b[ok] * vis[ok])[:, None] * cat.col[ok] * 255
        for oy in (-1, 0, 1):
            for ox in (-1, 0, 1):
                np.add.at(frame, (by + oy, bx + ox), val * k3[oy + 1, ox + 1])
        bright = np.nonzero(cat.b[ok] * vis[ok] > 0.85)[0][:30]
        for j in bright:
            _stamp(frame, qx[ok][j], qy[ok][j], spike_small, val[j] * 0.8)

        # --- fly-through layer, only while the camera moves
        logz = math.log(z)
        speed = max(0.0, (logz - prev_logz) * FPS)
        prev_logz = logz
        fz -= speed * 0.22 / FPS
        re = fz < 0.08
        if re.any():
            fz[re] += 0.92; fx[re] = rng.uniform(-1, 1, re.sum()); fy[re] = rng.uniform(-1, 1, re.sum())
        sx = W / 2 + (ct * fx - st_ * fy) / fz * L_ * 0.35
        sy = H / 2 + (st_ * fx + ct * fy) / fz * L_ * 0.35
        okf = (sx >= 1) & (sx < W - 1) & (sy >= 1) & (sy < H - 1)
        fv = (np.clip(1.15 - fz, 0, 1) ** 2 * fb * min(speed * 3, 1.0) * 200)[okf]
        for oy in (-1, 0, 1):
            for ox in (-1, 0, 1):
                np.add.at(frame, (sy[okf].astype(np.int32) + oy, sx[okf].astype(np.int32) + ox), (fv * k3[oy + 1, ox + 1])[:, None])

        # --- the person's star: grows from a pinprick into a radiant star
        g = math.log(z) / math.log(zoom)
        Tq = (W / 2 + ct * (Tv[0] - C[0]) / s0 - st_ * (Tv[1] - C[1]) / s0, H / 2 + st_ * (Tv[0] - C[0]) / s0 + ct * (Tv[1] - C[1]) / s0)
        r = int(14 + 140 * g ** 1.3)
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
        rr2 = xx ** 2 + yy ** 2
        sc = 1.0 + 5.0 * g
        stamp = (np.exp(-rr2 / (2 * sc ** 2)) * 1.0 + np.exp(-rr2 / (2 * (sc * 4) ** 2)) * 0.45 * (0.3 + g)
                 + np.exp(-rr2 / (2 * (r / 3.2) ** 2)) * 0.22 * g ** 1.5
                 + (np.exp(-np.abs(xx) / (r / 4.5)) * np.exp(-yy ** 2 / (0.5 + g))
                    + np.exp(-np.abs(yy) / (r / 4.5)) * np.exp(-xx ** 2 / (0.5 + g))) * 0.55 * (0.4 + g))
        breathe = 1 + 0.06 * math.sin(t * 1.3) if t > t_land else 1.0
        _stamp(frame, Tq[0], Tq[1], stamp.astype(np.float32), np.array([255, 236, 200], dtype=np.float32) * (0.75 + 0.5 * g) * breathe)

        # --- landing: the star bursts into the name
        if star_name and t > t_land - 1.0:
            k = np.clip((t - (t_land - 1.0) - p_delay) / p_len, 0, 1)
            kk = k * k * (3 - 2 * k)
            live = k > 0
            if live.any():
                ox_, oy_ = Tq
                dxn, dyn = px - ox_, py - oy_
                ln = np.hypot(dxn, dyn) + 1e-6
                arc = np.sin(np.pi * kk) * p_arc
                qx2 = ox_ + dxn * kk - dyn / ln * arc
                qy2 = oy_ + dyn * kk + dxn / ln * arc
                inten = (1.1 - 0.5 * kk) * (0.75 + 0.25 * np.sin(t * 7 + p_tw)) * 255
                okp = live & (qx2 >= 1) & (qx2 < W - 1) & (qy2 >= 1) & (qy2 < H - 1)
                pv = inten[okp][:, None] * np.array([1.0, 0.85, 0.55], dtype=np.float32)
                fade_p = 1 - _smooth((t - (t_land + 3.4)) / 1.5)
                for oy in (-1, 0, 1):
                    for ox in (-1, 0, 1):
                        np.add.at(frame, (qy2[okp].astype(np.int32) + oy, qx2[okp].astype(np.int32) + ox), pv * k3[oy + 1, ox + 1] * fade_p)
            a_n = float(_smooth((t - (t_land + 2.6)) / 1.6))
            if a_n > 0:
                frame += name_glow * 120 * a_n
                m = name_rgba[..., 3:4] * a_n
                frame = frame * (1 - m) + name_rgba[..., :3] * 255 * m
            if cap_rgba is not None:
                a_c = float(_smooth((t - (t_land + 4.2)) / 1.5))
                if a_c > 0:
                    m = cap_rgba[..., 3:4] * a_c
                    frame = frame * (1 - m) + cap_rgba[..., :3] * 255 * m
        elif not star_name:
            a_e = _fade(t, t_land + 2.0, dur + 2.0, ramp=2.0)
            if a_e > 0:
                m = end_rgba[..., 3:4] * a_e
                frame = frame * (1 - m) + end_rgba[..., :3] * 255 * m

        a_t = _fade(t, 0.5, 7.0)
        if a_t > 0:
            m = title_rgba[..., 3:4] * a_t
            frame = frame * (1 - m) + title_rgba[..., :3] * 255 * m
        if t > dur - 1.5:
            frame *= max(0.0, (dur - t) / 1.5)
        ff.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
        if i % (FPS * 30) == 0 and i:
            log(f"    {t:.0f}s / {dur:.0f}s")
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out
