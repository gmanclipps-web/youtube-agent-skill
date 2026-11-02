import json
import pytest
from pipeline.script_schema import load_script, SCENES, EXPRESSIONS


def _script(**over):
    s = {"topic": "inflation", "title": "T", "description": "D", "tags": ["a"],
         "hook_score": 61, "thumb_text": "PRICES JUMPED?!",
         "pinned_comment": "What costs more for you?",
         "beats": [{"line": "Hi.", "scene": "shop", "expression": "neutral", "props": {}}]}
    s.update(over)
    return s


def _write(tmp_path, s):
    p = tmp_path / "script.json"
    p.write_text(json.dumps(s))
    return str(p)


def test_load_script_ok(tmp_path):
    assert load_script(_write(tmp_path, _script()))["topic"] == "inflation"


def test_load_script_rejects_unknown_scene(tmp_path):
    s = _script(beats=[{"line": "Hi.", "scene": "beach", "expression": "neutral", "props": {}}])
    with pytest.raises(ValueError, match="scene"):
        load_script(_write(tmp_path, s))


def test_load_script_rejects_unknown_expression(tmp_path):
    s = _script(beats=[{"line": "Hi.", "scene": "shop", "expression": "angry", "props": {}}])
    with pytest.raises(ValueError, match="expression"):
        load_script(_write(tmp_path, s))


def test_load_script_missing_key(tmp_path):
    s = _script()
    del s["tags"]
    with pytest.raises(ValueError, match="tags"):
        load_script(_write(tmp_path, s))


def test_load_script_empty_beats_and_bad_line(tmp_path):
    with pytest.raises(ValueError, match="beats"):
        load_script(_write(tmp_path, _script(beats=[])))
    s = _script(beats=[{"line": "", "scene": "shop", "expression": "neutral", "props": {}}])
    with pytest.raises(ValueError, match="line"):
        load_script(_write(tmp_path, s))


def test_load_script_bad_props_and_hook_score(tmp_path):
    s = _script(beats=[{"line": "x", "scene": "shop", "expression": "neutral", "props": []}])
    with pytest.raises(ValueError, match="props"):
        load_script(_write(tmp_path, s))
    with pytest.raises(ValueError, match="hook_score"):
        load_script(_write(tmp_path, _script(hook_score="high")))


def test_constants():
    assert len(SCENES) == 8 and "shop" in SCENES
    assert EXPRESSIONS == ("neutral", "confused", "shocked", "aha", "smug")


def test_load_script_tags_must_be_non_empty_strings(tmp_path):
    for bad in (["ok", ""], ["ok", 5], ["ok", None], ["   "], "inflation"):
        with pytest.raises(ValueError, match="tags"):
            load_script(_write(tmp_path, _script(tags=bad)))
    assert load_script(_write(tmp_path, _script(tags=["a", "b c"])))["tags"] == ["a", "b c"]


def test_load_script_requires_thumb_text_of_one_to_three_words(tmp_path):
    s = _script()
    del s["thumb_text"]
    with pytest.raises(ValueError, match="thumb_text"):
        load_script(_write(tmp_path, s))
    for bad in ("", "   ", "ONE TWO THREE FOUR", 5, None, ["WOW"]):
        with pytest.raises(ValueError, match="thumb_text"):
            load_script(_write(tmp_path, _script(thumb_text=bad)))
    for good in ("WOW", "WAIT WHAT?!", "SNACKS COST MORE?!"):
        assert load_script(_write(tmp_path, _script(thumb_text=good)))["thumb_text"] == good


def test_load_script_thumb_expression_optional_but_known(tmp_path):
    assert "thumb_expression" not in load_script(_write(tmp_path, _script()))
    for e in EXPRESSIONS:
        assert load_script(_write(tmp_path, _script(thumb_expression=e)))["thumb_expression"] == e
    for bad in ("angry", "", None, 3):
        with pytest.raises(ValueError, match="thumb_expression"):
            load_script(_write(tmp_path, _script(thumb_expression=bad)))


def test_load_script_requires_pinned_comment_string(tmp_path):
    s = _script()
    del s["pinned_comment"]
    with pytest.raises(ValueError, match="pinned_comment"):
        load_script(_write(tmp_path, s))
    for bad in (5, None, "  ", ["Why?"]):
        with pytest.raises(ValueError, match="pinned_comment"):
            load_script(_write(tmp_path, _script(pinned_comment=bad)))


def test_load_script_beat_line_at_most_14_words(tmp_path):
    ok = " ".join(["word"] * 14)
    beat = {"scene": "shop", "expression": "neutral", "props": {}}
    assert load_script(_write(tmp_path, _script(beats=[{**beat, "line": ok}])))
    s = _script(beats=[{**beat, "line": "Hi."}, {**beat, "line": ok + " more"}])
    with pytest.raises(ValueError, match=r"beats\[1\]\.line.*15 words.*14"):
        load_script(_write(tmp_path, s))


def test_sample_script_follows_the_new_rules():
    from datetime import date
    from pathlib import Path
    from pipeline.build import content_checks
    from pipeline.checks import text_numbers
    root = Path(__file__).resolve().parents[2]
    s = load_script(str(root / "channel/samples/inflation/script.json"))
    assert s["thumb_text"] and s["thumb_expression"] in EXPRESSIONS
    assert 8 <= len(s["beats"]) <= 14
    assert not s["title"].lower().startswith("zorb")
    assert "will return" not in s["beats"][-1]["line"].lower()
    assert all("subscribe" not in b["line"].lower() for b in s["beats"])
    for b in s["beats"]:                         # at most one spoken number per beat
        assert len(text_numbers(b["line"])) <= 1, b["line"]
    checks = content_checks(s, root / "channel/facts", None, today=date(2026, 11, 2))
    bad = [(c.name, c.detail) for c in checks if not c.ok]
    assert bad == []
