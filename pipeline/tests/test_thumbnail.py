import pytest
from PIL import Image

from pipeline.thumbnail import render_thumbnail, thumb_words, W, H


def test_thumb_words_limits_to_three():
    assert thumb_words("pizza got rich") == ["PIZZA", "GOT", "RICH"]
    with pytest.raises(ValueError):
        thumb_words("one two three four")
    with pytest.raises(ValueError):
        thumb_words("  ")


def test_render_thumbnail_is_vertical_jpeg(tmp_path):
    out = render_thumbnail({"topic": "credit_score", "thumb_text": "YOU'RE BEING RATED"},
                           tmp_path / "t.jpg")
    im = Image.open(out)
    assert im.format == "JPEG" and im.size == (W, H)


def test_thumbnail_differs_by_text_and_topic(tmp_path):
    a = Image.open(render_thumbnail({"topic": "stocks", "thumb_text": "WOW"}, tmp_path / "a.jpg"))
    b = Image.open(render_thumbnail({"topic": "stocks", "thumb_text": "HUH"}, tmp_path / "b.jpg"))
    c = Image.open(render_thumbnail({"topic": "taxes_basics", "thumb_text": "WOW"}, tmp_path / "c.jpg"))
    assert a.tobytes() != b.tobytes() and a.tobytes() != c.tobytes()


def test_punch_text_helper_draws_in_box():
    from pipeline.scenes import palette
    from pipeline.thumbnail import draw_punch_text, highlight_colour
    import numpy as np
    pal = palette("inflation")
    img = Image.new("RGBA", (800, 700), (0, 0, 0, 0))
    draw_punch_text(img, ["PRICES", "JUMPED?!"], pal, (0, 0, 800, 700))
    a = np.asarray(img)
    hl = (a[..., :3] == np.array(highlight_colour(pal))).all(axis=2) & (a[..., 3] == 255)
    white = (a[..., :3] == 255).all(axis=2) & (a[..., 3] == 255)
    assert hl.sum() > 5000 and white.sum() > 5000
    assert hl[:350].sum() < hl[350:].sum()   # last word (lower line) is the highlighted one


def _beats(scene, props):
    return [{"line": "x", "scene": scene, "expression": "shocked", "props": props}]


def test_cover_shows_the_videos_key_picture(tmp_path):
    from pipeline.thumbnail import hero_beat
    s = {"topic": "inflation", "thumb_text": "WOW",
         "beats": _beats("planet", {}) + _beats("price_tag", {"from": "100", "to": "107"})}
    assert hero_beat(s)["scene"] == "price_tag"            # first beat with a number wins
    s2 = dict(s, thumb_scene={"scene": "vault", "props": {"label": "HI"}})
    assert hero_beat(s2)["scene"] == "vault"               # explicit choice wins
    a = Image.open(render_thumbnail(s, tmp_path / "a.jpg"))
    b = Image.open(render_thumbnail(s2, tmp_path / "b.jpg"))
    assert a.tobytes() != b.tobytes()


def test_cover_background_is_never_green(tmp_path):
    from pipeline.thumbnail import cover_colours
    from pipeline.scenes import palette
    for t in ["tariffs", "stocks", "inflation", "credit_score", "compound_interest",
              "interest_rates", "taxes_basics", "money_scams", "bonds_basics"]:
        r, g, b = cover_colours(palette(t))["burst"]
        assert not (g > r + 30 and g > b + 30), t
