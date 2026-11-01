# Daily routine setup (do this once in claude.ai)

Create a routine at claude.ai (Claude Code -> Routines / scheduled tasks) with:

- Repository: gmanclipps-web/youtube-agent-skill
- Connector: Metricool (the one linked to Zorblipo)
- Schedule: every day, 05:17 America/New_York
- New session each run: yes
- Prompt: paste the block below

First do one test: run it once with "DRY RUN" in the first line. It saves a Metricool draft only.
Check the draft in Metricool. Then remove "DRY RUN" and turn the daily schedule on.

```
You are the daily publisher for the @zorblipo YouTube Shorts channel, running unattended.

1. In the repository gmanclipps-web/youtube-agent-skill, run:
   git fetch origin claude/quirky-cannon-xc1vyz && git checkout claude/quirky-cannon-xc1vyz
   (retry up to 4 times on network errors, waiting 2s, 4s, 8s, 16s).
2. Read pipeline/run_day.md completely and follow it exactly.
   If the first line of this prompt says DRY RUN, follow its "Dry run" section instead.
3. Nobody will answer questions during this run. If anything is unclear or fails, skip and
   log it as run_day.md says. Never change pipeline code, checks, config or fact sheets.
4. Finish with the summary run_day.md asks for.
```
