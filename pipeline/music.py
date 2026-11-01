"""Procedural music bed: a soft chord pad generated in numpy (no licensed audio).

The pad is deterministic per topic. Its RMS level is set ``level_db`` below
``ref_rms`` (the voice's RMS when the renderer calls it), so it sits -24 dB
under the narration by default.
"""
import hashlib
import wave
from pathlib import Path

import numpy as np

SR = 48000
LEVEL_DB = -24.0
CHORD_SECONDS = 4.0

# Gentle progressions as semitone offsets from the root (major/minor triads + 7ths).
_PROGRESSIONS = (
    ((0, 4, 7, 11), (5, 9, 12, 16), (9, 12, 16, 19), (7, 11, 14, 17)),   # Imaj7 IVmaj7 vi7 V
    ((0, 3, 7, 10), (8, 12, 15, 19), (3, 7, 10, 14), (10, 14, 17, 21)),  # i7 VI III VII
    ((0, 4, 7, 14), (9, 12, 16, 21), (5, 9, 12, 19), (7, 11, 14, 21)),   # add9 colours
)


def _rng(topic: str) -> np.random.Generator:
    seed = int.from_bytes(hashlib.md5(str(topic).encode("utf-8")).digest()[:8], "little")
    return np.random.default_rng(seed)


def _voice(freq, t, rng):
    """One soft pad voice: two detuned sines plus a quiet octave."""
    d = 1.0 + rng.uniform(0.0015, 0.004)
    ph = rng.uniform(0, 2 * np.pi, 3)
    return (np.sin(2 * np.pi * freq * t + ph[0])
            + np.sin(2 * np.pi * freq * d * t + ph[1])
            + 0.25 * np.sin(2 * np.pi * 2 * freq * t + ph[2]))


def pad(duration: float, topic: str) -> np.ndarray:
    """Float32 mono pad in -1..1 (peak-normalised), faded in and out."""
    n = max(1, int(round(duration * SR)))
    rng = _rng(topic)
    prog = _PROGRESSIONS[int(rng.integers(len(_PROGRESSIONS)))]
    root = 110.0 * 2 ** (int(rng.integers(0, 7)) / 12)        # A2..E3
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float64)
    seg = int(CHORD_SECONDS * SR)
    xf = int(1.0 * SR)                                         # 1 s crossfade
    for k, start in enumerate(range(0, n, seg)):
        a, b = max(0, start - xf), min(n, start + seg + xf)
        tt = t[a:b]
        chord = prog[k % len(prog)]
        sig = sum(_voice(root * 2 ** (s / 12), tt, rng) for s in chord)
        env = np.ones(b - a)
        ramp = min(xf, (b - a) // 2)
        if ramp:
            env[:ramp] = np.sin(np.linspace(0, np.pi / 2, ramp)) ** 2
            env[-ramp:] = np.cos(np.linspace(0, np.pi / 2, ramp)) ** 2
        out[a:b] += sig * env
    out *= 0.85 + 0.15 * np.sin(2 * np.pi * 0.11 * t)          # slow swell
    fade = min(int(1.5 * SR), n // 3)
    if fade > 1:
        out[:fade] *= np.linspace(0, 1, fade) ** 2
        out[-fade:] *= np.linspace(1, 0, fade) ** 2
    out[0] = out[-1] = 0.0
    peak = np.abs(out).max()
    return (out / peak if peak > 0 else out).astype(np.float32)


def scaled_pad(duration: float, topic: str, ref_rms: float = 0.1,
               level_db: float = LEVEL_DB) -> np.ndarray:
    """Pad whose RMS is ``level_db`` relative to ``ref_rms``."""
    p = pad(duration, topic)
    rms = float(np.sqrt(np.mean(p.astype(np.float64) ** 2)))
    if rms <= 0:
        return p
    gain = ref_rms * 10 ** (level_db / 20) / rms
    return np.clip(p * gain, -1.0, 1.0).astype(np.float32)


def write_wav(path: Path, samples: np.ndarray, sr: int = SR) -> Path:
    path = Path(path)
    data = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())
    return path


def read_wav(path: Path) -> np.ndarray:
    """16-bit PCM wav -> float32 mono in -1..1 (channels averaged)."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit PCM")
        ch = w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data / 32768.0


def music_bed(duration: float, topic: str, path: Path, ref_rms: float = 0.1) -> Path:
    """Write a quiet pad (``LEVEL_DB`` under ``ref_rms``) of ``duration`` s to ``path``."""
    return write_wav(path, scaled_pad(duration, topic, ref_rms))
