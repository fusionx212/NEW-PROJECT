"""House fonts (all SIL Open Font License, bundled in skysoftly/fonts/).

- Fraunces (soft, storybook serif) for titles and body text
- Quicksand (rounded sans) for small labels
- Dancing Script for names
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

DIR = Path(__file__).parent / "fonts"
FILES = {
    "display": "Fraunces-Display.ttf",
    "text": "Fraunces-Text.ttf",
    "bold": "Fraunces-Bold.ttf",
    "italic": "Fraunces-Italic.ttf",
    "sans": "Quicksand-Medium.ttf",
    "name": "DancingScript-Bold.ttf",
}


def path(role: str) -> str:
    return str(DIR / FILES[role])


@lru_cache(maxsize=256)
def get(size: int, role: str = "display") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path(role), max(1, int(size)))


def font(size: int, serif: bool = True, italic: bool = False, bold: bool = False, role: str | None = None):
    """Drop-in for the old DejaVu helpers: serif/italic/bold map onto house roles."""
    if role is None:
        role = "italic" if italic else "bold" if bold else "display" if serif else "sans"
    return get(int(size), role)


def register_matplotlib() -> dict[str, str]:
    """Make the house fonts usable in matplotlib; returns family names by role."""
    from matplotlib import font_manager
    names = {}
    for role, f in FILES.items():
        p = DIR / f
        font_manager.fontManager.addfont(str(p))
        names[role] = font_manager.FontProperties(fname=str(p)).get_name()
    return names
