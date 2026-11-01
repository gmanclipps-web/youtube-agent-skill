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
