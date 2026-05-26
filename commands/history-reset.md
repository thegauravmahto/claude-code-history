---
description: Wipe the cc-history index and rebuild from scratch
---

Wipe the local cc-history index and rebuild from scratch.

Steps:
1. Warn the user this will delete `${CLAUDE_PLUGIN_DATA}/index.db` and trigger
   a full reindex on the next search. Any locally generated AI titles will be
   regenerated (Anthropic API calls + cost).
2. Ask for explicit confirmation.
3. On confirmation, use the Bash tool to delete the DB:
   `rm -f "$CLAUDE_PLUGIN_DATA/index.db"`
4. Trigger a reindex by calling `cc-history.list_recent_tool` once.
