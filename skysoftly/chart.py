"""All-sky chart for one place and moment, plus the printable kids' look-up card and keepsake page."""
from __future__ import annotations

import datetime as dt
import math
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patheffects as pe  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from .catalog import STAR_NAMES  # noqa: E402
from .fonts import register_matplotlib  # noqa: E402

_FAM = register_matplotlib()
plt.rcParams["font.family"] = _FAM["sans"]
SERIF = _FAM["display"]
SERIF_ITALIC = _FAM["italic"]
from .engine import load_constellations, load_stars, radec_to_altaz  # noqa: E402
from .script import direction, where, spoken_date  # noqa: E402

NAVY, INK, GOLD, PALE = "#0b1430", "#e8ecf8", "#f4c46a", "#8fa3d6"
HALO = [pe.withStroke(linewidth=2.5, foreground="#0b1430")]
PLANET_COLOURS = {"Mercury": "#c9b8a0", "Venus": "#fff3c4", "Mars": "#ff8a5c", "Jupiter": "#f2d7a6", "Saturn": "#e9cf8a"}


def _r(alt: float) -> float:
    """Stereographic radius from the zenith (0 at zenith, 1 at horizon)."""
    z = math.radians(90 - alt)
    return math.tan(z / 2) / math.tan(math.radians(45))


def _star_colour(bv: float) -> str:
    if bv < 0.0: return "#cfe0ff"
    if bv < 0.4: return "#eef3ff"
    if bv < 0.8: return "#fff6e0"
    if bv < 1.2: return "#ffe2b8"
    return "#ffc89a"


def draw_sky(ax, sky: dict, label_stars: int = 10, mag_limit: float = 5.0):
    lat, lst = sky["place"]["lat"], sky["lst_rad"]
    ax.set_facecolor(NAVY)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(1)  # east to the left, as when lying on your back looking up with north at the top
    ax.set_ylim(0, 1.02)
    ax.set_xticks([]); ax.set_yticks([])
    ax.spines["polar"].set_color(PALE); ax.spines["polar"].set_linewidth(1.2)

    stars = load_stars()
    pos = {}
    xs, ys, ss, cs = [], [], [], []
    for s in stars:
        alt, az = radec_to_altaz(s["ra"], s["dec"], lst, lat)
        if alt <= 0:
            continue
        pos[s["hip"]] = (math.radians(az), _r(alt))
        if s["mag"] <= mag_limit:
            xs.append(math.radians(az)); ys.append(_r(alt))
            ss.append(max(0.4, (mag_limit + 1.2 - s["mag"]) ** 2.1 * 1.3)); cs.append(_star_colour(s["bv"]))
    for c in load_constellations():
        for a, b in c["lines"]:
            if a in pos and b in pos:
                (t1, r1), (t2, r2) = pos[a], pos[b]
                if abs(t1 - t2) < math.pi:
                    ax.plot([t1, t2], [r1, r2], color=PALE, lw=0.6, alpha=0.45, zorder=1)
        alt, az = radec_to_altaz(c["ra"], c["dec"], lst, lat)
        if alt > 30:
            ax.text(math.radians(az), _r(alt), c["name"].upper(), color=PALE, fontsize=5, alpha=0.6,
                    ha="center", va="center", zorder=2)
    ax.scatter(xs, ys, s=ss, c=cs, linewidths=0, zorder=3)

    named = 0
    for s in sorted(stars, key=lambda s: s["mag"]):
        nm = STAR_NAMES.get(s["hip"])
        if nm and s["hip"] in pos and named < label_stars and pos[s["hip"]][1] < 0.93:
            t, r = pos[s["hip"]]
            ax.annotate(nm, (t, r), xytext=(0, 4), textcoords="offset points", color=INK, fontsize=6.5,
                        ha="center", va="bottom", zorder=4, path_effects=HALO)
            named += 1

    for p in sky["planets"]:
        if p["status"] == "up":
            t, r = math.radians(p["az"]), _r(p["alt"])
            ax.scatter([t], [r], s=55, c=PLANET_COLOURS[p["name"]], edgecolors=GOLD, linewidths=0.8, zorder=5)
            near_moon = sky["moon"]["status"] == "up" and p["extra"]["moon_separation"] < 8
            ax.annotate(p["name"], (t, r), xytext=(0, 8 if near_moon else -8), textcoords="offset points", color=GOLD, fontsize=8,
                        fontweight="bold", ha="center", va="bottom" if near_moon else "top", zorder=7, path_effects=HALO)
    m = sky["moon"]
    if m["status"] == "up":
        t, r = math.radians(m["az"]), _r(m["alt"])
        ax.scatter([t], [r], s=260, c="#f7f3e3", edgecolors=GOLD, linewidths=1, zorder=5)
        ax.annotate(f"Moon ({int(round(m['extra']['illumination']))}%)", (t, r), xytext=(0, -12), textcoords="offset points",
                    color=GOLD, fontsize=8, fontweight="bold", ha="center", va="top", zorder=6, path_effects=HALO)
    for lab, az in (("N", 0), ("E", 90), ("S", 180), ("W", 270)):
        ax.text(math.radians(az), 1.075, lab, color=INK, fontsize=12, fontweight="bold", ha="center", va="center")


def _look_list(sky: dict) -> list[str]:
    items = []
    m = sky["moon"]
    if m["status"] == "up":
        items.append(f"The Moon: {m['extra']['phase'].lower()}, {where(m['alt'], m['az'])}")
    for p in sorted([p for p in sky["planets"] if p["status"] == "up"], key=lambda p: p["mag"]):
        items.append(f"{p['name']}: {where(p['alt'], p['az'])}")
    for s in sky["stars"][:3]:
        items.append(f"{s['name']}: {where(s['alt'], s['az'])}")
    if sky["zenith_constellation"]:
        items.append(f"Overhead: {sky['zenith_constellation']}")
    for sh in sky["meteors_active"][:1]:
        items.append(f"Shooting stars: the {sh['name']}")
    return items[:7]


def lookup_card(sky: dict, out_base: Path, title: str = "Tonight's Sky, Softly") -> list[Path]:
    """A5-ish portrait card: chart on top, tick-box checklist below. Writes PNG and PDF."""
    day = dt.date.fromisoformat(sky["date"])
    look = dt.datetime.fromisoformat(sky["look_time"])
    fig = plt.figure(figsize=(5.83, 8.27), facecolor=NAVY)
    fig.text(0.5, 0.965, title, color=GOLD, fontsize=17, ha="center", va="top", family=SERIF)
    fig.text(0.5, 0.93, f"{sky['place']['name']}  ·  {spoken_date(day)} {day.year}  ·  {look.strftime('%H:%M')}",
             color=INK, fontsize=9, ha="center", va="top")
    ax = fig.add_axes([0.11, 0.375, 0.78, 0.5], projection="polar")
    draw_sky(ax, sky)
    fig.text(0.5, 0.318, "Hold the card above your head with the N pointing north.", color=PALE, fontsize=7.5, ha="center")
    fig.text(0.1, 0.28, "Tonight, look for:", color=GOLD, fontsize=12, ha="left", family=SERIF)
    y = 0.245
    for it in _look_list(sky):
        fig.text(0.1, y, "☐", color=INK, fontsize=12, ha="left", va="center")
        fig.text(0.16, y, it, color=INK, fontsize=9.5, ha="left", va="center")
        y -= 0.032
    fig.text(0.5, 0.02, "Computed from real ephemeris for this place and time.", color=PALE, fontsize=6.5, ha="center")
    out_base.parent.mkdir(parents=True, exist_ok=True)
    png, pdf = out_base.with_suffix(".png"), out_base.with_suffix(".pdf")
    fig.savefig(png, dpi=200, facecolor=NAVY); fig.savefig(pdf, facecolor=NAVY)
    plt.close(fig)
    return [png, pdf]


def keepsake_page(sky: dict, out_base: Path, headline: str, script_text: str, when: dt.datetime) -> list[Path]:
    """A4 two-page keepsake: page 1 the chart, page 2 the written sky report. PNG of page 1 for listings."""
    import re
    clean = re.sub(r"\s*\[pause [\d.]+\]\s*", " ", script_text).strip()
    fig1 = plt.figure(figsize=(8.27, 11.69), facecolor=NAVY)
    fig1.text(0.5, 0.95, headline, color=GOLD, fontsize=24, ha="center", va="top", family=SERIF)
    fig1.text(0.5, 0.905, f"{sky['place']['name']}  ·  {when.strftime('%A %d %B %Y')}  ·  {when.strftime('%H:%M')}",
              color=INK, fontsize=11, ha="center", va="top")
    ax = fig1.add_axes([0.09, 0.19, 0.82, 0.66], projection="polar")
    draw_sky(ax, sky, label_stars=14, mag_limit=5.5)
    fig1.text(0.5, 0.12, f"The sky above {sky['place']['name']}, latitude {sky['place']['lat']:.2f}°, longitude {sky['place']['lon']:.2f}°",
              color=PALE, fontsize=9, ha="center")
    fig1.text(0.5, 0.09, "With love, from the sky.", color=INK, fontsize=10,
              ha="center", family=SERIF_ITALIC)

    fig2 = plt.figure(figsize=(8.27, 11.69), facecolor="#fbf8f0")
    fig2.text(0.5, 0.94, "A letter from the sky", color=NAVY, fontsize=20, ha="center", va="top", family=SERIF)
    body = "\n\n".join(textwrap.fill(p.strip(), 88) for p in clean.split("\n\n") if p.strip())
    fig2.text(0.1, 0.88, body, color="#1d2340", fontsize=9.5, ha="left", va="top", family=SERIF, linespacing=1.5)

    out_base.parent.mkdir(parents=True, exist_ok=True)
    pdf, png = out_base.with_suffix(".pdf"), out_base.with_suffix(".png")
    with PdfPages(pdf) as pp:
        pp.savefig(fig1, facecolor=NAVY); pp.savefig(fig2, facecolor="#fbf8f0")
    fig1.savefig(png, dpi=150, facecolor=NAVY)
    plt.close(fig1); plt.close(fig2)
    return [png, pdf]


def cover_art(sky: dict, out_png: Path, subtitle: str) -> Path:
    """3000x3000 podcast cover: the real sky over the city, title on top."""
    fig = plt.figure(figsize=(10, 10), facecolor=NAVY)
    ax = fig.add_axes([0.06, 0.04, 0.88, 0.88], projection="polar")
    draw_sky(ax, sky, label_stars=0, mag_limit=4.8)
    for t in list(ax.texts):
        t.set_visible(False)
    fig.text(0.5, 0.6, "Tonight's Sky,", color=GOLD, fontsize=64, ha="center", va="center", family=SERIF, path_effects=[pe.withStroke(linewidth=10, foreground=NAVY)])
    fig.text(0.5, 0.49, "Softly", color=GOLD, fontsize=64, ha="center", va="center", family=SERIF_ITALIC, path_effects=[pe.withStroke(linewidth=10, foreground=NAVY)])
    fig.text(0.5, 0.38, subtitle, color=INK, fontsize=26, ha="center", va="center", path_effects=[pe.withStroke(linewidth=8, foreground=NAVY)])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=300, facecolor=NAVY)
    plt.close(fig)
    return out_png
