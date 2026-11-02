"""Load and validate script.json."""
import json

SCENES = ("shop", "price_tag", "vault", "stock_chart", "credit_card",
          "planet", "calendar", "money_stack")
EXPRESSIONS = ("neutral", "confused", "shocked", "aha", "smug")
MAX_LINE_WORDS = 14     # one beat = one picture; keep it short (checks.check_pacing too)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_cover(script):
    """thumb_text: 1-3 words (the Shorts cover); thumb_expression: optional, in EXPRESSIONS."""
    from pipeline.thumbnail import thumb_words   # lazy: thumbnail -> scenes -> this module
    text = script["thumb_text"]
    if not isinstance(text, str):
        raise ValueError("field thumb_text must be a string")
    thumb_words(text)                             # ValueError naming thumb_text
    if "thumb_expression" in script and script["thumb_expression"] not in EXPRESSIONS:
        raise ValueError(f"thumb_expression {script['thumb_expression']!r} not in {EXPRESSIONS}")


def load_script(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        script = json.load(f)
    if not isinstance(script, dict):
        raise ValueError("script must be a JSON object")
    for key in ("topic", "title", "description", "tags", "hook_score", "thumb_text",
                "pinned_comment", "beats"):
        if key not in script:
            raise ValueError(f"missing required field: {key}")
    for key in ("topic", "title", "description"):
        if not isinstance(script[key], str):
            raise ValueError(f"field {key} must be a string")
    if not isinstance(script["pinned_comment"], str) or not script["pinned_comment"].strip():
        raise ValueError("field pinned_comment must be a non-empty string")
    if not isinstance(script["tags"], list):
        raise ValueError("field tags must be a list")
    for i, tag in enumerate(script["tags"]):
        if not isinstance(tag, str) or not tag.strip():
            raise ValueError(f"tags[{i}] must be a non-empty string")
    _check_cover(script)
    if not _is_number(script["hook_score"]):
        raise ValueError("field hook_score must be a number")
    beats = script["beats"]
    if not isinstance(beats, list) or not beats:
        raise ValueError("field beats must be a non-empty list")
    for i, beat in enumerate(beats):
        where = f"beats[{i}]"
        if not isinstance(beat, dict):
            raise ValueError(f"{where} must be an object")
        line = beat.get("line")
        if not isinstance(line, str) or not line.strip():
            raise ValueError(f"{where}.line must be a non-empty string")
        n = len(line.split())
        if n > MAX_LINE_WORDS:
            raise ValueError(f"{where}.line has {n} words (max {MAX_LINE_WORDS})")
        if beat.get("scene") not in SCENES:
            raise ValueError(f"{where}.scene {beat.get('scene')!r} not in {SCENES}")
        if beat.get("expression") not in EXPRESSIONS:
            raise ValueError(f"{where}.expression {beat.get('expression')!r} not in {EXPRESSIONS}")
        if not isinstance(beat.get("props"), dict):
            raise ValueError(f"{where}.props must be an object")
    return script
