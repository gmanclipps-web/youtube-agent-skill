import json
import pytest
from pipeline.script_schema import load_script, SCENES, EXPRESSIONS


def _script(**over):
    s = {"topic": "inflation", "title": "T", "description": "D", "tags": ["a"],
         "hook_score": 61,
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
