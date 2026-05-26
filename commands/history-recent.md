---
description: Show Claude Code sessions from the last N days
---

Show the user's recent Claude Code sessions.

Steps:
1. Parse $ARGUMENTS as an integer number of days. Default to 7 if empty.
2. Call `cc-history.list_recent_tool` with that `days` value.
3. Render the sessions grouped by project, ordered by date (newest first).
4. For each session show title, summary, and the date.
