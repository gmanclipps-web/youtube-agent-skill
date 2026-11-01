"""Small deterministic helpers for the daily run (see pipeline/run_day.md).

    python3 -m pipeline.media today                      # NY date, weekday, monday flag
    python3 -m pipeline.media url YYYY-MM-DD <topic>     # raw URL of the media-branch mp4
    python3 -m pipeline.media slots [--config channel/config.json] [--per-day N]
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

REPO = "gmanclipps-web/youtube-agent-skill"
BRANCH = "media"
TZ = "America/New_York"
MIN_LEAD = timedelta(minutes=20)


def media_path(day: str, topic: str) -> str:
    return f"media/{day}/{topic}.mp4"


def raw_url(day: str, topic: str) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{media_path(day, topic)}"


def _now(now, tz):
    return (now or datetime.now(ZoneInfo("UTC"))).astimezone(ZoneInfo(tz))


def today(now=None, tz=TZ) -> dict:
    d = _now(now, tz)
    return {"date": d.date().isoformat(), "weekday": d.strftime("%A"),
            "monday": d.weekday() == 0}


def slots(config: dict, now=None, per_day=None) -> list:
    """First per_day slots for today in the config timezone; a slot already past
    or less than 20 minutes away moves to the same time tomorrow."""
    tz = config.get("timezone", TZ)
    zone = ZoneInfo(tz)
    local = _now(now, tz)
    n = config.get("per_day", 2) if per_day is None else per_day
    out = []
    for hhmm in config["slots"][:n]:
        h, m = (int(x) for x in hhmm.split(":"))
        when = datetime(local.year, local.month, local.day, h, m, tzinfo=zone)
        if when - local < MIN_LEAD:
            nxt = local.date() + timedelta(days=1)
            when = datetime(nxt.year, nxt.month, nxt.day, h, m, tzinfo=zone)
        out.append({"date": when.isoformat(timespec="seconds"),
                    "publicationDate": {"dateTime": when.strftime("%Y-%m-%dT%H:%M:%S"),
                                        "timezone": tz}})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m pipeline.media")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("today")
    u = sub.add_parser("url")
    u.add_argument("day")
    u.add_argument("topic")
    s = sub.add_parser("slots")
    s.add_argument("--config", default="channel/config.json")
    s.add_argument("--per-day", type=int, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "today":
        print(json.dumps(today()))
    elif a.cmd == "url":
        print(raw_url(a.day, a.topic))
    else:
        with open(a.config, encoding="utf-8") as f:
            cfg = json.load(f)
        print(json.dumps(slots(cfg, per_day=a.per_day), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
