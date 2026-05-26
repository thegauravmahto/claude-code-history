---
description: Search your Claude Code session history
---

Search the user's Claude Code session history for the query in $ARGUMENTS.

Steps:
1. Call the MCP tool `cc-history.search_history_tool` with `query=$ARGUMENTS`, `limit=5`.
2. Render results as a numbered list. For each session show:
   - **Title** (or `(untitled session <short-id>)` if title is null) — relative date (e.g. "2 days ago")
   - One-line summary
   - Tags as a small inline list
   - Project path (faint)
3. After the list, offer follow-ups:
   - "Type `open #N` to read session N in this conversation"
   - "Type `resume #N` to get a paste-ready resume command"

If no sessions are found, say so plainly and suggest broadening the query.
