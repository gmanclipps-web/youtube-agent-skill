"""CLI: script.json -> video.mp4 + report.json.

    python3 -m pipeline.build <script.json> <outdir> [--recent channel/log] [--facts channel/facts]
                              [--today YYYY-MM-DD]

Content checks (hook, metadata, facts, variety) run first; if any fails the
voice is never called. Exit 0 only if every check passes. "Today" (for the
title window and for expiring "(as of: ...)" fact bullets) defaults to the
America/New_York date.
"""
import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from pipeline import media as media_mod
from pipeline import render as render_mod
from pipeline.captions import caption_text, chunk_words
from pipeline.checks import (CheckResult, check_facts, check_hook, check_metadata,
                             check_technical, check_variety)
from pipeline.script_schema import load_script
from pipeline.voice import VoiceError, synthesize

TITLE_DAYS = 30
SCENE_VIDEOS = 10
_DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def today_ny() -> str:
    """Today's date in America/New_York (the channel's day), as YYYY-MM-DD."""
    return media_mod.today()["date"]


def _as_date(today):
    if today is None:
        today = today_ny()
    return date.fromisoformat(today) if isinstance(today, str) else today


def load_recent(log_dir, today=None):
    """(title_entries, scene_entries) from a log dir of YYYY-MM-DD.json files.

    Title entries: every entry in files dated within the last TITLE_DAYS days.
    Scene entries: the last SCENE_VIDEOS entries overall, oldest first.
    Entries without both "title" and "scenes" are ignored, as are files whose
    name is not a date or that do not hold a JSON list."""
    log_dir = Path(log_dir)
    today = _as_date(today)
    dated = []
    for p in log_dir.glob("*.json"):
        m = _DATED.match(p.name)
        if not m:
            continue
        try:
            day = date.fromisoformat(m.group(1))
            entries = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(entries, list):
            good = [e for e in entries if isinstance(e, dict)
                    and isinstance(e.get("title"), str) and isinstance(e.get("scenes"), list)]
            dated.append((day, good))
    dated.sort(key=lambda d: d[0])
    cutoff = today - timedelta(days=TITLE_DAYS)
    titles = [e for day, es in dated if day >= cutoff for e in es]
    everything = [e for _, es in dated for e in es]
    return titles, everything[-SCENE_VIDEOS:]


def variety(script, titles, scenes) -> CheckResult:
    """check_variety over the two windows: titles (30 days) and scenes (last 10)."""
    by_title = check_variety(script, [{"title": e["title"], "scenes": []} for e in titles])
    if not by_title.ok:
        return by_title
    by_scene = check_variety(script, [{"title": "", "scenes": e["scenes"]} for e in scenes])
    if not by_scene.ok:
        return by_scene
    return CheckResult("variety", True, f"title distinct from {len(titles)} videos "
                       f"(30 days), scenes distinct from last {len(scenes)}")


def content_checks(script, facts_dir, recent_dir, today=None) -> list:
    today = _as_date(today)
    checks = [check_hook(script), check_metadata(script)]
    facts_path = Path(facts_dir) / f"{script['topic']}.md"
    try:
        facts_text = facts_path.read_text(encoding="utf-8")
    except OSError as e:
        checks.append(CheckResult("facts", False,
                                  f"fact sheet {facts_path} not readable: {e.strerror or e}"))
    else:
        checks.append(check_facts(script, facts_text, today=today))
    titles, scenes = load_recent(recent_dir, today) if recent_dir else ([], [])
    checks.append(variety(script, titles, scenes))
    return checks


def _write_report(outdir: Path, ok, checks, duration, scenes, error):
    report = {"ok": bool(ok), "checks": [asdict(c) for c in checks],
              "duration": round(float(duration), 3), "scenes": scenes, "error": error}
    tmp = outdir / ".report.json.part"
    tmp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, outdir / "report.json")
    return report


def build(script_path, outdir, facts_dir="channel/facts", recent_dir=None, today=None) -> dict:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    video = outdir / "video.mp4"
    for stale in (video, outdir / "video.failed.mp4", outdir / "report.json"):
        stale.unlink(missing_ok=True)
    try:
        script = load_script(script_path)
    except (OSError, ValueError) as e:     # JSONDecodeError is a ValueError
        return _write_report(outdir, False, [], 0.0, [], f"bad script: {e}")
    scenes = [b["scene"] for b in script["beats"]]
    checks = content_checks(script, facts_dir, recent_dir, today)
    if not all(c.ok for c in checks):
        return _write_report(outdir, False, checks, 0.0, scenes,
                             "content checks failed; not voiced")
    try:
        with tempfile.TemporaryDirectory() as td:
            wav, words = synthesize(script["beats"], Path(td))
            render_mod.render(script, words, wav, video)
            duration = len(render_mod._read_voice(wav)) / render_mod.SR + render_mod.TAIL
    except VoiceError as e:
        return _write_report(outdir, False, checks, 0.0, scenes, f"voice failed: {e}")
    except (render_mod.RenderError, OSError, ValueError) as e:
        return _write_report(outdir, False, checks, 0.0, scenes, f"render failed: {e}")
    except Exception as e:  # anything unexpected: still a clean failed report
        if video.exists():
            video.unlink()
        return _write_report(outdir, False, checks, 0.0, scenes, f"build failed: {e!r}")
    spoken = " ".join(b["line"] for b in script["beats"])
    tech = check_technical(video, spoken, caption_text(chunk_words(words)))
    checks.append(tech)
    if not tech.ok:   # keep the file for inspection, but never as video.mp4
        os.replace(video, outdir / "video.failed.mp4")
        return _write_report(outdir, False, checks, duration, scenes,
                             "technical check failed")
    return _write_report(outdir, True, checks, duration, scenes, None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m pipeline.build",
                                 description="Build a Zorb Short from script.json")
    ap.add_argument("script")
    ap.add_argument("outdir")
    ap.add_argument("--recent", default=None, help="log dir of YYYY-MM-DD.json files")
    ap.add_argument("--facts", default="channel/facts", help="dir of <topic>.md fact sheets")
    ap.add_argument("--today", default=None, type=date.fromisoformat,
                    help="YYYY-MM-DD (default: today in America/New_York)")
    a = ap.parse_args(argv)
    report = build(a.script, a.outdir, a.facts, a.recent, a.today)
    print(json.dumps({"ok": report["ok"], "error": report["error"],
                      "failed": [c["name"] for c in report["checks"] if not c["ok"]]}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
