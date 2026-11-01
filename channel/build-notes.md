# Build notes - decisions made during the build (2026-11-01)

Each line: what was decided - why - what it costs if wrong.

- Layout: scene top, captions y1100-1400, Zorb bottom centre - no overlap - Zorb's feet sit under YouTube's bottom buttons.
- Scripts use the yt-script / yt-package tools directly - same tools and limits - slightly less polish than the full skill.
- Owner sees a sample before any schedule; Metricool calls and scheduling done by the controller, not build agents.
- Fact check ignores URLs and list numbers on sheets; "1.50" = "1.5" - else invented numbers could slip through.
- edge-tts pinned to 7.3.1 - voice code uses a private part of it - an upgrade could break the voice.
- Numbers on screen (scene props) are fact-checked; scenes never draw made-up default numbers - show "?" instead.
- Price-tag count-up shows in-between prices (e.g. $103 between $100 and $107) - animation only - brief unsourced numbers on screen.
- Voice retries 3 times; fact bullets marked "(as of: date)" expire after 45 days and are then not used. No automatic refresh.
- Video upload is one tested script using git plumbing - can never wipe the main checkout.
- Monday media-branch reset keeps yesterday and today - protects posts not yet published.
- A topic can repeat after 6 days (not 30), with a new angle - 12 topics would otherwise run dry in 6 days - risk of repetitive videos. Fix: add more topics.

Known limits:
- Time-sensitive facts start expiring 2026-11-28 (CPI), 2026-12-12 (Fed rate), 2026-12-16 (tax/currency). Those topics lose those numbers until the sheets are refreshed by hand.
- per_day 3 needs at least 15 topics.
