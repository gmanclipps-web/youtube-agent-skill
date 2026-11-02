"""edge-tts narration per beat -> one 48 kHz mono wav plus word timings."""
import asyncio
import os
import ssl
import subprocess
from pathlib import Path

import edge_tts

from pipeline.captions import sentence_ends

VOICE = "en-US-GuyNeural"
RATE = "+38%"          # ~150 words/minute, the pace of winning Shorts
PITCH = "+12Hz"
GAP = 0.25
TICKS = 1e7  # edge-tts offsets are 100 ns ticks


def _trust_env_ca():
    """edge-tts pins certifi's bundle; add the environment CA (e.g. an egress
    proxy's) to its context. Verification stays on."""
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        try:
            edge_tts.communicate._SSL_CTX.load_verify_locations(cafile=ca)
        except (AttributeError, ssl.SSLError, OSError):
            pass


_trust_env_ca()


class VoiceError(Exception):
    pass


async def _stream(text: str, mp3: Path):
    comm = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH,
                                boundary="WordBoundary")
    audio = bytearray()
    words = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            start = chunk["offset"] / TICKS
            words.append({"word": chunk["text"], "start": start,
                          "end": start + chunk["duration"] / TICKS})
    if not audio:
        raise VoiceError("edge-tts returned no audio")
    mp3.write_bytes(bytes(audio))
    return words


def _ffmpeg(*args):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise VoiceError(f"ffmpeg failed: {r.stderr.strip()}")


def _duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise VoiceError(f"ffprobe failed: {r.stderr.strip()}")
    return float(r.stdout.strip())


def synthesize(beats: list[dict], workdir: Path):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    words_out: list[dict] = []
    wavs = []
    offset = 0.0
    try:
        for i, beat in enumerate(beats):
            mp3 = workdir / f"beat_{i}.mp3"
            wav = workdir / f"beat_{i}.wav"
            words = asyncio.run(_stream(beat["line"], mp3))
            # pad with the inter-beat gap so concatenation keeps timing exact
            _ffmpeg("-i", str(mp3), "-ar", "48000", "-ac", "1",
                    "-af", f"apad=pad_dur={GAP}", "-c:a", "pcm_s16le", str(wav))
            ends = sentence_ends(beat["line"], words)
            for w, end in zip(words, ends):
                words_out.append({"word": w["word"], "start": offset + w["start"],
                                  "end": offset + w["end"], "beat": i,
                                  **({"sentence_end": True} if end else {})})
            offset += _duration(wav)
            wavs.append(wav)
        listing = workdir / "concat.txt"
        listing.write_text("".join(f"file '{w.resolve()}'\n" for w in wavs))
        out = workdir / "voice.wav"
        _ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing),
                "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "1", str(out))
    except VoiceError:
        raise
    except Exception as e:  # network / engine / ffmpeg launch failures
        raise VoiceError(str(e)) from e
    return out, words_out
