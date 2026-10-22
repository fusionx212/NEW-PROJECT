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
from PIL import Image, ImageDraw

from . import art
from .art import BEDROOM, RIBBON_PATH, along, ken_burns, screen, sprite
from .nebula import make_nebula
from .scenes import planet, starlight_silhouette
from .video import FPS, _affine, _font, _text_layer
from .zoom import (LEVEL_FIT, _smooth, _stamp, big_star, build_levels, name_points, pick_star_spot,
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
        self.pet = art.animal_key(animal)
        self.room_img = art.image("bedroom")
        bw, bh = self.room_img.size
        x0, y0, x1, y1 = BEDROOM["window"]
        yy, xx = np.mgrid[0:bh, 0:bw].astype(np.float32)
        edge = np.minimum.reduce([xx - x0 * bw, x1 * bw - xx, yy - y0 * bh, y1 * bh - yy])
        mask = np.clip(edge / 30.0, 0, 1)[..., None]
        field = np.asarray(art.image("starfield").resize((bw, bh)), np.float32)
        self.room_base = np.asarray(self.room_img, np.float32)
        self.tw_a = field * mask * 0.55
        self.tw_b = np.roll(field, (61, 97), (0, 1)) * mask * 0.55
        self.climb_img = art.image("town")
        self.space_img = art.image("space")
        self.planets = [p["name"] for p in (sky or {}).get("planets", []) if p["status"] in ("up", "rises_later")][:3] \
            or ["Jupiter", "Saturn", "Mars"]
        self.sky = sky
        self.chart = self._chart() if sky else None
        self.wide = sprinkle_stars(self.levels[0].resize((int(W * 2.2), int(W * 2.2 * 9 / 16))), seed=seed % 997, density=0.6)
        base = min(H, W * 1.2)
        self.title_rgba = _text_layer(W, H, [(title, int(base * 0.07), True, (0.96, 0.80, 0.50)),
                                             ("A bedtime story", int(base * 0.035), False, (0.92, 0.94, 0.98))], 0.5)
        self.msg_rgba = _text_layer(W, H, self._wrap(self.msg or "", int(base * 0.055)), 0.5) if self.msg else None
        fsize = int(base * 0.19)
        f = _font(fsize, "name")
        probe = ImageDraw.Draw(Image.new("L", (8, 8)))
        while probe.textlength(name, font=f) > W * 0.86 and fsize > 12:
            fsize = int(fsize * 0.92); f = _font(fsize, "name")
        self.px, self.py, _ = name_points(name, W, H, 0.72, f, seed=seed)
        self.name_rgba = _text_layer(W, H, [(name, fsize, "name", (1.0, 0.86, 0.58))], 0.72)
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

    # ---------- scene painters: each returns a float frame for local time u (0..1) and absolute t ----------
    def room(self, push, star_gain, t, pet=None, pet_gain=0.0):
        """The painted bedroom. push slowly moves the camera in towards the window (0..3).

        pet: None, "sit" (on the windowsill) or "sleep" (curled on the bed)."""
        W, H = self.W, self.H
        bg = self.room_base + self.tw_a * (0.5 + 0.5 * math.sin(t * 1.1)) + self.tw_b * (0.5 + 0.5 * math.sin(t * 0.83 + 2.0))
        bg = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8))
        z = 1.04 + 0.11 * push
        k = min(push / 3.0, 1.0)
        fx, fy = 0.5 + (BEDROOM["focus"][0] - 0.5) * k, 0.5 + (BEDROOM["focus"][1] - 0.5) * k
        f, to_s, sc = ken_burns(bg, W, H, z, fx, fy, th=0.004 * math.sin(t * 0.07))
        mx, my = to_s(*BEDROOM["moon"])
        screen(f, sprite("moon", int(H * 0.15 * z)), mx, my + 3 * math.sin(t * 0.4), 0.85 + 0.1 * math.sin(t * 0.6))
        sx, sy = to_s(*BEDROOM["star"])
        if star_gain > 0.01:
            pulse = 1 + 0.06 * math.sin(t * 2.2)
            screen(f, sprite("star", int(H * 0.2 * z * (0.55 + 0.45 * min(star_gain, 1.4)) * pulse)), sx, sy, min(star_gain, 1.6))
        if pet and pet_gain > 0.01:
            self.draw_pet(f, pet, to_s, sc, t, pet_gain)
        self.star_xy = (sx, sy)
        return f, z

    def draw_pet(self, f, pose, to_s, sc, t, gain):
        if pose == "sit":
            px, py = to_s(*BEDROOM["sill"])
            hgt = self.room_img.height * 0.30 * sc
        else:
            px, py = to_s(*BEDROOM["bed"])
            hgt = self.room_img.height * 0.20 * sc
        if self.pet:
            breathe = 1 + 0.012 * math.sin(t * (1.3 if pose == "sit" else 0.7))
            name = art.ANIMAL_ART[self.pet][pose]
            art.glow(f, sprite(name, int(hgt * breathe)), px, py + (2 * math.sin(t * 1.3) if pose == "sit" else 0),
                     gain * (0.92 + 0.08 * math.sin(t * 2.7)), anchor="bottom")
        else:
            starlight_silhouette(f, self.animal, px, py - hgt * 0.45, int(hgt), t=t, seed=self.seed % 100, alpha=gain)

    def climb(self, u, reverse, t):
        """Riding the moonbeam up over the painted town (or floating back down to it)."""
        W, H = self.W, self.H
        e = _ease(u)
        k = e if not reverse else 1 - e
        z = 1.3 - 0.22 * k
        f, to_s, sc = ken_burns(self.climb_img, W, H, z, 0.5 + 0.06 * math.sin(t * 0.05), 0.85 - 0.7 * k)
        rib = sprite("moonbeam", H)
        wave = 0.72 + 0.28 * np.sin(np.arange(rib.shape[1], dtype=np.float32) * 0.012 - t * 2.4)
        screen(f, rib * wave[None, :, None], W / 2, H / 2, 1.0)
        rk = 0.18 + 0.6 * e if not reverse else 0.78 - 0.6 * e
        (qx, qy), _ = along(RIBBON_PATH, rk)
        bx = W / 2 + (qx - 0.5) * rib.shape[1]
        by = H / 2 + (qy - 0.5) * rib.shape[0] - H * 0.06 + 6 * math.sin(t * 2.0)
        if self.pet:
            screen(f, sprite(art.ANIMAL_ART[self.pet]["leap"], int(H * 0.26), flip=reverse), bx, by, 1.0)
        else:
            starlight_silhouette(f, self.animal, bx, by, int(H * 0.22), t=t, seed=self.seed % 100)
        return f

    def planets_scene(self, u, t):
        W, H = self.W, self.H
        f, _, _ = ken_burns(self.space_img, W, H, 1.25, 0.25 + 0.5 * _ease(u), 0.5 + 0.04 * math.sin(t * 0.1))
        n = len(self.planets)
        for i, p in enumerate(self.planets):
            # each planet drifts across faster than the background (parallax)
            px = W * (1.15 + i * 0.75) - (W * (0.9 + n * 0.75)) * _ease(u)
            py = H * (0.32 + 0.3 * ((i * 37) % 3) / 2)
            r = {"Jupiter": 0.2, "Saturn": 0.11, "Mars": 0.07, "Venus": 0.09, "Mercury": 0.05}.get(p, 0.08) * H
            if -r * 3 < px < W + r * 3:
                if p.lower() in art.PLANETS:
                    # a soft halo, then the painted planet with a gentle drift
                    screen(f, sprite("star", int(r * 2.6)), px, py, 0.18)
                    art.over(f, art.solid(p.lower(), int(r * (2.6 if p == "Saturn" else 2.1))), px, py + 4 * math.sin(t * 0.5 + i))
                else:
                    planet(f, p, px, py, r)
        bx, by = W * 0.3, H * 0.7 + 10 * math.sin(t * 1.6)
        if self.pet:
            screen(f, sprite(art.ANIMAL_ART[self.pet]["leap"], int(H * 0.24)), bx, by, 1.0)
        else:
            starlight_silhouette(f, self.animal, bx, by, int(H * 0.2), t=t, seed=self.seed % 100)
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
            if tag == "companion":
                return self.room(2.0, 1.0, t, pet="sit", pet_gain=_ease((t - seg[0] - 1.0) / 3.0))[0]
            if tag == "curl":
                return self.room(2.0 - u, 0.8, t, pet="sleep", pet_gain=_ease(u * 4) * (1 - _ease((u - 0.7) / 0.3)))[0]
            return self.room(2.0, 1.0, t, pet="sit", pet_gain=0.9)[0]
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
                for j in range(22):                  # a glittering trail
                    _stamp(f, sx, sy - j * 16 * (1 - k) - 12, big_star(int(H * 0.03)), GOLD * (1 - j / 22) * 1.6)
                screen(f, sprite("star", int(H * 0.2)), sx, sy, 1.3)
            if landed:
                screen(f, sprite("star", int(H * (0.24 + 0.025 * landed) * (1 + 0.04 * math.sin(t * 2)))), cx, cy, 1.2)
                for j in range(landed):              # each landed wish settles into a little ring
                    a = 2 * math.pi * j / max(landed, 5) + t * 0.15
                    screen(f, sprite("star", int(H * 0.08)), cx + math.cos(a) * H * 0.2, cy + math.sin(a) * H * 0.12, 1.1)
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
            f, _ = self.room(2.0 + u, 1.0 + 0.4 * u, t, pet="sleep", pet_gain=0.6 * (1 - _ease(u * 3)))
            return self.name_burst(f, t, seg[0] + 1.0, *self.star_xy)
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
