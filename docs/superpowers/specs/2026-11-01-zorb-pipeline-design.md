# Zorb Shorts pipeline - design

Date: 2026-11-01. Channel: @zorblipo (UCNE_32O1wt5QjP6iYtV788Q).

## Goal

Fully automatic channel: every day, write, voice, animate, check and publish 2 (later 3) YouTube
Shorts in which Zorb, an alien, tries to understand one Earth money concept. No human review per
video. Success = Shorts go public on schedule, every check passes or the video is skipped, and the
log shows what happened.

## Decisions made with the owner

| Decision | Choice |
| --- | --- |
| Human approval per video | None. Fully automatic. Automated checks stand in for review. |
| Cadence | 2 per day to start, setting `per_day` raises it to 3. |
| Where the work runs | One scheduled Claude Code cloud session per day (owner's existing plan). |
| Publishing | Metricool (already linked to the channel). No Google Cloud project. |

## Daily run

One scheduled session, created with the Metricool connector, runs `pipeline/run_day.md`
(the session's instructions) which drives these steps:

1. **Pick topics.** Next `per_day` topics from `channel/topics.json` that have a fact sheet and were
   not scheduled in the last 5 days (a topic scheduled on day D is eligible again from D + 6;
   `python3 -m pipeline.media topics`, checked against `channel/log/`). A repeat must use a
   different fact-sheet bullet as its twist than the topic's scripts of the last 30 days.
2. **Write.** One script per topic using `/yt-script` (hooks scored by `skills/yt-script/hookscore.py`,
   best hook must score 65+) and `/yt-package` (title linted by `skills/yt-package/title.py`).
   Output is `script.json`: title, description, tags, `thumb_text` (1-3 cover words, different
   words from the title, linted as a pairing with `title.py --title ... --thumb ...`), optional
   `thumb_expression`, and a list of beats `{line, scene, expression, props}`. Length 30-57
   seconds of speech.
3. **Voice.** `pipeline/voice.py` renders each line with edge-tts (one fixed Zorb voice, slight
   pitch shift) and records word timings for captions. Voice engine is swappable; ElevenLabs only if
   a key is added later.
4. **Animate + edit.** `pipeline/render.py` draws every frame in code (Pillow + numpy) and encodes
   with ffmpeg: 1080x1920, 30 fps, H.264 + AAC.
5. **Check.** `pipeline/checks.py` (below). Any failure: skip that video, log the reason.
   After every check passes, `pipeline/build.py` renders the Shorts cover `thumbnail.jpg`
   (`pipeline/thumbnail.py`) next to `video.mp4`; if the cover fails, the build fails and
   `video.mp4` is removed.
6. **Publish.** Push the MP4 and `thumbnail.jpg` to the `media` branch (orphan branch, reset
   weekly so only ~7 days of files exist), verify both raw URLs, then schedule via Metricool
   `createScheduledPost` as a YouTube Short with the cover as `videoThumbnailUrl`. If Metricool
   answers `VIDEO_THUMBNAIL_NOT_APPLICABLE`, the payload is rebuilt with `--no-thumb` and
   scheduled once more (logged as "cover rejected by Metricool").
7. **Log.** `channel/log/YYYY-MM-DD.json`: topic, title, hook score, check results, Metricool
   planner URL or skip reason. Commit and push.

Publish times: 08:00, 13:00, 19:00 America/New_York (first `per_day` slots).

## Video look

- Zorb: green, one large eye, antenna, drawn from primitives. Blinks on a timer, mouth driven by
  the voice loudness envelope, 5 expressions: confused, shocked, aha, smug, neutral.
- 8 scene types: shop, price tag, bank vault, stock chart, credit card, planet, calendar, money
  stack. Each beat names its scene; props and colours vary per topic (palette from a topic seed).
- Burned-in captions, the current word highlighted, kept inside the safe zone (away from the
  bottom 20% and right edge where YouTube overlays sit).
- Quiet procedurally generated music bed (no licensed audio).
- Beat structure: hook in the first 2 s -> Zorb's confusion -> explanation through one visual
  metaphor -> twist -> recurring sign-off line.

## Checks (all must pass)

1. **Facts.** Every number and named claim in the script appears in `channel/facts/<topic>.md`
   (each fact has a source URL). The code checks every number (digits and number words, a lone
   "one" excepted) in the spoken lines, props, title, description, tags and thumbnail text. Bullets marked
   `(as of: YYYY-MM-DD)` expire 45 days later; a number found only in expired bullets fails.
   Runs never edit fact sheets. Scripts may not recommend specific securities, predict prices,
   or give personalised advice; a banned-phrase list (checked in lines, title, description,
   tags and thumbnail text) enforces this.
2. **Technical.** ffprobe: 1080x1920, duration <= 59 s, audio stream present, captions text equals
   the spoken script.
3. **Variety.** Title not within 0.8 similarity of any title from the last 30 days; scene sequence
   differs from each of the last 10 videos.
4. **Metadata.** Description contains "Education, not financial advice."; title <= 60 chars;
   `thumb_text` shares no word of 4+ letters with the title.

## Metricool post fields

`providers [{network: youtube}]`, `youtubeData {type: short, title, privacy: public, tags,
category: EDUCATION, madeForKids: false, isAiGeneratedContent: false}`, `autoPublish: true`,
`media [raw URL]`, `videoThumbnailUrl` (raw URL of the matching `.jpg`), timezone from brand
settings.

## Failure handling

- A failed check skips that video only.
- Metricool error (for example a plan post limit): stop publishing for the day, log the error text.
- If the run itself crashes, the next day's run starts fresh; the log shows the gap.

## Files

```
pipeline/  voice.py render.py zorb.py scenes.py captions.py checks.py run_day.md publish.md
pipeline/tests/
channel/   topics.json facts/<topic>.md log/
```

## Testing

Unit tests for checks (each rule has a passing and failing case), caption timing, and a render
smoke test (2-second clip, verify with ffprobe). Before any scheduling, render one full sample
Short and send it to the owner.

## Out of scope (phase 2)

Long-form videos, ElevenLabs voice, analytics feedback loop.
