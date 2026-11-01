"""Shorts cover image: big punch text, a giant Zorb, bright rays.

``render_thumbnail(script, out)`` writes a 1080x1920 JPEG. The text comes from
the script's ``thumb_text`` (at most 3 words, upper-cased); the last word is
drawn in the accent colour. Expression comes from ``thumb_expression``
(default "shocked"). Colours come from the topic palette so each topic looks
different, but rays and outline keep every cover loud at feed size.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from pipeline.scenes import font, palette, fit
from pipeline.zorb import draw_zorb

W, H = 1080, 1920
TEXT_TOP, TEXT_BOTTOM = 170, 820       # text block lives here
TEXT_MAX_W = 940
MAX_WORDS = 3


def thumb_words(text: str) -> list:
    """Split ``thumb_text`` into upper-case words; ValueError if empty or > 3 words."""
    words = str(text or "").upper().split()
    if not words or len(words) > MAX_WORDS:
        raise ValueError(f"thumb_text must be 1-{MAX_WORDS} words, got {len(words)}")
    return words


def _rays(img, pal):
    d = ImageDraw.Draw(img)
    cx, cy, r = W // 2, 1240, 2600
    n = 18
    for i in range(n):
        if i % 2:
            continue
        a0 = 2 * math.pi * i / n
        a1 = 2 * math.pi * (i + 1) / n
        d.polygon([(cx, cy), (cx + r * math.cos(a0), cy + r * math.sin(a0)),
                   (cx + r * math.cos(a1), cy + r * math.sin(a1))], fill=pal["accent"] + (70,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((cx - 460, cy - 460, cx + 460, cy + 460), fill=(255, 255, 255, 90))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))


def _highlight(pal):
    """Yellow, unless the rays are already yellowish: then cyan."""
    r, g, b = pal["accent"]
    return (0, 229, 255) if (r > 180 and g > 160 and b < 120) else (255, 214, 0)


def _lines(words):
    """Up to 3 words: one word per line when long, else pack two short ones."""
    if len(words) == 3 and len(words[0]) + len(words[1]) <= 5:
        return [words[0] + " " + words[1], words[2]]
    return words


def render_thumbnail(script: dict, out) -> Path:
    words = thumb_words(script.get("thumb_text"))
    pal = palette(script["topic"])
    img = Image.new("RGBA", (W, H), pal["bg"] + (255,))
    _rays(img, pal)

    draw_zorb(img, script.get("thumb_expression", "shocked"), 0.9, False, (W // 2, 1300), scale=2.1)

    d = ImageDraw.Draw(img)
    lines = _lines(words)
    size = min(fit(line, 240, TEXT_MAX_W) for line in lines)
    size = min(size, int((TEXT_BOTTOM - TEXT_TOP) / (len(lines) * 1.08)))
    f = font(size)
    y = TEXT_TOP + ((TEXT_BOTTOM - TEXT_TOP) - len(lines) * size * 1.08) / 2
    for i, line in enumerate(lines):
        colour = _highlight(pal) if i == len(lines) - 1 else (255, 255, 255)
        d.text((W // 2, y + size / 2), line, font=f, fill=colour, anchor="mm",
               stroke_width=max(6, size // 14), stroke_fill=(10, 10, 20))
        y += size * 1.08

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out


if __name__ == "__main__":
    import json, sys
    print(render_thumbnail(json.load(open(sys.argv[1])), sys.argv[2]))
