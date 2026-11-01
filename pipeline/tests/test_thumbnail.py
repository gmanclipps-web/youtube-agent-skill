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
