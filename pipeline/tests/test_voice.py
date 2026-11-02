import os
import subprocess

import pytest

from pipeline import voice

BEATS = [{"line": "Earth snacks cost more every year."},
         {"line": "That is called inflation."}]


def _dur(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


@pytest.mark.skipif(os.environ.get("ZORB_OFFLINE") == "1", reason="offline")
def test_synthesize_two_beats(tmp_path):
    wav, words = voice.synthesize(BEATS, tmp_path)
    assert wav.exists()
    assert len(words) >= 6
    starts = [w["start"] for w in words]
    assert starts == sorted(starts)
    assert all(w["end"] >= w["start"] for w in words)
    b0 = [w for w in words if w["beat"] == 0]
    b1 = [w for w in words if w["beat"] == 1]
    assert b0 and b1
    assert b1[0]["start"] >= b0[-1]["end"] + 0.25 - 1e-6
    assert _dur(wav) >= words[-1]["end"]


def test_voice_error_on_failure(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no network")
    monkeypatch.setattr(voice.edge_tts, "Communicate", boom)
    with pytest.raises(voice.VoiceError, match="no network"):
        voice.synthesize(BEATS, tmp_path)


def test_voice_rate_is_feed_speed_and_pitch_kept():
    # ~150 words/minute on the sample (measured: +8% gave 121 wpm, +38% gives 150)
    assert voice.RATE == "+38%"
    assert voice.PITCH == "+12Hz"


def test_synthesize_marks_sentence_ends(tmp_path, monkeypatch):
    async def fake_stream(text, mp3):
        import shutil
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=24000:cl=mono", "-t", "0.5", str(mp3)], check=True)
        return [{"word": w.strip(".?!"), "start": 0.01 * i, "end": 0.01 * i + 0.005}
                for i, w in enumerate(text.split())]
    monkeypatch.setattr(voice, "_stream", fake_stream)
    _, words = voice.synthesize([{"line": "Same snack. Bigger number."}], tmp_path)
    assert [w.get("sentence_end", False) for w in words] == [False, True, False, True]
