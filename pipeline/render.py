"""Render a Zorb Short: scene + captions + Zorb per frame, piped to ffmpeg.

Layout (1080x1920): scene y 0-1050, captions in the band y 1100-1400
(x 110-950, clear of the bottom 20% and right 12%), Zorb centred (540, 1660).
"""
import math
import os
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from pipeline import music
from pipeline.captions import active, chunk_words
from pipeline.scenes import SCENE_H, SCENE_PAINTERS, font, mix, palette
from pipeline.zorb import draw_zorb

FFMPEG = "ffmpeg"
W, H = 1080, 1920
FPS = 30
TAIL = 0.5
SR = 48000

CAP_TOP, CAP_BOTTOM = 1100, 1400
CAP_LEFT, CAP_RIGHT = 110, 950
CAP_PAD_X, CAP_PAD_Y = 34, 22
CAP_MAX_SIZE, CAP_MIN_SIZE = 104, 56
CAP_ONE_LINE_MIN = 80
CAP_FLOOR = 40
ELLIPSIS = "\u2026"
CAP_HOLD = 0.35          # keep a caption up through short pauses (s)
ZORB_CENTER = (540, 1660)
BLINK_EVERY = 105        # frames (3.5 s)
BLINK_FRAMES = 4


class RenderError(Exception):
    pass


# ---------------------------------------------------------------- audio

def _read_voice(path: Path) -> np.ndarray:
    """Voice wav as float32 mono at SR."""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
    a = music.read_wav(path)
    if sr != SR and len(a):
        n = int(round(len(a) * SR / sr))
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    return a


def mouth_levels(voice_wav: Path, n_frames: int, audio: np.ndarray | None = None) -> np.ndarray:
    """Per-frame mouth openness 0..1 from the voice RMS in each 1/FPS window."""
    a = _read_voice(voice_wav) if audio is None else audio
    hop = SR // FPS
    need = n_frames * hop
    a = np.pad(a[:need], (0, max(0, need - len(a))))
    rms = np.sqrt(np.mean(a.reshape(n_frames, hop).astype(np.float64) ** 2, axis=1))
    loud = rms[rms > 1e-4]
    if not len(loud):
        return np.zeros(n_frames)
    ref = max(np.percentile(loud, 95), 1e-6)
    lv = np.clip(rms / ref, 0.0, 1.0)
    lv[lv < 0.08] = 0.0                       # gate breath / noise
    return lv


def _mix(voice: np.ndarray, duration: float, topic: str) -> np.ndarray:
    n = int(round(duration * SR))
    v = np.zeros(n, dtype=np.float32)
    v[:min(n, len(voice))] = voice[:n]
    speech = voice[np.abs(voice) > 0.01]
    ref = float(np.sqrt(np.mean(speech.astype(np.float64) ** 2))) if len(speech) else 0.1
    bed = music.scaled_pad(duration, topic, ref_rms=ref)[:n]
    out = v + bed
    peak = float(np.abs(out).max()) if n else 0.0
    if peak > 0.99:
        out *= 0.99 / peak
    return out


# ---------------------------------------------------------------- timing

def beat_spans(beats: list[dict], words: list[dict], duration: float) -> list[tuple]:
    """(start, end) per beat: first word start to the next beat's first word start.
    Beat 0 starts at 0; the last beat runs to ``duration``. Beats without words
    get a zero-length span at the next beat's start."""
    n = len(beats)
    firsts = [None] * n
    for w in words:
        b = w.get("beat", 0)
        if 0 <= b < n and firsts[b] is None:
            firsts[b] = float(w["start"])
    starts = [0.0] * n
    nxt = duration
    for i in range(n - 1, 0, -1):
        nxt = firsts[i] if firsts[i] is not None else nxt
        starts[i] = nxt
    for i in range(1, n):                     # keep monotonic
        starts[i] = max(starts[i], starts[i - 1])
    ends = starts[1:] + [duration]
    return list(zip(starts, ends))


def _beat_at(spans, t):
    for i in range(len(spans) - 1, -1, -1):
        s, e = spans[i]
        if t >= s and e > s:
            return i
    return 0


# ---------------------------------------------------------------- drawing

def _base(pal) -> Image.Image:
    """Static lower half: a floor gradient under the scene, with Zorb's stage."""
    img = Image.new("RGB", (W, H), pal["bg"])
    d = ImageDraw.Draw(img)
    top, bottom = mix(pal["bg"], (0, 0, 0), 0.25), mix(pal["bg"], (0, 0, 0), 0.55)
    for y in range(SCENE_H, H):
        d.line([(0, y), (W, y)], fill=mix(top, bottom, (y - SCENE_H) / (H - SCENE_H)))
    d.line([(0, SCENE_H), (W, SCENE_H)], fill=mix(pal["bg"], pal["fg"], 0.35), width=4)
    cx, cy = ZORB_CENTER
    d.ellipse([cx - 250, cy + 150, cx + 250, cy + 250], fill=mix(bottom, pal["fg"], 0.12))
    return img


def _layout(words: list[str], size: int, max_w: int):
    """Greedy wrap of words at font size; returns (lines of (word, x_off, w), line_h)."""
    f = font(size)
    space = f.getlength(" ")
    lines, cur, cur_w = [], [], 0.0
    for i, word in enumerate(words):
        ww = f.getlength(word)
        add = ww if not cur else cur_w + space + ww
        if cur and add > max_w:
            lines.append((cur, cur_w))
            cur, cur_w = [], 0.0
            add = ww
        cur.append((i, word, ww))
        cur_w = add
    if cur:
        lines.append((cur, cur_w))
    return lines, space


def caption_layout(texts: list[str]):
    """Pick a font size for the chunk inside the band: one line if it fits at
    CAP_ONE_LINE_MIN px or more, else the largest size that fits in two lines,
    else as many lines as fit down to CAP_FLOOR px, else CAP_FLOOR px with the
    overflow cut and "…" appended. Text never leaves the band.
    Returns (size, lines, space, line_h)."""
    max_w = CAP_RIGHT - CAP_LEFT - 2 * CAP_PAD_X
    max_h = CAP_BOTTOM - CAP_TOP - 2 * CAP_PAD_Y
    for max_lines, floor in ((1, CAP_ONE_LINE_MIN), (2, CAP_MIN_SIZE), (99, CAP_FLOOR)):
        size = CAP_MAX_SIZE
        while size >= floor:
            lines, space = _layout(texts, size, max_w)
            line_h = int(size * 1.18)
            widest = max(w for _, w in lines)
            if len(lines) <= max_lines and widest <= max_w and len(lines) * line_h <= max_h:
                return size, lines, space, line_h
            size -= 4
    size, line_h = CAP_FLOOR, int(CAP_FLOOR * 1.18)
    f = font(size)
    fit_lines = max(1, max_h // line_h)
    words = list(texts)
    while words:
        shown = words[:-1] + [_clip(f, words[-1], max_w)]
        if len(words) < len(texts):
            shown[-1] = _clip(f, shown[-1] + ELLIPSIS, max_w)
        lines, space = _layout(shown, size, max_w)
        if len(lines) <= fit_lines and max(w for _, w in lines) <= max_w:
            return size, lines, space, line_h
        words.pop()
    lines, space = _layout([ELLIPSIS], size, max_w)
    return size, lines, space, line_h


def _clip(f, word: str, max_w: int) -> str:
    """Cut a single over-wide word to max_w, ending in an ellipsis."""
    if f.getlength(word) <= max_w:
        return word
    while len(word) > 1 and f.getlength(word + ELLIPSIS) > max_w:
        word = word[:-1]
    return word.rstrip(ELLIPSIS) + ELLIPSIS


def draw_caption(img: Image.Image, texts: list[str], current: int, pal: dict,
                 cache: dict | None = None):
    """Centred caption in the band; word ``current`` in the accent colour."""
    key = tuple(texts)
    if cache is not None and key in cache:
        size, lines, space, line_h = cache[key]
    else:
        size, lines, space, line_h = caption_layout(texts)
        if cache is not None:
            cache[key] = (size, lines, space, line_h)
    f = font(size)
    block_h = len(lines) * line_h
    widest = max(w for _, w in lines)
    mid_x = (CAP_LEFT + CAP_RIGHT) / 2
    mid_y = (CAP_TOP + CAP_BOTTOM) / 2
    box = [mid_x - widest / 2 - CAP_PAD_X, mid_y - block_h / 2 - CAP_PAD_Y,
           mid_x + widest / 2 + CAP_PAD_X, mid_y + block_h / 2 + CAP_PAD_Y]
    box = [max(CAP_LEFT, box[0]), max(CAP_TOP, box[1]),
           min(CAP_RIGHT, box[2]), min(CAP_BOTTOM, box[3])]
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(box, radius=28, fill=(*mix(pal["bg"], (0, 0, 0), 0.7), 205))
    region = (int(box[0]), int(box[1]), int(math.ceil(box[2])), int(math.ceil(box[3])))
    img.paste(Image.alpha_composite(img.crop(region).convert("RGBA"),
                                    overlay.crop(region)).convert("RGB"), region[:2])
    d = ImageDraw.Draw(img)
    stroke = max(2, size // 18)
    y = mid_y - block_h / 2
    for words, lw in lines:
        x = mid_x - lw / 2
        for i, word, ww in words:
            colour = pal["accent"] if i == current else pal["text"]
            d.text((x, y + line_h / 2), word, font=f, fill=colour, anchor="lm",
                   stroke_width=stroke, stroke_fill=(10, 8, 20))
            x += ww + space
        y += line_h


class Frames:
    """Draws frame ``f`` of a script; usable for stills and for the encoder."""

    def __init__(self, script: dict, words: list[dict], levels: np.ndarray, duration: float):
        self.beats = script["beats"]
        self.pal = palette(script["topic"])
        self.base = _base(self.pal)
        self.chunks = chunk_words(words)
        self.levels = levels
        self.duration = duration
        self.spans = beat_spans(self.beats, words, duration)
        self._cap_cache: dict = {}

    def caption_at(self, t: float):
        """Active chunk and word; a chunk is held up to CAP_HOLD s into a pause."""
        chunk, idx = active(self.chunks, t)
        if chunk is not None:
            return chunk, idx
        prev = None
        for c in self.chunks:                 # most recent chunk that already ended
            if c["end"] <= t:
                prev = c
        if prev is not None and t - prev["end"] <= CAP_HOLD:
            return prev, -1
        return None, -1

    def draw(self, f: int) -> Image.Image:
        t = f / FPS
        img = self.base.copy()
        bi = _beat_at(self.spans, t)
        beat = self.beats[bi]
        s, e = self.spans[bi]
        progress = 0.0 if e <= s else min(1.0, max(0.0, (t - s) / (e - s)))
        SCENE_PAINTERS[beat["scene"]](img, beat.get("props", {}), progress, self.pal)
        chunk, idx = self.caption_at(t)
        if chunk is not None:
            draw_caption(img, [w["word"] for w in chunk["words"]], idx, self.pal,
                         self._cap_cache)
        mouth = float(self.levels[f]) if f < len(self.levels) else 0.0
        blink = (f + 45) % BLINK_EVERY < BLINK_FRAMES
        draw_zorb(img, beat["expression"], mouth, blink, ZORB_CENTER, 1.0)
        return img


# ---------------------------------------------------------------- encode

def render(script: dict, words: list[dict], voice_wav: Path, out: Path,
           stats: dict | None = None) -> Path:
    """Render ``script`` with ``words`` timings and ``voice_wav`` to ``out`` (mp4).

    Writes to a temporary name and renames on success; on any failure the
    partial file is removed and RenderError is raised."""
    import time

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    voice = _read_voice(voice_wav)
    duration = len(voice) / SR + TAIL
    n_frames = int(math.ceil(duration * FPS))
    levels = mouth_levels(voice_wav, n_frames, voice)
    frames = Frames(script, words, levels, duration)
    part = out.with_name("." + out.name + ".part")
    with tempfile.TemporaryDirectory() as td:
        mix_wav = music.write_wav(Path(td) / "mix.wav", _mix(voice, duration, script["topic"]))
        cmd = [FFMPEG, "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
               "-i", "-", "-i", str(mix_wav),
               "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-c:a", "aac", "-b:a", "160k", "-ar", str(SR),
               "-t", f"{duration:.3f}", "-movflags", "+faststart",
               "-f", "mp4", str(part)]
        err_path = Path(td) / "ffmpeg.err"
        t0 = time.monotonic()
        try:
            with open(err_path, "wb") as err:
                try:
                    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err)
                except OSError as e:
                    raise RenderError(f"cannot start ffmpeg: {e}") from e
                failure = None
                try:
                    for f in range(n_frames):
                        proc.stdin.write(frames.draw(f).tobytes())
                except BrokenPipeError:
                    failure = "ffmpeg closed its input early"
                except Exception as e:
                    failure = f"frame drawing failed: {e!r}"
                    proc.kill()
                finally:
                    try:
                        proc.stdin.close()
                    except BrokenPipeError:
                        pass
                    code = proc.wait()
            if failure or code != 0:
                msg = err_path.read_text(errors="replace").strip()
                raise RenderError(f"{failure or f'ffmpeg exited {code}'}"
                                  + (f": {msg}" if msg else ""))
            os.replace(part, out)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
    if stats is not None:
        elapsed = time.monotonic() - t0
        stats.update(frames=n_frames, seconds=elapsed,
                     fps=n_frames / elapsed if elapsed > 0 else float("inf"),
                     duration=duration)
    return out
