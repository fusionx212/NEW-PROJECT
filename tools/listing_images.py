"""Etsy listing images (2000 x 2000) from a finished gift pack."""
from __future__ import annotations

import sys
from pathlib import Path

from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFilter, ImageFont

NAVY, GOLD, INK, PALE = (11, 20, 48), (245, 205, 130), (238, 240, 250), (150, 165, 215)
PX = 2000


def font(size, serif=True, italic=False):
    from skysoftly.fonts import font as house
    return house(size, serif=serif, italic=italic)


def centred(d, y, text, f, fill):
    d.text(((PX - d.textlength(text, font=f)) / 2, y), text, font=f, fill=fill)


def shadow_paste(base, im, xy, radius=30):
    sh = Image.new("RGBA", (im.width + 80, im.height + 80), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((40, 40, im.width + 40, im.height + 40), fill=(0, 0, 0, 170))
    sh = sh.filter(ImageFilter.GaussianBlur(radius))
    base.paste(sh, (xy[0] - 30, xy[1] - 20), sh)
    base.paste(im, xy)


def phone(still: Image.Image, h: int) -> Image.Image:
    w = int(h * 0.5)
    body = Image.new("RGB", (w, h), (18, 18, 22))
    scr = still.copy()
    sw, sh = w - 40, h - 80
    scale = max(sw / scr.width, sh / scr.height)
    scr = scr.resize((int(scr.width * scale), int(scr.height * scale)), Image.LANCZOS)
    left = (scr.width - sw) // 2
    body.paste(scr.crop((left, 0, left + sw, sh)), (20, 40))
    return body


def main(pack: Path, video_still: Path, video_still2: Path, page_a: Path, page_b: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    cover = Image.open(pack / "cover.jpg").convert("RGB")
    cert = Image.open(pack / "certificate.jpg").convert("RGB")
    still = Image.open(video_still).convert("RGB")
    bg = Image.open(video_still2).convert("RGB").resize((PX * 16 // 9, PX)).crop((0, 0, PX, PX)).filter(ImageFilter.GaussianBlur(6))

    # 1. Hero
    im = bg.copy(); d = ImageDraw.Draw(im)
    centred(d, 90, "A Bedtime Story Written in the Stars", font(92), GOLD)
    centred(d, 210, "Personalised story · narrated audio · nebula video · storybook · certificate", font(44, serif=False), INK)
    shadow_paste(im, cover.resize((900, 900), Image.LANCZOS), (150, 480))
    shadow_paste(im, phone(still, 1000), (1180, 420))
    shadow_paste(im, cert.resize((560, 560), Image.LANCZOS), (720, 1300))
    centred(d, 1900, "Their name, their own nebula, the real sky the night they were born", font(46, italic=True), INK)
    im.save(out / "01-hero.jpg", quality=90)

    # 2. What's inside
    im = Image.new("RGB", (PX, PX), NAVY); d = ImageDraw.Draw(im)
    centred(d, 110, "What's inside the gift", font(100), GOLD)
    items = [("A personalised bedtime story", "Read slowly and softly, about eight minutes, perfect for lights out."),
             ("A journey into their own nebula", "A video that dives deep into a nebula grown from their name, landing on a star that becomes their name."),
             ("The real sky they were born under", "The Moon, planets and stars from the night and place they were born, woven into the story."),
             ("An illustrated storybook", "Print at home or read on a tablet, 8 x 8 inches."),
             ("A nebula certificate", "Ready to print and frame for the nursery wall.")]
    y = 330
    for t, s in items:
        cx_, cy_ = 215, y + 42
        d.polygon([(cx_, cy_ - 34), (cx_ + 10, cy_ - 10), (cx_ + 34, cy_), (cx_ + 10, cy_ + 10), (cx_, cy_ + 34),
                   (cx_ - 10, cy_ + 10), (cx_ - 34, cy_), (cx_ - 10, cy_ - 10)], fill=GOLD)
        d.text((290, y), t, font=font(64), fill=INK)
        yy = y + 90
        words, line = s.split(), ""
        for w in words:
            if d.textlength(line + " " + w, font=font(44, serif=False)) > 1500:
                d.text((290, yy), line.strip(), font=font(44, serif=False), fill=PALE); yy += 60; line = ""
            line += " " + w
        d.text((290, yy), line.strip(), font=font(44, serif=False), fill=PALE)
        y = yy + 130
    im.save(out / "02-whats-inside.jpg", quality=90)

    # 3. Inside the storybook
    im = bg.copy(); d = ImageDraw.Draw(im)
    centred(d, 110, "Inside the storybook", font(100), GOLD)
    for i, p in enumerate((page_a, page_b)):
        pg = Image.open(p).convert("RGB").resize((820, 820), Image.LANCZOS)
        shadow_paste(im, pg, (140 + i * 900, 520))
    centred(d, 1500, "Every page goes a little deeper into their nebula", font(54, italic=True), INK)
    im.save(out / "03-storybook.jpg", quality=90)

    # 4. How to order
    im = Image.new("RGB", (PX, PX), NAVY); d = ImageDraw.Draw(im)
    centred(d, 110, "How to personalise", font(100), GOLD)
    steps = ["Child's first name, and she, he or they",
             "Age (for a birthday story) or leave blank for any night",
             "Favourite animal: it becomes their starlight companion",
             "Favourite colour: it sets the colours of their nebula",
             "Birth date and town: we weave in the real sky of that night",
             "Who it's from, and a short message the star reads out"]
    y = 360
    for i, s in enumerate(steps, 1):
        d.ellipse((170, y, 270, y + 100), outline=GOLD, width=5)
        d.text((220 - d.textlength(str(i), font=font(56)) / 2, y + 14), str(i), font=font(56), fill=GOLD)
        d.text((320, y + 18), s, font=font(52, serif=False), fill=INK)
        y += 210
    centred(d, 1700, "Delivered to your Etsy downloads, usually within 24 hours", font(50, italic=True), PALE)
    im.save(out / "04-how-to-order.jpg", quality=90)
    print("Listing images in", out)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(Path(a[0]), Path(a[1]), Path(a[2]), Path(a[3]), Path(a[4]), Path(a[5]))
