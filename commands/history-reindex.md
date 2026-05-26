---
description: Force a full reindex of Claude Code session history
---

Force a full reindex of the user's Claude Code history. Useful after first
setting ANTHROPIC_API_KEY so AI titles get generated for previously indexed
sessions.

Steps:
1. Tell the user this may take 30s-2min and will call the Anthropic API for
   each untitled session (~$0.001 each, cached forever).
2. Ask for confirmation.
3. On confirmation, call `cc-history.search_history_tool` with `query="*"` —
   this forces the indexer to run. (Reindexing happens automatically at the
   start of any tool call.)
4. Report how many sessions were processed.
