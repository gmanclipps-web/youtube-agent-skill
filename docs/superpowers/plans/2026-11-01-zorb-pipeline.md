# Zorb Shorts Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily, fully automatic run that turns a topic into a checked, rendered Zorb Short and schedules it on YouTube through Metricool.

**Architecture:** Deterministic Python does everything that can be tested (voice, captions, drawing, encoding, checks) behind one CLI, `python3 -m pipeline.build <script.json> <outdir>`, which writes `video.mp4` and `report.json`. The daily Claude session does the judgement work (writing `script.json` with the yt-* skills) and the publishing (git push to `media`, Metricool MCP call), following `pipeline/run_day.md`.

**Tech Stack:** Python 3.13, Pillow 12, numpy, edge-tts 7.3, ffmpeg/ffprobe, pytest. Metricool MCP for publishing.

**Spec:** `docs/superpowers/specs/2026-11-01-zorb-pipeline-design.md`

## Global Constraints

- Video 1080x1920, 30 fps, H.264 + AAC, duration <= 59 s; speech 30-50 s.
- Description must contain exactly `Education, not financial advice.`; title <= 60 chars.
- Best hook score >= 55 (`skills/yt-script/hookscore.py --json`).
- Variety: title similarity < 0.8 vs last 30 days of titles; scene sequence not identical to any of the last 10 videos.
- Facts: every number in the spoken script must appear in `channel/facts/<topic>.md`.
- No licensed audio: music bed is generated in code.
- Captions stay out of the bottom 20% and right 12% of the frame.
- Publish slots 08:00, 13:00, 19:00 America/New_York; `per_day` in `channel/config.json`, default 2.
- Metricool: `blogId` 7783344, `youtubeData {type: "short", privacy: "public", category: "EDUCATION", madeForKids: false, isAiGeneratedContent: false}`, `autoPublish: true`.
- Dependencies limited to: Pillow, numpy, edge-tts, pytest (`pipeline/requirements.txt`).

## Review Focus

- Numbers written differently in script vs fact sheet ("$1,000" vs "1000", "7%" vs "7 percent") - normalise before comparing, so real facts pass and invented ones fail.
- edge-tts unreachable or rate-limited - build exits non-zero with a clear `report.json` error, no half-made video.
- A script that runs long (> 59 s once voiced) - technical check fails it rather than YouTube treating it as a long video.
- Captions vs speech mismatch from punctuation/case - compare normalised words only.
- Topic list exhausted (all used within 30 days) - run_day logs "no eligible topics" and publishes nothing.

---

## File structure

```
pipeline/__init__.py
pipeline/requirements.txt
pipeline/script_schema.py   load + validate script.json
pipeline/checks.py          facts, metadata, variety, technical checks
pipeline/voice.py           edge-tts per beat -> wav + word timings
pipeline/captions.py        word timings -> caption chunks, active word at t
pipeline/zorb.py            draw Zorb (expression, mouth, blink)
pipeline/scenes.py          8 scene painters + topic palette
pipeline/music.py           procedural music bed
pipeline/render.py          frames + audio -> mp4 via ffmpeg pipe
pipeline/build.py           CLI: script.json -> video.mp4 + report.json
pipeline/run_day.md         instructions for the daily session
pipeline/tests/...
channel/config.json  channel/topics.json  channel/facts/*.md  channel/log/
```

`script.json` shape (used by every task):

```json
{"topic": "inflation", "title": "...", "description": "...", "tags": ["..."],
 "hook_score": 61,
 "beats": [{"line": "Earth snacks cost more every year.", "scene": "price_tag",
            "expression": "confused", "props": {"from": "1", "to": "1.50"}}]}
```

Scenes: `shop, price_tag, vault, stock_chart, credit_card, planet, calendar, money_stack`.
Expressions: `neutral, confused, shocked, aha, smug`.

---

### Task 1: Script schema and content checks

**Files:**
- Create: `pipeline/__init__.py`, `pipeline/requirements.txt`, `pipeline/script_schema.py`, `pipeline/checks.py`
- Test: `pipeline/tests/test_schema.py`, `pipeline/tests/test_checks.py`

**Interfaces:**
- Produces: `load_script(path: str) -> dict` (raises `ValueError` naming the bad field); `SCENES: tuple[str, ...]`, `EXPRESSIONS: tuple[str, ...]`.
- Produces: `CheckResult = dataclass(name: str, ok: bool, detail: str)`.
- Produces: `check_facts(script: dict, facts_text: str) -> CheckResult`, `check_metadata(script) -> CheckResult`, `check_variety(script, recent: list[dict]) -> CheckResult` where each `recent` item is `{"title": str, "scenes": list[str]}`, `check_hook(script) -> CheckResult`.
- Produces: `normalise_numbers(text: str) -> set[str]` ("$1,000" -> "1000", "7 percent"/"7%" -> "7").

- [ ] **Step 1: Write failing tests**

```python
def test_load_script_rejects_unknown_scene(tmp_path): ...  # scene "beach" -> ValueError mentioning "scene"
def test_normalise_numbers():
    assert normalise_numbers("$1,000 at 7% or 7 percent, 2.5") == {"1000", "7", "2.5"}
def test_facts_pass_when_numbers_on_sheet():  # sheet has "2%" , script says "2 percent" -> ok
def test_facts_fail_on_invented_number():     # script says "9%" not on sheet -> not ok, detail contains "9"
def test_facts_fail_on_banned_phrase():       # "you should buy" / "guaranteed return" -> not ok
def test_metadata_requires_disclaimer_and_title_len():  # missing line -> fail; 61-char title -> fail
def test_variety_fails_similar_title():       # "Zorb Discovers Inflation" vs "Zorb Discovers Inflation!" -> fail
def test_variety_fails_identical_scene_sequence():
def test_hook_threshold():                    # 54 -> fail, 55 -> pass
```

- [ ] **Step 2:** Run `python3 -m pytest pipeline/tests -q` - expect import failures.
- [ ] **Step 3:** Implement. Title similarity via `difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.8`. Banned phrases list in `checks.py`: `you should buy`, `guaranteed`, `will go up`, `will crash`, `buy now`, `financial advice for you`.
- [ ] **Step 4:** Run tests - all pass.
- [ ] **Step 5:** Commit `feat: script schema and content checks`.

### Task 2: Voice with word timings

**Files:**
- Create: `pipeline/voice.py`
- Test: `pipeline/tests/test_voice.py`

**Interfaces:**
- Produces: `VOICE = "en-US-GuyNeural"`, `RATE = "+8%"`, `PITCH = "+12Hz"`.
- Produces: `synthesize(beats: list[dict], workdir: Path) -> tuple[Path, list[dict]]` returning one concatenated 48 kHz mono wav and words `[{"word": str, "start": float, "end": float, "beat": int}]` in seconds on the global timeline; 0.25 s gap between beats.
- Produces: `VoiceError(Exception)` raised on network/engine failure.

- [ ] **Step 1: Failing tests** - `test_synthesize_two_beats` (network; skip if `ZORB_OFFLINE=1`): words monotonic, beat 1 starts >= end of beat 0 + 0.25, wav duration (via ffprobe) >= last word end. `test_voice_error_on_failure` monkeypatches edge_tts.Communicate to raise -> `VoiceError`.
- [ ] **Step 2:** Run, expect FAIL.
- [ ] **Step 3:** Implement with `edge_tts.Communicate(..., boundary="WordBoundary")` streaming; offsets are 100-ns ticks; convert mp3 -> wav and concatenate with ffmpeg.
- [ ] **Step 4:** Run, PASS.
- [ ] **Step 5:** Commit `feat: edge-tts voice with word timings`.

### Task 3: Captions

**Files:**
- Create: `pipeline/captions.py`
- Test: `pipeline/tests/test_captions.py`

**Interfaces:**
- Produces: `chunk_words(words: list[dict], max_words: int = 3) -> list[dict]` -> `[{"words": [...], "start": float, "end": float}]`, never crossing a beat boundary.
- Produces: `active(chunks, t: float) -> tuple[dict | None, int]` (chunk shown at t and index of highlighted word, -1 between words).
- Produces: `caption_text(chunks) -> str` (space-joined words, for the technical check).

- [ ] **Step 1: Failing tests** - 7 words in one beat -> chunks of 3,3,1; chunk never mixes beats; `active` at a word's midpoint returns that word's index; `active` after the last end returns `(None, -1)`.
- [ ] **Step 2-4:** Run fail, implement, run pass.
- [ ] **Step 5:** Commit `feat: caption chunking`.

### Task 4: Zorb and scenes

**Files:**
- Create: `pipeline/zorb.py`, `pipeline/scenes.py`
- Test: `pipeline/tests/test_drawing.py`

**Interfaces:**
- Produces: `draw_zorb(img: Image.Image, expression: str, mouth: float, blink: bool, center: tuple[int, int], scale: float = 1.0) -> None` (mouth 0..1).
- Produces: `palette(topic: str) -> dict[str, tuple[int,int,int]]` keys `bg, fg, accent, text` - deterministic from `hashlib.md5(topic)`.
- Produces: `SCENE_PAINTERS: dict[str, Callable[[Image.Image, dict, float, dict], None]]` called as `painter(img, props, progress_0_to_1, pal)`, one per name in `SCENES`.
- Zorb occupies the lower-middle third; scenes draw in the top 55%; captions band is y 1150-1450.

- [ ] **Step 1: Failing tests** - every expression draws without error and changes pixels vs a blank canvas; `mouth=0` vs `mouth=1` images differ; every scene in `SCENES` has a painter and renders at progress 0, 0.5, 1; `palette("inflation") == palette("inflation")` and differs from `palette("stocks")`.
- [ ] **Step 2-4:** Run fail, implement with `ImageDraw` primitives only, run pass.
- [ ] **Step 5:** Commit `feat: Zorb character and scene painters`.

### Task 5: Render and build CLI

**Files:**
- Create: `pipeline/music.py`, `pipeline/render.py`, `pipeline/build.py`
- Modify: `pipeline/checks.py` (add technical check)
- Test: `pipeline/tests/test_render.py`, `pipeline/tests/test_checks.py`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: `music_bed(duration: float, topic: str, path: Path) -> Path` (quiet pad, -24 dB under voice).
- Produces: `render(script: dict, words: list[dict], voice_wav: Path, out: Path) -> Path` - streams RGB frames to `ffmpeg -f rawvideo -pix_fmt rgb24 -s 1080x1920 -r 30 -i - ...` mixed with voice + music; mouth from voice RMS per frame; blink every ~3.5 s for 4 frames.
- Produces: `check_technical(mp4: Path, spoken: str, captions: str) -> CheckResult` (ffprobe size, <= 59 s, audio stream; normalised word lists equal).
- Produces: CLI `python3 -m pipeline.build <script.json> <outdir> [--recent channel/log] [--facts channel/facts]` -> writes `video.mp4`, `report.json` `{"ok": bool, "checks": [...], "duration": float, "scenes": [...], "error": str|null}`; exit 0 only if every check passes. Content checks run BEFORE voicing (fail fast).

- [ ] **Step 1: Failing tests** - `test_render_smoke`: one-beat script with mocked words (2 s) and a generated sine wav -> mp4 where ffprobe reports 1080x1920, audio present; `test_technical_fails_over_59s` using a 60 s silent mp4 from ffmpeg `lavfi`; `test_build_fails_fast_on_bad_facts` (no voice call made).
- [ ] **Step 2-4:** Run fail, implement, run pass.
- [ ] **Step 5:** Commit `feat: renderer and build CLI`.

### Task 6: Channel content and first sample Short

**Files:**
- Create: `channel/config.json` (`{"per_day": 2, "slots": ["08:00","13:00","19:00"], "timezone": "America/New_York", "blog_id": "7783344"}`), `channel/topics.json` (12 topics: inflation, compound_interest, credit_score, stocks, interest_rates, tariffs, national_debt, printing_money, emergency_fund, budgeting_50_30_20, index_funds, taxes_basics), `channel/facts/<topic>.md` for each (facts as bullets, each with a source URL from a government/central-bank/regulator page fetched during this task), `channel/samples/inflation/script.json`.

- [ ] **Step 1:** Write facts for all 12 topics; each bullet `- <fact> (source: <url>)`.
- [ ] **Step 2:** Write the inflation script with `/yt-script` + `/yt-package`; hook >= 55.
- [ ] **Step 3:** Run `python3 -m pipeline.build channel/samples/inflation/script.json /tmp/sample` - expect exit 0 and `"ok": true`.
- [ ] **Step 4:** Extract 3 frames (`ffmpeg -ss 1,15,30`) and inspect them; fix visuals if Zorb/captions overlap or text is cut.
- [ ] **Step 5:** Commit content (not the mp4); send the sample mp4 to the owner and wait for feedback before Task 7.

### Task 7: Daily run instructions and schedule

**Files:**
- Create: `pipeline/run_day.md`

**Interfaces:**
- Consumes: build CLI, config, topics, facts, log format `channel/log/YYYY-MM-DD.json` = list of `{"topic","title","scenes","hook_score","checks","status": "scheduled"|"skipped"|"error","planner_url","media_url","reason"}`.

- [ ] **Step 1:** Write `run_day.md`: install requirements; pick topics (eligible = has facts and not in logs from the last 30 days; none -> log "no eligible topics", stop); for each: write script, build, on ok push mp4 to orphan `media` branch at `media/YYYY-MM-DD/<topic>.mp4` (on Mondays recreate the branch empty first), verify the raw URL returns 200, call Metricool `createScheduledPost` with the Global Constraints fields; on Metricool error log it and stop publishing that day; commit the log to `claude/quirky-cannon-xc1vyz` and push.
- [ ] **Step 2:** Dry run: follow `run_day.md` with `per_day: 1` and Metricool `draft: true` - confirm one draft appears (planner URL in the log), then delete it in Metricool or leave as draft and tell the owner.
- [ ] **Step 3:** Create the scheduled task: daily at 05:17 America/New_York, fresh session per fire, connectors `["Metricool"]`, prompt = "Follow pipeline/run_day.md in gmanclipps-web/youtube-agent-skill on branch claude/quirky-cannon-xc1vyz."
- [ ] **Step 4:** Commit `feat: daily run instructions`; report the schedule to the owner.
