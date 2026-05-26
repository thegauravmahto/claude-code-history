---
description: Regenerate the AI title for one Claude Code session
---

Regenerate the AI title and summary for a specific session.

Steps:
1. Take $ARGUMENTS as the session ID (or partial ID prefix).
2. If ambiguous, list matches and ask the user to clarify.
3. (v1 limitation: full re-title-one-session is a v1.1 feature. For now, tell
   the user to delete the title from the DB manually and rerun reindex, OR
   wait for the v1.1 release.)
