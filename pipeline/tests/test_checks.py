from pipeline.checks import (normalise_numbers, check_facts, check_metadata,
                             check_variety, check_hook)

DISC = "Education, not financial advice."


def script(lines=("Hello.",), scenes=None, **over):
    scenes = scenes or ["shop"] * len(lines)
    s = {"topic": "t", "title": "Zorb Discovers Inflation", "description": f"About money. {DISC}",
         "tags": ["a"], "hook_score": 60, "thumb_text": "PRICES JUMPED?!",
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
    assert not check_hook(script(hook_score=64)).ok
    assert check_hook(script(hook_score=65)).ok


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


def test_facts_checks_numbers_in_props():
    s = script(["Prices went up."])
    s["beats"][0]["props"] = {"from": "1", "to": "9.99"}
    r = check_facts(s, "Snack went from 1 to 1.50.")
    assert not r.ok and "9.99" in r.detail and "on screen" in r.detail
    s["beats"][0]["props"] = {"from": 1, "to": "$1.50", "label": "SNACKS", "trend": "up"}
    assert check_facts(s, "Snack went from 1 to 1.50.").ok
    s["beats"][0]["props"] = {"amount": 1000.0, "nested": [{"apr": 22}]}
    r = check_facts(s, "1,000 saved")
    assert not r.ok and "22" in r.detail
    s["beats"][0]["props"] = {"open": True}
    assert check_facts(s, "").ok


# ---------------------------------------------------------------- metadata, number words

from datetime import date  # noqa: E402

from pipeline.checks import (expired_bullets, fact_bullets, number_words,  # noqa: E402
                             text_numbers)


def test_facts_digit_in_title_must_be_on_sheet():
    r = check_facts(script(["Prices rose 2 percent."], title="Zorb Sees 9 Percent"),
                    "Inflation was 2%.")
    assert not r.ok and "9" in r.detail and "title" in r.detail


def test_facts_digit_in_description_must_be_on_sheet():
    r = check_facts(script(["Prices rose."], description=f"Since 1999. {DISC}"), "Inflation 2%.")
    assert not r.ok and "1999" in r.detail
    assert check_facts(script(["Prices rose."], description=f"Goal 2 percent. {DISC}"),
                       "Inflation 2%.").ok


def test_facts_digit_in_tag_must_be_on_sheet():
    r = check_facts(script(["Prices rose."], tags=["inflation", "50 percent"]), "Inflation 2%.")
    assert not r.ok and "50" in r.detail
    assert check_facts(script(["Prices rose."], tags=["#Shorts", "inflation"]), "").ok


def test_facts_number_word_in_spoken_line_must_be_on_sheet():
    r = check_facts(script(["Prices doubled in twenty five years."]), "Prices rose 2%.")
    assert not r.ok and "25" in r.detail
    assert check_facts(script(["Not zero. Two."]), "The goal is 2 percent.").ok
    assert check_facts(script(["One meter says so."]), "").ok     # "one" is ignored
    r = check_facts(script(["Three hundred stores."]), "300 stores, 3 kinds")
    assert r.ok, r.detail
    assert not check_facts(script(["A million stores."]), "300 stores").ok


def test_facts_banned_phrase_in_metadata():
    assert not check_facts(script(["Hello."], title="Zorb: Guaranteed Money"), "").ok
    assert not check_facts(script(["Hello."], description=f"Buy now! {DISC}"), "").ok
    assert not check_facts(script(["Hello."], tags=["will crash"]), "").ok


def test_number_words():
    assert number_words("twenty five, twenty-five and ninety") == {"25", "90"}
    assert number_words("One. two hundred and five; three thousand") == {"205", "3000"}
    assert number_words("five two, ninety nine, twenty twelve") == {"5", "2", "99", "20", "12"}
    assert number_words("half, double, twice, triple") == {"0.5", "2", "3"}
    assert number_words("$1 billion and 16.7 trillion dollars") == set()   # digits carry it
    assert number_words("a trillion, a hundred") == {"1000000000000", "100"}
    assert number_words("one rule, one-time, someone, fifteen") == {"15"}
    assert number_words("one hundred") == {"100"}
    assert text_numbers("2 or two, 2026") == {"2", "2026"}


# ---------------------------------------------------------------- freshness

SHEET = ("# Rates\n\n"
         "- The goal is 2 percent. (source: https://a.gov/x)\n"
         "- In 2026 the range was 3.75 to 4 percent. (as of: 2026-10-28) (source: https://a.gov/y)\n"
         "- Rates were 4 percent in 2007. (source: https://a.gov/z)\n")


def test_fact_bullets_parse_as_of_marker():
    bullets = fact_bullets(SHEET)
    bullets = [b for b in bullets if b[0].startswith("-")]
    assert [b[1] for b in bullets] == [None, date(2026, 10, 28), None]
    assert "(as of" not in bullets[1][0]


def test_expired_bullets_after_45_days():
    assert expired_bullets(SHEET, date(2026, 12, 12)) == []          # day 45: still fresh
    out = expired_bullets(SHEET, date(2026, 12, 13))
    assert len(out) == 1 and "3.75" in out[0]


def test_facts_reject_numbers_only_in_expired_bullets():
    s = script(["The range is 3.75 to 4 percent."])
    assert check_facts(s, SHEET, today=date(2026, 11, 1)).ok
    assert check_facts(s, SHEET).ok                          # no date given: no expiry
    r = check_facts(s, SHEET, today=date(2026, 12, 13))
    assert not r.ok and "3.75" in r.detail and "expired" in r.detail
    assert "4," not in r.detail and not r.detail.endswith(" 4")   # 4 is also in a live bullet
    assert check_facts(script(["The goal is 2 percent."]), SHEET, today=date(2027, 6, 1)).ok


def test_as_of_marker_date_is_not_a_sheet_number():
    assert not check_facts(script(["Day 28 of month 10."]), SHEET).ok
