"""Content checks run before a video is built."""
import json
import math
import re
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from difflib import SequenceMatcher

BANNED_PHRASES = ("you should buy", "guaranteed", "will go up", "will crash",
                  "buy now", "financial advice for you")
DISCLAIMER = "Education, not financial advice."
MAX_TITLE = 60
HOOK_MIN = 55
TITLE_SIMILARITY_MAX = 0.8
VIDEO_SIZE = (1080, 1920)
MAX_DURATION = 59.0

_NUM = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
FRESH_DAYS = 45          # a bullet marked "(as of: YYYY-MM-DD)" expires this many days later
_AS_OF = re.compile(r"\(as of:\s*(\d{4}-\d{2}-\d{2})\)", re.IGNORECASE)
_BULLET_START = re.compile(r"^[ \t>]*(?:\d+[.)]|[-*+])[ \t]+")

_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split()) if i}
_TENS = {w: 10 * i for i, w in enumerate(
    "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i > 1}
_SCALES = {"thousand": 10 ** 3, "million": 10 ** 6, "billion": 10 ** 9, "trillion": 10 ** 12}
_SPECIAL = {"half": "0.5", "double": "2", "doubles": "2", "doubled": "2", "doubling": "2",
            "twice": "2", "triple": "3", "triples": "3", "tripled": "3", "tripling": "3"}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


_URL = re.compile(r"(?:https?|ftp)://\S+|www\.\S+", re.IGNORECASE)
_LIST_MARKER = re.compile(r"^[ \t>]*(?:\d+[.)]|[-*+])[ \t]+", re.MULTILINE)


def _plain_number(m: str) -> str:
    m = m.replace(",", "")
    if "." in m:
        m = m.rstrip("0").rstrip(".")
    return m


def normalise_numbers(text: str) -> set:
    """Numbers in text as plain strings: '$1,000' -> '1000', '1.50' -> '1.5';
    '%'/'percent' ignored."""
    return {_plain_number(m) for m in _NUM.findall(text)}


def number_words(text: str) -> set:
    """Numbers written as words, as digit strings: 'twenty five' -> '25',
    'three thousand' -> '3000', 'half' -> '0.5', 'double'/'twice' -> '2'.

    A lone "one" is ignored (too common: "one rule", "one-time"), but counts
    inside a compound ("one hundred", "twenty one"). A scale word right after a
    digit ("$1 billion", "16.7 trillion") adds nothing: the digit carries it."""
    out = set()
    total = current = 0
    words = []          # number words in the group being read
    prev_digit = False

    def flush():
        nonlocal total, current, words
        if words and words != ["one"]:
            out.add(str(total + current))
        total = current = 0
        words = []

    for raw in re.split(r"[\s\-\u2010-\u2015]+", text.lower()):
        tok = re.sub(r"[^a-z0-9.,]", "", raw).strip(".,")
        ends = bool(re.search(r"[.,;:!?)\]]$", raw))
        if tok in _UNITS or tok in _TENS:
            val = _UNITS.get(tok) or _TENS[tok]
            low = current % 100
            fits = low == 0 or (tok in _UNITS and val < 10 and low >= 20 and low % 10 == 0)
            if words and not fits:
                flush()                               # "five two": two separate numbers
            current += val
            words.append(tok)
        elif tok == "hundred" or tok in _SCALES:
            scale = 100 if tok == "hundred" else _SCALES[tok]
            if not words and prev_digit:
                pass                                  # "$1 billion": digit already counted
            elif tok == "hundred":
                current = (current or 1) * 100
                words.append(tok)
            else:
                total += (current or 1) * scale
                current = 0
                words.append(tok)
        elif tok == "and" and words and words[-1] in ("hundred", *_SCALES) and not ends:
            pass                                      # "two hundred and five"
        else:
            flush()
            if tok in _SPECIAL:
                out.add(_SPECIAL[tok])
        prev_digit = bool(re.fullmatch(r"\$?\d[\d,]*(?:\.\d+)?%?", tok or "x"))
        if ends:
            flush()
    flush()
    return out


def text_numbers(text: str) -> set:
    """Every number in text, as digit strings: digits and number words."""
    return normalise_numbers(text) | number_words(text)


def fact_bullets(facts_text: str) -> list:
    """[(text, as_of date or None)] for each bullet (and each other non-blank
    line) of a fact sheet; the "(as of: ...)" marker is removed from text."""
    blocks, cur = [], None
    for line in facts_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            cur = None
            if line.strip():
                blocks.append([line])
            continue
        if cur is None or _BULLET_START.match(line):
            cur = [line]
            blocks.append(cur)
        else:
            cur.append(line)
    out = []
    for b in blocks:
        text = "\n".join(b)
        m = _AS_OF.search(text)
        as_of = date.fromisoformat(m.group(1)) if m else None
        out.append((_AS_OF.sub(" ", text), as_of))
    return out


def is_expired(as_of, today) -> bool:
    return as_of is not None and today is not None and today > as_of + timedelta(days=FRESH_DAYS)


def expired_bullets(facts_text: str, today) -> list:
    """Bullets whose "(as of: YYYY-MM-DD)" is more than FRESH_DAYS days before today."""
    return [t.strip() for t, as_of in fact_bullets(facts_text) if is_expired(as_of, today)]


def _numbers_of(text: str) -> set:
    text = _URL.sub(" ", text)
    text = _LIST_MARKER.sub("", text)
    return text_numbers(text)


def _fact_numbers(facts_text: str, today=None) -> set:
    """Numbers on a fact sheet (digits and number words), ignoring source URLs,
    markdown list markers, "(as of: ...)" markers and, when today is given,
    bullets that have expired."""
    return set().union(*[_numbers_of(t) for t, as_of in fact_bullets(facts_text)
                         if not is_expired(as_of, today)])


def _spoken(script: dict) -> str:
    return " ".join(b["line"] for b in script["beats"])


def _prop_strings(v):
    """Every string and number inside a props value (dicts and lists walked)."""
    if isinstance(v, bool) or v is None:
        return
    if isinstance(v, str):
        yield v
    elif isinstance(v, int):
        yield str(v)
    elif isinstance(v, float):
        if math.isfinite(v):
            yield str(int(v)) if v.is_integer() else f"{v:f}"
    elif isinstance(v, dict):
        for x in v.values():
            yield from _prop_strings(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _prop_strings(x)


def _props_text(script: dict) -> str:
    """All prop values of all beats as text: numbers the scenes put on screen."""
    return " ".join(s for b in script["beats"] for s in _prop_strings(b.get("props", {})))


def _metadata_parts(script: dict) -> list:
    tags = script.get("tags") or []
    return [("title", str(script.get("title", ""))),
            ("description", str(script.get("description", ""))),
            ("tags", " | ".join(str(t) for t in (tags if isinstance(tags, list) else [tags])))]


def _sort_numbers(nums) -> list:
    return sorted(nums, key=lambda n: (float(n), n))


def check_facts(script: dict, facts_text: str, today=None) -> CheckResult:
    """Every number (digits or number words) in the spoken lines, props, title,
    description and tags must be on the fact sheet, in a bullet that has not
    expired by `today` (a date; None = no expiry); no banned phrases anywhere."""
    if isinstance(today, str):
        today = date.fromisoformat(today)
    parts = [("spoken", _spoken(script))] + _metadata_parts(script)
    problems = []
    for where, text in parts:
        hits = [p for p in BANNED_PHRASES if p in text.lower()]
        if hits:
            problems.append(f"banned phrase in {where}: " + ", ".join(hits))
    every = _fact_numbers(facts_text)
    sheet = _fact_numbers(facts_text, today)
    parts.insert(1, ("on screen (props)", _props_text(script)))
    expired = set()
    for where, text in parts:
        nums = text_numbers(text)
        unknown = nums - every
        if unknown:
            label = "numbers not in fact sheet" if where == "spoken" else \
                f"{where} numbers not in fact sheet"
            problems.append(f"{label}: " + ", ".join(_sort_numbers(unknown)))
        expired |= (nums & every) - sheet
    if expired:
        problems.append(f"numbers only in expired fact-sheet bullets (as of more than "
                        f"{FRESH_DAYS} days ago): " + ", ".join(_sort_numbers(expired)))
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


def _words(text: str) -> list:
    """Lowercase words with punctuation stripped: 'Save $1,000!' -> ['save', '1000']."""
    out = []
    for tok in text.lower().split():
        tok = re.sub(r"[^\w]", "", tok)
        if tok:
            out.append(tok)
    return out


def check_technical(mp4, spoken: str, captions: str) -> CheckResult:
    """ffprobe: 1080x1920, <= 59 s, has audio; captions say exactly the spoken words."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,width,height:format=duration", "-of", "json", str(mp4)],
            capture_output=True, text=True)
    except OSError as e:
        return CheckResult("technical", False, f"cannot run ffprobe: {e}")
    if r.returncode != 0:
        return CheckResult("technical", False, f"ffprobe failed: {r.stderr.strip()}")
    info = json.loads(r.stdout or "{}")
    streams = info.get("streams", [])
    problems = []
    video = [s for s in streams if s.get("codec_type") == "video"]
    if not video:
        problems.append("no video stream")
    else:
        size = (video[0].get("width"), video[0].get("height"))
        if size != VIDEO_SIZE:
            problems.append(f"size {size[0]}x{size[1]} (need 1080x1920)")
    if not any(s.get("codec_type") == "audio" for s in streams):
        problems.append("no audio stream")
    try:
        duration = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
        problems.append("duration unknown")
    if duration is not None and duration > MAX_DURATION:
        problems.append(f"duration {duration:.2f}s > {MAX_DURATION:.0f}s")
    said, shown = _words(spoken), _words(captions)
    if said != shown:
        i = next((k for k, (a, b) in enumerate(zip(said, shown)) if a != b),
                 min(len(said), len(shown)))
        problems.append(f"captions differ from speech at word {i}: "
                        f"spoken {said[i:i + 3]} vs caption {shown[i:i + 3]}")
    if problems:
        return CheckResult("technical", False, "; ".join(problems))
    return CheckResult("technical", True,
                       f"1080x1920, {duration:.2f}s, audio present, captions match speech")
