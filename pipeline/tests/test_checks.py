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


def test_normalise_drops_trailing_decimal_zeros():
    assert normalise_numbers("1.50 and 2.0 and 100 and 3.05") == {"1.5", "2", "100", "3.05"}


def test_facts_ignore_numbers_in_urls_and_list_markers():
    sheet = ("1. Inflation was 2% (https://www.bls.gov/cpi/2024/table9.htm)\n"
             "2) See http://example.com/page/42\n"
             "- Rate: 7 percent\n")
    nums = sheet  # numbers 9, 42, 2024 live only in URLs; 1 only as list marker
    assert not check_facts(script(["It went up 9 percent."]), nums).ok
    assert not check_facts(script(["Since 2024."]), nums).ok
    assert not check_facts(script(["Step 1 is easy."]), nums).ok
    assert check_facts(script(["Prices rose 2% then 7%."]), nums).ok


def test_facts_dollar_thousand_vs_plain():
    assert check_facts(script(["Save $1,000 this year."]), "Goal: 1000 dollars.").ok
    assert check_facts(script(["It cost $1.50."]), "Price 1.5").ok
