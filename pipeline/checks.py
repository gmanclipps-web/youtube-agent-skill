"""Content checks run before a video is built."""
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

BANNED_PHRASES = ("you should buy", "guaranteed", "will go up", "will crash",
                  "buy now", "financial advice for you")
DISCLAIMER = "Education, not financial advice."
MAX_TITLE = 60
HOOK_MIN = 55
TITLE_SIMILARITY_MAX = 0.8

_NUM = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def normalise_numbers(text: str) -> set:
    """Numbers in text as plain strings: '$1,000' -> '1000'; '%'/'percent' ignored."""
    return {m.replace(",", "") for m in _NUM.findall(text)}


def _spoken(script: dict) -> str:
    return " ".join(b["line"] for b in script["beats"])


def check_facts(script: dict, facts_text: str) -> CheckResult:
    spoken = _spoken(script)
    problems = []
    lowered = spoken.lower()
    hits = [p for p in BANNED_PHRASES if p in lowered]
    if hits:
        problems.append("banned phrase: " + ", ".join(hits))
    unknown = sorted(normalise_numbers(spoken) - normalise_numbers(facts_text))
    if unknown:
        problems.append("numbers not in fact sheet: " + ", ".join(unknown))
    if problems:
        return CheckResult("facts", False, "; ".join(problems))
    return CheckResult("facts", True, "all numbers on fact sheet, no banned phrases")


def check_metadata(script: dict) -> CheckResult:
    problems = []
    if DISCLAIMER not in script.get("description", ""):
        problems.append(f"description missing '{DISCLAIMER}'")
    n = len(script.get("title", ""))
    if n > MAX_TITLE:
        problems.append(f"title is {n} chars (max {MAX_TITLE})")
    if problems:
        return CheckResult("metadata", False, "; ".join(problems))
    return CheckResult("metadata", True, "disclaimer present, title length ok")


def check_variety(script: dict, recent: list) -> CheckResult:
    title = script["title"].lower()
    scenes = [b["scene"] for b in script["beats"]]
    for item in recent:
        ratio = SequenceMatcher(None, title, item["title"].lower()).ratio()
        if ratio >= TITLE_SIMILARITY_MAX:
            return CheckResult("variety", False,
                               f"title too similar ({ratio:.2f}) to {item['title']!r}")
        if list(item["scenes"]) == scenes:
            return CheckResult("variety", False,
                               f"scene sequence identical to recent video {item['title']!r}")
    return CheckResult("variety", True, f"distinct from {len(recent)} recent videos")


def check_hook(script: dict) -> CheckResult:
    score = script["hook_score"]
    if score >= HOOK_MIN:
        return CheckResult("hook", True, f"hook score {score} >= {HOOK_MIN}")
    return CheckResult("hook", False, f"hook score {score} < {HOOK_MIN}")
