"""Load and validate script.json."""
import json

SCENES = ("shop", "price_tag", "vault", "stock_chart", "credit_card",
          "planet", "calendar", "money_stack")
EXPRESSIONS = ("neutral", "confused", "shocked", "aha", "smug")


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def load_script(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        script = json.load(f)
    if not isinstance(script, dict):
        raise ValueError("script must be a JSON object")
    for key in ("topic", "title", "description", "tags", "hook_score", "beats"):
        if key not in script:
            raise ValueError(f"missing required field: {key}")
    for key in ("topic", "title", "description"):
        if not isinstance(script[key], str):
            raise ValueError(f"field {key} must be a string")
    if not isinstance(script["tags"], list):
        raise ValueError("field tags must be a list")
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
        if beat.get("scene") not in SCENES:
            raise ValueError(f"{where}.scene {beat.get('scene')!r} not in {SCENES}")
        if beat.get("expression") not in EXPRESSIONS:
            raise ValueError(f"{where}.expression {beat.get('expression')!r} not in {EXPRESSIONS}")
        if not isinstance(beat.get("props"), dict):
            raise ValueError(f"{where}.props must be an object")
    return script
