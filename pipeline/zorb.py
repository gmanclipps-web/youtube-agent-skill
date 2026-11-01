"""Draw Zorb, the one-eyed green alien, with ImageDraw primitives only.

Zorb is rendered as an RGBA sprite at 2x resolution, downscaled with LANCZOS
for clean edges, and pasted onto the frame. Sprites are cached per
(expression, quantised mouth, blink, scale), so a full video costs only a
few hundred unique sprite draws.

At scale 1.0 the sprite spans 480x480 px around ``center``; the visible art
(antenna glow to shadow) stays within y -228..+215 and x -235..+235 of it, so
centred at (540, 1660) Zorb fits inside y 1430-1890 and x < 950.
"""
import math
from functools import lru_cache

from PIL import Image, ImageDraw

from pipeline.script_schema import EXPRESSIONS
from pipeline.scenes import Pen

HALF = 240          # sprite half-size in 1x units
SS = 2              # supersampling factor

BODY = (118, 204, 92)
BODY_LIGHT = (168, 232, 140)
BELLY = (150, 222, 118)
SPOT = (92, 172, 74)
LID = (102, 186, 80)
LINE = (30, 78, 42)
IRIS = (92, 58, 176)
PUPIL = (18, 12, 30)
WHITE = (255, 255, 255)
MOUTH = (78, 18, 42)
TONGUE = (238, 110, 130)
BULB = (255, 120, 175)
BULB_AHA = (255, 228, 80)
GLOW = (255, 238, 140, 175)
BLUSH = (240, 150, 150)
SWEAT = (140, 210, 255)


def _bezier(p0, p1, p2, n=12):
    out = []
    for i in range(n + 1):
        t = i / n
        a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
        out.append((a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]))
    return out


# Per-expression pose table.
_POSE = {
    #            antenna ctrl, antenna tip, eye radii, iris offset, iris r
    "neutral": dict(ctrl=(4, -170), tip=(16, -192), eye=(82, 76), look=(0, 4), iris=38),
    "confused": dict(ctrl=(-30, -165), tip=(-8, -192), eye=(82, 76), look=(-22, -18), iris=33),
    "shocked": dict(ctrl=(0, -170), tip=(0, -197), eye=(92, 88), look=(0, 0), iris=20),
    "aha": dict(ctrl=(0, -168), tip=(6, -192), eye=(84, 80), look=(8, -12), iris=44),
    "smug": dict(ctrl=(20, -168), tip=(38, -184), eye=(82, 76), look=(26, 8), iris=34),
}
EYE_C = (0, -35)
MOUTH_C = (0, 95)
SHOULDER = 128


def _arms(pen, expression):
    """Arms are drawn before the body so the shoulders tuck behind it."""
    w = 24
    if expression == "neutral":
        arms = [[(-SHOULDER, 35), (-172, 100)], [(SHOULDER, 35), (172, 100)]]
        hands = [(-174, 110), (174, 110)]
    elif expression == "confused":   # shrug, palms out
        arms = [[(-SHOULDER, 40), (-190, 30), (-208, 2)], [(SHOULDER, 40), (190, 30), (208, 2)]]
        hands = [(-210, -6), (210, -6)]
    elif expression == "shocked":    # hands thrown up
        arms = [[(-SHOULDER, 10), (-182, -50), (-196, -112)], [(SHOULDER, 10), (182, -50), (196, -112)]]
        hands = [(-198, -122), (198, -122)]
    elif expression == "aha":        # one finger raised
        arms = [[(-SHOULDER, 35), (-172, 100)], [(SHOULDER, 10), (190, -40), (200, -105)]]
        hands = [(-174, 110), (201, -114)]
    else:                            # smug: hands on hips
        arms = [[(-SHOULDER, 20), (-205, 60), (-140, 112)], [(SHOULDER, 20), (205, 60), (140, 112)]]
        hands = []
    for pts in arms:
        pen.stroke(pts, LINE, w + 10)
        pen.stroke(pts, BODY, w)
    for x, y in hands:
        pen.circle(x, y, 19, fill=BODY, outline=LINE, width=5)
    if expression == "aha":  # pointing finger
        hx, hy = hands[1]
        pen.stroke([(hx, hy - 8), (hx + 2, hy - 40)], LINE, 18)
        pen.stroke([(hx, hy - 8), (hx + 2, hy - 40)], BODY, 9)


def _antenna(pen, expression, pose):
    base = (0, -128)
    pts = _bezier(base, pose["ctrl"], pose["tip"])
    pen.stroke(pts, LINE, 13)
    pen.stroke(pts, BODY, 6)
    tx, ty = pose["tip"]
    if expression == "aha":
        pen.circle(tx, ty, 30, fill=GLOW)
        for i in range(8):
            a = math.pi * 2 * i / 8 + 0.2
            if math.sin(a) > 0.55:      # skip rays pointing into the head
                continue
            r0, r1 = 22, 34
            pen.stroke([(tx + r0 * math.cos(a), ty - r0 * math.sin(a)),
                        (tx + r1 * math.cos(a), ty - r1 * math.sin(a))], (255, 205, 40), 5)
        pen.circle(tx, ty, 16, fill=BULB_AHA, outline=LINE, width=4)
        pen.circle(tx - 5, ty - 5, 5, fill=WHITE)
    else:
        pen.circle(tx, ty, 15, fill=BULB, outline=LINE, width=4)
        pen.circle(tx - 5, ty - 5, 4, fill=WHITE)


def _body(pen):
    pen.ellipse(-130, 188, 130, 212, fill=(0, 0, 0, 60))                 # ground shadow
    for x0 in (-98, 28):
        pen.ellipse(x0, 158, x0 + 70, 200, fill=BODY, outline=LINE, width=6)  # feet
    pen.ellipse(-150, -140, 150, 175, fill=BODY, outline=LINE, width=7)
    pen.ellipse(-82, 48, 82, 158, fill=BELLY)
    pen.ellipse(-112, -112, -52, -70, fill=BODY_LIGHT)                    # highlight
    for x, y, r in ((-122, 20, 9), (-108, 52, 6), (118, 28, 8), (124, -10, 5), (104, 60, 6)):
        pen.circle(x, y, r, fill=SPOT)


def _eye(pen, expression, pose, blink):
    cx, cy = EYE_C
    rx, ry = pose["eye"]
    box = (cx - rx, cy - ry, cx + rx, cy + ry)
    if blink:
        pen.ellipse(*box, fill=LID, outline=LINE, width=6)
        pen.arc(cx - rx * 0.8, cy - ry * 0.7, cx + rx * 0.8, cy + ry * 0.45,
                15, 165, LINE, 8)
        return
    pen.ellipse(*box, fill=WHITE, outline=LINE, width=6)
    lx, ly = pose["look"]
    ir = pose["iris"]
    ix, iy = cx + lx, cy + ly
    pen.circle(ix, iy, ir, fill=IRIS)
    pen.circle(ix, iy, ir * 0.55, fill=PUPIL)
    pen.circle(ix - ir * 0.38, iy - ir * 0.42, max(5, ir * 0.28), fill=WHITE)
    if expression == "aha":
        sx, sy, s = ix + ir * 0.35, iy + ir * 0.3, 9
        pen.polygon([(sx, sy - s), (sx + 3, sy - 3), (sx + s, sy), (sx + 3, sy + 3),
                     (sx, sy + s), (sx - 3, sy + 3), (sx - s, sy), (sx - 3, sy - 3)], fill=WHITE)
    if expression == "smug":     # heavy upper lid
        pen.chord(*box, 180, 360, fill=LID)
        pen.stroke([(cx - rx + 2, cy), (cx + rx - 2, cy)], LINE, 8)
        pen.ellipse(*box, outline=LINE, width=6)


def _brow(pen, expression):
    pts = {
        "neutral": [(-55, -121), (0, -130), (55, -121)],
        "confused": [(-58, -104), (-10, -116), (20, -126), (58, -130)],
        "shocked": [(-62, -128), (0, -150), (62, -128)],
        "aha": [(-56, -124), (0, -145), (56, -124)],
        "smug": [(-60, -60), (0, -70), (60, -84)],
    }[expression]
    pen.stroke(pts, LINE, 13)


def _mouth(pen, expression, m):
    cx, cy = MOUTH_C
    if expression == "shocked":
        w, h = 22 + 10 * m, 26 + 26 * m
        pen.ellipse(cx - w, cy + 4 - h, cx + w, cy + 4 + h, fill=MOUTH, outline=LINE, width=6)
        pen.ellipse(cx - w * 0.55, cy + 4 + h * 0.25, cx + w * 0.55, cy + 4 + h * 0.9, fill=TONGUE)
        return
    if expression == "aha":
        w, h = 58, 22 + 40 * m
        pen.chord(cx - w, cy - h, cx + w, cy + h, 0, 180, fill=MOUTH, outline=LINE, width=6)
        pen.chord(cx - w * 0.82, cy - 4, cx + w * 0.82, cy + 16, 0, 180, fill=WHITE)  # teeth
        pen.ellipse(cx - w * 0.45, cy + h * 0.5, cx + w * 0.45, cy + h * 0.92, fill=TONGUE)
        pen.stroke([(cx - w, cy), (cx + w, cy)], LINE, 7)
        return
    if expression == "neutral":
        ox, w = 0, 40
    elif expression == "confused":
        ox, w = -10, 30
    else:  # smug
        ox, w = 16, 28
    if m < 0.08:
        if expression == "neutral":
            pen.arc(cx - 38, cy - 22, cx + 38, cy + 16, 25, 155, LINE, 8)
        elif expression == "confused":
            pen.stroke([(cx - 40, cy + 4), (cx - 22, cy - 6), (cx - 4, cy + 6),
                        (cx + 14, cy - 6), (cx + 30, cy + 2)], LINE, 8)
        else:
            pen.stroke([(cx - 34, cy + 2), (cx, cy + 8), (cx + 30, cy - 2), (cx + 44, cy - 16)], LINE, 8)
        return
    h = 6 + 46 * m
    x = cx + ox
    if expression == "neutral":
        pen.chord(x - w, cy - h * 0.4, x + w, cy + h, 0, 180, fill=MOUTH, outline=LINE, width=6)
        pen.stroke([(x - w, cy + h * 0.3), (x + w, cy + h * 0.3)], LINE, 6)
        if h > 16:
            pen.ellipse(x - w * 0.5, cy + h * 0.55, x + w * 0.5, cy + h * 0.95, fill=TONGUE)
    else:
        pen.ellipse(x - w, cy - h * 0.45, x + w, cy + h * 0.55, fill=MOUTH, outline=LINE, width=6)
        if h > 16:
            pen.ellipse(x - w * 0.5, cy + h * 0.1, x + w * 0.5, cy + h * 0.5, fill=TONGUE)


def _extras(pen, expression):
    if expression == "confused":
        pen.text(198, -150, "?", 78, WHITE, stroke=5, stroke_fill=LINE)
    elif expression == "shocked":
        pen.polygon([(150, -146), (138, -120), (142, -108), (150, -104), (158, -108),
                     (162, -120)], fill=SWEAT, outline=LINE, width=3)
    elif expression == "aha":
        for x in (-96, 96):
            pen.ellipse(x - 22, 46, x + 22, 66, fill=BLUSH)
    elif expression == "smug":
        pen.ellipse(70, 48, 108, 64, fill=BLUSH)


@lru_cache(maxsize=512)
def _sprite(expression, mouth_q, blink, scale):
    k = SS * scale
    size = round(2 * HALF * k)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = Pen(ImageDraw.Draw(layer), k, HALF, HALF)
    pose = _POSE[expression]
    _arms(pen, expression)
    _antenna(pen, expression, pose)
    _body(pen)
    _eye(pen, expression, pose, blink)
    _brow(pen, expression)
    _mouth(pen, expression, mouth_q / 20)
    _extras(pen, expression)
    out = round(2 * HALF * scale)
    return layer.resize((out, out), Image.LANCZOS)


def draw_zorb(img: Image.Image, expression: str, mouth: float, blink: bool,
              center: tuple, scale: float = 1.0) -> None:
    """Paste Zorb onto ``img`` (in place).

    expression: one of EXPRESSIONS. mouth: 0 (closed) .. 1 (wide open), clamped
    and quantised to 1/20 steps. blink: eye closed. center: (x, y) of the body.
    """
    if expression not in EXPRESSIONS:
        raise ValueError(f"unknown expression {expression!r}; expected one of {EXPRESSIONS}")
    try:
        m = float(mouth)
    except (TypeError, ValueError):
        m = 0.0
    mouth_q = round(min(1.0, max(0.0, m)) * 20)
    scale = round(max(0.05, float(scale)), 3)
    sprite = _sprite(expression, mouth_q, bool(blink), scale)
    off = round(HALF * scale)
    img.paste(sprite, (round(center[0]) - off, round(center[1]) - off), sprite)
