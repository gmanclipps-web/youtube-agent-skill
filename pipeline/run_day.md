# Daily run: publish Zorb Shorts for @zorblipo

You are an unattended Claude Code session. Nobody will answer questions. Follow this file
top to bottom, exactly. **When anything is unclear, skip that topic and log why. Never guess.**

Repo: `gmanclipps-web/youtube-agent-skill`. Work branch: `claude/quirky-cannon-xc1vyz`.
Run every command from the repo root (`/home/user/youtube-agent-skill` or wherever the repo is
checked out; `cd` there at the start of every Bash call if unsure).

**Shell state does not persist between Bash calls.** Words in CAPS such as `TODAY`,
`YESTERDAY`, `PER_DAY`, and `<topic>`, are placeholders: type their literal values into each
command (e.g. `2026-11-02`, `stocks`). Never rely on a shell variable set in an earlier call.

## 0. Get the work branch (before anything else)

A fresh session may start on another branch. Before reading or running anything else:

```bash
git fetch origin claude/quirky-cannon-xc1vyz && git checkout claude/quirky-cannon-xc1vyz
git merge --ff-only origin/claude/quirky-cannon-xc1vyz
git status --short --branch          # must show claude/quirky-cannon-xc1vyz
```

If `git fetch` fails with a network error, retry up to 4 times, waiting 2 s, 4 s, 8 s, 16 s.
If it still fails, or the checkout or merge fails, stop: there is nothing to log against;
report it in the final summary. Every file this run reads (this one included) is the copy on
that branch.

**All pushes go to `claude/quirky-cannon-xc1vyz` (step 7) and to `media` (only through
`python3 -m pipeline.media upload`, step 5). Never push anything to any other branch.**

## Hard rules (read before doing anything else)

1. Never publish (schedule) a video whose `report.json` has `"ok": false`, or whose
   `video.mp4` or `thumbnail.jpg` is missing.
2. Never edit anything under `pipeline/` or `skills/`, never weaken a check, never change
   `channel/config.json`, `channel/topics.json` or any `channel/facts/*.md` fact sheet (the
   owner maintains the sheets; a run only reads them). If the code seems broken, log it and stop.
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
   same topic, with one exception: when the first call is rejected with
   `VIDEO_THUMBNAIL_NOT_APPLICABLE`, call it once more without the cover (step 6). After any
   other Metricool error, schedule nothing more today, and if today's log already holds a
   Metricool error, schedule nothing at all today.
7. Push only to `claude/quirky-cannon-xc1vyz`; only `python3 -m pipeline.media upload` writes
   to the `media` branch. Never touch that
   branch with other git commands, never force-push any branch, never run `git rm`, `git clean`,
   `git reset --hard` or `rm -rf` inside the repo checkout.
8. Use the timezone `America/New_York` for every date in this file ("today" = the New York date).

## Dry run

The owner may start you with "dry run". Then do everything below exactly the same, with only
these differences:

- use `PER_DAY=1` instead of `per_day` from the config (step 1); do not edit the config,
- in step 6 add `--draft` to the `payload` command (it then prints `"draft": true`;
  everything else identical),
- when the draft was created, log it with `"status": "skipped"` (a draft is not a published
  video, so the topic stays eligible for real runs and its slot stays free),
  `"reason": "dry run: draft only"`, `"title": null`, `"scenes": []`, and still fill
  `planner_url`, `media_url` and `publish_at`.

A dry run still commits and pushes its log, script and media like a real run. Say "DRY RUN"
at the start of the final summary.

## 1. Set up

```bash
git status --short --branch          # must be on claude/quirky-cannon-xc1vyz (step 0)
python3 -m pipeline.media today --log-dir channel/log
```

It prints e.g. `{"date": "2026-11-02", "weekday": "Monday", "monday": true,
"yesterday": "2026-11-01", "scheduled_today": 0, "metricool_error_today": false}`.
Note `TODAY` = `date` and create today's work directory **now, before any other file is
written there** (every entry file in step L lives in it):

```bash
mkdir -p /tmp/zorb/TODAY
pip install -q -r pipeline/requirements.txt
cat channel/config.json
```

- If you are not on `claude/quirky-cannon-xc1vyz`, go back to step 0.
- If `pip install` fails, retry once; if it still fails, log one entry (step L:
  `"topic": null`, `"status": "error"`, `"reason"` = the pip error's last line), push (step 7), stop.
- `YESTERDAY` = `yesterday`.
  `PER_DAY` = `per_day` from `channel/config.json` (1 in a dry run).
- If `metricool_error_today` is true: a Metricool error already happened today. Schedule
  nothing; finish with the summary (step 8).
- If `scheduled_today >= PER_DAY`, today is done (a rerun): write nothing, finish with the summary.
  Otherwise `REMAINING` = `PER_DAY` minus `scheduled_today` (normally `REMAINING` = `PER_DAY`).
- Work directory for build files: `/tmp/zorb/TODAY/<topic>/` (not committed). Create it with
  `mkdir -p /tmp/zorb/TODAY/<topic>` before writing anything there (`/tmp/zorb/TODAY` itself
  already exists from the `mkdir -p` above).

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
  "reason": "<why skipped / error text; null when scheduled, unless step 6 says otherwise>",
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

Run this (`N` = `REMAINING + 2`, the most topics you may attempt today, e.g. `4`):

```bash
python3 -m pipeline.media topics --log-dir channel/log --topics channel/topics.json --facts channel/facts --n N
```

It prints the eligible topic ids in the order to try them, e.g. `["stocks", "tariffs"]`.
Eligible = has a fact sheet, not already tried today, and not scheduled in the last 5 days
(a topic scheduled on day D is eligible again from day D + 6). The code decides; do not
second-guess or reorder the list.

- A topic is "used" when a log entry for it has `"status": "scheduled"`. Never-used topics come
  first, then the ones used longest ago; topics tried and skipped recently go later. Topics
  repeat about once a week, so a repeat must tell a **different** story (step 3).
- If the list is empty: log one entry (step L) with `"topic": null`, `"status": "skipped"`,
  `"reason": "no eligible topics"` (other fields null / `[]`), do step 7, stop.
- Work through the list in order, one topic at a time (steps 3-6), then the next. Stop when
  `REMAINING` topics are scheduled, when you have attempted `REMAINING + 2` topics, when a
  Metricool error happened, or when the list runs out. Each attempted topic gets exactly one
  log entry (step L).

## 3. For each topic: check the fact sheet and earlier scripts

Read `channel/facts/<topic>.md` in full. Each bullet ends with `(source: URL)`.

**Freshness.** Only bullets that carry the marker `(as of: YYYY-MM-DD)` can go out of date
(latest-release figures: CPI, the current rate range, this year's tax figures...); they expire
45 days after that date. Bullets without the marker (definitions, rules, historical facts,
fixed examples) never expire, whatever dates they mention. List the expired bullets:

```bash
python3 -m pipeline.media stale channel/facts/<topic>.md
```

It prints `none`, or each expired bullet on its own line. **Expired bullets are simply not
used**: none of their numbers or claims go into the script, props, title, description or tags
(the build rejects any number that appears only in expired bullets). There is no refreshing:
never edit a fact sheet during a run (hard rule 2), even if you could fetch a newer figure.
Note the expired bullets for the final summary, so the owner can refresh them. If fewer than
two non-expired bullets with something concrete to say remain, skip the topic (log it per
step L: `"status": "skipped"`, `"reason": "fact sheet stale"`).

**Earlier scripts of this topic.** Topics come back about once a week, so read every earlier
script of this topic before writing:

```bash
ls channel/scripts/*/<topic>.json channel/samples/<topic>/script.json 2>/dev/null
```

Read each file listed (the `channel/samples/` one was published on 2026-11-01; the others are
dated by their folder). For the ones from the last 30 days, note their titles, their twist
(the surprising fact) and which fact-sheet bullets their numbers came from. The new script must
use a **different angle**: its twist and main numbers come from a fact-sheet bullet that none of
those scripts used for its twist, and its title, hook and visual metaphor must differ from
theirs. If every usable bullet has already been the twist of one of them, skip the topic
(step L: `"status": "skipped"`, `"reason": "no fresh angle on the fact sheet"`).

## 4. For each topic: write the script, then build

### 4a. Voice and shape

Copy the shape of `channel/samples/inflation/script.json` (read it now; it passed every check
when it was published; its facts may have expired since and its hook score (60) is below today's minimum of 65, so copy its shape, not its numbers or its hook).

- Zorb is a small, curious, baffled, funny alien reporting on Earth money. Zorb talks to
  "Earthlings", in short sentences, present tense, no jargon without a one-line explanation.
- 75-110 spoken words in total (about 30-57 seconds), 6-9 beats, one idea per beat.
- Structure: **hook** (beat 1) -> **confusion** (Zorb does not get it) -> **one visual
  metaphor** carried over 2-3 beats -> **twist** (the surprising true fact) -> sign-off.
- The last beat's line is exactly: `Zorb will return. Earth money remains confusing.`
  (scene `planet`, expression `smug`, props `{}`).
- At least 4 distinct scenes, and the scene sequence must not copy any recent video's
  sequence (the build checks this against the last 10 scheduled videos in the logs).
- Scenes: `shop, price_tag, vault, stock_chart, credit_card, planet, calendar, money_stack`.
  Expressions: `neutral, confused, shocked, aha, smug`. Vary the expressions.
- **Every number** spoken in a line, in a prop, in the title, description or tags must appear on
  the topic's fact sheet, in a bullet that has not expired (step 3). The build checks this.
  Number words count too: "two", "twenty five", "hundred", "thousand", "million", "half",
  "double", "twice", "triple" ... are read as 2, 25, 100, 1000, 1000000, 0.5, 2, 2, 3 and need
  that number on the sheet (only a lone "one" is ignored). Prefer digits ("7 percent",
  "100 dollars"). Years, ages and counts are numbers too ("15 years" needs a 15 on the sheet).
  If you are unsure a number is there, leave it out.
- Banned anywhere (lines, title, description, tags; the build fails on these): "you should
  buy", "guaranteed", "will go up", "will crash", "buy now", "financial advice for you". Also
  obey hard rule 5.

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
`verdict` (an integer) in `hook_score`. It must be `>= 65`. If none reaches 65, write five
more; if still none, skip the topic (step L: `"status": "skipped"`, `"reason": "no hook >= 65"`). Never type a score you did
not get from the tool.

### 4d. Title, description, tags (skills/yt-package/SKILL.md)

- Title: starts with `Zorb`, at most 60 characters, plays on the topic's `title_seed` in
  `channel/topics.json`, a concrete number from the sheet if it fits. Write 5 options, run
  each through `python3 skills/yt-package/title.py --json --title "<title>"`, take the best
  score. It must not resemble a title from the last 30 days of logs, nor the title of any
  earlier script of this topic (step 3).
- Description: 2-3 plain sentences (what Zorb discovers; name the source organisation of the
  figures), then a blank line, then exactly `Education, not financial advice.`, then a blank
  line, then 3 hashtags on one line, the first being `#Shorts` (e.g.
  `#Shorts #inflation #personalfinance`). No links, no advice, no digits in hashtags.
- Tags: 5-10 short search phrases (topic name, "<topic> explained", "personal finance",
  "money basics", "Zorb", "cartoon alien" ...).
- Cover text (`thumb_text`): the words printed big on the Short's cover image. At most 3
  words, upper case, punchy, a curiosity gap the title does not close (e.g.
  `SNACKS COST MORE?!`). It must use **different words from the title** (the build fails if
  they share any word of 4+ letters) and, like the title, any number in it must come from a
  non-expired bullet of the sheet (prefer no number at all). Write 3 options and lint each
  together with the chosen title:

  ```bash
  python3 skills/yt-package/title.py --title "<title>" --thumb "<thumb_text>"
  ```

  Pick an option whose output has **no `duplicate` warning** and no `thumb-length` warning;
  if none qualifies, write 3 more. Never put banned phrases or advice in it (hard rule 5).
- Cover face (`thumb_expression`): one of `neutral, confused, shocked, aha, smug`, the one
  that fits the cover text (e.g. `confused` for a question, `shocked` for a surprise).

### 4e. Save and pre-check

Write the script to `/tmp/zorb/TODAY/<topic>/script.json` with the fields
`topic, title, description, tags, hook_score, thumb_text, thumb_expression, beats` (each beat:
`line, scene, expression, props`).
Then run both checks:

```bash
python3 -c "import json,sys; s=json.load(open(sys.argv[1])); print(sum(len(b['line'].split()) for b in s['beats']), len(s['beats']), len({b['scene'] for b in s['beats']}))" /tmp/zorb/TODAY/<topic>/script.json
python3 -m pipeline.media numbers /tmp/zorb/TODAY/<topic>/script.json channel/facts/<topic>.md
```

The first must print words 75-110, beats 6-9, distinct scenes >= 4. The second must print `ok`
(it lists any number, digits or words, in the title, description, tags or `thumb_text` that is
not in a non-expired bullet of the sheet; remove or fix those). Fix the script until both pass; these fixes do not count as rewrites.

Then save a copy: `mkdir -p channel/scripts/TODAY && cp /tmp/zorb/TODAY/<topic>/script.json
channel/scripts/TODAY/<topic>.json` (repeat the copy after every rewrite, so the committed copy
is the script you last built).

### 4f. Build

```bash
python3 -m pipeline.build /tmp/zorb/TODAY/<topic>/script.json /tmp/zorb/TODAY/<topic>/out --recent channel/log --facts channel/facts
cat /tmp/zorb/TODAY/<topic>/out/report.json
```

Read `report.json` (`ok`, `checks`, `duration`, `scenes`, `error`, `thumbnail`):

- `ok: true` and both `/tmp/zorb/TODAY/<topic>/out/video.mp4` and
  `/tmp/zorb/TODAY/<topic>/out/thumbnail.jpg` exist: go to step 5. (The build renders the
  cover `thumbnail.jpg` from `thumb_text` and `thumb_expression` after every check passes.)
- `error` starts with `voice failed` (e.g. "No audio was received"): wait 30 s and build again.
  At most 3 builds in total for voice failures; after the third, log it (step L:
  `"status": "error"`, `"reason"` = the error text) and go to the next topic.
- `error` is `content checks failed; not voiced` or `technical check failed`: read the failing
  checks' `detail`, rewrite the script to fix exactly that (remove an unknown number, shorten a
  script that runs over 59 s, change a title too similar to a recent one, reorder scenes...),
  redo 4e and build again (a `metadata` failure saying `thumb_text repeats the title` is fixed
  by new cover words, re-linted as in 4d). At most 2 rewrites; then log it (step L:
  `"status": "skipped"`, `"reason"` = "checks failed: " + the failing checks' `name: detail`, joined by "; ") and go to
  the next topic. Never "fix" a check by editing pipeline code, the fact sheet or the logs.
  **A failing `facts` check is never fixed by editing a fact sheet**: remove or change the
  number in the script, or skip the topic.
- `error` starts with `bad script`, `render failed`, `thumbnail failed` or `build failed`: fix an
  obviously malformed script.json once; otherwise log it (step L: `"status": "error"`, `"reason"` = the error text)
  and go to the next topic.

## 5. Host the mp4 and the cover on the `media` branch

Only for a topic whose report has `ok: true`. Upload the video, then the cover (two commands,
in this order; each prints its raw URL):

```bash
python3 -m pipeline.media upload TODAY <topic> /tmp/zorb/TODAY/<topic>/out/video.mp4
python3 -m pipeline.media upload TODAY <topic> /tmp/zorb/TODAY/<topic>/out/thumbnail.jpg
```

`URL` = the first printed URL (ends in `/<topic>.mp4`), `THUMB_URL` = the second (ends in
`/<topic>.jpg`). Each commits its file as `media/TODAY/<topic>.mp4` / `.jpg` on origin's
orphan `media` branch with git plumbing and a throwaway index (your checkout, branch and files
are not touched) and pushes with retries (2, 4, 8, 16 s). On a Monday's first upload it restarts the
branch from scratch, keeping only yesterday's and today's folders (posts that may not have
published yet). Re-running it with the same file is harmless.

If either exits non-zero: if the message says `rejected` (someone else pushed meanwhile), run
the same command once more. Otherwise, or if it fails again, log it (step L: `"status": "error"`,
`"reason"` = the printed error) and go to the next topic.

Then check both URLs really serve these files (200 and the file's exact Content-Length):

```bash
python3 -m pipeline.media verify TODAY <topic> /tmp/zorb/TODAY/<topic>/out/video.mp4
python3 -m pipeline.media verify TODAY <topic> /tmp/zorb/TODAY/<topic>/out/thumbnail.jpg
```

Each retries for about a minute and prints `ok 200 <bytes>`. If either exits non-zero, do not
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
time tomorrow; it looks at most 2 days ahead) and skips every slot already booked by a
`scheduled` entry in the logs of today and the 2 days before, so each topic gets its own slot and a rerun never double-books. If it prints
`[]`, log the topic (step L: `"status": "skipped"`, `"reason": "no free slot"`) and stop
scheduling.

Print the exact tool arguments (`SLOT_DATE` = the slot's `date`, e.g.
`2026-11-02T08:00:00-05:00`; `URL` and `THUMB_URL` = the mp4 and jpg raw URLs printed by the
uploads in step 5; add `--draft` in a dry run):

```bash
python3 -m pipeline.media payload /tmp/zorb/TODAY/<topic>/script.json SLOT_DATE URL /tmp/zorb/TODAY/<topic>/out/report.json --thumb THUMB_URL
```

It refuses (exit non-zero, message on stderr) unless `report.json` says `"ok": true` and
`video.mp4` and `thumbnail.jpg` sit next to it, the slot date is a slot as printed by `slots`,
the URL is this topic's media URL and `THUMB_URL` is the matching `.jpg` URL (same day and
topic). The cover goes into `info` as `videoThumbnailUrl`. If it refuses, do not schedule:
log it (step L: `"status": "error"`, `"reason"` = the printed error) and go to the next topic.

Otherwise it prints one JSON object with exactly three keys: `blogId`, `date` and `info`.
Call `createScheduledPost` with exactly those three values, copied verbatim: `info` is
already a JSON **string**; pass that string as it is (do not parse, re-serialise, re-escape
or edit it, and do not build the JSON yourself). Do not add any other argument.

- Success: the response contains a `plannerUrl`. **Immediately** log it (step L:
  `"status": "scheduled"`, `title`, `scenes`, `planner_url`, `media_url` = `URL` (the mp4),
  `publish_at` = the slot's `date`, `"reason": null`), commit, and push (step 7's push command), before doing anything else. This
  is what stops a crashed-and-restarted run from scheduling the same video twice.
- The error mentions `VIDEO_THUMBNAIL_NOT_APPLICABLE` (Metricool will not take the cover; no
  post was created): rebuild the payload without the cover, the same command with `--no-thumb`
  in place of `--thumb THUMB_URL` (keep `--draft` in a dry run):

  ```bash
  python3 -m pipeline.media payload /tmp/zorb/TODAY/<topic>/script.json SLOT_DATE URL /tmp/zorb/TODAY/<topic>/out/report.json --no-thumb
  ```

  and call `createScheduledPost` **once more** with its three values (same rules as above).
  This is the only second call allowed for a topic (hard rule 6), and only for this exact
  error. Do not pick a new slot: reuse the same `SLOT_DATE`. If it succeeds, log it exactly as
  the Success bullet says, but with `"reason": "cover rejected by Metricool"` (in a dry run:
  `"reason": "dry run: draft only; cover rejected by Metricool"`), commit and push at once. If
  it fails too (any error, or no `plannerUrl`), handle that failure as the next bullet says.
- Any other error, or a response without a `plannerUrl`: log it (step L: `"status": "error"`,
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
planner URL (or the reason it was skipped), every expired fact-sheet bullet you saw (step 3) so
the owner can refresh it, any topic scheduled without its cover ("cover rejected by
Metricool"), and anything else the owner should look at. Prefix it with "DRY RUN" for a dry run.
