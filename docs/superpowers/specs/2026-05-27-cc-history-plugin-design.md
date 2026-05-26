# Design: `cc-history` — Claude Code session search plugin

Date: 2026-05-27
Author: Gaurav (with Claude)
Status: Draft v1 — ready for review

---

## 1. Problem

Claude Code stores every session as a JSONL file under `~/.claude/projects/<project-slug>/<uuid>.jsonl`. Heavy users accumulate hundreds of sessions across many projects. Today there is no built-in way to:

- Find a past conversation by what it was *about* (only by hex UUID).
- Tell sessions apart at a glance — they are named `1780bae5-8773-4614-b276-8f795477d43a.jsonl`.
- Recall a specific decision, snippet, or answer from weeks ago without re-running the work.

The pain is acute for users with 50+ sessions. Native `--resume` only lists recent sessions and shows no titles.

## 2. Goal

Ship a Claude Code plugin that turns the user's local session history into a searchable, *named* corpus the user can interrogate from inside any Claude Code session — without leaving the terminal.

### Primary user journeys

| ID | Journey | Success looks like |
|---|---|---|
| **A** | "Find that conversation where I figured out X." | User types one sentence; gets ≤5 ranked sessions with human-readable titles + summaries in <2s. |
| **B** | "Resume an old session I half-remember." | User finds the session via search, asks "resume that one" → gets the exact `cd … && claude --resume <id>` command, copy-ready. |
| **D** | "Find a specific snippet or answer Claude gave me." | User searches for code/error text; gets matching turns with file/line context and surrounding conversation. |

### Non-goals (v1)

- Web UI / browser dashboard (revisit as v2 if requested).
- Cross-machine sync.
- Editing or deleting sessions.
- Semantic / vector search (keyword + AI-title retrieval is enough for v1).
- Auto-tagging beyond what Haiku title-generation produces.

## 3. Solution shape

A Claude Code plugin named `cc-history` containing:

1. **MCP server** (`cc-history-mcp`) — long-lived stdio process spawned by Claude Code, exposes 4 tools for search/read/resume.
2. **Slash command** `/history <query>` — terminal-fast keyword search wrapper.
3. **SQLite index** at `${CLAUDE_PLUGIN_DATA}/index.db` — FTS5 full-text + metadata + AI-generated titles.
4. **Indexer** — lazy, incremental. Runs on first MCP tool call; subsequent calls only process JSONL files with newer mtime than last indexed.
5. **AI title generator** — opt-in. Calls Claude Haiku once per session to produce `{title, summary, tags}`. Cached in the DB forever.

The plugin is **conversational-first**: the value lands when a user, in any CC session, says *"find that thing where I was exploring Twilio + Gemini Live"* and Claude calls `search_history`, reads results, and answers in-place.

## 4. Architecture

```
~/.claude/projects/                    (input: Claude Code session files)
        │
        ▼
┌───────────────────┐    SQLite FTS5    ┌──────────────────┐
│  Indexer (Python) │ ───────────────▶  │  index.db        │
│  - JSONL parser   │                   │  - sessions      │
│  - turn extractor │                   │  - turns (FTS5)  │
│  - Haiku titler   │                   │  - tags          │
└───────────────────┘                   └──────────────────┘
        ▲                                       ▲
        │ on-demand                             │ reads
        │                                       │
┌───────────────────┐    MCP / stdio    ┌──────────────────┐
│  Claude Code      │ ◀───────────────▶ │  cc-history-mcp  │
│  (any session)    │                   │  (Python server) │
└───────────────────┘                   └──────────────────┘
```

### Plugin layout

```
cc-history/
├── .claude-plugin/
│   └── plugin.json              # name, version, author
├── .mcp.json                    # spawns the MCP server
├── commands/
│   └── history.md               # /history slash command
├── src/                         # Python package (published to PyPI)
│   └── cc_history/
│       ├── server.py            # MCP server entrypoint
│       ├── indexer.py           # JSONL → SQLite
│       ├── titler.py            # Haiku title/summary generation
│       ├── search.py            # FTS5 queries
│       └── models.py            # data classes
├── pyproject.toml               # publishes `cc-history-mcp` console script
└── README.md
```

### Distribution

- Python package `cc-history-mcp` published to PyPI.
- Plugin manifest invokes it via `uvx`:

  ```json
  // .mcp.json
  {
    "mcpServers": {
      "cc-history": {
        "command": "uvx",
        "args": ["cc-history-mcp"],
        "env": {
          "CC_HISTORY_DB": "${CLAUDE_PLUGIN_DATA}/index.db",
          "CC_HISTORY_SESSIONS_DIR": "~/.claude/projects",
          "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"
        }
      }
    }
  }
  ```

  `uvx` handles dependency isolation; user only needs `uv` (or we ship a fallback `pip install` instruction).

- GitHub repo hosts the plugin. Users install with:

  ```
  /plugin marketplace add <gh-user>/cc-history
  /plugin install cc-history@cc-history
  ```

- Submission to `claude-plugins-community` after first 50 stars or first external user.

## 5. Data model

SQLite, single file at `${CLAUDE_PLUGIN_DATA}/index.db`.

```sql
CREATE TABLE sessions (
  id              TEXT PRIMARY KEY,          -- UUID from filename
  project_slug    TEXT NOT NULL,             -- e.g. "-Users-gauravdhir"
  project_path    TEXT NOT NULL,             -- decoded: /Users/gauravdhir
  file_path       TEXT NOT NULL,             -- absolute path to JSONL
  file_mtime      REAL NOT NULL,             -- for incremental reindex
  started_at      TEXT,                      -- ISO timestamp of first turn
  ended_at        TEXT,
  turn_count      INTEGER,
  title           TEXT,                      -- AI-generated, nullable
  summary         TEXT,                      -- AI-generated, nullable
  tags            TEXT,                      -- AI-generated, JSON array
  title_model     TEXT,                      -- which model produced the title
  title_generated_at TEXT
);

CREATE INDEX idx_sessions_project ON sessions(project_path);
CREATE INDEX idx_sessions_started ON sessions(started_at DESC);

-- FTS5 virtual table for full-text search across all turns
CREATE VIRTUAL TABLE turns_fts USING fts5(
  session_id UNINDEXED,
  turn_index UNINDEXED,
  role,            -- 'user' | 'assistant'
  content,         -- the text content of the turn
  tokenize = 'porter unicode61'
);

CREATE TABLE index_meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
-- e.g. ('last_full_scan_at', '2026-05-27T10:14:00Z')
```

**Why FTS5**: built into stock SQLite, no extra deps, fast on hundreds of thousands of turns, supports phrase + prefix + boolean queries (`MATCH 'gemini AND live'`).

**What we store from each turn**: role + concatenated text content. Tool calls and tool results are dropped from the FTS index (too noisy); they remain accessible via `get_session` which reads the raw JSONL.

## 6. MCP tool API

The server exposes exactly 4 tools. Each tool's input/output schema is published in the MCP manifest.

### `search_history`

Inputs:
- `query` (string, required) — FTS5 query syntax (the server tolerates plain prose and rewrites it).
- `limit` (int, default 5, max 20)
- `project` (string, optional) — restrict to a project path substring
- `since_days` (int, optional) — only sessions started in the last N days

Returns: list of sessions, each with `{id, title, summary, tags, project_path, started_at, turn_count, matched_snippets: [...]}`.

### `get_session`

Inputs:
- `session_id` (string, required)
- `include_tool_calls` (bool, default false) — controls verbosity
- `max_turns` (int, default 200) — safety cap

Returns: ordered list of turns with role, content, and timestamp. Reads the original JSONL — the FTS index is only used for search.

### `list_recent`

Inputs:
- `days` (int, default 7, max 90)
- `project` (string, optional)

Returns: sessions ordered by `started_at DESC`, with titles + summaries. Used for "what did I work on this week?"

### `get_resume_command`

Inputs:
- `session_id` (string, required)

Returns: `{command: "cd /Users/gaurav/Projects/foo && claude --resume 1780bae5-…", project_path, session_title}`. The user (or Claude on their behalf) pastes this into a terminal.

## 7. Slash commands

All slash commands are thin markdown skills under `commands/` that instruct Claude to call the MCP tools. They are convenience sugar — the MCP tools also work via free-form requests.

| Command | Behavior |
|---|---|
| `/history <query>` | Calls `search_history(query, limit=5)`. Renders numbered list with title + summary + relative date. Offers follow-ups: "Open #2", "Resume #1", "Show more". |
| `/history-recent [days]` | Calls `list_recent`. Default 7 days. |
| `/history-reindex` | Forces a full reindex (re-scans all JSONL, regenerates missing titles). Useful after schema changes or first time setting `ANTHROPIC_API_KEY`. |
| `/history-retitle <session-id>` | Regenerates the title for one session. For when an AI title misses the mark. |
| `/history-reset` | Wipes `index.db` and rebuilds from scratch. Recovery command. |

## 8. AI title generation

### Trigger

Title generation runs as part of indexing, but is opt-in:

- If `ANTHROPIC_API_KEY` is set → titles are generated automatically for new/changed sessions.
- If not set → indexing still works, sessions show `(untitled)` and the user can run `/history reindex --titles` later after setting the key.

### Prompt (sketch, to be tuned in implementation)

```
You are titling a Claude Code conversation. Read the first user message and the
first 2 assistant responses below, then produce JSON:

{
  "title": "<8-12 word descriptive title in Title Case>",
  "summary": "<one-sentence summary of what was discussed/decided, ≤25 words>",
  "tags": ["<2-5 short lowercase topic tags>"]
}

CONVERSATION:
[user]: …
[assistant]: …
[user]: …
[assistant]: …

Return JSON only.
```

Model: `claude-haiku-4-5-20251001` (cheap, fast, accurate enough for titles). One call per session, cached in `sessions` row, never re-run unless user passes `--retitle`.

### Cost estimate

- ~2k input tokens + ~80 output tokens per session.
- Haiku 4.5 pricing → roughly **$0.001 per session**, **~$0.50 for 500 sessions** one-time.
- Cached forever in SQLite → re-titling is a deliberate user action.

### Privacy posture

- README is explicit: the only network call is the Anthropic API for title generation.
- Title-generation can be disabled by simply not setting the API key.
- All session data stays on disk.
- No telemetry.

## 9. Indexing strategy

- **First run**: full scan of `~/.claude/projects/`. Shows a progress line via stderr (MCP transport allows logging on stderr without breaking the JSON-RPC channel).
- **Subsequent calls**: compare each JSONL file's mtime against `sessions.file_mtime`. Re-index only changed/new files.
- **Trigger**: indexing runs at the start of any tool call that needs fresh data (`search_history`, `list_recent`). The first tool call after the user opens CC may take a couple seconds; subsequent calls are instant.
- **No daemon, no file watcher.** Keeps the install zero-config.

## 10. Error handling

| Failure | Behavior |
|---|---|
| `~/.claude/projects/` doesn't exist or is empty | Tool returns `{sessions: [], note: "No Claude Code history found at ~/.claude/projects/"}` |
| JSONL file is malformed mid-stream | Skip bad lines, count them, surface count in indexer log; the session is still indexed with what's parseable |
| `ANTHROPIC_API_KEY` missing | Indexing proceeds without titles; tools return sessions with `title: null, summary: null` |
| Haiku API call fails (network, rate limit) | Retry once with 1s backoff; on second failure, leave `title=null` and continue; the session is re-eligible next index run |
| SQLite DB corrupt | Tool returns error; provide `/history reset-index` slash command to wipe and rebuild |

## 11. Testing approach

Use TDD per the project's `superpowers:test-driven-development` skill:

- **Unit**: JSONL parser, FTS query builder, title prompt formatter (mocked Haiku response).
- **Integration**: real SQLite, fixture JSONL files mimicking real `~/.claude/projects/` shape, run `search_history` end-to-end.
- **Live smoke**: against the user's actual `~/.claude/projects/` (40+ projects) — does indexing complete, are searches fast, do titles look reasonable?

## 12. Open risks

1. **`uv` / `uvx` dependency**: requires the user has `uv` installed. Mitigation: README provides one-line install (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and a pip-based fallback.
2. **Haiku title quality on long sessions**: first-3-turns prompt may not capture the meat of a long meandering session. Acceptable for v1; revisit if titles feel off.
3. **JSONL schema drift**: Claude Code's JSONL format evolves. Indexer must tolerate unknown fields. Pin a minimum CC version in README.
4. **Privacy concern about Haiku call**: users may not want their conversations sent anywhere. Default-off behavior (no API key = no calls) mitigates.

## 13. Success criteria

For v1 to be considered done:

- [ ] User can install the plugin in <2 minutes via README instructions.
- [ ] First-run indexing completes in <30s for the author's ~40 projects.
- [ ] `search_history` returns relevant results for "gemini live api" and "telephony compliance" against the author's real history.
- [ ] AI titles for 90% of sessions read as human and on-topic (manual eval of 20 random titles).
- [ ] `get_resume_command` produces a working `claude --resume` command that lands the user in the intended past session.
- [ ] README is screenshot-worthy: shows a `/history` query and a clean result list.

## 14. v2 candidates (not in scope)

Roadmap candidates, ranked by my guess of value:

1. Web UI for browsing/reading (the original mockup).
2. Semantic search (sentence-transformers locally, or Voyage embeddings).
3. Bookmark/star sessions; "favorites" view.
4. Auto-summary "this week" digest.
5. Export session as Markdown.

Ship v1, see what users ask for, then pick.

---

## Appendix A: example end-to-end flow

```
User (inside any CC session):
  > find the session where I was figuring out outbound calling with twilio

Claude (calls search_history):
  Found 3 matches:
  1. **Outbound calling PoC: Gemini Live + Twilio bridge** — May 12
     Architecture for AI marketing calls; explored Indian DLT compliance.
     [voice-AI · telephony · compliance]
  2. **Twilio number provisioning for Indian numbers** — Apr 30
     DLT registration steps; chose Plivo as alternative.
  3. **Real-time STT comparison for telephony** — Apr 19
     Cost/latency analysis; picked Gemini Live.

User:
  > resume #1

Claude (calls get_resume_command):
  Here's the command (copied to your clipboard):
    cd /Users/gauravdhir/Desktop/AI-Counsellor && claude --resume 1780bae5-…
  Paste it into a fresh terminal tab.
```
