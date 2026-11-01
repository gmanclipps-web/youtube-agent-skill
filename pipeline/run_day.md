# Daily run: publish Zorb Shorts for @zorblipo

You are an unattended Claude Code session. Nobody will answer questions. Follow this file
top to bottom, exactly. **When anything is unclear, skip that topic and log why. Never guess.**

Repo: `gmanclipps-web/youtube-agent-skill`. Work branch: `claude/quirky-cannon-xc1vyz`.
All commands run from the repo root unless a step says otherwise.

## 0. Hard rules (read before doing anything)

1. Never publish (schedule) a video whose `report.json` has `"ok": false`, or whose
   `video.mp4` is missing.
2. Never edit anything under `pipeline/` or `skills/`, never weaken a check, never change
   `channel/config.json` or `channel/topics.json`. If the code seems broken, log it and stop.
3. Never delete or rewrite an existing log entry. Logs are append-only.
4. Never invent a number, a fact or a source. Never cite a page you did not read in this session
   or that is not already on the fact sheet.
5. Content is education only: never recommend a specific stock, fund, coin or other security,
   never predict prices or returns, never give personalised advice, never use imperative advice
   ("you should...", "buy...", "start saving..."). Describe how Earth money works; do not tell
   anyone what to do. If a fact-sheet bullet sounds like advice, use it only descriptively
   ("Earth guides say many people keep...") or not at all.
6. Do not call any Metricool tool other than `createScheduledPost`. Never call it twice for the
   same topic. After any Metricool error, schedule nothing more today.
7. The `media` branch only ever holds the mp4 files described in step 5. Never put anything else
   there, and never force-push any other branch.
8. Use the timezone `America/New_York` for every date in this file ("today" = the New York date).

## Dry run

The owner may start you with "dry run". Then do everything below exactly the same, with only
these differences:

- use `PER_DAY=1` instead of `per_day` from the config (step 1); do not edit the config,
- in step 6 send `"draft": true` instead of `"draft": false` (everything else identical),
- when the draft was created, log it with `"status": "skipped"` (a draft is not a published
  video, so the topic stays eligible for real runs), `"reason": "dry run: draft only"`, and
  still fill `planner_url`, `media_url` and `publish_at`.

A dry run still commits and pushes its log, script and media like a real run. Say "DRY RUN"
at the start of the final summary.

## 1. Set up

```bash
git status --short --branch          # must be on claude/quirky-cannon-xc1vyz
git pull --ff-only origin claude/quirky-cannon-xc1vyz
pip install -q -r pipeline/requirements.txt
cat channel/config.json
python3 -m pipeline.media today      # {"date": "YYYY-MM-DD", "weekday": ..., "monday": ...}
```

- If you are not on `claude/quirky-cannon-xc1vyz`, run `git checkout claude/quirky-cannon-xc1vyz`.
  If that fails, stop (nothing to log against; report it in the summary).
- If `pip install` fails, retry once; if it still fails, log one entry
  (`"topic": null`, `"status": "error"`, `"reason"` = the pip error's last line), do step 7, stop.
- Remember `TODAY` = the `date` printed above and `MONDAY` = the `monday` flag.
  `PER_DAY` = `per_day` from `channel/config.json` (1 in a dry run).
- The log file is `channel/log/TODAY.json`. If it exists, read it: it is a JSON list. Count its
  entries with `"status": "scheduled"`; if that count is already `>= PER_DAY`, today is done
  (a rerun): write nothing, finish with the summary.
  Otherwise `REMAINING` = `PER_DAY` minus that count (normally `REMAINING` = `PER_DAY`).
- Work directory for build files: `/tmp/zorb/TODAY/<topic>/` (not committed).

## 2. Choose topics

Run this exactly; it prints the eligible topic ids in the order to try them:

```bash
python3 - <<'PY'
import json, re
from datetime import date, timedelta
from pathlib import Path
from pipeline.media import today
TODAY = date.fromisoformat(today()["date"])
topics = [t["id"] for t in json.loads(Path("channel/topics.json").read_text())]
last_sched, last_try = {}, {}
for p in sorted(Path("channel/log").glob("*.json")):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", p.name):
        continue
    day = p.stem
    try:
        entries = json.loads(p.read_text())
    except ValueError:
        continue
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict) or not e.get("topic"):
            continue
        last_try[e["topic"]] = max(last_try.get(e["topic"], ""), day)
        if e.get("status") == "scheduled":
            last_sched[e["topic"]] = max(last_sched.get(e["topic"], ""), day)
cutoff = (TODAY - timedelta(days=30)).isoformat()
eligible = [t for t in topics
            if Path(f"channel/facts/{t}.md").is_file()
            and last_sched.get(t, "") < cutoff          # not scheduled in the last 30 days
            and last_try.get(t, "") != TODAY.isoformat()]  # not already tried today
eligible.sort(key=lambda t: (last_sched.get(t, ""), last_try.get(t, ""), topics.index(t)))
print(json.dumps(eligible))
PY
```

- A topic is "used" when a log entry for it has `"status": "scheduled"`. Never-used topics come
  first, then the ones used longest ago; topics tried and skipped recently go later.
- If the list is empty: append one entry `{"topic": null, "status": "skipped",
  "reason": "no eligible topics", ...}` (all other fields null / empty, see step 7), do step 7, stop.
- Work through the list in order, one topic at a time (steps 3-6), then the next. Stop when
  `REMAINING` topics are scheduled, when you have attempted `REMAINING + 2` topics, or when
  the list runs out. Each attempted topic gets exactly
  one log entry.

## 3. For each topic: check the fact sheet

Read `channel/facts/<topic>.md` in full. Each bullet ends with `(source: URL)`.

**Freshness.** For every bullet that states a calendar date (e.g. "release of October 14, 2026",
"12 months ending September 2026", "as of 2026"), take the most recent date it states (a month
counts as its last day, a bare year as December 31). If that date is more than 45 days before
TODAY, the bullet is **stale**: do not use any of its numbers in the script or props.
Bullets without dates (definitions, rules, fixed examples) are fine.

You may refresh a stale bullet, only like this:
1. Fetch the bullet's own source (same agency or organisation) with WebFetch or Firecrawl and
   actually read the current figure on the page.
2. Rewrite the bullet with the new figure, the new date stated on the page, and a stable URL for
   that exact release (an archive/permalink URL of the release, not a "latest" page, when the
   source offers one).
3. Commit it alone: `git add channel/facts/<topic>.md && git commit -m "facts: refresh <topic>"`.

If the fetch fails or the page does not state the figure clearly, leave the sheet unchanged and
just avoid that bullet. Never add a bullet from a source you did not read. If fewer than two
non-stale bullets with something concrete to say remain, skip the topic
(`"reason": "fact sheet stale"`).

## 4. For each topic: write the script, then build

### 4a. Voice and shape

Copy the shape of `channel/samples/inflation/script.json` (read it now; it passes every check).

- Zorb is a small, curious, baffled, funny alien reporting on Earth money. Zorb talks to
  "Earthlings", in short sentences, present tense, no jargon without a one-line explanation.
- 75-120 spoken words in total (about 30-50 seconds), 6-9 beats, one idea per beat.
- Structure: **hook** (beat 1) -> **confusion** (Zorb does not get it) -> **one visual
  metaphor** carried over 2-3 beats -> **twist** (the surprising true fact) -> sign-off.
- The last beat's line is exactly: `Zorb will return. Earth money remains confusing.`
  (scene `planet`, expression `smug`, props `{}`).
- At least 4 distinct scenes, and the scene sequence must not copy any recent video's
  sequence (the build checks this against the last 10 logged videos).
- Scenes: `shop, price_tag, vault, stock_chart, credit_card, planet, calendar, money_stack`.
  Expressions: `neutral, confused, shocked, aha, smug`. Vary the expressions.
- **Every number** spoken in a line, in a prop or in the title must appear on the topic's fact
  sheet (in a non-stale bullet). Write numbers as digits ("7 percent", "100 dollars") so the
  checker can match them. Years, ages and counts are numbers too ("15 years" needs a 15 on the
  sheet). If you are unsure a number is there, leave it out.
- Banned in any line (the build fails on these): "you should buy", "guaranteed", "will go up",
  "will crash", "buy now", "financial advice for you". Also obey hard rule 5.

### 4b. Props: every numeric scene gets explicit numbers

Painters show "?" when a number prop is missing. Avoid that: give every numeric scene its props,
taken from the sheet, or use a non-numeric scene instead.

| scene | props |
|---|---|
| `shop` | `item` (box label, <= 10 chars), `price` (burst text, e.g. `"$100"`; shows "?" if absent: always set it) |
| `price_tag` | `from`, `to` (numbers or numeric strings, e.g. `"100"`, `"107"`), optional `currency` (default `"$"`). Always set both. |
| `credit_card` | `apr` (number gets a "%" added, e.g. `22.8`), `balance` (e.g. `"1000"`). Always set both. |
| `money_stack` | `amount` (total shown above the stacks), optional `currency`. Set it, or the scene has no total. |
| `stock_chart` | `trend` (`"up"` or `"down"`), `label` (<= 8 chars headline, e.g. `"+7%"`; defaults to UP/DOWN) |
| `calendar` | `years` (int, pages read YEAR 1..n) or `start` (month name, 6 months flip) |
| `vault` | `label` (<= 12 chars), optional `open` (bool) |
| `planet` | `label` (<= 12 chars, default "EARTH") |

Text props are upper-cased and cut to the lengths above; keep labels short.

### 4c. Hook (skills/yt-script/SKILL.md)

Write FIVE hook options for beat 1 (each one Zorb's opening line, using the formulas in
`skills/yt-script/hooks.json`) and score each:

```bash
python3 skills/yt-script/hookscore.py --json --hook "<hook option>"
```

Use the one with the highest `verdict` as beat 1's `line`, word for word, and put that
`verdict` (an integer) in `hook_score`. It must be `>= 55`. If none reaches 55, write five
more; if still none, skip the topic (`"reason": "no hook >= 55"`). Never type a score you did
not get from the tool.

### 4d. Title, description, tags (skills/yt-package/SKILL.md)

- Title: starts with `Zorb`, at most 60 characters, plays on the topic's `title_seed` in
  `channel/topics.json`, a concrete number from the sheet if it fits. Write 5 options, run
  each through `python3 skills/yt-package/title.py --json --title "<title>"`, take the best
  score. It must not resemble a title from the last 30 days of logs.
- Description: 2-3 plain sentences (what Zorb discovers; name the source organisation of the
  figures), then a blank line, then exactly `Education, not financial advice.`, then a blank
  line, then 3 hashtags on one line, the first being `#Shorts` (e.g.
  `#Shorts #inflation #personalfinance`). No links, no advice.
- Tags: 5-10 short search phrases (topic name, "<topic> explained", "personal finance",
  "money basics", "Zorb", "cartoon alien" ...).

### 4e. Save and pre-check

Write the script to `/tmp/zorb/TODAY/<topic>/script.json` with the fields
`topic, title, description, tags, hook_score, beats` (each beat: `line, scene, expression, props`).
Count the words:

```bash
python3 -c "import json,sys; s=json.load(open(sys.argv[1])); print(sum(len(b['line'].split()) for b in s['beats']), len(s['beats']), len({b['scene'] for b in s['beats']}))" /tmp/zorb/TODAY/<topic>/script.json
```

Must print words 75-120, beats 6-9, distinct scenes >= 4; fix the script until it does.

### 4f. Build

```bash
python3 -m pipeline.build /tmp/zorb/TODAY/<topic>/script.json /tmp/zorb/TODAY/<topic>/out \
  --recent channel/log --facts channel/facts
cat /tmp/zorb/TODAY/<topic>/out/report.json
```

Read `report.json` (`ok`, `checks`, `duration`, `scenes`, `error`):

- `ok: true` and `out/video.mp4` exists: go to step 5.
- `error` starts with `voice failed` (e.g. "No audio was received"): wait 30 s and build again.
  At most 3 builds in total for voice failures; after the third, skip the topic
  (`"status": "error"`, `"reason"` = the error text).
- `error` is `content checks failed; not voiced` or `technical check failed`: read the failing
  checks' `detail`, rewrite the script to fix exactly that (remove an unknown number, shorten a
  script that runs over 59 s, change a title too similar to a recent one, reorder scenes...) and
  build again. At most 2 rewrites; then skip the topic (`"status": "skipped"`,
  `"reason"` = "checks failed: " + the failing checks' `name: detail`, joined by "; ").
  Never "fix" a check by editing pipeline code, the fact sheet's numbers or the logs.
- `error` starts with `bad script`, `render failed` or `build failed`: fix an obviously malformed
  script.json once; otherwise skip the topic (`"status": "error"`, `"reason"` = the error text).

Copy the final script you built (passed or not) to `channel/scripts/TODAY/<topic>.json`.

## 5. Host the mp4 on the `media` branch

Only for a topic whose report has `ok: true`. Use a separate worktree so the main checkout
never leaves `claude/quirky-cannon-xc1vyz`.

```bash
W=/tmp/zorb/media-wt
V=/tmp/zorb/TODAY/<topic>/out/video.mp4
git worktree remove --force "$W" 2>/dev/null; rm -rf "$W"; git worktree prune
git branch -D media 2>/dev/null
git fetch origin media 2>/dev/null && HAVE_MEDIA=1 || HAVE_MEDIA=0
```

**Fresh branch** — if `HAVE_MEDIA=0`, or if `MONDAY` is true and this is the first upload of
this session (do this at most once per session):

```bash
git worktree add --detach "$W" HEAD
cd "$W"
git checkout --orphan media
git rm -rfq . && git clean -fdxq
# keep folders of posts that may still be pending (only if the remote branch exists):
for d in YESTERDAY TODAY; do git checkout origin/media -- "media/$d" 2>/dev/null || true; done
```

(`YESTERDAY` = the New York date before TODAY.) The Monday reset keeps the media small; the two
kept folders protect posts scheduled yesterday or earlier today that may not have published yet.

**Existing branch** — otherwise:

```bash
git worktree add -B media "$W" origin/media
cd "$W"
```

Then, in both cases:

```bash
mkdir -p media/TODAY
cp "$V" media/TODAY/<topic>.mp4
git add media/TODAY/<topic>.mp4
git commit -q -m "media: TODAY <topic>"
```

Push with up to 4 retries on network errors, waiting 2 s, 4 s, 8 s, 16 s between tries:

```bash
git push -u origin media            # existing branch
git push -u --force origin media    # fresh branch only (this is the ONLY force push allowed)
```

If the push is rejected as non-fast-forward (another run pushed meanwhile), redo step 5 from the
top once. If it still fails, skip the topic (`"status": "error"`, `"reason"` = the git error).
Then go back: `cd <repo root>` and `git worktree remove --force "$W"`.
`git status --short --branch` must again show `claude/quirky-cannon-xc1vyz`.

**Verify the URL** before scheduling:

```bash
URL=$(python3 -m pipeline.media url TODAY <topic>)
SIZE=$(stat -c %s "$V")
curl -sSI "$URL" | tr -d '\r' | grep -iE '^(HTTP|content-length)'
```

Needs `HTTP/2 200` (or `HTTP/1.1 200`) and `content-length` equal to `$SIZE`. If not, wait 15 s
and try again, up to 5 times. Still wrong: do not schedule; log `"status": "error"`,
`"reason": "media URL not served: <status> <length> vs <SIZE>"`, and move on to the next topic.

## 6. Schedule with Metricool

Load the tool first (its schema is deferred):
`ToolSearch` with query `select:mcp__Metricool_Social_Media_Management__createScheduledPost`.
If the tool is not available, log `"status": "error"`, `"reason": "Metricool tool unavailable"`,
and schedule nothing today.

Get the slot times once per session:

```bash
python3 -m pipeline.media slots --per-day <PER_DAY>
```

It prints one object per slot (`date` with UTC offset, `publicationDate`). Slots already past or
less than 20 minutes away are moved to the same time tomorrow. Give the topics, in the order
they get scheduled, the slots in order, skipping any slot whose `date` already appears as
`publish_at` of a `scheduled` entry in today's log (a rerun). If no slot is left, do not
schedule: log `"status": "skipped"`, `"reason": "no free slot"` and stop.

Call `createScheduledPost` with these arguments (fill `<...>` from the script and the slot;
`info` is a JSON **string**, so serialise this object with proper escaping of quotes and
newlines in the description):

```json
{
  "blogId": "7783344",
  "date": "<slot.date, e.g. 2026-11-02T08:00:00-05:00>",
  "info": {
    "providers": [{"network": "youtube"}],
    "text": "<script.description, exactly>",
    "media": ["<URL from step 5>"],
    "publicationDate": {"dateTime": "<slot.publicationDate.dateTime, e.g. 2026-11-02T08:00:00>",
                        "timezone": "America/New_York"},
    "autoPublish": true,
    "draft": false,
    "descendants": [],
    "firstCommentText": "",
    "hasNotReadNotes": false,
    "mediaAltText": [],
    "shortener": false,
    "smartLinkData": {"ids": []},
    "youtubeData": {
      "title": "<script.title>",
      "type": "short",
      "privacy": "public",
      "tags": ["<script.tags ...>"],
      "category": "EDUCATION",
      "madeForKids": false,
      "isAiGeneratedContent": false
    }
  }
}
```

(Dry run: `"draft": true`.) Do not add any other field (no thumbnail fields).

- Success: the response contains a `plannerUrl`; record it as `planner_url` and the slot's
  `date` as `publish_at`; status `scheduled`.
- Any error, or a response without a `plannerUrl`: status `error`, `reason` = the error text
  verbatim (or the full response if there is no error text). **Do not retry, do not start
  another topic, and schedule nothing more today**; go to step 7.

## 7. Log, commit, push

Append one entry per attempted topic to `channel/log/TODAY.json` (create it as `[]` if missing;
keep existing entries untouched; write valid JSON, 2-space indent):

```json
{
  "topic": "<topic id or null>",
  "title": "<script title or null>",
  "scenes": ["<scene of each beat, in order>"],
  "hook_score": 60,
  "checks": [{"name": "hook", "ok": true, "detail": "..."}],
  "status": "scheduled | skipped | error",
  "planner_url": "<plannerUrl or null>",
  "media_url": "<raw URL or null>",
  "reason": "<why skipped / error text, or null>",
  "publish_at": "<slot date with offset, or null>"
}
```

`checks` = the `checks` list of the last `report.json` for that topic (`[]` if never built).
Use `[]` for `scenes` and `null` for `title`/`hook_score` when no script exists.
Only `scheduled` entries' titles and scenes matter for variety, but log them all honestly.

```bash
python3 -c "import json; json.load(open('channel/log/TODAY.json'))"   # must not fail
git add channel/log/TODAY.json channel/scripts/TODAY/
git commit -m "run: TODAY (<n> scheduled)"
git push -u origin claude/quirky-cannon-xc1vyz
```

Push retries: up to 4 on network errors, waiting 2 s, 4 s, 8 s, 16 s. If rejected as
non-fast-forward, `git pull --rebase origin claude/quirky-cannon-xc1vyz` once and push again.
Never force-push this branch.

## 8. Finish

End with one paragraph: the date, each topic attempted with its status, title, publish time and
planner URL (or the reason it was skipped), anything refreshed on a fact sheet, and anything
the owner should look at. Prefix it with "DRY RUN" for a dry run.
