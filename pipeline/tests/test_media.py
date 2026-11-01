import json
from datetime import datetime
from zoneinfo import ZoneInfo

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
    assert s[0]["date"] == "2026-11-03T08:00:00-05:00"
    assert s[1]["date"] == "2026-11-02T13:00:00-05:00"
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
