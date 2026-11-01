"""Content checks run before a video is built."""
import json
import math
import re
import subprocess
from dataclasses import dataclass
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


def _fact_numbers(facts_text: str) -> set:
    """Numbers on a fact sheet, ignoring source URLs and markdown list markers."""
    text = _URL.sub(" ", facts_text)
    text = _LIST_MARKER.sub("", text)
    return normalise_numbers(text)


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


def check_facts(script: dict, facts_text: str) -> CheckResult:
    spoken = _spoken(script)
    problems = []
    lowered = spoken.lower()
    hits = [p for p in BANNED_PHRASES if p in lowered]
    if hits:
        problems.append("banned phrase: " + ", ".join(hits))
    sheet = _fact_numbers(facts_text)
    unknown = sorted(normalise_numbers(spoken) - sheet)
    if unknown:
        problems.append("numbers not in fact sheet: " + ", ".join(unknown))
    on_screen = sorted(normalise_numbers(_props_text(script)) - sheet)
    if on_screen:
        problems.append("on screen (props) numbers not in fact sheet: " + ", ".join(on_screen))
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
