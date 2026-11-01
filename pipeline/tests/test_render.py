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
    s = {"topic": "inflation", "title": "Why Earth Snacks Cost More",
         "description": f"Zorb learns about prices. {DISC}", "tags": ["money"],
         "hook_score": 62,
         "beats": [{"line": "Earth snacks cost more.", "scene": "price_tag",
                    "expression": "confused", "props": {"from": "1", "to": "1.50"}}]}
    s.update(over)
    return s


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
    sp.write_text(json.dumps(script or _script(
        beats=[{"line": "Snacks cost 1 then 1.50.", "scene": "price_tag",
                "expression": "confused", "props": {}}])))
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
        words = [{"word": w, "start": 0.2 + i * 0.3, "end": 0.45 + i * 0.3, "beat": 0}
                 for i, w in enumerate("Snacks cost 1 then 1.50.".split())]
        return wav, words
    monkeypatch.setattr(build, "synthesize", fake)
    sp, fd = _setup(tmp_path)
    out = tmp_path / "out"
    assert build.main([str(sp), str(out), "--facts", str(fd)]) == 0
    rep = json.loads((out / "report.json").read_text())
    assert rep["ok"] is True and rep["error"] is None
    assert rep["scenes"] == ["price_tag"]
    assert {c["name"] for c in rep["checks"]} == {"hook", "metadata", "facts",
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
