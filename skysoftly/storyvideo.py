"""Animated bedtime story video: illustrated scenes that follow the narration line by line.

Every story paragraph carries a scene tag (see story.make_story(with_scenes=True)) and the narrator's
timings are recorded while the voice is generated (render.render(timing_json=...)). Scenes change exactly
when the narrator reaches them, wishes fall one per sentence, and countdown numbers appear as each is spoken.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .nebula import make_nebula
from .scenes import bedroom_window, planet, starlight_silhouette
from .video import FPS, _affine, _font, _text_layer
from .zoom import (LEVEL_FIT, _smooth, _spike_stamp, _stamp, big_star, build_levels, name_points, pick_star_spot,
                   sprinkle_stars)

GOLD = np.array([255, 214, 140], np.float32)
XFADE = 1.2


def _ease(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def _over(frame, rgba, a):
    if a <= 0:
        return frame
    m = rgba[..., 3:4] * a
    return frame * (1 - m) + rgba[..., :3] * 255 * m


class StoryVideo:
    def __init__(self, W, H, seed, style, name, animal, caption, sky=None, giver_message=None, title=""):
        self.W, self.H, self.seed, self.name, self.animal = W, H, seed, name, animal
        self.caption, self.title, self.msg = caption, title, giver_message
        self.rng = np.random.default_rng(seed)
        gas, _ = make_nebula(seed, style, 2048)
        self.n = 2048
        self.T = pick_star_spot(gas)
        self.levels = build_levels(gas, self.T, 6, seed, log=lambda *a: None)
        dark = Image.fromarray((np.asarray(self.levels[0], np.float32) * 0.45).astype(np.uint8))
        self.room_img = Image.fromarray(np.clip(bedroom_window(W, H, dark, 0.0, seed=seed % 1000), 0, 255).astype(np.uint8))
        self.star_xy = (W * 0.55, H * 0.3)
        self.planets = [p["name"] for p in (sky or {}).get("planets", []) if p["status"] in ("up", "rises_later")][:3] \
            or ["Jupiter", "Saturn", "Mars"]
        self.sky = sky
        self.chart = self._chart() if sky else None
        self.climb_img = self._climb_canvas()
        self.wide = sprinkle_stars(self.levels[0].resize((int(W * 2.2), int(W * 2.2 * 9 / 16))), seed=seed % 997, density=0.6)
        base = min(H, W * 1.2)
        self.title_rgba = _text_layer(W, H, [(title, int(base * 0.07), True, (0.96, 0.80, 0.50)),
                                             ("A bedtime story", int(base * 0.035), False, (0.92, 0.94, 0.98))], 0.5)
        self.msg_rgba = _text_layer(W, H, self._wrap(self.msg or "", int(base * 0.055)), 0.5) if self.msg else None
        fsize = int(base * 0.15)
        f = _font(fsize)
        probe = ImageDraw.Draw(Image.new("L", (8, 8)))
        while probe.textlength(name, font=f) > W * 0.86 and fsize > 12:
            fsize = int(fsize * 0.92); f = _font(fsize)
        self.px, self.py, _ = name_points(name, W, H, 0.72, f, seed=seed)
        self.name_rgba = _text_layer(W, H, [(name, fsize, True, (1.0, 0.86, 0.58))], 0.72)
        self.cap_rgba = _text_layer(W, H, [(caption, int(base * 0.034), False, (0.9, 0.92, 0.98))], 0.82)
        k = len(self.px)
        self.p_delay = self.rng.uniform(0, 0.9, k); self.p_len = self.rng.uniform(2.4, 3.6, k)
        self.p_arc = self.rng.normal(0, base * 0.12, k); self.p_tw = self.rng.uniform(0, 6.28, k)
        self.number_cache = {}
        self.k3 = np.array([[0.2, 0.55, 0.2], [0.55, 1.0, 0.55], [0.2, 0.55, 0.2]], np.float32)

    # ---------- precomputed backdrops ----------
    def _wrap(self, text, size):
        f = _font(size, True)
        d = ImageDraw.Draw(Image.new("L", (8, 8)))
        lines, cur = [], ""
        for w in text.split():
            if d.textlength((cur + " " + w).strip(), font=f) > self.W * 0.75:
                lines.append(cur); cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        out = []
        for i, ln in enumerate(lines):
            txt = ("\u201c" if i == 0 else "") + ln + ("\u201d" if i == len(lines) - 1 else "")
            out.append((txt, size, True, (1.0, 0.88, 0.62)))
        return out

    def _chart(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from .chart import draw_sky
        fig = plt.figure(figsize=(self.W / 100, self.H / 100), dpi=100, facecolor="#070b1e")
        ax = fig.add_axes([0.2, 0.04, 0.6, 0.92], projection="polar")
        draw_sky(ax, self.sky, label_stars=10)
        fig.canvas.draw()
        im = Image.frombuffer("RGBA", fig.canvas.get_width_height(), fig.canvas.buffer_rgba()).convert("RGB")
        plt.close(fig)
        return im.resize((self.W, self.H))

    def _climb_canvas(self):
        """A tall night scene for the moonbeam ride: rooftops at the bottom, clouds, then open sky."""
        W, H = self.W, self.H
        CH = H * 3
        sky = np.asarray(sprinkle_stars(self.levels[0].resize((W, CH)), seed=7, density=0.9), np.float32)
        grad = np.linspace(0.85, 0.25, CH)[::-1][:, None, None]
        sky = sky * grad + np.array([10, 14, 40]) * (1 - grad)
        im = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8)).convert("RGBA")
        # clouds: soft blobs in the middle band
        cl = Image.new("L", (W, CH), 0); dc = ImageDraw.Draw(cl)
        rng = np.random.default_rng(3)
        for _ in range(45):
            cx, cy = rng.uniform(-100, W + 100), rng.uniform(CH * 0.38, CH * 0.62)
            rw, rh = rng.uniform(120, 320), rng.uniform(40, 90)
            dc.ellipse((cx - rw, cy - rh, cx + rw, cy + rh), fill=int(rng.uniform(40, 95)))
        cl = cl.filter(ImageFilter.GaussianBlur(28))
        im.alpha_composite(Image.merge("RGBA", (*[Image.new("L", (W, CH), v) for v in (110, 120, 170)], cl)))
        # rooftops along the bottom with a few warm windows
        rt = Image.new("RGBA", (W, CH), (0, 0, 0, 0)); dr = ImageDraw.Draw(rt)
        x = -40
        while x < W + 40:
            bw = int(rng.uniform(110, 200)); bh = int(rng.uniform(140, 260)); top = CH - bh
            dr.rectangle((x, top, x + bw, CH), fill=(14, 16, 34, 255))
            dr.polygon([(x - 10, top), (x + bw / 2, top - bw * 0.45), (x + bw + 10, top)], fill=(14, 16, 34, 255))
            if rng.uniform() < 0.6:
                dr.rectangle((x + bw * 0.7, top - bw * 0.35, x + bw * 0.8, top - bw * 0.1), fill=(14, 16, 34, 255))
            for _ in range(int(rng.integers(0, 3))):
                wx, wy = x + rng.uniform(15, bw - 40), top + rng.uniform(25, bh - 60)
                dr.rectangle((wx, wy, wx + 22, wy + 28), fill=(255, 196, 110, 255))
            x += bw + int(rng.uniform(0, 20))
        im.alpha_composite(rt)
        return im.convert("RGB")

    # ---------- scene painters: each returns a float frame for local time u (0..1) and absolute t ----------
    def room(self, push, star_gain, t):
        W, H = self.W, self.H
        z = 1.0 + 0.12 * push
        im = self.room_img.transform((W, H), Image.AFFINE, _affine(W / 2, H * 0.42, 1 / z, 0, W, H), resample=Image.BILINEAR)
        f = np.asarray(im, np.float32)
        sx = W / 2 + (self.star_xy[0] - W / 2) * z; sy = H * 0.42 + (self.star_xy[1] - H * 0.42) * z
        if star_gain > 0.01:
            _stamp(f, sx, sy, big_star(int(H * 0.16 * (0.6 + 0.4 * star_gain))), GOLD * (0.4 + 0.8 * star_gain))
        return f, z

    def climb(self, u, reverse, t):
        W, H = self.W, self.H
        CH = self.climb_img.height
        e = _ease(u)
        y = (CH - H) * (1 - e) if not reverse else (CH - H) * e
        f = np.asarray(self.climb_img.crop((0, int(y), W, int(y) + H)), np.float32)
        # the moonbeam ribbon sweeping up through the frame
        rib = Image.new("L", (W, H), 0); d = ImageDraw.Draw(rib)
        ph = t * 0.6
        pts = [(int(-60 + k * (W + 120) / 60), int(H * (0.95 - 0.8 * k / 60) + 40 * math.sin(k / 7 + ph))) for k in range(61)]
        d.line(pts, fill=255, width=30, joint="curve")
        r = np.asarray(rib.filter(ImageFilter.GaussianBlur(12)), np.float32)[..., None] / 255
        f = f + r * np.array([190, 205, 245]) * 0.75
        k = int(30 + 0.4 * (60 - 30))
        ax, ay = pts[k]
        starlight_silhouette(f, self.animal, ax, ay - H * 0.09, int(H * 0.22), t=t, seed=self.seed % 100)
        return f

    def planets_scene(self, u, t):
        W, H = self.W, self.H
        wide = self.wide
        x = (wide.width - W) * _ease(u)
        y = (wide.height - H) * 0.5
        f = np.asarray(wide.crop((int(x), int(y), int(x) + W, int(y) + H)), np.float32) * 0.85
        n = len(self.planets)
        for i, p in enumerate(self.planets):
            # each planet drifts across faster than the background (parallax)
            px = W * (1.15 + i * 0.75) - (W * (0.9 + n * 0.75)) * _ease(u)
            py = H * (0.32 + 0.3 * ((i * 37) % 3) / 2)
            r = {"Jupiter": 0.2, "Saturn": 0.11, "Mars": 0.07, "Venus": 0.09, "Mercury": 0.05}.get(p, 0.08) * H
            if -r * 3 < px < W + r * 3:
                planet(f, p, px, py, r)
        starlight_silhouette(f, self.animal, W * 0.3, H * 0.72 + 8 * math.sin(t), int(H * 0.2), t=t, seed=self.seed % 100)
        return f

    def nebula(self, z, t, dim=1.0):
        W, H = self.W, self.H
        n = self.n; f0 = 0.85; L_ = max(W, H)
        Tv = np.array(self.T); C0 = np.array([n / 2, n / 2])
        C = Tv + (C0 - Tv) / z ** 1.5
        th = 0.03 * math.sin(t * 0.05)

        def lev(L):
            s0 = f0 * n / z / L_
            u_ = C.copy() if L == 0 else (C - Tv) * 2 ** L + n / 2
            s = s0 * (2 ** L if L else 1)
            hx = 0.5 * s * (W * abs(math.cos(th)) + H * abs(math.sin(th))); hy = 0.5 * s * (W * abs(math.sin(th)) + H * abs(math.cos(th)))
            u_ = np.array([min(max(u_[0], hx), n - hx), min(max(u_[1], hy), n - hy)])
            return np.asarray(self.levels[L].transform((W, H), Image.AFFINE, _affine(u_[0], u_[1], s, th, W, H),
                                                       resample=Image.BILINEAR), np.float32)
        width0 = f0 / z
        best = 0
        for L in range(1, len(self.levels)):
            if width0 * 2 ** L <= LEVEL_FIT:
                best = L
        if best == 0:
            f = lev(0)
        else:
            a = float(_smooth((LEVEL_FIT - width0 * 2 ** best) / (LEVEL_FIT - 0.62)))
            f = lev(best) * a + lev(best - 1) * (1 - a) if a < 0.999 else lev(best)
        return f * dim

    def name_burst(self, f, t, t0, sx, sy):
        k = np.clip((t - t0 - self.p_delay) / self.p_len, 0, 1)
        kk = k * k * (3 - 2 * k)
        live = k > 0
        if live.any():
            dx, dy = self.px - sx, self.py - sy
            ln = np.hypot(dx, dy) + 1e-6
            arc = np.sin(np.pi * kk) * self.p_arc
            qx = sx + dx * kk - dy / ln * arc; qy = sy + dy * kk + dx / ln * arc
            inten = (1.1 - 0.5 * kk) * (0.75 + 0.25 * np.sin(t * 7 + self.p_tw)) * 255
            ok = live & (qx >= 1) & (qx < self.W - 1) & (qy >= 1) & (qy < self.H - 1)
            pv = inten[ok][:, None] * np.array([1.0, 0.85, 0.55], np.float32) * (1 - _ease((t - t0 - 4.2) / 1.5))
            for oy in (-1, 0, 1):
                for ox in (-1, 0, 1):
                    np.add.at(f, (qy[ok].astype(int) + oy, qx[ok].astype(int) + ox), pv * self.k3[oy + 1, ox + 1])
        f = _over(f, self.name_rgba, _ease((t - t0 - 3.0) / 1.6))
        f = _over(f, self.cap_rgba, _ease((t - t0 - 4.6) / 1.5))
        return f

    def number(self, n_word: str):
        if n_word not in self.number_cache:
            self.number_cache[n_word] = _text_layer(self.W, self.H, [(n_word, int(self.H * 0.22), True, (1.0, 0.88, 0.62))], 0.5)
        return self.number_cache[n_word]

    def paint(self, tag, u, t, seg, para):
        """One frame of a scene. seg = (start, end) of the scene; para = paragraph timing records."""
        W, H = self.W, self.H
        if tag in ("settle", "breathe"):
            pulse = 0.5 + 0.5 * math.sin(t * 2 * math.pi / 8) if tag == "breathe" else 0.3
            f, _ = self.room(u if tag == "settle" else 1.0, 0.25 + 0.25 * pulse, t)
            return f
        if tag == "star":
            dt_ = t - seg[0]
            blink = 1.0 if dt_ > 2.4 else (0.3 + 0.7 * (math.sin(dt_ * math.pi / 0.6) ** 2 if dt_ > 0.8 else 0))
            f, _ = self.room(1.0 + u, 0.4 + 0.8 * blink, t)
            return f
        if tag == "birthsky":
            if self.chart is None:
                return self.room(2.0, 1.0, t)[0]
            z = 1.0 + 0.08 * u
            im = self.chart.transform((W, H), Image.AFFINE, _affine(W / 2, H / 2, 1 / z, 0.05 * u, W, H), resample=Image.BILINEAR)
            return np.asarray(im, np.float32)
        if tag in ("companion", "curl", "secret"):
            f, z = self.room(2.0, 1.0 if tag != "curl" else 0.8, t)
            if tag == "companion":
                a = _ease((t - seg[0] - 1.0) / 3.0)
                starlight_silhouette(f, self.animal, W * 0.5, H * 0.6, int(H * 0.3), t=t, seed=self.seed % 100, alpha=a)
            elif tag == "curl":
                a = 1 - _ease(u * 1.2 - 0.2)
                starlight_silhouette(f, self.animal, W * 0.32, H * 0.84, int(H * 0.2), t=t * 0.5, seed=self.seed % 100, alpha=a)
            return f
        if tag in ("moonbeam", "home"):
            return self.climb(u, tag == "home", t)
        if tag == "planets":
            return self.planets_scene(u, t)
        if tag == "nebula":
            return self.nebula(math.exp(math.log(8) * _ease(u)), t)
        if tag == "wishes":
            f = self.nebula(8 + 2 * u, t, dim=0.85)
            sents = [s for p in para for s in p.get("sentences", [])]
            cx, cy = W / 2, H * 0.62
            landed = 0
            for s in [x for x in sents if "little star floated down" in x.get("text", "")] or sents[1:]:
                t0, t1 = s["start"], s["end"]
                if t < t0:
                    continue
                k = _ease((t - t0) / max(1.5, (t1 - t0) * 0.6))
                if k >= 1:
                    landed += 1
                    continue
                sx = cx + (hash((int(t0 * 10), self.seed)) % 600 - 300) * (1 - k)
                sy = -40 + (cy + 40) * k
                for j in range(18):                  # a glittering trail
                    _stamp(f, sx, sy - j * 18 * (1 - k) - 10, _spike_stamp(7), GOLD * (1 - j / 18) * 1.2)
                _stamp(f, sx, sy, big_star(int(H * 0.09)), GOLD * 1.4)
            if landed:
                _stamp(f, cx, cy, big_star(int(H * (0.12 + 0.015 * landed))), GOLD * (0.8 + 0.08 * landed))
                for j in range(landed):              # each landed wish settles into a little ring
                    a = 2 * math.pi * j / max(landed, 5) + t * 0.15
                    _stamp(f, cx + math.cos(a) * H * 0.14, cy + math.sin(a) * H * 0.09, big_star(int(H * 0.035)), GOLD)
            return f
        if tag == "message":
            f = self.nebula(10, t, dim=0.45)
            return _over(f, self.msg_rgba, _ease((t - seg[0] - 1.5) / 2.0)) if self.msg_rgba is not None else f
        if tag == "countdown":
            f, _ = self.room(2.0, 1.0 - 0.6 * u, t)
            words_ = ["Ten", "Nine", "Eight", "Seven", "Six", "Five", "Four", "Three", "Two", "One"]
            sents = [s for p in para for s in p.get("sentences", [])]
            by_word = {x.get("text", "").strip(" .").capitalize(): x for x in sents}
            for wd in words_:
                s = by_word.get(wd)
                if s is None:
                    continue
                if s["start"] - 0.2 <= t <= s["end"] + 1.6:
                    a = _ease((t - s["start"] + 0.2) / 0.5) * (1 - _ease((t - s["end"] - 0.6) / 1.0))
                    f = _over(f, self.number(wd), a * 0.85)
            return f
        if tag == "goodnight":
            f, z = self.room(2.0 + u, 1.0 + 0.4 * u, t)
            sx = W / 2 + (self.star_xy[0] - W / 2) * z; sy = H * 0.42 + (self.star_xy[1] - H * 0.42) * z
            return self.name_burst(f, t, seg[0] + 1.0, sx, sy)
        return self.room(1.0, 0.8, t)[0]


CHAPTER_TITLES = {
    "settle": "Settling in", "breathe": "Slow breaths", "star": "The star at the window", "birthsky": "The night you were born",
    "companion": "A friend made of starlight", "moonbeam": "The moonbeam", "planets": "Past the planets",
    "nebula": "Your own nebula", "wishes": "The wishes", "message": "A message for you", "home": "Floating home",
    "countdown": "Counting the stars", "curl": "Curling up", "secret": "A secret to keep", "goodnight": "Goodnight",
}


def write_chapters(timing_json: Path, tags: list[str], out: Path) -> Path:
    """Chapter list (start seconds and title) for YouTube descriptions, from the scene timings."""
    paras = json.loads(Path(timing_json).read_text())["paragraphs"]
    chapters, last = [], None
    for p, tg in zip(paras, tags):
        if tg != last:
            chapters.append({"start": 0.0 if not chapters else p["start"], "title": CHAPTER_TITLES.get(tg, tg.title())})
            last = tg
    Path(out).write_text(json.dumps({"chapters": chapters}, indent=1))
    return Path(out)


def render_story_video(audio: Path, timing_json: Path, tags: list[str], out: Path, *, seed: int, style: str,
                       name: str, animal: str, caption: str, title: str, sky=None, giver_message=None,
                       size=(1280, 720), crf=21, max_seconds=None, log=print) -> Path:
    W, H = size
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)],
                               capture_output=True, text=True, check=True).stdout.strip())
    if max_seconds:
        dur = min(dur, max_seconds)
    paras = json.loads(Path(timing_json).read_text())["paragraphs"]
    assert len(paras) == len(tags), f"{len(paras)} timed paragraphs but {len(tags)} scene tags"
    # group consecutive paragraphs with the same tag into scenes
    segs = []
    for p, tg in zip(paras, tags):
        if segs and segs[-1]["tag"] == tg:
            segs[-1]["end"] = p["end"]; segs[-1]["paras"].append(p)
        else:
            segs.append({"tag": tg, "start": p["start"], "end": p["end"], "paras": [p]})
    segs[0]["start"] = 0.0
    for a, b in zip(segs, segs[1:]):
        a["end"] = b["start"]
    segs[-1]["end"] = dur + 0.01
    log(f"  preparing scenes: {' > '.join(s['tag'] for s in segs)}")
    sv = StoryVideo(W, H, seed, style, name, animal, caption, sky=sky, giver_message=giver_message, title=title)
    n_frames = int(math.ceil(dur * FPS))
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-t", f"{dur:.2f}", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE)
    si = 0
    for i in range(n_frames):
        t = i / FPS
        while si < len(segs) - 1 and t >= segs[si]["end"]:
            si += 1
        s = segs[si]
        u = (t - s["start"]) / max(0.1, s["end"] - s["start"])
        f = sv.paint(s["tag"], u, t, (s["start"], s["end"]), s["paras"])
        if si > 0 and t - s["start"] < XFADE:          # dissolve from the previous scene
            p = segs[si - 1]
            up = (t - p["start"]) / max(0.1, p["end"] - p["start"])
            a = _ease((t - s["start"]) / XFADE)
            f = sv.paint(p["tag"], min(up, 1.0), t, (p["start"], p["end"]), p["paras"]) * (1 - a) + f * a
        if t < 7.5:
            f = _over(f, sv.title_rgba, min(1.0, t / 1.2) * (1 - _ease((t - 5.5) / 2.0)))
        if t > dur - 2.0:
            f *= max(0.0, (dur - t) / 2.0)
        ff.stdin.write(np.clip(f, 0, 255).astype(np.uint8).tobytes())
        if i and i % (FPS * 60) == 0:
            log(f"    {t / 60:.0f} min / {dur / 60:.1f} min")
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out
