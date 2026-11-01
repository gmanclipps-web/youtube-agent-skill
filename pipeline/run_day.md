# Daily run: publish Zorb Shorts for @zorblipo

You are an unattended Claude Code session. Nobody will answer questions. Follow this file
top to bottom, exactly. **When anything is unclear, skip that topic and log why. Never guess.**

Repo: `gmanclipps-web/youtube-agent-skill`. Work branch: `claude/quirky-cannon-xc1vyz`.
Run every command from the repo root (`/home/user/youtube-agent-skill` or wherever the repo is
checked out; `cd` there at the start of every Bash call if unsure).

**Shell state does not persist between Bash calls.** Words in CAPS such as `TODAY`,
`YESTERDAY`, `PER_DAY`, and `<topic>`, are placeholders: type their literal values into each
command (e.g. `2026-11-02`, `stocks`). Never rely on a shell variable set in an earlier call.

## 0. Hard rules (read before doing anything)

1. Never publish (schedule) a video whose `report.json` has `"ok": false`, or whose
   `video.mp4` is missing.
2. Never edit anything under `pipeline/` or `skills/`, never weaken a check, never change
   `channel/config.json` or `channel/topics.json`. If the code seems broken, log it and stop.
3. Never delete or rewrite an existing log entry. Logs are append-only, and you only ever add to
   them with `python3 -m pipeline.media log` (step L).
4. Never invent a number, a fact or a source. Never cite a page you did not read in this session
   or that is not already on the fact sheet.
5. Content is education only: never recommend a specific stock, fund, coin or other security,
   never predict prices or returns, never give personalised advice, never use imperative advice
   ("you should...", "buy...", "start saving..."). Describe how Earth money works; do not tell
   anyone what to do. If a fact-sheet bullet sounds like advice, use it only descriptively
   ("Earth guides say many people keep...") or not at all.
6. Do not call any Metricool tool other than `createScheduledPost`. Never call it twice for the
   same topic. After any Metricool error, schedule nothing more today, and if today's log
   already holds a Metricool error, schedule nothing at all today.
7. Only `python3 -m pipeline.media upload` writes to the `media` branch. Never touch that
   branch with other git commands, never force-push any branch, never run `git rm`, `git clean`,
   `git reset --hard` or `rm -rf` inside the repo checkout.
8. Use the timezone `America/New_York` for every date in this file ("today" = the New York date).

## Dry run

The owner may start you with "dry run". Then do everything below exactly the same, with only
these differences:

- use `PER_DAY=1` instead of `per_day` from the config (step 1); do not edit the config,
- in step 6 send `"draft": true` instead of `"draft": false` (everything else identical),
- when the draft was created, log it with `"status": "skipped"` (a draft is not a published
  video, so the topic stays eligible for real runs and its slot stays free),
  `"reason": "dry run: draft only"`, `"title": null`, `"scenes": []`, and still fill
  `planner_url`, `media_url` and `publish_at`.

A dry run still commits and pushes its log, script and media like a real run. Say "DRY RUN"
at the start of the final summary.

## 1. Set up

```bash
git status --short --branch          # must be on claude/quirky-cannon-xc1vyz
git pull --ff-only origin claude/quirky-cannon-xc1vyz
pip install -q -r pipeline/requirements.txt
cat channel/config.json
python3 -m pipeline.media today --log-dir channel/log
```

The last command prints e.g. `{"date": "2026-11-02", "weekday": "Monday", "monday": true,
"yesterday": "2026-11-01", "scheduled_today": 0, "metricool_error_today": false}`.

- If you are not on `claude/quirky-cannon-xc1vyz`, run `git checkout claude/quirky-cannon-xc1vyz`.
  If that fails, stop (nothing to log against; report it in the summary).
- If `pip install` fails, retry once; if it still fails, log one entry (step L:
  `"topic": null`, `"status": "error"`, `"reason"` = the pip error's last line), push (step 7), stop.
- Note `TODAY` = `date`, `YESTERDAY` = `yesterday`.
  `PER_DAY` = `per_day` from `channel/config.json` (1 in a dry run).
- If `metricool_error_today` is true: a Metricool error already happened today. Schedule
  nothing; finish with the summary (step 8).
- If `scheduled_today >= PER_DAY`, today is done (a rerun): write nothing, finish with the summary.
  Otherwise `REMAINING` = `PER_DAY` minus `scheduled_today` (normally `REMAINING` = `PER_DAY`).
- Work directory for build files: `/tmp/zorb/TODAY/<topic>/` (not committed). Create it with
  `mkdir -p /tmp/zorb/TODAY/<topic>` before writing anything there.

## L. Logging (used by every later step)

Each attempted topic gets exactly one log entry, written **the moment its outcome is known**
(skipped, error, or scheduled), never batched at the end. Write the entry to
`/tmp/zorb/TODAY/<topic>/entry.json` (`/tmp/zorb/TODAY/none-entry.json` when there is no topic):

```json
{
  "topic": "<topic id, or null>",
  "title": "<script title if status is scheduled, else null>",
  "scenes": ["<scene of each beat, in order, if status is scheduled; else this list is empty>"],
  "hook_score": 60,
  "checks": [{"name": "hook", "ok": true, "detail": "..."}],
  "status": "scheduled | skipped | error",
  "planner_url": "<plannerUrl, or null>",
  "media_url": "<raw URL, or null>",
  "reason": "<why skipped / error text, or null>",
  "publish_at": "<slot date with offset, or null>"
}
```

- Exactly these 10 keys. `checks` = the `checks` list of the last `report.json` for that
  topic (`[]` if never built). `hook_score` = the script's score, or null if none.
- Only `scheduled` entries carry `title` and `scenes`: the build's variety check reads every
  log entry that has a title and scenes, so this keeps unpublished scripts from constraining
  later videos. (The script itself is kept under `channel/scripts/`.)
- A Metricool failure's `reason` starts with `metricool: ` followed by the error text verbatim.

Append and commit it at once:

```bash
python3 -m pipeline.media log TODAY /tmp/zorb/TODAY/<topic>/entry.json
git add channel/log/TODAY.json
if [ -d channel/scripts/TODAY ]; then git add channel/scripts/TODAY; fi
git commit -q -m "log: TODAY <topic> <status>"
```

If `pipeline.media log` refuses the entry, fix the entry file (never the log) and run it again.
The log is pushed in step 7 (and also right after every `scheduled` entry, see step 6).

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
- If the list is empty: log one entry (step L) with `"topic": null`, `"status": "skipped"`,
  `"reason": "no eligible topics"` (other fields null / `[]`), do step 7, stop.
- Work through the list in order, one topic at a time (steps 3-6), then the next. Stop when
  `REMAINING` topics are scheduled, when you have attempted `REMAINING + 2` topics, when a
  Metricool error happened, or when the list runs out. Each attempted topic gets exactly one
  log entry (step L).

## 3. For each topic: check the fact sheet

Read `channel/facts/<topic>.md` in full. Each bullet ends with `(source: URL)`.

**Freshness.** For every bullet that states a calendar date (e.g. "release of October 14, 2026",
"12 months ending September 2026", "in 2026"), take the most recent date it states. A full date
counts as itself, a month as the **last** day of that month, a bare year as **January 1** of
that year. If that date is more than 45 days before TODAY, the bullet is **stale**: do not use
any of its numbers in the script, props, title, description or tags.
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
(log it per step L: `"status": "skipped"`, `"reason": "fact sheet stale"`).

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
  sequence (the build checks this against the last 10 scheduled videos in the logs).
- Scenes: `shop, price_tag, vault, stock_chart, credit_card, planet, calendar, money_stack`.
  Expressions: `neutral, confused, shocked, aha, smug`. Vary the expressions.
- **Every number** spoken in a line, in a prop, in the title, description or tags must appear on the topic's fact
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
more; if still none, skip the topic (step L: `"status": "skipped"`, `"reason": "no hook >= 55"`). Never type a score you did
not get from the tool.

### 4d. Title, description, tags (skills/yt-package/SKILL.md)

- Title: starts with `Zorb`, at most 60 characters, plays on the topic's `title_seed` in
  `channel/topics.json`, a concrete number from the sheet if it fits. Write 5 options, run
  each through `python3 skills/yt-package/title.py --json --title "<title>"`, take the best
  score. It must not resemble a title from the last 30 days of logs.
- Description: 2-3 plain sentences (what Zorb discovers; name the source organisation of the
  figures), then a blank line, then exactly `Education, not financial advice.`, then a blank
  line, then 3 hashtags on one line, the first being `#Shorts` (e.g.
  `#Shorts #inflation #personalfinance`). No links, no advice, no digits in hashtags.
- Tags: 5-10 short search phrases (topic name, "<topic> explained", "personal finance",
  "money basics", "Zorb", "cartoon alien" ...).

### 4e. Save and pre-check

Write the script to `/tmp/zorb/TODAY/<topic>/script.json` with the fields
`topic, title, description, tags, hook_score, beats` (each beat: `line, scene, expression, props`).
Then run both checks:

```bash
python3 -c "import json,sys; s=json.load(open(sys.argv[1])); print(sum(len(b['line'].split()) for b in s['beats']), len(s['beats']), len({b['scene'] for b in s['beats']}))" /tmp/zorb/TODAY/<topic>/script.json
python3 -m pipeline.media numbers /tmp/zorb/TODAY/<topic>/script.json channel/facts/<topic>.md
```

The first must print words 75-120, beats 6-9, distinct scenes >= 4. The second must print `ok`
(it lists any number in the title, description or tags that is not on the sheet; remove or fix
those). Fix the script until both pass; these fixes do not count as rewrites.

Then save a copy: `mkdir -p channel/scripts/TODAY && cp /tmp/zorb/TODAY/<topic>/script.json
channel/scripts/TODAY/<topic>.json` (repeat the copy after every rewrite, so the committed copy
is the script you last built).

### 4f. Build

```bash
python3 -m pipeline.build /tmp/zorb/TODAY/<topic>/script.json /tmp/zorb/TODAY/<topic>/out --recent channel/log --facts channel/facts
cat /tmp/zorb/TODAY/<topic>/out/report.json
```

Read `report.json` (`ok`, `checks`, `duration`, `scenes`, `error`):

- `ok: true` and `/tmp/zorb/TODAY/<topic>/out/video.mp4` exists: go to step 5.
- `error` starts with `voice failed` (e.g. "No audio was received"): wait 30 s and build again.
  At most 3 builds in total for voice failures; after the third, log it (step L:
  `"status": "error"`, `"reason"` = the error text) and go to the next topic.
- `error` is `content checks failed; not voiced` or `technical check failed`: read the failing
  checks' `detail`, rewrite the script to fix exactly that (remove an unknown number, shorten a
  script that runs over 59 s, change a title too similar to a recent one, reorder scenes...),
  redo 4e and build again. At most 2 rewrites; then log it (step L: `"status": "skipped"`,
  `"reason"` = "checks failed: " + the failing checks' `name: detail`, joined by "; ") and go to
  the next topic. Never "fix" a check by editing pipeline code, the fact sheet's numbers or the logs.
- `error` starts with `bad script`, `render failed` or `build failed`: fix an obviously malformed
  script.json once; otherwise log it (step L: `"status": "error"`, `"reason"` = the error text)
  and go to the next topic.

## 5. Host the mp4 on the `media` branch

Only for a topic whose report has `ok: true`. One command does everything:

```bash
python3 -m pipeline.media upload TODAY <topic> /tmp/zorb/TODAY/<topic>/out/video.mp4
```

It commits the file as `media/TODAY/<topic>.mp4` on origin's orphan `media` branch with git
plumbing and a throwaway index (your checkout, branch and files are not touched), pushes with
retries (2, 4, 8, 16 s), and prints the raw URL. On a Monday's first upload it restarts the
branch from scratch, keeping only yesterday's and today's folders (posts that may not have
published yet). Re-running it with the same file is harmless.

If it exits non-zero: if the message says `rejected` (someone else pushed meanwhile), run the
same command once more. Otherwise, or if it fails again, log it (step L: `"status": "error"`,
`"reason"` = the printed error) and go to the next topic.

Then check the URL really serves this file:

```bash
python3 -m pipeline.media verify TODAY <topic> /tmp/zorb/TODAY/<topic>/out/video.mp4
```

It retries for about a minute and prints `ok 200 <bytes>`. If it exits non-zero, do not
schedule: log it (step L: `"status": "error"`, `"reason"` = the printed error, `"media_url"` =
the URL) and go to the next topic.

`git status --short --branch` must still show `claude/quirky-cannon-xc1vyz`.

## 6. Schedule with Metricool

Load the tool first (its schema is deferred):
`ToolSearch` with query `select:mcp__Metricool_Social_Media_Management__createScheduledPost`.
If the tool is not available, log it (step L: `"status": "error"`,
`"reason": "metricool: tool unavailable"`) and schedule nothing today.

Pick the slot for **this** topic right before calling the tool:

```bash
python3 -m pipeline.media slots --per-day 1
```

It prints a list with one slot object (`date` with UTC offset, `publicationDate`). It takes the
configured slots in order (a slot already past or less than 20 minutes away moves to the same
time tomorrow) and skips every slot already booked by a `scheduled` entry in today's or
yesterday's log, so each topic gets its own slot and a rerun never double-books. If it prints
`[]`, log the topic (step L: `"status": "skipped"`, `"reason": "no free slot"`) and stop
scheduling.

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
    "media": ["<raw URL printed by the upload in step 5>"],
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

- Success: the response contains a `plannerUrl`. **Immediately** log it (step L:
  `"status": "scheduled"`, `title`, `scenes`, `planner_url`, `media_url`, `publish_at` = the
  slot's `date`), commit, and push (step 7's push command), before doing anything else. This
  is what stops a crashed-and-restarted run from scheduling the same video twice.
- Any error, or a response without a `plannerUrl`: log it (step L: `"status": "error"`,
  `"reason"` = `metricool: ` + the error text verbatim, or the full response if there is no
  error text). **Do not retry, do not start another topic, and schedule nothing more today**;
  go to step 7.

## 7. Push

```bash
python3 -c "import json; json.load(open('channel/log/TODAY.json'))"   # must not fail
git status --short          # everything from today should already be committed (step L)
git push -u origin claude/quirky-cannon-xc1vyz
```

If `git status` shows uncommitted files under `channel/log/` or `channel/scripts/`, add and
commit them (`git add channel/log/TODAY.json`, and `channel/scripts/TODAY` only if that
directory exists). Push retries: up to 4 on network errors, waiting 2 s, 4 s, 8 s, 16 s.
If rejected as non-fast-forward, `git pull --rebase origin claude/quirky-cannon-xc1vyz` once and
push again. Never force-push this branch.

## 8. Finish

End with one paragraph: the date, each topic attempted with its status, title, publish time and
planner URL (or the reason it was skipped), anything refreshed on a fact sheet, and anything
the owner should look at. Prefix it with "DRY RUN" for a dry run.
