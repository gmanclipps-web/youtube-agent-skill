import json
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from pipeline import media

NY = ZoneInfo("America/New_York")
CFG = {"per_day": 2, "slots": ["08:00", "13:00", "19:00"], "timezone": "America/New_York"}


def test_raw_url_and_path():
    assert media.media_path("2026-11-02", "stocks") == "media/2026-11-02/stocks.mp4"
    assert media.raw_url("2026-11-02", "stocks") == (
        "https://raw.githubusercontent.com/gmanclipps-web/youtube-agent-skill/"
        "media/media/2026-11-02/stocks.mp4")


def test_today_uses_new_york_date():
    # 03:00 UTC on Nov 2 is still Nov 1 (Sunday) in New York
    info = media.today(datetime(2026, 11, 2, 3, 0, tzinfo=ZoneInfo("UTC")))
    assert info == {"date": "2026-11-01", "weekday": "Sunday", "monday": False}
    info = media.today(datetime(2026, 11, 2, 9, 0, tzinfo=NY))
    assert info["monday"] is True and info["date"] == "2026-11-02"


def test_slots_future_today():
    now = datetime(2026, 11, 2, 5, 17, tzinfo=NY)
    s = media.slots(CFG, now)
    assert [x["publicationDate"] for x in s] == [
        {"dateTime": "2026-11-02T08:00:00", "timezone": "America/New_York"},
        {"dateTime": "2026-11-02T13:00:00", "timezone": "America/New_York"}]
    assert s[0]["date"] == "2026-11-02T08:00:00-05:00"


def test_slot_too_close_or_past_moves_to_tomorrow():
    now = datetime(2026, 11, 2, 7, 45, tzinfo=NY)   # 15 min before 08:00
    s = media.slots(CFG, now)
    assert s[0]["date"] == "2026-11-02T13:00:00-05:00"   # earliest free slot first
    assert s[1]["date"] == "2026-11-02T19:00:00-05:00"
    now = datetime(2026, 11, 2, 20, 0, tzinfo=NY)
    assert [x["date"][:10] for x in media.slots(CFG, now)] == ["2026-11-03", "2026-11-03"]


def test_slot_exactly_20_minutes_is_kept():
    now = datetime(2026, 11, 2, 7, 40, tzinfo=NY)
    assert media.slots(CFG, now)[0]["date"] == "2026-11-02T08:00:00-05:00"


def test_slots_per_day_override_and_dst_offset():
    now = datetime(2026, 10, 1, 5, 0, tzinfo=NY)
    s = media.slots(CFG, now, per_day=1)
    assert len(s) == 1 and s[0]["date"] == "2026-10-01T08:00:00-04:00"


def test_cli_url(capsys):
    assert media.main(["url", "2026-11-02", "stocks"]) == 0
    assert capsys.readouterr().out.strip().endswith("/media/media/2026-11-02/stocks.mp4")


def test_cli_slots_reads_config(tmp_path, capsys):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(CFG))
    assert media.main(["slots", "--config", str(p), "--per-day", "1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out) == 1 and set(out[0]) == {"date", "publicationDate"}


# ---------------------------------------------------------------- slots vs logs

def _log(d, day, entries):
    d.mkdir(exist_ok=True)
    (d / f"{day}.json").write_text(json.dumps(entries))


def test_slots_skip_slots_booked_today_or_yesterday(tmp_path):
    logs = tmp_path / "log"
    # yesterday's late run rolled its 08:00 slot to today
    _log(logs, "2026-11-01", [{"status": "scheduled", "publish_at": "2026-11-02T08:00:00-05:00"},
                              {"status": "error", "publish_at": "2026-11-02T13:00:00-05:00"}])
    _log(logs, "2026-11-02", [{"status": "scheduled", "publish_at": "2026-11-02T13:00:00-05:00"}])
    now = datetime(2026, 11, 2, 5, 17, tzinfo=NY)
    s = media.slots(CFG, now, per_day=2, log_dir=logs)
    assert [x["date"] for x in s] == ["2026-11-02T19:00:00-05:00", "2026-11-03T08:00:00-05:00"]


def test_slots_ignore_older_logs_and_bad_files(tmp_path):
    logs = tmp_path / "log"
    _log(logs, "2026-10-30", [{"status": "scheduled", "publish_at": "2026-11-02T08:00:00-05:00"}])
    (logs / "2026-11-02.json").write_text("not json")
    now = datetime(2026, 11, 2, 5, 17, tzinfo=NY)
    assert media.slots(CFG, now, per_day=1, log_dir=logs)[0]["date"] == "2026-11-02T08:00:00-05:00"


def test_slots_read_three_days_of_logs_matching_two_day_lookahead(tmp_path):
    logs = tmp_path / "log"
    # a run two days ago could book today's 08:00 (its lookahead reaches 2 days ahead)
    _log(logs, "2026-10-31", [{"status": "scheduled", "publish_at": "2026-11-02T08:00:00-05:00"}])
    now = datetime(2026, 11, 2, 5, 17, tzinfo=NY)
    assert media.slots(CFG, now, per_day=1, log_dir=logs)[0]["date"] == "2026-11-02T13:00:00-05:00"


def test_metricool_error_today(tmp_path):
    logs = tmp_path / "log"
    _log(logs, "2026-11-02", [{"status": "error", "reason": "metricool: boom"}])
    assert media.metricool_failed(logs, "2026-11-02") is True
    assert media.metricool_failed(logs, "2026-11-03") is False
    _log(logs, "2026-11-03", [{"status": "error", "reason": "voice failed: x"}])
    assert media.metricool_failed(logs, "2026-11-03") is False


# ---------------------------------------------------------------- log append

def _entry(**over):
    e = {k: None for k in media.LOG_KEYS}
    e.update({"topic": "stocks", "scenes": [], "checks": [], "status": "skipped", "reason": "x"})
    e.update(over)
    return e


def test_log_append_creates_and_appends(tmp_path):
    logs = tmp_path / "log"
    src = tmp_path / "e.json"
    src.write_text(json.dumps(_entry()))
    media.log_append(logs, "2026-11-02", src)
    media.log_append(logs, "2026-11-02", src)
    data = json.loads((logs / "2026-11-02.json").read_text())
    assert len(data) == 2 and data[0]["topic"] == "stocks"


def test_log_append_rejects_bad_entries(tmp_path):
    src = tmp_path / "e.json"
    for bad in ({"topic": "x"}, _entry(status="done"), _entry(status="skipped", title="T")):
        src.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            media.log_append(tmp_path / "log", "2026-11-02", src)
    assert not (tmp_path / "log" / "2026-11-02.json").exists()


def test_log_append_refuses_corrupt_log(tmp_path):
    logs = tmp_path / "log"
    logs.mkdir()
    (logs / "2026-11-02.json").write_text("{oops")
    src = tmp_path / "e.json"
    src.write_text(json.dumps(_entry()))
    with pytest.raises(ValueError):
        media.log_append(logs, "2026-11-02", src)
    assert (logs / "2026-11-02.json").read_text() == "{oops"


# ---------------------------------------------------------------- metadata numbers

SHEET = "# T\n\n- A basket that cost $100 now costs $107, 7 percent, in 2026. (source: https://x.gov/a_10142026.htm)\n"


def _meta_script(tmp_path, **over):
    s = {"title": "Zorb Learns Why $100 Buys Less", "description":
         "Zorb sees 7 percent.\n\nEducation, not financial advice.\n\n#Shorts #inflation #money",
         "tags": ["inflation", "7 percent inflation"]}
    s.update(over)
    p = tmp_path / "s.json"
    p.write_text(json.dumps(s))
    f = tmp_path / "f.md"
    f.write_text(SHEET)
    return p, f


def test_metadata_numbers_ok(tmp_path):
    assert media.metadata_numbers(*_meta_script(tmp_path)) == []


def test_metadata_numbers_flags_unknown(tmp_path):
    p, f = _meta_script(tmp_path, title="Zorb 2025 vs $1,000", tags=["50 dollars"],
                        description="x #budget503020")
    assert media.metadata_numbers(p, f) == ["1000", "2025", "50", "503020"]


def test_metadata_numbers_ignores_url_numbers_on_sheet(tmp_path):
    p, f = _meta_script(tmp_path, title="Zorb 10142026")
    assert media.metadata_numbers(p, f) == ["10142026"]


def test_cli_numbers_exit_code(tmp_path, capsys):
    p, f = _meta_script(tmp_path)
    assert media.main(["numbers", str(p), str(f)]) == 0
    p, f = _meta_script(tmp_path, title="Zorb 99")
    assert media.main(["numbers", str(p), str(f)]) == 1
    assert "99" in capsys.readouterr().out


# ---------------------------------------------------------------- verify

class _Head:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self, url):
        self.calls += 1
        return self.answers.pop(0)


def test_verify_ok_after_retry(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x" * 10)
    head = _Head([(404, None), (200, 10)])
    sleeps = []
    assert media.verify("u", v, head=head, sleep=sleeps.append) == (200, 10)
    assert head.calls == 2 and sleeps == [15]


def test_verify_fails_on_length_mismatch(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x" * 10)
    head = _Head([(200, 9)] * 5)
    with pytest.raises(media.MediaError, match="200 9 vs 10"):
        media.verify("u", v, head=head, sleep=lambda s: None)
    assert head.calls == 5


def test_parse_head_takes_final_response():
    raw = ("HTTP/1.1 200 Connection established\r\n\r\n"
           "HTTP/2 200\r\ncontent-type: application/octet-stream\r\nContent-Length: 1234\r\n\r\n")
    assert media.parse_head(raw) == (200, 1234)
    assert media.parse_head("") == (None, None)


# ---------------------------------------------------------------- push retries

def test_push_retries_network_errors_then_gives_up():
    calls, sleeps = [], []

    def run(args):
        calls.append(args)
        return 128, "fatal: unable to access: Could not resolve host"
    with pytest.raises(media.MediaError):
        media.push_with_retry(run, ["push"], sleep=sleeps.append)
    assert len(calls) == 5 and sleeps == [2, 4, 8, 16]


def test_push_does_not_retry_rejection():
    calls = []

    def run(args):
        calls.append(args)
        return 1, " ! [rejected] media -> media (non-fast-forward)"
    with pytest.raises(media.MediaError, match="rejected"):
        media.push_with_retry(run, ["push"], sleep=lambda s: None)
    assert len(calls) == 1


# ---------------------------------------------------------------- upload (local bare origin)

def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null",
                 "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(k, v)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    (work / "keep.txt").write_text("main checkout file\n")
    _git(work, "add", "keep.txt")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "main")
    (work / "untracked.txt").write_text("must survive\n")
    return work, origin


def _mp4(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _files(origin):
    out = _git(origin, "ls-tree", "-r", "--name-only", "media")
    return sorted(out.splitlines())


def test_upload_creates_orphan_branch_and_leaves_checkout_alone(repo, tmp_path):
    work, origin = repo
    v = _mp4(tmp_path, "a.mp4", b"video-a")
    url = media.upload("2026-11-01", "stocks", v, repo=work, sleep=lambda s: None)
    assert url == media.raw_url("2026-11-01", "stocks")
    assert _files(origin) == ["media/2026-11-01/stocks.mp4"]
    assert _git(origin, "rev-list", "--count", "media") == "1"      # orphan: no main history
    assert _git(origin, "show", "media:media/2026-11-01/stocks.mp4") == "video-a"
    assert _git(work, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _git(work, "status", "--porcelain") == "?? untracked.txt"
    assert (work / "keep.txt").exists()


def test_upload_appends_on_normal_days_and_is_idempotent(repo, tmp_path):
    work, origin = repo
    media.upload("2026-11-01", "stocks", _mp4(tmp_path, "a.mp4", b"a"), repo=work)
    media.upload("2026-11-01", "taxes_basics", _mp4(tmp_path, "b.mp4", b"b"), repo=work)
    media.upload("2026-11-01", "taxes_basics", _mp4(tmp_path, "b.mp4", b"b"), repo=work)
    assert _files(origin) == ["media/2026-11-01/stocks.mp4", "media/2026-11-01/taxes_basics.mp4"]
    assert _git(origin, "rev-list", "--count", "media") == "2"


def test_upload_monday_resets_keeping_yesterday_and_today(repo, tmp_path):
    work, origin = repo
    for day in ("2026-10-31", "2026-11-01"):           # Saturday, Sunday
        media.upload(day, "stocks", _mp4(tmp_path, "a.mp4", day.encode()), repo=work)
    media.upload("2026-11-02", "inflation", _mp4(tmp_path, "c.mp4", b"c"), repo=work)  # Monday
    assert _files(origin) == ["media/2026-11-01/stocks.mp4", "media/2026-11-02/inflation.mp4"]
    assert _git(origin, "rev-list", "--count", "media") == "1"
    # second Monday upload (same day, or a rerun) must not reset again
    media.upload("2026-11-02", "tariffs", _mp4(tmp_path, "d.mp4", b"d"), repo=work)
    assert _files(origin) == ["media/2026-11-01/stocks.mp4", "media/2026-11-02/inflation.mp4",
                              "media/2026-11-02/tariffs.mp4"]


def test_upload_missing_file_errors(repo, tmp_path):
    work, _ = repo
    with pytest.raises(media.MediaError, match="no such file"):
        media.upload("2026-11-01", "stocks", tmp_path / "nope.mp4", repo=work)


def test_cli_upload_prints_url(repo, tmp_path, capsys):
    work, _ = repo
    v = _mp4(tmp_path, "a.mp4", b"a")
    assert media.main(["upload", "2026-11-01", "stocks", str(v), "--repo", str(work)]) == 0
    assert capsys.readouterr().out.strip() == media.raw_url("2026-11-01", "stocks")
    assert media.main(["upload", "2026-11-01", "stocks", str(tmp_path / "x"),
                       "--repo", str(work)]) == 1



# ---------------------------------------------------------------- topics

TOPIC_IDS = [f"t{i:02d}" for i in range(12)]


def _topic_setup(tmp_path, ids=TOPIC_IDS, sheets=None):
    tp = tmp_path / "topics.json"
    tp.write_text(json.dumps([{"id": t, "title_seed": "x"} for t in ids]))
    facts = tmp_path / "facts"
    facts.mkdir()
    for t in (ids if sheets is None else sheets):
        (facts / f"{t}.md").write_text("- x (source: https://a.gov)\n")
    logs = tmp_path / "log"
    logs.mkdir()
    return logs, tp, facts


def _add(logs, day, topic, status="scheduled"):
    p = logs / f"{day}.json"
    data = json.loads(p.read_text()) if p.exists() else []
    data.append({"topic": topic, "status": status})
    p.write_text(json.dumps(data))


def test_topics_six_day_window(tmp_path):
    logs, tp, facts = _topic_setup(tmp_path)
    _add(logs, "2026-10-27", "t00")          # 5 days before Nov 1: still excluded
    _add(logs, "2026-10-26", "t01")          # 6 days before: eligible again
    _add(logs, "2026-10-26", "t02", "skipped")
    out = media.topics(logs, tp, facts, today="2026-11-01")
    assert "t00" not in out and "t01" in out
    assert out[:2] == ["t03", "t04"]          # never used, never tried come first
    assert out.index("t02") > out.index("t11") and out[-1] == "t01"   # used longest ago last


def test_topics_exclude_tried_today_and_missing_sheet_and_limit(tmp_path, capsys):
    logs, tp, facts = _topic_setup(tmp_path, sheets=TOPIC_IDS[1:])
    _add(logs, "2026-11-01", "t05", "skipped")
    out = media.topics(logs, tp, facts, today="2026-11-01")
    assert "t00" not in out and "t05" not in out and len(out) == 10
    assert media.topics(logs, tp, facts, today="2026-11-01", n=3) == ["t01", "t02", "t03"]
    assert media.main(["topics", "--log-dir", str(logs), "--topics", str(tp), "--facts",
                       str(facts), "--n", "2", "--today", "2026-11-01"]) == 0
    assert json.loads(capsys.readouterr().out) == ["t01", "t02"]


def test_topics_twelve_topics_two_a_day_never_run_dry(tmp_path):
    from datetime import date, timedelta
    logs, tp, facts = _topic_setup(tmp_path)
    start = date(2026, 11, 1)
    for k in range(60):
        day = (start + timedelta(days=k)).isoformat()
        pick = media.topics(logs, tp, facts, today=day, n=4)
        assert len(pick) >= 2, (day, pick)
        for t in pick[:2]:
            _add(logs, day, t)


def test_topics_ignore_bad_log_files(tmp_path):
    logs, tp, facts = _topic_setup(tmp_path)
    (logs / "2026-10-31.json").write_text("{oops")
    (logs / "notes.json").write_text(json.dumps([{"topic": "t00", "status": "scheduled"}]))
    assert len(media.topics(logs, tp, facts, today="2026-11-01")) == 12


# ---------------------------------------------------------------- stale

STALE_SHEET = ("# T\n\n- Timeless 2 percent. (source: https://a.gov/x)\n"
               "- Latest was 3.7 percent. (as of: 2026-10-14) (source: https://a.gov/y)\n")


def test_stale_lists_expired_bullets(tmp_path, capsys):
    f = tmp_path / "f.md"
    f.write_text(STALE_SHEET)
    assert media.main(["stale", str(f), "--today", "2026-11-28"]) == 0
    assert capsys.readouterr().out.strip() == "none"
    assert media.main(["stale", str(f), "--today", "2026-11-29"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and "3.7 percent" in out[0]


def test_metadata_numbers_word_numbers_and_expiry(tmp_path):
    p, f = _meta_script(tmp_path, title="Zorb Counts Fifty Snacks")
    assert media.metadata_numbers(p, f) == ["50"]
    p, f = _meta_script(tmp_path)
    f.write_text("- $100 to $107, 7 percent in 2026. (as of: 2026-01-01) (source: https://a.gov)\n")
    assert media.metadata_numbers(p, f, today="2026-11-01") == ["100", "7"]
    assert media.metadata_numbers(p, f, today="2026-01-02") == []


# ---------------------------------------------------------------- payload

DESC = 'Zorb finds "prices" rise.\n\nEducation, not financial advice.\n\n#Shorts #inflation #money'
URL = "https://raw.githubusercontent.com/gmanclipps-web/youtube-agent-skill/media/media/2026-11-02/inflation.mp4"


def _payload_setup(tmp_path, ok=True, video=True):
    sp = tmp_path / "script.json"
    sp.write_text(json.dumps({"topic": "inflation", "title": "Zorb Learns Why $100 Buys Less",
                              "description": DESC, "tags": ["inflation", "Zorb"],
                              "hook_score": 70, "thumb_text": "SNACKS COST MORE?!",
                              "beats": [{"line": "Hi.", "scene": "shop",
                                         "expression": "neutral", "props": {}}]}))
    out = tmp_path / "out"
    out.mkdir()
    (out / "report.json").write_text(json.dumps({"ok": ok, "checks": [], "error": None}))
    if video:
        (out / "video.mp4").write_bytes(b"x")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({**CFG, "blog_id": "7783344"}))
    return sp, out / "report.json", cfg


def test_payload_exact_arguments(tmp_path, capsys):
    sp, rp, cfg = _payload_setup(tmp_path)
    assert media.main(["payload", str(sp), "2026-11-02T08:00:00-05:00", URL, str(rp),
                       "--config", str(cfg)]) == 0
    args = json.loads(capsys.readouterr().out)
    assert set(args) == {"blogId", "date", "info"}
    assert args["blogId"] == "7783344" and args["date"] == "2026-11-02T08:00:00-05:00"
    assert isinstance(args["info"], str)
    info = json.loads(args["info"])
    assert info == {
        "providers": [{"network": "youtube"}], "text": DESC, "media": [URL],
        "publicationDate": {"dateTime": "2026-11-02T08:00:00", "timezone": "America/New_York"},
        "autoPublish": True, "draft": False, "descendants": [], "firstCommentText": "",
        "hasNotReadNotes": False, "mediaAltText": [], "shortener": False,
        "smartLinkData": {"ids": []},
        "youtubeData": {"title": "Zorb Learns Why $100 Buys Less", "type": "short",
                        "privacy": "public", "tags": ["inflation", "Zorb"],
                        "category": "EDUCATION", "madeForKids": False,
                        "isAiGeneratedContent": False}}


def test_payload_draft_flag(tmp_path):
    sp, rp, cfg = _payload_setup(tmp_path)
    args = media.payload(sp, "2026-07-02T19:00:00-04:00", URL, rp, config_path=cfg, draft=True)
    info = json.loads(args["info"])
    assert info["draft"] is True and info["publicationDate"]["dateTime"] == "2026-07-02T19:00:00"


def test_payload_refuses_unless_report_ok_and_video_present(tmp_path, capsys):
    sp, rp, cfg = _payload_setup(tmp_path, ok=False)
    assert media.main(["payload", str(sp), "2026-11-02T08:00:00-05:00", URL, str(rp),
                       "--config", str(cfg)]) == 1
    assert "ok" in capsys.readouterr().err
    for kw in ({"ok": True, "video": False},):
        d = tmp_path / "b"
        d.mkdir()
        sp, rp, cfg = _payload_setup(d, **kw)
        with pytest.raises(media.MediaError, match="video.mp4"):
            media.payload(sp, "2026-11-02T08:00:00-05:00", URL, rp, config_path=cfg)
    rp.unlink()
    with pytest.raises((media.MediaError, OSError)):
        media.payload(sp, "2026-11-02T08:00:00-05:00", URL, rp, config_path=cfg)


def test_payload_rejects_bad_slot_and_url(tmp_path):
    sp, rp, cfg = _payload_setup(tmp_path)
    for bad in ("2026-11-02T08:00:00", "2026-11-02T13:00:00+00:00", "tomorrow"):
        with pytest.raises(media.MediaError, match="slot"):
            media.payload(sp, bad, URL, rp, config_path=cfg)
    for bad in ("http://example.com/x.mp4", URL.replace("inflation.mp4", "stocks.mp4")):
        with pytest.raises(media.MediaError, match="url"):
            media.payload(sp, "2026-11-02T08:00:00-05:00", bad, rp, config_path=cfg)


def test_slots_prefer_later_today_over_rolled_morning_slot():
    now = datetime(2026, 11, 1, 11, 45, tzinfo=NY)   # 08:00 passed; 13:00 and 19:00 still open
    s = media.slots(CFG, now, per_day=3)
    assert [x["date"] for x in s] == ["2026-11-01T13:00:00-05:00",
                                       "2026-11-01T19:00:00-05:00",
                                       "2026-11-02T08:00:00-05:00"]


def test_upload_jpg_cover_next_to_video(repo, tmp_path):
    work, origin = repo
    media.upload("2026-11-01", "stocks", _mp4(tmp_path, "a.mp4", b"v"), repo=work, sleep=lambda s: None)
    url = media.upload("2026-11-01", "stocks", _mp4(tmp_path, "t.jpg", b"j"), repo=work,
                       sleep=lambda s: None)
    assert url == media.raw_url("2026-11-01", "stocks", "jpg")
    assert url.endswith("/media/2026-11-01/stocks.jpg")
    assert _files(origin) == ["media/2026-11-01/stocks.jpg", "media/2026-11-01/stocks.mp4"]


def test_upload_rejects_other_file_types(repo, tmp_path):
    work, _ = repo
    with pytest.raises(media.MediaError, match="unsupported"):
        media.upload("2026-11-01", "stocks", _mp4(tmp_path, "x.png", b"p"), repo=work,
                     sleep=lambda s: None)
