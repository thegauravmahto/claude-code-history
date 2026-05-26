# cc-history

> Find, read, and resume your past Claude Code sessions — from inside any Claude Code session.

Claude Code stores every conversation as a JSONL file under `~/.claude/projects/`. After a few weeks of heavy use you have dozens of sessions named like `1780bae5-8773-4614-b276-8f795477d43a.jsonl` and no way to find anything.

`cc-history` is a Claude Code plugin that:

- Indexes all your local session files into a fast SQLite full-text search index
- Generates a human-readable title + summary for each session using Claude Haiku (opt-in)
- Lets you search your history conversationally — just ask Claude "find that session where we figured out X"
- Hands you a paste-ready `claude --resume` command when you find the right session

Everything runs locally. The only network call is the (opt-in) Haiku call to title sessions.

## Install

```bash
# 1. Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Add this plugin to Claude Code
/plugin marketplace add gauravdhir/cc-history
/plugin install cc-history@cc-history
```

(Replace `gauravdhir` with this repo's owner.)

## Use

In any Claude Code session, just ask:

> *find that session where I was figuring out the Twilio bridge for Gemini Live*

Claude will call the `search_history` MCP tool and surface ranked matches with titles and summaries.

Or use the slash commands:

| Command | What it does |
|---|---|
| `/history <query>` | Search across all sessions |
| `/history-recent [days]` | Sessions from the last N days (default 7) |
| `/history-reindex` | Force a full reindex (re-titles untitled sessions) |
| `/history-reset` | Wipe the index and rebuild from scratch |

## AI titles (optional)

Without an API key, the plugin still works — but sessions show as `(untitled)`. Set `ANTHROPIC_API_KEY` in your shell to enable Haiku-generated titles. Cost: ~$0.001 per session, one-time, cached forever.

## Privacy

- All session data stays on your machine.
- The only outbound network call is the Anthropic API for title generation (only when `ANTHROPIC_API_KEY` is set).
- No telemetry.

## License

MIT
