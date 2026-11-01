import numpy as np
import pytest
from PIL import Image

from pipeline.script_schema import SCENES, EXPRESSIONS
from pipeline import zorb, scenes

W, H = 1080, 1920
CAPTION_BAND = (1100, 1400)


def _blank(color=(30, 30, 40)):
    return Image.new("RGB", (W, H), color)


def _arr(img):
    return np.asarray(img).astype(int)


def _draw(expression="neutral", mouth=0.0, blink=False, center=(540, 1660), scale=1.0):
    img = _blank()
    zorb.draw_zorb(img, expression, mouth, blink, center, scale)
    return img


@pytest.mark.parametrize("expression", EXPRESSIONS)
def test_every_expression_changes_pixels(expression):
    blank = _arr(_blank())
    drawn = _arr(_draw(expression))
    assert (blank != drawn).any()


def test_expressions_are_distinct():
    imgs = {e: _arr(_draw(e)) for e in EXPRESSIONS}
    for i, a in enumerate(EXPRESSIONS):
        for b in EXPRESSIONS[i + 1:]:
            diff = (imgs[a] != imgs[b]).any(axis=2).sum()
            assert diff > 500, f"{a} vs {b} differ in only {diff} px"


def test_mouth_open_differs_from_closed():
    assert (_arr(_draw(mouth=0.0)) != _arr(_draw(mouth=1.0))).any()


def test_blink_differs_from_open_eye():
    assert (_arr(_draw(blink=False)) != _arr(_draw(blink=True))).any()


def test_unknown_expression_raises():
    with pytest.raises(ValueError):
        _draw("furious")


@pytest.mark.parametrize("expression", EXPRESSIONS)
def test_zorb_fits_its_band_and_avoids_captions(expression):
    blank = _arr(_blank())
    for mouth in (0.0, 1.0):
        drawn = _arr(_draw(expression, mouth=mouth))
        ys, xs = np.nonzero((blank != drawn).any(axis=2))
        assert ys.min() >= 1430 and ys.max() <= 1890, (ys.min(), ys.max())
        assert xs.max() <= 950


def test_zorb_scale_changes_size():
    blank = _arr(_blank())
    small = (_arr(_draw(scale=0.5)) != blank).any(axis=2).sum()
    big = (_arr(_draw(scale=1.0)) != blank).any(axis=2).sum()
    assert small < big


def test_every_scene_has_a_painter():
    assert set(scenes.SCENE_PAINTERS) == set(SCENES)


@pytest.mark.parametrize("scene", SCENES)
def test_scene_renders_at_all_progress_and_stays_out_of_captions(scene):
    pal = scenes.palette("inflation")
    frames = []
    for p in (0.0, 0.5, 1.0):
        img = _blank(pal["bg"])
        scenes.SCENE_PAINTERS[scene](img, {}, p, pal)
        a = _arr(img)
        assert (a != _arr(_blank(pal["bg"]))).any()
        band = a[CAPTION_BAND[0]:CAPTION_BAND[1]]
        assert (band == np.array(pal["bg"])).all(), f"{scene} drew in captions band"
        assert (a[1050:] == np.array(pal["bg"])).all(), f"{scene} drew below y 1050"
        frames.append(a)
    assert (frames[0] != frames[2]).any(), f"{scene} does not animate"


@pytest.mark.parametrize("scene,props", [
    ("price_tag", {"from": "2", "to": "9.99"}),
    ("stock_chart", {"trend": "down"}),
    ("money_stack", {"amount": "1,000"}),
    ("calendar", {"years": 30}),
    ("credit_card", {"apr": "24%"}),
    ("vault", {"label": "SAVINGS"}),
    ("shop", {"item": "SNACK", "price": "$3"}),
    ("planet", {"label": "MARS"}),
])
def test_scene_props_change_output(scene, props):
    pal = scenes.palette("stocks")
    a = _blank(pal["bg"])
    b = _blank(pal["bg"])
    scenes.SCENE_PAINTERS[scene](a, {}, 1.0, pal)
    scenes.SCENE_PAINTERS[scene](b, props, 1.0, pal)
    assert (_arr(a) != _arr(b)).any()


@pytest.mark.parametrize("scene", SCENES)
def test_scene_tolerates_junk_props(scene):
    pal = scenes.palette("x")
    img = _blank(pal["bg"])
    junk = {"from": None, "to": "abc", "trend": 5, "amount": [], "years": "lots",
            "apr": None, "label": 7, "item": None, "price": {}}
    scenes.SCENE_PAINTERS[scene](img, junk, 0.5, pal)


def test_palette_deterministic_and_topic_specific():
    assert scenes.palette("inflation") == scenes.palette("inflation")
    assert scenes.palette("inflation") != scenes.palette("stocks")
    assert set(scenes.palette("inflation")) == {"bg", "fg", "accent", "text"}


def _lum(c):
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("topic", ["inflation", "stocks", "credit", "savings", "taxes",
                                   "compound interest", "budget", "", "a" * 200,
                                   "bonds", "crypto", "mortgage", "retirement"])
def test_palette_text_contrasts_with_bg(topic):
    pal = scenes.palette(topic)
    for v in pal.values():
        assert len(v) == 3 and all(isinstance(x, int) and 0 <= x <= 255 for x in v)
    assert _contrast(pal["text"], pal["bg"]) >= 4.5


def test_palette_contrast_over_many_topics():
    for i in range(300):
        pal = scenes.palette(f"topic-{i}")
        assert _contrast(pal["text"], pal["bg"]) >= 4.5
