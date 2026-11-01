from pipeline.checks import (normalise_numbers, check_facts, check_metadata,
                             check_variety, check_hook)

DISC = "Education, not financial advice."


def script(lines=("Hello.",), scenes=None, **over):
    scenes = scenes or ["shop"] * len(lines)
    s = {"topic": "t", "title": "Zorb Discovers Inflation", "description": f"About money. {DISC}",
         "tags": ["a"], "hook_score": 60,
         "beats": [{"line": l, "scene": sc, "expression": "neutral", "props": {}}
                   for l, sc in zip(lines, scenes)]}
    s.update(over)
    return s


def test_normalise_numbers():
    assert normalise_numbers("$1,000 at 7% or 7 percent, 2.5") == {"1000", "7", "2.5"}


def test_facts_pass_when_numbers_on_sheet():
    assert check_facts(script(["Prices rose 2 percent."]), "Inflation was 2%.").ok


def test_facts_fail_on_invented_number():
    r = check_facts(script(["Prices rose 9%."]), "Inflation was 2%.")
    assert not r.ok and "9" in r.detail


def test_facts_fail_on_banned_phrase():
    assert not check_facts(script(["You should buy it."]), "").ok
    assert not check_facts(script(["A Guaranteed return."]), "").ok


def test_metadata_requires_disclaimer_and_title_len():
    assert check_metadata(script()).ok
    assert not check_metadata(script(description="About money.")).ok
    assert not check_metadata(script(title="x" * 61)).ok
    assert check_metadata(script(title="x" * 60)).ok


def test_variety_fails_similar_title():
    r = check_variety(script(), [{"title": "Zorb Discovers Inflation!", "scenes": ["vault"]}])
    assert not r.ok


def test_variety_fails_identical_scene_sequence():
    s = script(["a", "b"], ["shop", "vault"], title="Totally Different")
    r = check_variety(s, [{"title": "Other thing here", "scenes": ["shop", "vault"]}])
    assert not r.ok
    assert check_variety(s, [{"title": "Other thing here", "scenes": ["vault", "shop"]}]).ok


def test_hook_threshold():
    assert not check_hook(script(hook_score=54)).ok
    assert check_hook(script(hook_score=55)).ok
