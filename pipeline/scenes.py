"""Scene painters and the per-topic palette.

Every painter has the signature ``painter(img, props, progress, pal)`` and
paints the scene area (full width, y 0..1049) of a 1080x1920 frame in place.
Nothing is drawn at or below y 1050: the captions band (y 1100-1400) and
Zorb (y 1430-1890) belong to other layers. Main art stays inside x 110..930
so it avoids the right 12% of the frame.

Painters draw at 2x on a cached background and downscale with a box filter
(``Image.reduce``) for anti-aliased edges. ``progress`` (0..1, clamped)
animates within the beat. ``props`` is free-form; missing or junk values fall
back to defaults, so every painter works with ``props={}``.
"""
import colorsys
import hashlib
import math
import random
import re
from functools import lru_cache, wraps

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pipeline.script_schema import SCENES

W = 1080
SCENE_H = 1050
SS = 2
CX = 520            # horizontal centre of scene art (left of 540: keeps clear of right 12%)

_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
_MONO_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
)


@lru_cache(maxsize=128)
def font(size: int, mono: bool = False):
    """Bold sans (or mono) TTF at ``size`` px; Pillow's default font if none found."""
    size = max(1, int(size))
    for path in (_MONO_PATHS if mono else ()) + _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------- colour

def _lum(c):
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    """WCAG contrast ratio between two RGB colours."""
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _hsv(h, s, v):
    return tuple(int(round(x * 255)) for x in colorsys.hsv_to_rgb(h % 1.0, s, v))


def mix(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def palette(topic: str) -> dict:
    """Deterministic colours for a topic: keys bg, fg, accent, text.

    Hue comes from md5(topic) but skips the greens so Zorb never blends in.
    ``bg`` is dark, ``text`` is near-white and always >= 4.5:1 against ``bg``.
    """
    d = hashlib.md5(str(topic).encode("utf-8")).digest()
    h = 0.5 + d[0] / 255 * 0.62            # 0.50..1.12: cyan, blue, violet, magenta, red, orange
    bg = _hsv(h, 0.50 + d[1] / 255 * 0.25, 0.20 + d[2] / 255 * 0.10)
    fg = _hsv(h, 0.14 + d[3] / 255 * 0.10, 0.94)
    accent = _hsv(h + 0.42 + d[4] / 255 * 0.16, 0.72, 0.98)
    text = _hsv(h, 0.04, 1.0)
    while contrast(text, bg) < 4.5:
        bg = mix(bg, (0, 0, 0), 0.15)
    return {"bg": bg, "fg": fg, "accent": accent, "text": text}


# ---------------------------------------------------------------- props

def _num(v, default):
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else default
    if isinstance(v, str):
        s = re.sub(r"[^0-9.\-]", "", v)
        try:
            f = float(s)
        except ValueError:
            return default
        return f if math.isfinite(f) else default
    return default


def _decimals(v):
    if isinstance(v, float):
        if not math.isfinite(v):
            return 0
        frac = f"{v:.10f}".rstrip("0").split(".")[1]
        return min(2, len(frac))
    if isinstance(v, str) and "." in v:
        return min(2, len(re.sub(r"[^0-9]", "", v.split(".", 1)[1])))
    return 0


def _text(v, default, limit=14):
    if isinstance(v, bool) or v is None:
        return default
    if isinstance(v, (int, float)):
        v = str(v)
    if isinstance(v, str) and v.strip():
        return v.strip().upper()[:limit]
    return default


UNKNOWN = "?"   # shown where a number would go but the script supplied none


def _fmt(x, decimals):
    return f"{x:,.{decimals}f}"


# ---------------------------------------------------------------- easing

def _clamp(t, lo=0.0, hi=1.0):
    if not math.isfinite(t):
        return lo
    return lo if t < lo else hi if t > hi else t


def ease_out(t):
    return 1 - (1 - _clamp(t)) ** 3


def ease_in_out(t):
    t = _clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_back(t):
    t = _clamp(t)
    c1 = 1.70158
    return 1 + (c1 + 1) * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _seg(p, a, b):
    """Local 0..1 progress of p within [a, b]."""
    return _clamp((p - a) / (b - a))


# ---------------------------------------------------------------- pen

class Pen:
    """ImageDraw wrapper that takes 1x coordinates and draws at ``k``x."""

    def __init__(self, draw, k, ox=0.0, oy=0.0):
        self.d = draw
        self.k = k
        self.ox = ox
        self.oy = oy

    def p(self, x, y):
        return ((self.ox + x) * self.k, (self.oy + y) * self.k)

    def box(self, x0, y0, x1, y1):
        return [*self.p(x0, y0), *self.p(x1, y1)]

    def w(self, width):
        return max(1, round(width * self.k))

    def rect(self, x0, y0, x1, y1, fill=None, outline=None, width=0):
        self.d.rectangle(self.box(x0, y0, x1, y1), fill=fill, outline=outline,
                         width=self.w(width) if outline else 0)

    def rrect(self, x0, y0, x1, y1, r, fill=None, outline=None, width=0, corners=None):
        self.d.rounded_rectangle(self.box(x0, y0, x1, y1), radius=r * self.k, fill=fill,
                                 outline=outline, width=self.w(width) if outline else 0,
                                 corners=corners)

    def ellipse(self, x0, y0, x1, y1, fill=None, outline=None, width=0):
        self.d.ellipse(self.box(x0, y0, x1, y1), fill=fill, outline=outline,
                       width=self.w(width) if outline else 0)

    def circle(self, x, y, r, **kw):
        self.ellipse(x - r, y - r, x + r, y + r, **kw)

    def chord(self, x0, y0, x1, y1, start, end, fill=None, outline=None, width=0):
        self.d.chord(self.box(x0, y0, x1, y1), start, end, fill=fill,
                     outline=outline, width=self.w(width) if outline else 0)

    def pieslice(self, x0, y0, x1, y1, start, end, fill=None):
        self.d.pieslice(self.box(x0, y0, x1, y1), start, end, fill=fill)

    def arc(self, x0, y0, x1, y1, start, end, fill, width):
        self.d.arc(self.box(x0, y0, x1, y1), start, end, fill=fill, width=self.w(width))

    def stroke(self, pts, fill, width):
        """Polyline with round joints and caps."""
        pts = list(pts)
        self.d.line([self.p(x, y) for x, y in pts], fill=fill, width=self.w(width), joint="curve")
        for x, y in (pts[0], pts[-1]):
            self.circle(x, y, width / 2, fill=fill)

    def line(self, pts, fill, width):
        self.d.line([self.p(x, y) for x, y in pts], fill=fill, width=self.w(width))

    def polygon(self, pts, fill=None, outline=None, width=1):
        self.d.polygon([self.p(x, y) for x, y in pts], fill=fill,
                       outline=outline, width=self.w(width) if outline else 1)

    def text(self, x, y, s, size, fill, anchor="mm", stroke=0, stroke_fill=None,
             max_w=None, mono=False):
        size = fit(s, size, max_w, mono) if max_w else size
        f = font(round(size * self.k), mono)
        self.d.text(self.p(x, y), s, font=f, fill=fill, anchor=anchor,
                    stroke_width=self.w(stroke) if stroke else 0, stroke_fill=stroke_fill)


def fit(s, size, max_w, mono=False):
    """Largest size <= ``size`` at which ``s`` is at most ``max_w`` px wide."""
    while size > 12 and font(size, mono).getlength(s) > max_w:
        size = int(size * 0.92)
    return size


def _star(cx, cy, r_out, r_in, n=12, rot=0.0):
    pts = []
    for i in range(n * 2):
        a = rot + math.pi * i / n
        r = r_out if i % 2 == 0 else r_in
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


# ---------------------------------------------------------------- background

@lru_cache(maxsize=16)
def _background(bg, fg):
    """2x scene background: vertical gradient into ``bg``, a soft spotlight and stars."""
    h, w = SCENE_H * SS, W * SS
    top = np.array(mix(bg, fg, 0.10), float)
    bot = np.array(bg, float)
    t = np.linspace(0, 1, h)[:, None] ** 1.4
    col = top + (bot - top) * t
    arr = np.repeat(col[:, None, :], w, axis=1)
    img = Image.fromarray(arr.round().astype(np.uint8), "RGB")
    pen = Pen(ImageDraw.Draw(img), SS)
    spot = mix(bg, fg, 0.07)
    pen.circle(CX, 520, 430, fill=spot)
    pen.circle(CX, 520, 360, fill=mix(bg, fg, 0.10))
    rng = random.Random(hashlib.md5(repr(bg).encode()).hexdigest())
    for _ in range(46):
        x, y = rng.uniform(20, W - 20), rng.uniform(20, SCENE_H - 120)
        r = rng.choice((2, 2, 3, 4))
        pen.circle(x, y, r, fill=mix(bg, fg, rng.uniform(0.25, 0.6)))
    return img


def _scene(fn):
    """Run a painter body on a 2x copy of the background, then downscale into img."""
    @wraps(fn)
    def painter(img, props, progress, pal):
        props = props if isinstance(props, dict) else {}
        try:
            p = float(progress)
        except (TypeError, ValueError):
            p = 0.0
        p = _clamp(p) if math.isfinite(p) else 0.0
        layer = _background(tuple(pal["bg"]), tuple(pal["fg"])).copy()
        pen = Pen(ImageDraw.Draw(layer), SS)
        fn(pen, props, p, pal, layer)
        img.paste(layer.reduce(SS), (0, 0))
    return painter


def _ink(pal):
    """Dark ink for text on light panels."""
    return mix(pal["bg"], (0, 0, 0), 0.35)


GOLD = (246, 196, 64)
GOLD_DARK = (176, 122, 30)
RED = (232, 72, 72)
GREEN = (74, 214, 120)
WHITE = (255, 255, 255)


# ---------------------------------------------------------------- scenes

@_scene
def shop(pen, props, p, pal, layer):
    """A little Earth shop; an item drops onto the counter and its price pops up.

    props: ``item`` (label on the box, default "SNACKS"), ``price`` (text on the
    price burst; when absent the burst shows "?", never an invented number).
    """
    item = _text(props.get("item"), "SNACKS", 10)
    price = _text(props.get("price"), UNKNOWN, 8)
    ink = _ink(pal)
    wall = mix(pal["fg"], pal["bg"], 0.12)
    pen.rect(0, 975, W, 1010, fill=mix(pal["bg"], (0, 0, 0), 0.3))           # pavement
    pen.rect(150, 300, 890, 980, fill=wall, outline=ink, width=6)
    pen.rrect(200, 150, 840, 270, 18, fill=pal["accent"], outline=ink, width=6)
    pen.text(CX, 212, "SHOP", 84, ink)
    # awning
    n, x0, x1, y0, y1 = 8, 130, 910, 270, 370
    sw = (x1 - x0) / n
    for i in range(n):
        c = pal["accent"] if i % 2 == 0 else WHITE
        pen.rect(x0 + i * sw, y0, x0 + (i + 1) * sw, y1, fill=c)
        pen.pieslice(x0 + i * sw, y1 - sw / 2, x0 + (i + 1) * sw, y1 + sw / 2, 0, 180, fill=c)
    pen.rect(x0, y0, x1, y0 + 10, fill=ink)
    # window + shelves
    glass = mix(pal["bg"], (0, 0, 0), 0.15)
    pen.rrect(210, 440, 830, 830, 10, fill=glass, outline=ink, width=8)
    for sy in (560, 690):
        pen.rect(225, sy, 815, sy + 12, fill=mix(wall, ink, 0.4))
    jar_colors = (RED, GOLD, (110, 170, 250), (240, 140, 200), GREEN)
    for i, jx in enumerate(range(255, 800, 68)):
        c = jar_colors[i % len(jar_colors)]
        pen.rrect(jx, 505, jx + 44, 560, 8, fill=c)
        pen.rect(jx + 6, 495, jx + 38, 507, fill=mix(c, WHITE, 0.5))
        if i % 2 == 0:
            pen.ellipse(jx - 2, 640, jx + 46, 690, fill=jar_colors[(i + 2) % 5])
    # counter
    pen.rect(185, 820, 855, 900, fill=(150, 96, 62), outline=ink, width=6)
    pen.rect(185, 820, 855, 838, fill=(190, 130, 84))
    # item drops in with a bounce
    dy = -(1 - ease_back(_seg(p, 0.0, 0.45))) * 330
    bx0, by0, bx1, by1 = 400, 690 + dy, 640, 822 + dy
    pen.rrect(bx0, by0, bx1, by1, 12, fill=RED, outline=ink, width=6)
    pen.rect(bx0, by0 + 40, bx1, by0 + 92, fill=WHITE)
    pen.text((bx0 + bx1) / 2, by0 + 66, item, 40, ink, max_w=220)
    # price burst pops
    s = ease_back(_seg(p, 0.4, 0.75))
    if s > 0.01:
        r = 92 * s
        pen.polygon(_star(745, 640, r, r * 0.8, 14, p * 0.6), fill=GOLD, outline=ink, width=5)
        pen.text(745, 640, price, max(8, 58 * s), ink, max_w=max(10, 140 * s))


@_scene
def price_tag(pen, props, p, pal, layer):
    """A giant price tag whose number climbs (or falls) from ``from`` to ``to``.

    props: ``from`` (start price), ``to`` (end price), ``currency`` (prefix,
    default "$"). With both, the old price is struck out while the new one
    counts to it and an arrow shows the direction. With only one, that price
    is shown still; with neither, the tag reads "$?" (no invented numbers).
    """
    a = _num(props.get("from"), None)
    b = _num(props.get("to"), None)
    both = a is not None and b is not None
    if not both:
        a = b = a if a is not None else b
    dec = max(_decimals(props.get("from")), _decimals(props.get("to")))
    if a is not None and dec == 0 and (a != int(a) or b != int(b)):
        dec = 2
    cur = props.get("currency") if isinstance(props.get("currency"), str) else "$"
    cur = cur[:3]
    ink = _ink(pal)
    bob = math.sin(p * math.pi * 2) * 8
    # string
    pen.stroke([(285, 555 + bob), (240, 360), (300, 140), (360, 70)], mix(pal["fg"], ink, 0.3), 7)
    tag = [(340, 300 + bob), (870, 300 + bob), (870, 810 + bob), (340, 810 + bob), (170, 555 + bob)]
    pen.polygon([(x + 12, y + 14) for x, y in tag], fill=mix(pal["bg"], (0, 0, 0), 0.4))
    pen.polygon(tag, fill=pal["fg"], outline=ink, width=8)
    pen.polygon([(352, 318 + bob), (852, 318 + bob), (852, 792 + bob), (352, 792 + bob),
                 (196, 555 + bob)], outline=mix(pal["fg"], ink, 0.25), width=3)
    pen.circle(285, 555 + bob, 30, fill=pal["bg"], outline=ink, width=6)
    t = ease_in_out(_seg(p, 0.1, 0.85)) if both else 0.0
    rising = not both or b >= a
    if both:
        # old price, struck through progressively
        old = f"{cur}{_fmt(a, dec)}"
        pen.text(610, 400 + bob, old, 64, mix(pal["fg"], ink, 0.55), max_w=380)
        ow = min(380, font(fit(old, 64, 380)).getlength(old))
        sx = ease_out(_seg(p, 0.0, 0.3))
        if sx > 0.01:
            pen.stroke([(610 - ow / 2 - 10, 402 + bob),
                        (610 - ow / 2 - 10 + (ow + 20) * sx, 402 + bob)], RED, 8)
    col = mix(ink, (200, 40, 40) if rising else (30, 140, 70), t)
    if both:
        pop = 1 + 0.06 * math.sin(_seg(p, 0.1, 0.85) * math.pi * 6) * (1 - t)
    else:   # a single (or unknown) price pops onto the tag
        pop = ease_back(_seg(p, 0.0, 0.3))
    shown = UNKNOWN if a is None else _fmt(a + (b - a) * t, dec)
    if pop > 0.01:
        pen.text(610, 600 + bob, f"{cur}{shown}", max(8, 190 * pop), col,
                 max_w=max(10, 470 * pop))
    # direction arrow
    if both and a != b:
        ar = ease_back(_seg(p, 0.55, 0.9))
        if ar > 0.01:
            ax, ay, s = 820, 250 + bob, 70 * ar
            c = RED if rising else GREEN
            d = -1 if rising else 1
            pts = [(ax, ay + d * s), (ax + s * 0.8, ay), (ax + s * 0.32, ay),
                   (ax + s * 0.32, ay - d * s * 0.9), (ax - s * 0.32, ay - d * s * 0.9),
                   (ax - s * 0.32, ay), (ax - s * 0.8, ay)]
            pen.polygon(pts, fill=c, outline=ink, width=5)


@_scene
def vault(pen, props, p, pal, layer):
    """A bank vault: the wheel spins, then the round door swings open on gold.

    props: ``label`` (plate text, default "VAULT"), ``open`` (bool, default
    True; False keeps the door shut while the wheel turns).
    """
    label = _text(props.get("label"), "VAULT", 12)
    opens = props.get("open", True) is not False
    ink = (34, 36, 44)
    steel = (172, 178, 190)
    steel_d = (120, 126, 140)
    cx, cy, r = CX, 520, 315
    pen.rrect(130, 120, 910, 985, 30, fill=(86, 92, 106), outline=ink, width=8)
    for x, y in ((165, 155), (875, 155), (165, 950), (875, 950)):
        pen.circle(x, y, 12, fill=steel_d, outline=ink, width=3)
    pen.circle(cx, cy, r + 22, fill=(58, 62, 74), outline=ink, width=6)
    # interior: dark room, gold bars, coins
    pen.circle(cx, cy, r, fill=(44, 36, 30))
    rows = [(4, 700), (3, 640), (2, 580), (1, 520)]
    for n, y in rows:
        bw = 92
        x0 = cx - n * bw / 2
        for i in range(n):
            bx = x0 + i * bw
            pen.polygon([(bx + 4, y + 58), (bx + bw - 4, y + 58), (bx + bw - 16, y + 2), (bx + 16, y + 2)],
                        fill=GOLD, outline=GOLD_DARK, width=4)
            pen.rect(bx + 22, y + 10, bx + bw - 22, y + 18, fill=(255, 232, 140))
    for x, y in ((400, 778), (640, 778), (365, 728), (675, 728)):
        pen.ellipse(x - 30, y - 14, x + 30, y + 14, fill=GOLD, outline=GOLD_DARK, width=3)
    for x, y, s in ((440, 450, 20), (610, 420, 14), (530, 360, 11)):
        pen.polygon(_star(x, y, s, s * 0.3, 4), fill=(255, 245, 200))
    # door: squashes toward the right-hand hinge as it opens
    o = ease_in_out(_seg(p, 0.45, 1.0)) if opens else 0.0
    wf = 1 - 0.86 * o
    hinge = cx + r

    def tx(x):
        return hinge - (hinge - x) * wf

    shade = mix(steel, (60, 64, 76), o * 0.6)
    pen.ellipse(tx(cx - r), cy - r, hinge, cy + r, fill=shade, outline=ink, width=7)
    pen.ellipse(tx(cx - r + 55), cy - r + 55, tx(cx + r - 55), cy + r - 55,
                outline=mix(shade, ink, 0.4), width=6)
    for i in range(12):
        a = math.pi * 2 * i / 12
        bx, by = cx + (r - 28) * math.cos(a), cy + (r - 28) * math.sin(a)
        pen.ellipse(tx(bx - 11), by - 11, tx(bx + 11), by + 11, fill=steel_d, outline=ink, width=3)
    spin = ease_in_out(_seg(p, 0.0, 0.5)) * math.pi * 1.5 + 0.3
    wr = 105
    for i in range(3):
        a = spin + math.pi * i / 3
        x0, y0 = cx + wr * math.cos(a), cy + wr * math.sin(a)
        x1, y1 = cx - wr * math.cos(a), cy - wr * math.sin(a)
        pen.stroke([(tx(x0), y0), (tx(x1), y1)], ink, 20)
        pen.stroke([(tx(x0), y0), (tx(x1), y1)], steel_d, 11)
    pen.ellipse(tx(cx - wr), cy - wr, tx(cx + wr), cy + wr, outline=ink, width=16)
    pen.ellipse(tx(cx - wr), cy - wr, tx(cx + wr), cy + wr, outline=steel_d, width=8)
    pen.ellipse(tx(cx - 34), cy - 34, tx(cx + 34), cy + 34, fill=steel_d, outline=ink, width=5)
    for hy in (cy - 190, cy + 150):
        pen.rrect(hinge - 14, hy, hinge + 30, hy + 44, 6, fill=steel_d, outline=ink, width=4)
    # plate
    pen.rrect(370, 878, 670, 950, 12, fill=GOLD, outline=GOLD_DARK, width=5)
    pen.text(520, 914, label, 46, (70, 46, 10), max_w=270)


def _series(trend):
    rng = random.Random(7 if trend == "up" else 11)
    vals, v = [], 0.0
    drift = 0.55 if trend == "up" else -0.55
    for _ in range(26):
        vals.append(v)
        v += drift + rng.uniform(-1.6, 1.6)
    return vals


@_scene
def stock_chart(pen, props, p, pal, layer):
    """A trading screen whose price line draws itself left to right.

    props: ``trend`` ("up" or "down", default "up"), ``label`` (headline such
    as "+7%"; default "UP"/"DOWN", never an invented percentage).
    """
    trend = props.get("trend") if props.get("trend") in ("up", "down") else "up"
    ink = _ink(pal)
    panel = mix(pal["bg"], (0, 0, 0), 0.4)
    gx0, gy0, gx1, gy1 = 175, 300, 865, 870
    pen.rrect(110, 170, 910, 940, 28, fill=panel, outline=mix(pal["fg"], pal["bg"], 0.6), width=5)
    grid = mix(panel, pal["fg"], 0.12)
    for i in range(6):
        y = gy0 + (gy1 - gy0) * i / 5
        pen.line([(gx0, y), (gx1, y)], grid, 2)
    for i in range(7):
        x = gx0 + (gx1 - gx0) * i / 6
        pen.line([(x, gy0), (x, gy1)], grid, 2)
    vals = _series(trend)
    lo, hi = min(vals), max(vals)
    pts = [(gx0 + (gx1 - gx0) * i / (len(vals) - 1),
            gy1 - 30 - (gy1 - gy0 - 60) * (v - lo) / (hi - lo)) for i, v in enumerate(vals)]
    t = ease_in_out(_seg(p, 0.0, 0.9)) * (len(pts) - 1)
    k = int(t)
    shown = pts[:k + 1]
    if k < len(pts) - 1:
        f = t - k
        (x0, y0), (x1, y1) = pts[k], pts[k + 1]
        shown.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
    col = GREEN if trend == "up" else RED
    if len(shown) > 1:
        pen.polygon(shown + [(shown[-1][0], gy1), (shown[0][0], gy1)], fill=mix(panel, col, 0.25))
        pen.stroke(shown, col, 10)
    ex, ey = shown[-1]
    pen.circle(ex, ey, 22 + 4 * math.sin(p * 20), fill=mix(panel, col, 0.45))
    pen.circle(ex, ey, 12, fill=WHITE, outline=col, width=4)
    pen.line([(gx0, gy1), (gx1, gy1)], mix(panel, pal["fg"], 0.4), 4)
    label = _text(props.get("label"), trend.upper(), 8)
    pen.text(180, 236, label, 64, col, anchor="lm", max_w=420)
    # mini arrow icon
    ax, ay = 820, 236
    if trend == "up":
        pen.polygon([(ax, ay - 32), (ax + 30, ay + 12), (ax - 30, ay + 12)], fill=col)
    else:
        pen.polygon([(ax, ay + 32), (ax + 30, ay - 12), (ax - 30, ay - 12)], fill=col)
    pen.rect(gx0 - 2, gy0 - 40, gx0 + 120, gy0 - 36, fill=mix(panel, pal["fg"], 0.2))


@lru_cache(maxsize=16)
def _card(accent, ink):
    """2x credit-card face (RGBA) with diagonal shine, cached per palette."""
    cw, ch = 700 * SS, 440 * SS
    face = Image.new("RGB", (cw, ch), accent)
    pen = Pen(ImageDraw.Draw(face), SS)
    pen.polygon([(380, 0), (560, 0), (300, 440), (120, 440)], fill=mix(accent, WHITE, 0.18))
    pen.polygon([(600, 0), (660, 0), (400, 440), (340, 440)], fill=mix(accent, WHITE, 0.10))
    pen.rect(0, 340, 700, 440, fill=mix(accent, (0, 0, 0), 0.12))
    pen.rrect(70, 110, 170, 185, 12, fill=GOLD, outline=GOLD_DARK, width=3)
    for y in (135, 160):
        pen.line([(70, y), (170, y)], GOLD_DARK, 3)
    pen.line([(120, 110), (120, 185)], GOLD_DARK, 3)
    for i, rr in enumerate((18, 32, 46)):
        pen.arc(210 - rr, 148 - rr, 210 + rr, 148 + rr, -50, 50, WHITE, 5)
    pen.text(60, 260, "**** **** **** ****", 46, WHITE, anchor="lm", mono=True)
    pen.text(60, 390, "ZORB Z. ALIEN", 32, WHITE, anchor="lm")
    pen.circle(580, 385, 36, fill=(235, 60, 60))
    pen.circle(628, 385, 36, fill=(250, 170, 40))
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=40 * SS, fill=255)
    out = face.convert("RGBA")
    out.putalpha(mask)
    return out


@_scene
def credit_card(pen, props, p, pal, layer):
    """A credit card slides in, an APR badge pops and the balance counts up.

    props: ``apr`` (badge text; numbers get a "%" added; "?" when absent),
    ``balance`` (final balance; "$?" when absent), ``currency`` (default "$").
    """
    apr_v = props.get("apr")
    if _num(apr_v, None) is not None and not isinstance(apr_v, str):
        apr = f"{apr_v:g}%"[:6]
    else:
        apr = _text(apr_v, UNKNOWN, 6)
    bal = _num(props.get("balance"), None)
    dec = _decimals(props.get("balance"))
    cur = props.get("currency") if isinstance(props.get("currency"), str) else "$"
    ink = _ink(pal)
    slide = ease_back(_seg(p, 0.0, 0.35))
    x0 = 170 - (1 - slide) * 900
    y0 = 230
    pen.rrect(x0 + 16, y0 + 22, x0 + 716, y0 + 462, 40, fill=mix(pal["bg"], (0, 0, 0), 0.45))
    card = _card(tuple(pal["accent"]), ink)
    layer.paste(card, (round(x0 * SS), round(y0 * SS)), card)
    pen.rrect(x0, y0, x0 + 700, y0 + 440, 40, outline=mix(pal["accent"], ink, 0.5), width=4)
    # balance panel
    pen.rrect(190, 740, 850, 960, 30, fill=pal["fg"], outline=ink, width=6)
    pen.text(CX, 790, "BALANCE", 40, mix(pal["fg"], ink, 0.6))
    shown = UNKNOWN if bal is None else _fmt(bal * ease_out(_seg(p, 0.3, 1.0)), dec)
    pen.text(CX, 880, f"{cur}{shown}", 110, mix(ink, (200, 40, 40), _seg(p, 0.3, 1.0)),
             max_w=600)
    # APR badge
    s = ease_back(_seg(p, 0.45, 0.75))
    if s > 0.01:
        bx, by, r = 800, 230, 95 * s
        pen.polygon(_star(bx, by, r, r * 0.84, 16, p), fill=RED, outline=ink, width=5)
        pen.text(bx, by - 14 * s, apr, max(8, 46 * s), WHITE, max_w=max(10, 140 * s))
        pen.text(bx, by + 30 * s, "APR", max(8, 30 * s), WHITE)


_CONTINENTS = [  # (x, y, rx, ry) in a 1200-wide wrapping strip, planet-local
    (80, 160, 90, 60), (130, 230, 70, 90), (170, 330, 50, 70),
    (420, 140, 120, 70), (470, 230, 70, 120), (560, 190, 80, 60),
    (760, 300, 110, 80), (820, 200, 70, 60), (720, 420, 60, 50),
    (1000, 120, 90, 50), (1050, 380, 100, 70), (980, 480, 60, 40),
]


@lru_cache(maxsize=4)
def _planet_masks(d):
    size = d * SS
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    shade = Image.new("L", (size, size), 0)       # soft terminator on the lower right
    sd = ImageDraw.Draw(shade)
    for i in range(10):
        off = size * (0.18 + i * 0.035)
        sd.ellipse([-size * 0.2 + off, -size * 0.2 + off, size * 1.4, size * 1.4], fill=int(9 + i * 9))
    return mask, shade


def _ufo(pen, x, y, s):
    pen.ellipse(x - 30 * s, y - 40 * s, x + 30 * s, y + 5 * s, fill=(170, 235, 255), outline=(30, 40, 60), width=4)
    pen.ellipse(x - 60 * s, y - 14 * s, x + 60 * s, y + 18 * s, fill=(190, 196, 210), outline=(30, 40, 60), width=4)
    for i in range(-2, 3):
        pen.circle(x + i * 22 * s, y + 3 * s, 5 * s, fill=(255, 220, 90))


@_scene
def planet(pen, props, p, pal, layer):
    """Planet Earth slowly rotating while Zorb's saucer orbits it.

    props: ``label`` (text under the planet, default "EARTH").
    """
    label = _text(props.get("label"), "EARTH", 12)
    cx, cy, r = CX, 500, 300
    pen.circle(cx, cy, r + 34, fill=mix(pal["bg"], (120, 190, 255), 0.12))
    pen.circle(cx, cy, r + 16, fill=mix(pal["bg"], (120, 190, 255), 0.25))
    ang = p * math.pi * 2 * 0.75 + 2.6
    ux, uy = cx + 370 * math.cos(ang), cy + 120 * math.sin(ang) - 40
    ring = mix(pal["bg"], pal["fg"], 0.35)
    pen.arc(cx - 370, cy - 160, cx + 370, cy + 80, 180, 360, ring, 4)
    behind = math.sin(ang) < 0
    if behind:
        _ufo(pen, ux, uy, 0.8)
    # planet surface on its own layer, masked to a circle
    d = 2 * r
    surf = Image.new("RGB", (d * SS, d * SS), (52, 120, 214))
    sp = Pen(ImageDraw.Draw(surf), SS)
    shift = -p * 260
    sp.ellipse(110, 70, 230, 150, fill=(98, 158, 230))           # ocean glint
    for x, y, rx, ry in _CONTINENTS:
        for wrap in (0, 1200, -1200):
            xx = (x + shift) % 1200 - 300 + wrap
            if -rx < xx < d + rx:
                sp.ellipse(xx - rx, y - ry, xx + rx, y + ry, fill=(86, 176, 92))
                sp.ellipse(xx - rx * 0.5, y - ry * 0.6, xx + rx * 0.3, y + ry * 0.1, fill=(120, 196, 104))
    for x, y in ((200, 90), (560, 300), (900, 470), (350, 520), (1080, 220)):
        xx = (x + shift * 1.6) % 1200 - 300
        sp.ellipse(xx - 70, y - 16, xx + 70, y + 16, fill=(236, 244, 255))
    mask, shade = _planet_masks(d)
    surf.paste((10, 10, 40), (0, 0), shade)
    layer.paste(surf, (round((cx - r) * SS), round((cy - r) * SS)), mask)
    pen.circle(cx, cy, r, outline=mix(pal["bg"], (0, 0, 0), 0.3), width=4)
    pen.arc(cx - 370, cy - 160, cx + 370, cy + 80, 0, 180, ring, 4)
    if not behind:
        _ufo(pen, ux, uy, 1.0)
    pen.text(CX, 925, label, 76, pal["text"], stroke=4, stroke_fill=mix(pal["bg"], (0, 0, 0), 0.5),
             max_w=600)


_MONTHS = ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
           "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER")


@_scene
def calendar(pen, props, p, pal, layer):
    """A wall calendar: days get crossed off and pages flip as time passes.

    props: ``years`` (int; pages show "YEAR 1".."YEAR n" instead of months,
    up to 10 flips), ``start`` (first month name or 1-12, default January).
    """
    years = _num(props.get("years"), None)
    if years is not None and years >= 1:
        n = int(years)
        steps = max(1, min(n, 10))
        labels = [f"YEAR {1 + round(i * (n - 1) / max(1, steps - 1))}" for i in range(steps)]
    else:
        st = props.get("start")
        si = 0
        if isinstance(st, str) and st.strip()[:3].upper() in [m[:3] for m in _MONTHS]:
            si = [m[:3] for m in _MONTHS].index(st.strip()[:3].upper())
        elif isinstance(st, int) and not isinstance(st, bool) and 1 <= st <= 12:
            si = st - 1
        steps = 6
        labels = [_MONTHS[(si + i) % 12] for i in range(steps)]
    ink = _ink(pal)
    paper = (250, 248, 240)
    head = RED
    x0, y0, x1, y1 = 190, 190, 850, 960
    hh = 190
    t = p * steps
    idx = min(steps - 1, int(t))
    frac = t - idx if idx < steps - 1 or t < steps else 1.0
    flip = _seg(frac, 0.7, 1.0) if idx < steps - 1 else 0.0

    def page(i, crossed):
        pen.rrect(x0, y0, x1, y1, 24, fill=paper, outline=ink, width=6)
        pen.rrect(x0, y0, x1, y0 + hh, 24, fill=head, outline=ink, width=6, corners=(True, True, False, False))
        pen.text((x0 + x1) / 2, y0 + hh / 2 + 10, labels[i], 96, WHITE, max_w=560)
        cw, chh = (x1 - x0 - 80) / 7, (y1 - y0 - hh - 80) / 5
        for k in range(35):
            gx = x0 + 40 + (k % 7) * cw
            gy = y0 + hh + 40 + (k // 7) * chh
            pen.rrect(gx + 6, gy + 6, gx + cw - 6, gy + chh - 6, 8, fill=(232, 228, 216))
            if k < 31:
                pen.text(gx + cw / 2, gy + chh / 2, str(k + 1), 30, (130, 124, 112))
            if k < min(crossed, 31):
                m = 18
                pen.stroke([(gx + m, gy + m), (gx + cw - m, gy + chh - m)], RED, 7)
                pen.stroke([(gx + cw - m, gy + m), (gx + m, gy + chh - m)], RED, 7)

    # stack edges under the pad
    for k in (2, 1):
        pen.rrect(x0 + 6 * k, y0 + 10 * k, x1 + 6 * k, y1 + 10 * k, 24,
                  fill=mix(paper, ink, 0.12 * k), outline=ink, width=4)
    if flip > 0:
        page(idx + 1, 0)
        # departing page lifts upward like a flip-pad sheet
        f = ease_in_out(flip)
        by = y1 - (y1 - y0) * f
        spread = 60 * math.sin(f * math.pi)
        hy = y0 + min(hh, by - y0)
        pen.polygon([(x0, y0), (x1, y0), (x1 + spread, by), (x0 - spread, by)],
                    fill=mix(paper, ink, 0.15 * f), outline=ink, width=5)
        if hy > y0 + 4:
            sh = (hy - y0) / (by - y0 + 1e-6) * spread
            pen.polygon([(x0, y0), (x1, y0), (x1 + sh, hy), (x0 - sh, hy)], fill=head, outline=ink, width=5)
    else:
        page(idx, int(_seg(frac, 0.0, 0.7) * 35) if idx < steps - 1 else int(frac * 35))
    # binder rings
    for i in range(6):
        rx = x0 + 70 + i * (x1 - x0 - 140) / 5
        pen.circle(rx, y0 + 26, 13, fill=mix(pal["bg"], (0, 0, 0), 0.3))
        pen.stroke([(rx, y0 + 26), (rx, y0 - 30)], (200, 204, 214), 12)
        pen.arc(rx - 16, y0 - 46, rx + 16, y0 - 14, 180, 360, (200, 204, 214), 9)


def _bill(pen, x, y, ink):
    """One bill seen slightly from above; (x, y) = bottom-centre of its front face."""
    th, hw = 26, 115
    pen.polygon([(x - hw, y - th), (x - hw + 28, y - th - 20), (x + hw + 28, y - th - 20), (x + hw, y - th)],
                fill=(122, 204, 128), outline=(34, 94, 50), width=3)
    pen.rect(x - hw, y - th, x + hw, y, fill=(64, 152, 84), outline=(34, 94, 50), width=3)
    pen.rect(x - 22, y - th, x + 22, y, fill=(236, 226, 176))
    pen.polygon([(x - 22, y - th), (x + 22, y - th), (x + 50, y - th - 20), (x + 6, y - th - 20)],
                fill=(246, 238, 196))


@_scene
def money_stack(pen, props, p, pal, layer):
    """Stacks of cash grow while the total counts up above them.

    props: ``amount`` (final total; no total is shown when absent),
    ``currency`` (default "$").
    """
    amt = _num(props.get("amount"), None)
    dec = _decimals(props.get("amount"))
    cur = props.get("currency") if isinstance(props.get("currency"), str) else "$"
    ink = _ink(pal)
    g = ease_out(_seg(p, 0.0, 0.85))
    per, stacks = 11, (300, 540, 780)
    total = 1 + round(g * (per * 3 - 1))
    counts = [0, 0, 0]
    order = (1, 0, 2)
    left = total
    for layer_i in range(per):
        for s in order:
            if left > 0:
                counts[s] += 1
                left -= 1
    base = 930
    pen.ellipse(130, base - 34, 920, base + 40, fill=mix(pal["bg"], (0, 0, 0), 0.35))
    for s in (0, 2, 1):     # back stacks first, centre stack in front
        x = stacks[s] - 20
        for i in range(counts[s]):
            _bill(pen, x, base - i * 27, ink)
    for x, y in ((170, 950), (220, 965), (860, 945), (900, 960)):
        pen.ellipse(x - 34, y - 14, x + 34, y + 14, fill=GOLD, outline=GOLD_DARK, width=4)
        pen.ellipse(x - 34, y - 22, x + 34, y + 6, fill=(255, 216, 96), outline=GOLD_DARK, width=4)
    if amt is not None:
        v = amt * ease_out(_seg(p, 0.0, 0.9))
        pen.text(CX, 250, f"{cur}{_fmt(v, dec)}", 150, GOLD, stroke=6,
                 stroke_fill=mix(pal["bg"], (0, 0, 0), 0.5), max_w=700)
    tw = 0.5 + 0.5 * math.sin(p * math.pi * 6)
    for x, y, sz in ((190, 420, 22), (850, 470, 18), (800, 120, 14), (240, 130, 16)):
        sz *= 0.6 + 0.4 * tw
        pen.polygon(_star(x, y, sz, sz * 0.3, 4), fill=(255, 240, 170))


SCENE_PAINTERS = {
    "shop": shop,
    "price_tag": price_tag,
    "vault": vault,
    "stock_chart": stock_chart,
    "credit_card": credit_card,
    "planet": planet,
    "calendar": calendar,
    "money_stack": money_stack,
}
assert set(SCENE_PAINTERS) == set(SCENES)
