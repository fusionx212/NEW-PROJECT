"""Printable storybook PDF: cover, dedication, illustrated story pages, the birth-night sky and a certificate.

Pages are 8 x 8 inches at 300 dpi. Illustrations come from the child's own nebula, going deeper into it
page by page, just as the story travels deeper into space.
"""
from __future__ import annotations

import datetime as dt
import re
import textwrap
from pathlib import Path

import numpy as np
from .fonts import font
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PX = 2400
NAVY = (11, 20, 48)
INK = (238, 240, 250)
GOLD = (245, 205, 130)
PALE = (150, 165, 215)


def _fam():
    from .fonts import register_matplotlib
    return register_matplotlib()


def _font(size: int, serif: bool = True, italic: bool = False):
    return font(size, serif=serif, italic=italic)


def _centered(d: ImageDraw.ImageDraw, y: int, text: str, font, fill, width: int = PX):
    tw = d.textlength(text, font=font)
    d.text(((width - tw) / 2, y), text, font=font, fill=fill)


def _wrap(d, text, font, max_w):
    out, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if d.textlength(trial, font=font) <= max_w:
            line = trial
        else:
            out.append(line); line = word
    if line:
        out.append(line)
    return out


def _clean(script: str) -> list[str]:
    paras = [re.sub(r"\s*\[pause [\d.]+\]\s*", " ", p).strip() for p in script.split("\n\n")]
    return [re.sub(r"\s+", " ", p) for p in paras if p]


def _pages(paras: list[str], target_words: int = 95) -> list[str]:
    pages, cur = [], []
    for p in paras:
        if cur and sum(len(x.split()) for x in cur) + len(p.split()) > target_words * 1.35:
            pages.append(" ".join(cur)); cur = []
        cur.append(p)
        if sum(len(x.split()) for x in cur) >= target_words:
            pages.append(" ".join(cur)); cur = []
    if cur:
        pages.append(" ".join(cur))
    return pages


def _art(levels: list[Image.Image], depth: int, h: int) -> Image.Image:
    from .zoom import sprinkle_stars
    im = levels[min(depth, len(levels) - 1)]
    n = im.size[0]
    c = n // 2
    half = int(n * 0.36)
    crop = im.crop((c - half, c - int(half * h / PX), c + half, c + int(half * h / PX)))
    return sprinkle_stars(crop.resize((PX, h), Image.LANCZOS), seed=depth * 7919 + h)


def _vignette(img: Image.Image, strength: float = 0.55) -> Image.Image:
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = ((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2) * 2
    m = np.clip(1 - strength * r, 0, 1)[..., None]
    return Image.fromarray((np.asarray(img, dtype=np.float32) * m).astype(np.uint8))


def make_storybook(out_pdf: Path, *, title: str, name: str, script: str, levels: list[Image.Image],
                   giver: str | None = None, message: str | None = None, sky: dict | None = None,
                   born: dt.date | None = None, place: str | None = None, caption: str = "") -> list[Path]:
    """Writes the PDF and a PNG of the cover and certificate (for listings and sharing)."""
    pages: list[Image.Image] = []
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    # Cover
    cover = _vignette(_art(levels, 0, PX), 0.6)
    d = ImageDraw.Draw(cover)
    ft = _font(150); fs = _font(70, serif=False)
    lines = _wrap(d, title, ft, PX * 0.8)
    y = int(PX * 0.12)
    for ln in lines:
        for dx, dy in ((0, 5), (5, 0), (0, -5), (-5, 0)):
            d.text(((PX - d.textlength(ln, font=ft)) / 2 + dx, y + dy), ln, font=ft, fill=(5, 8, 25))
        _centered(d, y, ln, ft, GOLD)
        y += 175
    _centered(d, int(PX * 0.86), f"A bedtime story for {name}", fs, INK)
    pages.append(cover)

    # Dedication
    ded = Image.new("RGB", (PX, PX), NAVY)
    d = ImageDraw.Draw(ded)
    fi = _font(84, italic=True)
    text = message or f"For {name}, who is loved to the stars and back."
    y = int(PX * 0.38)
    for ln in _wrap(d, f"“{text}”", fi, PX * 0.7):
        _centered(d, y, ln, fi, INK); y += 120
    if giver:
        _centered(d, y + 60, f"With love from {giver}", _font(70, serif=False), GOLD)
    pages.append(ded)

    # Story pages
    texts = _pages(_clean(script))
    fb = _font(64)
    for i, body in enumerate(texts):
        pg = Image.new("RGB", (PX, PX), NAVY)
        art_h = int(PX * 0.5)
        art = _vignette(_art(levels, 1 + i * (len(levels) - 1) // max(1, len(texts)), art_h), 0.35)
        pg.paste(art, (0, 0))
        fade = Image.linear_gradient("L").resize((PX, 260))
        pg.paste(Image.new("RGB", (PX, 260), NAVY), (0, art_h - 260), fade)
        d = ImageDraw.Draw(pg)
        y = art_h + 30
        for ln in _wrap(d, body, fb, PX * 0.82):
            d.text((PX * 0.09, y), ln, font=fb, fill=INK); y += 92
        _centered(d, PX - 120, str(i + 1), _font(44, serif=False), PALE)
        pages.append(pg)

    # The real sky page
    if sky:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from .chart import draw_sky
        fig = plt.figure(figsize=(8, 8), dpi=300, facecolor="#0b1430")
        ax = fig.add_axes([0.1, 0.16, 0.8, 0.7], projection="polar")
        draw_sky(ax, sky, label_stars=12)
        when = born.strftime("%d %B %Y").lstrip("0") if born else ""
        fig.text(0.5, 0.94, "The sky on the night you were born", color="#f5cd82", fontsize=22, ha="center", family=_fam()["display"])
        fig.text(0.5, 0.9, f"{place} · {when}", color="#e8ecf8", fontsize=11, ha="center")
        fig.text(0.5, 0.06, "Computed from the real positions of the Moon, planets and stars.", color="#8fa3d6", fontsize=9, ha="center")
        tmp = out_pdf.with_suffix(".sky.png")
        fig.savefig(tmp, dpi=300, facecolor="#0b1430"); plt.close(fig)
        pages.append(Image.open(tmp).convert("RGB").resize((PX, PX), Image.LANCZOS))
        tmp.unlink()

    # Certificate
    cert = Image.new("RGB", (PX, PX), (250, 246, 236))
    d = ImageDraw.Draw(cert)
    d.rectangle((70, 70, PX - 70, PX - 70), outline=(190, 150, 80), width=10)
    d.rectangle((105, 105, PX - 105, PX - 105), outline=(190, 150, 80), width=3)
    _centered(d, 230, "Certificate of a Nebula", _font(130), (40, 45, 80))
    neb = _art(levels, 0, 900).crop((450, 0, 1950, 900)).resize((1100, 660), Image.LANCZOS)
    cert.paste(neb, ((PX - 1100) // 2, 470))
    d.rectangle(((PX - 1100) // 2, 470, (PX + 1100) // 2, 1130), outline=(190, 150, 80), width=6)
    _centered(d, 1210, "This nebula was created especially for", _font(66, italic=True), (70, 75, 105))
    _centered(d, 1310, name, font(190, role="name"), (150, 105, 35))
    y = 1560
    for ln in ([caption] if caption else []) + ([f"Under the real sky of {place}, {born.strftime('%d %B %Y').lstrip('0')}"] if (born and place) else []):
        _centered(d, y, ln, _font(60, serif=False), (60, 65, 95)); y += 90
    small = _font(40, serif=False)
    for ln in textwrap.wrap("This is an original artwork made for one person. Its shapes and colours grow from the name it "
                            "was made for, so no one else has one quite like it. It is a keepsake, not an official "
                            "astronomical name.", 95):
        _centered(d, y + 80, ln, small, (110, 110, 130)); y += 56
    pages.append(cert)

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(out_pdf, save_all=True, append_images=pages[1:], resolution=300)
    cover_png = out_pdf.with_name("cover.jpg"); pages[0].resize((1200, 1200), Image.LANCZOS).save(cover_png, quality=90)
    cert_png = out_pdf.with_name("certificate.jpg"); cert.save(cert_png, quality=92)
    return [out_pdf, cover_png, cert_png]
