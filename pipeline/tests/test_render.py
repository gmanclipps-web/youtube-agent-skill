import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from pipeline import build, music, render
from pipeline.checks import check_technical

DISC = "Education, not financial advice."


def _probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,r_frame_rate:format=duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _sine_wav(path, seconds=2.0, sr=48000):
    t = np.arange(int(seconds * sr)) / sr
    amp = 0.4 * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))  # wobbling level -> mouth moves
    data = (amp * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())
    return path


def _script(**over):
    s = {"topic": "inflation", "title": "Why Earth Snacks Cost More #money #inflation",
         "description": f"Zorb learns about prices. {DISC}", "tags": ["money"],
         "hook_score": 70, "thumb_text": "PRICES JUMPED?!",
         "pinned_comment": "What got pricier for you?",
         "beats": [{"line": "Earth snacks cost more.", "scene": "price_tag",
                    "expression": "confused", "props": {"from": "1", "to": "1.50"}}]}
    s.update(over)
    return s


SCENE_CYCLE = ["price_tag", "shop", "planet", "vault", "calendar", "money_stack",
               "stock_chart", "credit_card"]
LINES8 = ["Snacks cost 1 then 1.50.", "Same snack.", "Bigger number.", "Earth calls it inflation.",
          "Prices rise.", "Money shrinks.", "Zorb is puzzled.", "Why do snacks cost more?"]


def _beats8():
    return [{"line": line, "scene": sc, "expression": "confused", "props": {}}
            for line, sc in zip(LINES8, SCENE_CYCLE)]


def _words_for(beats, step=0.07):
    out = []
    for b, beat in enumerate(beats):
        for w in beat["line"].split():
            i = len(out)
            out.append({"word": w, "start": 0.05 + i * step, "end": 0.05 + i * step + step * 0.8,
                        "beat": b})
    return out


WORDS = [{"word": "Earth", "start": 0.1, "end": 0.5, "beat": 0},
         {"word": "snacks", "start": 0.55, "end": 0.95, "beat": 0},
         {"word": "cost", "start": 1.0, "end": 1.3, "beat": 0},
         {"word": "more.", "start": 1.35, "end": 1.75, "beat": 0}]


def test_music_bed_is_quiet_and_right_length(tmp_path):
    p = music.music_bed(3.0, "inflation", tmp_path / "bed.wav")
    info = _probe(p)
    assert abs(float(info["format"]["duration"]) - 3.0) < 0.05
    a = music.read_wav(p)
    assert a.max() <= 1.0 and np.abs(a).max() > 0.01
    assert abs(a[0]) < 1e-3 and abs(a[-1]) < 1e-3          # faded in and out
    b = music.read_wav(music.music_bed(3.0, "inflation", tmp_path / "b2.wav"))
    assert np.array_equal(a, b)                              # deterministic per topic


def test_mouth_levels_follow_voice(tmp_path):
    wav = _sine_wav(tmp_path / "v.wav", 2.0)
    lv = render.mouth_levels(wav, 60)
    assert len(lv) == 60
    assert lv.max() == pytest.approx(1.0) and lv.min() < 0.6


def test_render_smoke(tmp_path):
    wav = _sine_wav(tmp_path / "v.wav", 2.0)
    out = render.render(_script(), WORDS, wav, tmp_path / "video.mp4")
    assert out.exists()
    info = _probe(out)
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    a = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert (v["width"], v["height"]) == (1080, 1920)
    assert v["codec_name"] == "h264" and v["r_frame_rate"] == "30/1"
    assert a and a[0]["codec_name"] == "aac"
    assert abs(float(info["format"]["duration"]) - 2.5) < 0.15
    ok = check_technical(out, "Earth snacks cost more.", "Earth snacks cost more.")
    assert ok.ok, ok.detail


def test_render_failure_leaves_no_video(tmp_path, monkeypatch):
    wav = _sine_wav(tmp_path / "v.wav", 1.0)
    monkeypatch.setattr(render, "FFMPEG", "ffmpeg-does-not-exist")
    with pytest.raises(render.RenderError):
        render.render(_script(), WORDS, wav, tmp_path / "video.mp4")
    assert list(tmp_path.glob("*.mp4")) == []


def test_render_midway_failure_leaves_no_partial(tmp_path, monkeypatch):
    wav = _sine_wav(tmp_path / "v.wav", 1.0)
    real = render.Frames.draw

    def draw(self, f):
        if f == 3:
            raise RuntimeError("paint blew up")
        return real(self, f)
    monkeypatch.setattr(render.Frames, "draw", draw)
    with pytest.raises(render.RenderError, match="paint blew up"):
        render.render(_script(), WORDS, wav, tmp_path / "video.mp4")
    left = [p.name for p in tmp_path.iterdir() if p.name.endswith((".part", ".mp4"))]
    assert left == []


def test_caption_never_leaves_band():
    from PIL import Image
    words = ("this caption chunk is far too long to fit on "
             "without help").split()
    assert len(words) == 12
    size, lines, _, line_h = render.caption_layout(words)
    assert size >= 40
    assert len(lines) * line_h <= render.CAP_BOTTOM - render.CAP_TOP - 2 * render.CAP_PAD_Y
    pal = {"bg": (20, 20, 40), "fg": (200, 200, 220), "accent": (250, 220, 60),
           "text": (250, 250, 255)}
    img = Image.new("RGB", (1080, 1920), pal["bg"])
    render.draw_caption(img, words, 0, pal)
    a = np.asarray(img)
    outside = np.ones(a.shape[:2], bool)
    outside[render.CAP_TOP:render.CAP_BOTTOM, render.CAP_LEFT:render.CAP_RIGHT] = False
    assert (a[outside] == np.array(pal["bg"])).all()
    longer = words * 6
    size, lines, _, line_h = render.caption_layout(longer)
    assert len(lines) * line_h <= render.CAP_BOTTOM - render.CAP_TOP - 2 * render.CAP_PAD_Y
    assert lines[-1][0][-1][1].endswith("…")
    img = Image.new("RGB", (1080, 1920), pal["bg"])
    render.draw_caption(img, longer, 70, pal)
    assert (np.asarray(img)[outside] == np.array(pal["bg"])).all()


def _lavfi(path, seconds, audio=True, size="1080x1920"):
    args = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
            "-i", f"color=c=black:s={size}:r=30:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono", "-t", str(seconds),
                 "-c:a", "aac"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, check=True)
    return path


def test_technical_fails_over_59s(tmp_path):
    mp4 = _lavfi(tmp_path / "long.mp4", 60)
    r = check_technical(mp4, "hi", "hi")
    assert not r.ok and "duration" in r.detail


def test_technical_size_audio_and_words(tmp_path):
    good = _lavfi(tmp_path / "ok.mp4", 1)
    assert check_technical(good, "Save $1,000, now!", "save $1,000 now").ok
    r = check_technical(good, "Save a lot now", "save now")
    assert not r.ok and "caption" in r.detail
    r = check_technical(_lavfi(tmp_path / "mute.mp4", 1, audio=False), "a", "a")
    assert not r.ok and "audio" in r.detail
    r = check_technical(_lavfi(tmp_path / "wide.mp4", 1, size="1920x1080"), "a", "a")
    assert not r.ok and "1920x1080" in r.detail
    r = check_technical(tmp_path / "missing.mp4", "a", "a")
    assert not r.ok


# ---------------------------------------------------------------- build CLI

def _setup(tmp_path, facts="Snacks went from 1 to 1.50.", script=None):
    sp = tmp_path / "script.json"
    sp.write_text(json.dumps(script or _script(beats=_beats8())))
    fd = tmp_path / "facts"
    fd.mkdir()
    if facts is not None:
        (fd / "inflation.md").write_text(facts)
    return sp, fd


def _no_voice(monkeypatch):
    calls = []

    def fake(*a, **k):
        calls.append(a)
        raise AssertionError("voice must not be called")
    monkeypatch.setattr(build, "synthesize", fake)
    return calls


def test_build_fails_fast_on_bad_facts(tmp_path, monkeypatch):
    calls = _no_voice(monkeypatch)
    sp, fd = _setup(tmp_path, facts="Snacks went from 1 to 2.")
    out = tmp_path / "out"
    code = build.main([str(sp), str(out), "--facts", str(fd)])
    assert code == 1 and calls == []
    rep = json.loads((out / "report.json").read_text())
    assert rep["ok"] is False
    facts = [c for c in rep["checks"] if c["name"] == "facts"][0]
    assert not facts["ok"] and "1.5" in facts["detail"]
    assert not (out / "video.mp4").exists()


def test_build_missing_facts_file_fails(tmp_path, monkeypatch):
    calls = _no_voice(monkeypatch)
    sp, fd = _setup(tmp_path, facts=None)
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd)]) == 1 and calls == []
    rep = json.loads((out / "report.json").read_text())
    facts = [c for c in rep["checks"] if c["name"] == "facts"][0]
    assert not facts["ok"] and "inflation.md" in facts["detail"]


def test_build_bad_script_reports_error(tmp_path):
    sp = tmp_path / "script.json"
    sp.write_text("{}")
    out = tmp_path / "out"
    assert build.main([str(sp), str(out)]) == 1
    rep = json.loads((out / "report.json").read_text())
    assert rep["ok"] is False and "missing required field" in rep["error"]


def test_load_recent_windows(tmp_path):
    log = tmp_path / "log"
    log.mkdir()
    (log / "2026-09-01.json").write_text(json.dumps(
        [{"title": "Old Title", "scenes": ["vault"]}]))
    (log / "2026-10-30.json").write_text(json.dumps(
        [{"title": "New A", "scenes": ["shop"]}, {"note": "no title"},
         {"title": "New B", "scenes": ["planet"]}]))
    (log / "notes.json").write_text("[]")
    titles, scenes = build.load_recent(log, today="2026-11-01")
    assert [e["title"] for e in titles] == ["New A", "New B"]
    assert [e["title"] for e in scenes] == ["Old Title", "New A", "New B"]
    many = [{"title": f"T{i}", "scenes": ["shop"]} for i in range(15)]
    (log / "2026-10-31.json").write_text(json.dumps(many))
    _, scenes = build.load_recent(log, today="2026-11-01")
    assert len(scenes) == 10 and scenes[-1]["title"] == "T14"


def test_build_recent_similar_title_fails_fast(tmp_path, monkeypatch):
    calls = _no_voice(monkeypatch)
    sp, fd = _setup(tmp_path)
    log = tmp_path / "log"
    log.mkdir()
    from datetime import date
    (log / f"{date.today().isoformat()}.json").write_text(json.dumps(
        [{"title": "Why Earth Snacks Cost More!", "scenes": ["vault"]}]))
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd), "--recent", str(log)]) == 1
    assert calls == []


def test_build_voice_error_reports(tmp_path, monkeypatch):
    from pipeline.voice import VoiceError

    def fail(*a, **k):
        raise VoiceError("edge-tts rate limited")
    monkeypatch.setattr(build, "synthesize", fail)
    sp, fd = _setup(tmp_path)
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd)]) == 1
    rep = json.loads((out / "report.json").read_text())
    assert rep["ok"] is False and "rate limited" in rep["error"]
    assert not (out / "video.mp4").exists()


def test_build_end_to_end_with_fake_voice(tmp_path, monkeypatch):
    def fake(beats, workdir):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        wav = _sine_wav(Path(workdir) / "voice.wav", 2.0)
        return wav, _words_for(beats)
    monkeypatch.setattr(build, "synthesize", fake)
    sp, fd = _setup(tmp_path)
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd)]) == 0
    rep = json.loads((out / "report.json").read_text())
    assert rep["ok"] is True and rep["error"] is None
    assert rep["scenes"] == SCENE_CYCLE
    assert {c["name"] for c in rep["checks"]} == {"hook", "metadata", "pacing", "facts",
                                                  "variety", "technical"}
    assert 2.4 < rep["duration"] < 2.7
    assert (out / "video.mp4").exists()


def test_cli_module_runs(tmp_path):
    sp = tmp_path / "script.json"
    sp.write_text("{}")
    r = subprocess.run([sys.executable, "-m", "pipeline.build", str(sp), str(tmp_path / "o")],
                       cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert r.returncode == 1


def test_build_technical_failure_hides_video(tmp_path, monkeypatch):
    def fake(beats, workdir):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        wav = _sine_wav(Path(workdir) / "voice.wav", 1.0)
        return wav, [{"word": "Snacks", "start": 0.1, "end": 0.4, "beat": 0}]
    monkeypatch.setattr(build, "synthesize", fake)
    sp, fd = _setup(tmp_path)
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd)]) == 1
    rep = json.loads((out / "report.json").read_text())
    tech = [c for c in rep["checks"] if c["name"] == "technical"][0]
    assert not tech["ok"] and "captions differ" in tech["detail"]
    assert not (out / "video.mp4").exists() and (out / "video.failed.mp4").exists()


def test_build_unexpected_error_reports(tmp_path, monkeypatch):
    def fake(beats, workdir):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        return _sine_wav(Path(workdir) / "voice.wav", 1.0), WORDS

    def boom(*a, **k):
        raise KeyError("scene")
    monkeypatch.setattr(build, "synthesize", fake)
    monkeypatch.setattr(build.render_mod, "render", boom)
    sp, fd = _setup(tmp_path)
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd)]) == 1
    rep = json.loads((out / "report.json").read_text())
    assert rep["ok"] is False and rep["error"] == "build failed: KeyError('scene')"
    assert not (out / "video.mp4").exists()


def test_build_rejects_numbers_only_in_expired_bullets(tmp_path, monkeypatch):
    calls = _no_voice(monkeypatch)
    sheet = ("- Snacks went from 1 to 1.50. (as of: 2026-01-01) (source: https://a.gov/x)\n"
             "- A snack is 1 item. (source: https://a.gov/y)\n")
    sp, fd = _setup(tmp_path, facts=sheet)
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd), "--today", "2026-11-01"]) == 1
    assert calls == []
    facts = [c for c in json.loads((out / "report.json").read_text())["checks"]
             if c["name"] == "facts"][0]
    assert not facts["ok"] and "expired" in facts["detail"] and "1.5" in facts["detail"]
    checks = build.content_checks(json.loads(sp.read_text()), fd, None, today="2026-01-15")
    assert [c for c in checks if c.name == "facts"][0].ok


def test_build_default_today_is_new_york_date(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from pipeline import media
    # 03:00 UTC on Nov 2 is still Nov 1 in New York
    fixed = datetime(2026, 11, 2, 3, 0, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(media, "_now", lambda now, tz: fixed.astimezone(ZoneInfo(tz)))
    assert build.today_ny() == "2026-11-01"
    log = tmp_path / "log"
    log.mkdir()
    (log / "2026-10-02.json").write_text(json.dumps([{"title": "Edge", "scenes": ["shop"]}]))
    titles, _ = build.load_recent(log)
    assert [e["title"] for e in titles] == ["Edge"]   # 30 days before Nov 1, not Nov 2


# ---------------------------------------------------------------- cover image

def _fake_voice_ok(monkeypatch):
    def fake(beats, workdir):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        wav = _sine_wav(Path(workdir) / "voice.wav", 2.0)
        return wav, _words_for(beats)
    monkeypatch.setattr(build, "synthesize", fake)


def test_build_renders_thumbnail_next_to_video(tmp_path, monkeypatch):
    from PIL import Image
    _fake_voice_ok(monkeypatch)
    sp, fd = _setup(tmp_path)
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd)]) == 0
    rep = json.loads((out / "report.json").read_text())
    assert rep["ok"] is True and rep["thumbnail"] == "thumbnail.jpg"
    im = Image.open(out / "thumbnail.jpg")
    assert im.format == "JPEG" and im.size == (1080, 1920)
    assert (out / "video.mp4").exists()


def test_build_thumbnail_failure_removes_video(tmp_path, monkeypatch):
    _fake_voice_ok(monkeypatch)

    def boom(script, out):
        Path(out).write_bytes(b"half a jpeg")
        raise OSError("disk full")
    monkeypatch.setattr(build, "render_thumbnail", boom)
    sp, fd = _setup(tmp_path)
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd)]) == 1
    rep = json.loads((out / "report.json").read_text())
    assert rep["ok"] is False and rep["error"].startswith("thumbnail failed: ")
    assert "disk full" in rep["error"] and rep["thumbnail"] is None
    assert [c["name"] for c in rep["checks"]][-1] == "technical"
    assert not (out / "video.mp4").exists() and not (out / "thumbnail.jpg").exists()


def test_build_thumbnail_not_a_cover_fails(tmp_path, monkeypatch):
    _fake_voice_ok(monkeypatch)
    from PIL import Image

    def tiny(script, out):
        Image.new("RGB", (10, 10)).save(out, "JPEG")
        return Path(out)
    monkeypatch.setattr(build, "render_thumbnail", tiny)
    sp, fd = _setup(tmp_path)
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd)]) == 1
    rep = json.loads((out / "report.json").read_text())
    assert rep["error"].startswith("thumbnail failed: ") and "1080x1920" in rep["error"]
    assert not (out / "video.mp4").exists() and not (out / "thumbnail.jpg").exists()


def test_build_clears_stale_thumbnail(tmp_path, monkeypatch):
    calls = _no_voice(monkeypatch)
    sp, fd = _setup(tmp_path, facts="Snacks went from 1 to 2.")
    out = tmp_path / "out"
    out.mkdir()
    (out / "thumbnail.jpg").write_bytes(b"old")
    assert build.main([str(sp), str(out), "--facts", str(fd)]) == 1 and calls == []
    assert not (out / "thumbnail.jpg").exists()
    assert json.loads((out / "report.json").read_text())["thumbnail"] is None


def test_build_fails_fast_on_too_few_beats(tmp_path, monkeypatch):
    calls = _no_voice(monkeypatch)
    sp, fd = _setup(tmp_path, script=_script(beats=_beats8()[:7]))
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd)]) == 1 and calls == []
    rep = json.loads((out / "report.json").read_text())
    pacing = [c for c in rep["checks"] if c["name"] == "pacing"][0]
    assert not pacing["ok"] and "7" in pacing["detail"]


# ---------------------------------------------------------------- feed look (v2)

def _frames(beats=None, duration=12.0, **over):
    beats = beats or _beats8()
    words = []
    per = duration / len(beats)
    for b, beat in enumerate(beats):
        ws = beat["line"].split()
        for k, w in enumerate(ws):
            st = b * per + 0.1 + k * 0.3
            words.append({"word": w, "start": st, "end": st + 0.25, "beat": b})
    n = int(duration * render.FPS)
    return render.Frames(_script(beats=beats, **over), words, np.zeros(n), duration)


def _count(img, colour, box=(0, 0, 1080, 1050)):
    a = np.asarray(img.crop(box)).reshape(-1, 3)
    return int((a == np.array(colour)).all(axis=1).sum())


def test_hook_card_shows_thumb_text_from_frame_0():
    from pipeline.thumbnail import highlight_colour
    fr = _frames()
    hl = highlight_colour(fr.pal)
    first = [_count(fr.draw(f), hl) for f in (0, 3, 15)]
    white = _count(fr.draw(0), (255, 255, 255))
    assert min(first) > 4000, first          # last word in the highlight colour, big
    assert white > 8000                      # other words bold white
    late = _count(fr.draw(int(2.5 * render.FPS)), hl)
    assert late < first[0] / 4               # the card is gone after the hook


def test_hook_card_pops_in():
    from pipeline.thumbnail import highlight_colour
    fr = _frames()
    hl = np.array(highlight_colour(fr.pal))

    def width(f):
        a = np.asarray(fr.draw(f).crop((0, 0, 1080, 1050)))
        xs = np.where((a == hl).all(axis=2).any(axis=0))[0]
        return xs.max() - xs.min()
    w0, w6, w12 = width(0), width(6), width(12)
    assert 0.5 < w0 / w12 < 0.75             # starts at ~0.6 scale
    assert abs(w6 - w12) <= 2                # full size after 6 frames
    assert render.hook_scale(0) == pytest.approx(0.6)
    assert render.hook_scale(6) == pytest.approx(1.0)
    assert render.HOOK_SECONDS == pytest.approx(1.8)


def test_hook_card_and_cover_share_drawing_code():
    from pipeline import thumbnail
    assert render.draw_punch_text is thumbnail.draw_punch_text


def test_push_in_and_pop_curves():
    assert render.push_zoom(0.0) == pytest.approx(1.0)
    assert render.push_zoom(1.0) == pytest.approx(1.08)
    assert 1.0 < render.push_zoom(0.5) < 1.08
    s0, f0 = render.pop(0)
    assert s0 == pytest.approx(0.92) and 0 < f0 <= 0.35
    for k in range(5):
        s, f = render.pop(k)
        assert 0.92 <= s <= 1.0 and 0 <= f <= 0.35
    assert render.pop(5) == (1.0, 0.0) and render.pop(40) == (1.0, 0.0)


def test_scene_moves_within_a_beat_and_pops_at_beat_change():
    beats = [{"line": "Look at Earth now.", "scene": "planet", "expression": "neutral",
              "props": {}}] * 8
    fr = _frames(beats, duration=24.0, thumb_text="WOW")
    s1 = fr.spans[1][0]
    f_start, f_end = int(s1 * render.FPS) + 6, int(fr.spans[1][1] * render.FPS) - 1
    a = np.asarray(fr.draw(f_start).crop((0, 0, 1080, 1050))).astype(int)
    b = np.asarray(fr.draw(f_end).crop((0, 0, 1080, 1050))).astype(int)
    assert np.abs(a - b).mean() > 2          # push-in: the picture visibly moves
    flash = np.asarray(fr.draw(int(np.ceil(s1 * render.FPS))).crop((0, 0, 1080, 1050)))
    assert flash.mean() > a.mean() + 10      # white flash on the cut


def test_zorb_bigger_bobs_and_squashes():
    from PIL import Image
    from pipeline.zorb import draw_zorb
    assert render.ZORB_SCALE == pytest.approx(1.25)
    poses = [render.zorb_pose(f, 0) for f in range(90)]
    ys = [p[1] for p in poses]
    assert 18 <= max(ys) - min(ys) <= 21     # +-10 px bob
    period = round(1.2 * render.FPS)
    assert render.zorb_pose(10 + period, -1000)[1] == pytest.approx(
        render.zorb_pose(10, -1000)[1], abs=0.01)
    assert poses[1][3] < 0.97                # squash right after the beat starts
    assert render.zorb_pose(30, 0)[2:] == (1.0, 1.0)
    def box(expr, center, scale, stretch=(1.0, 1.0)):
        img = Image.new("RGBA", (1080, 2400), (0, 0, 0, 0))
        draw_zorb(img, expr, 1.0, False, center, scale, stretch=stretch)
        return img.getbbox()
    for expr in ("shocked", "aha", "neutral", "confused", "smug"):
        b0 = box(expr, (540, 1200), 1.0)
        for f in range(0, 40):
            cx, cy, sx, sy = render.zorb_pose(f, 0)
            x0, y0, x1, y1 = box(expr, (cx, cy), render.ZORB_SCALE, (sx, sy))
            assert x0 > 0 and x1 < 1080 and y1 <= 1920, (expr, f, y1)
            assert y0 >= render.CAP_BOTTOM, (expr, f, y0)   # never under the captions
            assert x1 - x0 >= 1.15 * (b0[2] - b0[0])         # much bigger than before


def test_captions_bigger_and_in_safe_zone():
    assert render.CAP_BOTTOM <= 0.8 * 1920 and render.CAP_RIGHT <= 0.88 * 1080
    assert render.CAP_TOP >= 1050            # below the scene
    for chunk in (["Earth", "snacks", "cost"], ["Prices", "keep", "growing."],
                  ["The", "central", "bank"], ["Same", "money."]):
        size = render.caption_layout(chunk)[0]
        assert size >= 84, (chunk, size)
