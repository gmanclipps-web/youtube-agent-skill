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


def highlight_colour(pal):
    """Yellow, unless the rays are already yellowish: then cyan."""
    r, g, b = pal["accent"]
    return (0, 229, 255) if (r > 180 and g > 160 and b < 120) else (255, 214, 0)


STROKE = (10, 10, 20)
LINE_GAP = 1.08


def _lines(words):
    """Up to 3 words: one word per line when long, else pack two short ones."""
    if len(words) == 3 and len(words[0]) + len(words[1]) <= 5:
        return [words[0] + " " + words[1], words[2]]
    return words


def draw_punch_text(img, words, pal, box, max_size=240):
    """The cover's punch text, centred in ``box`` (x0, y0, x1, y1) of ``img``:
    bold white with a dark stroke, the last line in the highlight colour, as
    large as fits (at most ``max_size`` px). Shared by the cover and the
    video's hook card. Returns the font size used."""
    x0, y0, x1, y1 = box
    lines = _lines(list(words))
    size = min(fit(line, max_size, x1 - x0) for line in lines)
    size = max(1, min(size, int((y1 - y0) / (len(lines) * LINE_GAP))))
    f = font(size)
    d = ImageDraw.Draw(img)
    y = y0 + ((y1 - y0) - len(lines) * size * LINE_GAP) / 2
    for i, line in enumerate(lines):
        colour = highlight_colour(pal) if i == len(lines) - 1 else (255, 255, 255)
        d.text(((x0 + x1) / 2, y + size / 2), line, font=f, fill=colour, anchor="mm",
               stroke_width=max(6, size // 14), stroke_fill=STROKE)
        y += size * LINE_GAP
    return size


def cover_colours(pal):
    """Burst colour for the cover: the topic accent, unless it is greenish
    (Zorb is green and would vanish) - then a hot orange."""
    r, g, b = pal["accent"]
    burst = (255, 120, 40) if (g > r + 30 and g > b + 30) else (r, g, b)
    return {"burst": burst, "bg": pal["bg"]}


def hero_beat(script):
    """The beat whose picture goes on the cover: ``thumb_scene`` if given,
    else the first beat with a number in its props, else the first beat."""
    if isinstance(script.get("thumb_scene"), dict):
        return script["thumb_scene"]
    beats = script.get("beats") or []
    for b in beats:
        if any(any(ch.isdigit() for ch in str(v)) for v in (b.get("props") or {}).values()):
            return b
    return beats[0] if beats else None


def _hero_card(img, script, pal):
    from pipeline.scenes import SCENE_PAINTERS
    hb = hero_beat(script)
    if not hb or hb.get("scene") not in SCENE_PAINTERS:
        return
    scene = Image.new("RGBA", (W, 1050), pal["bg"] + (255,))
    SCENE_PAINTERS[hb["scene"]](scene, hb.get("props") or {}, 1.0, pal)
    card = scene.crop((60, 40, 1020, 1000)).resize((700, 700), Image.LANCZOS)
    framed = Image.new("RGBA", (740, 740), (255, 255, 255, 255))
    framed.paste(card, (20, 20))
    framed = framed.rotate(-4, resample=Image.BICUBIC, expand=True)
    shadow = Image.new("RGBA", framed.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 150), (0, 0), framed)
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    x, y = W - framed.width + 40, 640
    img.alpha_composite(shadow, (x + 14, y + 22))
    img.alpha_composite(framed, (x, y))


def _arrow(img, start, end, colour=(255, 40, 60)):
    d = ImageDraw.Draw(img)
    d.line([start, end], fill=STROKE, width=46)
    d.line([start, end], fill=colour, width=30)
    ang = math.atan2(end[1] - start[1], end[0] - start[0])
    tip = [end,
           (end[0] - 80 * math.cos(ang - 0.5), end[1] - 80 * math.sin(ang - 0.5)),
           (end[0] - 80 * math.cos(ang + 0.5), end[1] - 80 * math.sin(ang + 0.5))]
    d.polygon(tip, fill=colour, outline=STROKE, width=6)


def render_cover(script: dict) -> Image.Image:
    """The cover as an RGBA image: huge punch text on top, the video's key
    picture on a tilted card, a big reacting Zorb."""
    words = thumb_words(script.get("thumb_text"))
    pal = palette(script["topic"])
    cc = cover_colours(pal)
    img = Image.new("RGBA", (W, H), cc["bg"] + (255,))
    _rays(img, {**pal, "accent": cc["burst"]})
    _hero_card(img, script, pal)
    draw_zorb(img, script.get("thumb_expression", "shocked"), 0.9, False, (300, 1560), scale=1.9)
    draw_punch_text(img, words, {**pal, "accent": cc["burst"]}, (40, 70, W - 40, 620), max_size=260)
    return img


def render_thumbnail(script: dict, out) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    render_cover(script).convert("RGB").save(out, "JPEG", quality=90)
    return out


if __name__ == "__main__":
    import json, sys
    print(render_thumbnail(json.load(open(sys.argv[1])), sys.argv[2]))
