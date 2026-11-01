"""Small deterministic helpers for the daily run (see pipeline/run_day.md).

    python3 -m pipeline.media today [--log-dir channel/log]
    python3 -m pipeline.media topics [--log-dir channel/log] [--topics channel/topics.json]
                                     [--facts channel/facts] [--n N] [--today DATE]
    python3 -m pipeline.media stale SHEET [--today DATE]   # expired "(as of: ...)" bullets
    python3 -m pipeline.media slots --per-day N [--config channel/config.json] [--log-dir channel/log]
    python3 -m pipeline.media numbers SCRIPT FACTS [--today DATE]  # title/description/tags numbers on sheet?
    python3 -m pipeline.media payload SCRIPT SLOT_DATE URL REPORT [--config channel/config.json] [--draft]
    python3 -m pipeline.media upload DATE TOPIC MP4 [--repo .]   # push mp4 to the media branch
    python3 -m pipeline.media verify DATE TOPIC MP4        # raw URL serves the same bytes?
    python3 -m pipeline.media log DATE ENTRY_JSON [--log-dir channel/log]
    python3 -m pipeline.media url DATE TOPIC

Every command exits 0 on success and non-zero (message on stderr) otherwise.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pipeline.checks import _fact_numbers, expired_bullets, text_numbers
from pipeline.script_schema import load_script

REPO = "gmanclipps-web/youtube-agent-skill"
BRANCH = "media"
TZ = "America/New_York"
MIN_LEAD = timedelta(minutes=20)
PUSH_DELAYS = (2, 4, 8, 16)
VERIFY_TRIES, VERIFY_WAIT = 5, 15
LOG_KEYS = ("topic", "title", "scenes", "hook_score", "checks", "status",
            "planner_url", "media_url", "reason", "publish_at")
STATUSES = ("scheduled", "skipped", "error")
METRICOOL_PREFIX = "metricool:"
TOPIC_GAP_DAYS = 6      # a topic scheduled on day D is eligible again from D + 6
SLOT_LOOKAHEAD = 2      # slots() offers slots up to this many days ahead
_DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


class MediaError(Exception):
    pass


def media_path(day: str, topic: str) -> str:
    return f"media/{day}/{topic}.mp4"


def raw_url(day: str, topic: str) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{media_path(day, topic)}"


def _now(now, tz):
    return (now or datetime.now(ZoneInfo("UTC"))).astimezone(ZoneInfo(tz))


# ---------------------------------------------------------------- logs

def _read_log(log_dir, day):
    """Entries of log_dir/day.json; [] if missing or unreadable."""
    try:
        data = json.loads((Path(log_dir) / f"{day}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def metricool_failed(log_dir, day) -> bool:
    return any(e.get("status") == "error" and str(e.get("reason") or "").startswith(METRICOOL_PREFIX)
               for e in _read_log(log_dir, day))


def today(now=None, tz=TZ, log_dir=None) -> dict:
    d = _now(now, tz)
    info = {"date": d.date().isoformat(), "weekday": d.strftime("%A"), "monday": d.weekday() == 0}
    if log_dir is not None:
        entries = _read_log(log_dir, info["date"])
        info["yesterday"] = (d.date() - timedelta(days=1)).isoformat()
        info["scheduled_today"] = sum(e.get("status") == "scheduled" for e in entries)
        info["metricool_error_today"] = metricool_failed(log_dir, info["date"])
    return info


def log_append(log_dir, day, entry_path):
    """Validate one entry (JSON file) and append it to log_dir/day.json atomically."""
    entry = json.loads(Path(entry_path).read_text(encoding="utf-8"))
    if not isinstance(entry, dict) or set(entry) != set(LOG_KEYS):
        raise ValueError(f"entry must have exactly the keys {LOG_KEYS}")
    if entry["status"] not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if not isinstance(entry["scenes"], list) or not isinstance(entry["checks"], list):
        raise ValueError("scenes and checks must be lists")
    if entry["status"] == "scheduled":
        if not isinstance(entry["title"], str) or not entry["scenes"]:
            raise ValueError("a scheduled entry needs its title and scenes")
    elif entry["title"] is not None or entry["scenes"]:
        raise ValueError("only scheduled entries carry title and scenes (use null and [])")
    path = Path(log_dir) / f"{day}.json"
    entries = []
    if path.exists():
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ValueError(f"{path} is not valid JSON; not touching it: {e}")
        if not isinstance(entries, list):
            raise ValueError(f"{path} is not a JSON list; not touching it")
    entries.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part")
    tmp.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- slots

def slots(config: dict, now=None, per_day=None, log_dir=None) -> list:
    """Next free publish slots.

    The configured slots in order, each for today in the config timezone, or
    tomorrow if already past or less than 20 minutes away; then the following
    days' slots in time order (up to SLOT_LOOKAHEAD days ahead). Slots already
    used (publish_at of a scheduled entry in the logs of today and the
    SLOT_LOOKAHEAD days before, any of which could have booked them) are
    skipped. Returns the first per_day."""
    tz = config.get("timezone", TZ)
    zone = ZoneInfo(tz)
    local = _now(now, tz)
    n = config.get("per_day", 2) if per_day is None else per_day
    booked = set()
    if log_dir is not None:
        # a run up to SLOT_LOOKAHEAD days ago may have booked a slot we would offer
        for day in (local.date() - timedelta(days=k) for k in range(SLOT_LOOKAHEAD + 1)):
            booked |= {e.get("publish_at") for e in _read_log(log_dir, day.isoformat())
                       if e.get("status") == "scheduled"}
    hm = [tuple(int(x) for x in s.split(":")) for s in config["slots"]]

    def at(d, h, m):
        return datetime(d.year, d.month, d.day, h, m, tzinfo=zone)

    first = []
    for h, m in hm:
        when = at(local.date(), h, m)
        if when - local < MIN_LEAD:
            when = at(local.date() + timedelta(days=1), h, m)
        first.append(when)
    later = sorted(at(local.date() + timedelta(days=k), h, m)
                   for k in range(1, SLOT_LOOKAHEAD + 1) for h, m in hm)
    out, seen = [], set()
    for when in first + later:
        iso = when.isoformat(timespec="seconds")
        if iso in seen or iso in booked or when - local < MIN_LEAD:
            continue
        seen.add(iso)
        out.append({"date": iso,
                    "publicationDate": {"dateTime": when.strftime("%Y-%m-%dT%H:%M:%S"),
                                        "timezone": tz}})
        if len(out) == n:
            break
    return out


# ---------------------------------------------------------------- numbers

def _date(d):
    if d is None:
        return date.fromisoformat(today()["date"])
    return date.fromisoformat(d) if isinstance(d, str) else d


def metadata_numbers(script_path, facts_path, today=None) -> list:
    """Numbers (digits or number words) in title, description and tags that are
    not on the fact sheet, or only in bullets expired by `today` (None = no expiry)."""
    s = json.loads(Path(script_path).read_text(encoding="utf-8"))
    text = " ".join([str(s.get("title", "")), str(s.get("description", ""))]
                    + [str(t) for t in s.get("tags", [])])
    sheet = _fact_numbers(Path(facts_path).read_text(encoding="utf-8"),
                          _date(today) if today is not None else None)
    return sorted(text_numbers(text) - sheet)


def stale(facts_path, today=None) -> list:
    """Bullets of a fact sheet whose "(as of: YYYY-MM-DD)" is more than 45 days old."""
    return expired_bullets(Path(facts_path).read_text(encoding="utf-8"), _date(today))


# ---------------------------------------------------------------- topics

def topics(log_dir, topics_path, facts_dir, today=None, n=None) -> list:
    """Eligible topic ids, in the order to try them.

    Eligible: has a fact sheet, was not tried today, and was not scheduled in
    the last TOPIC_GAP_DAYS - 1 days (scheduled on day D -> eligible from
    D + TOPIC_GAP_DAYS). Order: least recently scheduled first (never = first),
    then least recently tried, then the order of topics.json. At most n."""
    day = _date(today)
    ids = [t["id"] for t in json.loads(Path(topics_path).read_text(encoding="utf-8"))]
    last_sched, last_try = {}, {}
    for p in Path(log_dir).glob("*.json"):
        if not _DATED.match(p.name):
            continue
        for e in _read_log(log_dir, p.stem):
            t = e.get("topic")
            if not isinstance(t, str) or not t:
                continue
            last_try[t] = max(last_try.get(t, ""), p.stem)
            if e.get("status") == "scheduled":
                last_sched[t] = max(last_sched.get(t, ""), p.stem)
    cutoff = (day - timedelta(days=TOPIC_GAP_DAYS)).isoformat()
    eligible = [t for t in ids
                if (Path(facts_dir) / f"{t}.md").is_file()
                and last_sched.get(t, "") <= cutoff
                and last_try.get(t, "") != day.isoformat()]
    eligible.sort(key=lambda t: (last_sched.get(t, ""), last_try.get(t, ""), ids.index(t)))
    return eligible if n is None else eligible[:n]


# ---------------------------------------------------------------- payload

def payload(script_path, slot_date, url, report_path, config_path="channel/config.json",
            draft=False) -> dict:
    """The exact createScheduledPost arguments {blogId, date, info (a JSON string)}.

    Refuses (MediaError) unless report.json says ok: true and video.mp4 sits
    next to it, the slot date is a full local time in the config timezone with
    its UTC offset, and the URL is this repo's raw media URL for the topic."""
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("ok") is not True:
        raise MediaError(f"{report_path} does not say ok: true; never schedule it")
    if not (report_path.parent / "video.mp4").is_file():
        raise MediaError(f"no video.mp4 next to {report_path}; never schedule it")
    script = load_script(script_path)
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    tz = cfg.get("timezone", TZ)
    try:
        when = datetime.fromisoformat(slot_date)
    except ValueError:
        raise MediaError(f"bad slot date {slot_date!r}")
    if when.tzinfo is None or \
            when.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds") != slot_date:
        raise MediaError(f"slot date {slot_date!r} must be the slot's 'date' as printed by "
                         f"slots (local {tz} time with its offset)")
    prefix = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/media/"
    if not (url.startswith(prefix) and url.endswith(f"/{script['topic']}.mp4")):
        raise MediaError(f"media url {url!r} is not {prefix}<date>/{script['topic']}.mp4")
    info = {
        "providers": [{"network": "youtube"}],
        "text": script["description"],
        "media": [url],
        "publicationDate": {"dateTime": when.strftime("%Y-%m-%dT%H:%M:%S"), "timezone": tz},
        "autoPublish": True,
        "draft": bool(draft),
        "descendants": [],
        "firstCommentText": "",
        "hasNotReadNotes": False,
        "mediaAltText": [],
        "shortener": False,
        "smartLinkData": {"ids": []},
        "youtubeData": {
            "title": script["title"],
            "type": "short",
            "privacy": "public",
            "tags": list(script["tags"]),
            "category": "EDUCATION",
            "madeForKids": False,
            "isAiGeneratedContent": False,
        },
    }
    return {"blogId": str(cfg["blog_id"]), "date": slot_date,
            "info": json.dumps(info, ensure_ascii=False)}


# ---------------------------------------------------------------- git / upload

def push_with_retry(run, args, sleep=time.sleep):
    """run(args) -> (returncode, output). Retries network failures 4 times
    (2, 4, 8, 16 s); a rejection is final."""
    for attempt in range(len(PUSH_DELAYS) + 1):
        rc, out = run(args)
        if rc == 0:
            return out
        if "rejected" in out or "stale info" in out:
            raise MediaError(f"git {' '.join(args[:1])} rejected: {out.strip()}")
        if attempt < len(PUSH_DELAYS):
            sleep(PUSH_DELAYS[attempt])
    raise MediaError(f"git {' '.join(args[:1])} failed after {attempt + 1} tries: {out.strip()}")


def upload(day, topic, mp4, repo=".", sleep=time.sleep) -> str:
    """Commit mp4 as media/DAY/TOPIC.mp4 on origin's orphan `media` branch and push.

    Uses git plumbing with a throwaway index: the main checkout's HEAD, index
    and files are never touched. A new orphan branch is started when origin
    has none, or on a Monday's first upload (keeping only yesterday's and
    today's folders). Re-uploading identical content pushes nothing.
    Returns the raw URL."""
    date.fromisoformat(day)
    if not re.fullmatch(r"[a-z0-9_]+", topic):
        raise MediaError(f"bad topic id: {topic!r}")
    mp4 = Path(mp4).resolve()
    if not mp4.is_file():
        raise MediaError(f"no such file: {mp4}")
    repo = Path(repo).resolve()

    def run(args, env=None):
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           env={**os.environ, **(env or {})})
        return r.returncode, (r.stdout + r.stderr)

    def git(*args, env=None):
        rc, out = run(list(args), env)
        if rc != 0:
            raise MediaError(f"git {' '.join(args)} failed: {out.strip()}")
        return out.strip()

    heads = push_with_retry(run, ["ls-remote", "--heads", "origin", BRANCH], sleep)
    have = bool(heads.strip())
    parent = None
    if have:
        push_with_retry(run, ["fetch", "-q", "origin",
                              f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}"], sleep)
        parent = git("rev-parse", f"refs/remotes/origin/{BRANCH}")

    def exists(path):
        return parent is not None and run(["cat-file", "-e", f"{parent}:{path}"])[0] == 0

    d = date.fromisoformat(day)
    fresh = not have or (d.weekday() == 0 and not exists(f"media/{day}"))
    dest = media_path(day, topic)
    with tempfile.TemporaryDirectory(prefix="zorb-media-") as td:
        env = {"GIT_INDEX_FILE": str(Path(td) / "index")}
        if fresh:
            git("read-tree", "--empty", env=env)
            for keep in ((d - timedelta(days=1)).isoformat(), day):
                if exists(f"media/{keep}"):
                    git("read-tree", f"--prefix=media/{keep}/", f"{parent}:media/{keep}", env=env)
        else:
            git("read-tree", parent, env=env)
        blob = git("hash-object", "-w", str(mp4))
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},{dest}", env=env)
        tree = git("write-tree", env=env)
    if not fresh and tree == git("rev-parse", f"{parent}^{{tree}}"):
        return raw_url(day, topic)           # already there, identical bytes
    commit = git("commit-tree", tree, *(["-p", parent] if not fresh else []),
                 "-m", f"media: {day} {topic}")
    push = ["push", "-q", "origin", f"{commit}:refs/heads/{BRANCH}"]
    if fresh and have:   # replace the branch, but only if nobody moved it meanwhile
        push.insert(2, f"--force-with-lease=refs/heads/{BRANCH}:{parent}")
    push_with_retry(run, push, sleep)
    return raw_url(day, topic)


# ---------------------------------------------------------------- verify

def parse_head(raw: str):
    """(status, content_length) of the last HTTP response in curl -sSIL output."""
    status = length = None
    for line in raw.replace("\r", "").splitlines():
        m = re.match(r"HTTP/[\d.]+\s+(\d{3})", line)
        if m:
            status, length = int(m.group(1)), None
            continue
        m = re.match(r"content-length:\s*(\d+)", line, re.IGNORECASE)
        if m:
            length = int(m.group(1))
    return status, length


def _curl_head(url):
    r = subprocess.run(["curl", "-sSIL", "--max-time", "30", url], capture_output=True, text=True)
    return parse_head(r.stdout)


def verify(url, mp4, head=_curl_head, sleep=time.sleep):
    """Raw URL answers 200 with the mp4's exact Content-Length (5 tries, 15 s apart)."""
    size = Path(mp4).stat().st_size
    for i in range(VERIFY_TRIES):
        status, length = head(url)
        if status == 200 and length == size:
            return status, length
        if i < VERIFY_TRIES - 1:
            sleep(VERIFY_WAIT)
    raise MediaError(f"media URL not served: {status} {length} vs {size}")


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m pipeline.media")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("today")
    t.add_argument("--log-dir", default=None)
    u = sub.add_parser("url")
    u.add_argument("day")
    u.add_argument("topic")
    s = sub.add_parser("slots")
    s.add_argument("--config", default="channel/config.json")
    s.add_argument("--per-day", type=int, default=None)
    s.add_argument("--log-dir", default="channel/log")
    n = sub.add_parser("numbers")
    n.add_argument("script")
    n.add_argument("facts")
    n.add_argument("--today", default=None, help="YYYY-MM-DD (default: New York today)")
    tp = sub.add_parser("topics")
    tp.add_argument("--log-dir", default="channel/log")
    tp.add_argument("--topics", default="channel/topics.json")
    tp.add_argument("--facts", default="channel/facts")
    tp.add_argument("--n", type=int, default=None)
    tp.add_argument("--today", default=None)
    st = sub.add_parser("stale")
    st.add_argument("sheet")
    st.add_argument("--today", default=None)
    pl = sub.add_parser("payload")
    pl.add_argument("script")
    pl.add_argument("slot_date")
    pl.add_argument("url")
    pl.add_argument("report")
    pl.add_argument("--config", default="channel/config.json")
    pl.add_argument("--draft", action="store_true")
    up = sub.add_parser("upload")
    up.add_argument("day")
    up.add_argument("topic")
    up.add_argument("mp4")
    up.add_argument("--repo", default=".")
    v = sub.add_parser("verify")
    v.add_argument("day")
    v.add_argument("topic")
    v.add_argument("mp4")
    lg = sub.add_parser("log")
    lg.add_argument("day")
    lg.add_argument("entry")
    lg.add_argument("--log-dir", default="channel/log")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "today":
            print(json.dumps(today(log_dir=a.log_dir)))
        elif a.cmd == "url":
            print(raw_url(a.day, a.topic))
        elif a.cmd == "slots":
            with open(a.config, encoding="utf-8") as f:
                cfg = json.load(f)
            print(json.dumps(slots(cfg, per_day=a.per_day, log_dir=a.log_dir), indent=1))
        elif a.cmd == "numbers":
            bad = metadata_numbers(a.script, a.facts, _date(a.today))
            if bad:
                print("numbers in title/description/tags not on fact sheet: " + ", ".join(bad))
                return 1
            print("ok")
        elif a.cmd == "topics":
            print(json.dumps(topics(a.log_dir, a.topics, a.facts, a.today, a.n)))
        elif a.cmd == "stale":
            print("\n".join(stale(a.sheet, a.today)) or "none")
        elif a.cmd == "payload":
            print(json.dumps(payload(a.script, a.slot_date, a.url, a.report,
                                     config_path=a.config, draft=a.draft),
                             indent=1, ensure_ascii=False))
        elif a.cmd == "upload":
            print(upload(a.day, a.topic, a.mp4, repo=a.repo))
        elif a.cmd == "verify":
            status, length = verify(raw_url(a.day, a.topic), a.mp4)
            print(f"ok {status} {length}")
        elif a.cmd == "log":
            print(log_append(a.log_dir, a.day, a.entry))
    except (MediaError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
