# cc-history Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Claude Code plugin that indexes the user's local `~/.claude/projects/` JSONL files into a SQLite FTS5 store and exposes 4 MCP tools + 5 slash commands so users can find, read, and resume past Claude sessions by what they were *about*.

**Architecture:** Python package `cc-history-mcp` (PyPI) implements an MCP server (FastMCP-based) backed by SQLite FTS5. The server is spawned via `uvx` by a thin Claude Code plugin manifest. Indexer runs lazily and incrementally on tool calls; AI titles are generated via Claude Haiku 4.5 (opt-in, requires `ANTHROPIC_API_KEY`).

**Tech Stack:** Python 3.11+, `mcp` SDK (FastMCP), `anthropic` SDK, stdlib `sqlite3` (FTS5), `pytest` for tests, `uv`/`uvx` for distribution.

**Spec:** `docs/superpowers/specs/2026-05-27-cc-history-plugin-design.md`

---

## File Structure

```
cc-history-search/
├── .claude-plugin/
│   └── plugin.json
├── .mcp.json
├── commands/
│   ├── history.md
│   ├── history-recent.md
│   ├── history-reindex.md
│   ├── history-retitle.md
│   └── history-reset.md
├── src/cc_history/
│   ├── __init__.py
│   ├── config.py          # env-var driven settings
│   ├── models.py          # dataclasses: Turn, Session, SearchHit
│   ├── jsonl_parser.py    # JSONL file → Turn list + session metadata
│   ├── slug.py            # project-slug ↔ filesystem path conversion
│   ├── db.py              # SQLite schema, connection, migrations
│   ├── titler.py          # Haiku prompt + parse + retry
│   ├── indexer.py         # orchestrates parser → titler → db
│   ├── search.py          # FTS5 query builder + search/list_recent
│   └── server.py          # FastMCP server: 4 tools + main()
├── tests/
│   ├── conftest.py        # pytest fixtures: tmp db, sample jsonl
│   ├── fixtures/
│   │   ├── sample_session_a.jsonl
│   │   ├── sample_session_b.jsonl
│   │   └── malformed.jsonl
│   ├── test_slug.py
│   ├── test_jsonl_parser.py
│   ├── test_db.py
│   ├── test_indexer.py
│   ├── test_search.py
│   ├── test_titler.py
│   └── test_server.py
├── pyproject.toml
├── README.md
└── .gitignore             # already exists
```

**Why these boundaries:** Each module has one job: `slug.py` does path conversion, `jsonl_parser.py` reads JSONL into typed objects, `db.py` owns schema + queries, `indexer.py` orchestrates, `search.py` is read-side, `titler.py` is the only file that talks to the Anthropic API, `server.py` is the only file that talks to MCP. This lets each unit be tested in isolation.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/cc_history/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "cc-history-mcp"
version = "0.1.0"
description = "Search Claude Code session history from inside Claude Code via MCP"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Gaurav Dhir" }]
dependencies = [
    "mcp>=1.2.0",
    "anthropic>=0.40.0",
]

[project.scripts]
cc-history-mcp = "cc_history.server:main"

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/cc_history"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create empty package + test init**

```python
# src/cc_history/__init__.py
__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

- [ ] **Step 3: Create shared pytest fixtures**

```python
# tests/conftest.py
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_index.db"


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_jsonl_a(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample_session_a.jsonl"


@pytest.fixture
def sample_jsonl_b(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample_session_b.jsonl"


@pytest.fixture
def malformed_jsonl(fixtures_dir: Path) -> Path:
    return fixtures_dir / "malformed.jsonl"
```

- [ ] **Step 4: Install dev deps and verify**

Run:
```bash
cd /Users/gauravdhir/Projects/cc-history-search
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest --collect-only
```

Expected: pytest finds no tests (none written yet) but exits 0.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/cc_history/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: scaffold python package and pytest setup"
```

---

## Task 2: Project-slug ↔ filesystem path conversion

Claude Code encodes project paths as `-Users-gauravdhir-Documents-Foo`. We need both directions.

**Files:**
- Create: `src/cc_history/slug.py`
- Test: `tests/test_slug.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_slug.py
from cc_history.slug import slug_to_path, path_to_slug


def test_slug_to_path_basic():
    assert slug_to_path("-Users-gauravdhir") == "/Users/gauravdhir"


def test_slug_to_path_nested():
    assert slug_to_path("-Users-gauravdhir-Documents-Foo") == "/Users/gauravdhir/Documents/Foo"


def test_slug_to_path_with_dashes_in_dir():
    # Claude Code encodes literal dashes as dashes too — we can't reliably distinguish.
    # Confirm the documented behavior: every dash becomes a slash.
    assert slug_to_path("-Users-foo-my-project") == "/Users/foo/my/project"


def test_path_to_slug_basic():
    assert path_to_slug("/Users/gauravdhir") == "-Users-gauravdhir"


def test_path_to_slug_roundtrip():
    for path in ["/Users/x", "/Users/x/Documents/Bar"]:
        assert slug_to_path(path_to_slug(path)) == path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_slug.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cc_history.slug'`

- [ ] **Step 3: Implement `slug.py`**

```python
# src/cc_history/slug.py
"""Convert between Claude Code's slugged project names and filesystem paths.

Claude Code stores sessions at ~/.claude/projects/<slug>/<uuid>.jsonl where
<slug> is the project's absolute path with `/` replaced by `-`. Directory names
that contain literal dashes are not distinguishable on the reverse — we accept
that ambiguity (rare in practice).
"""


def slug_to_path(slug: str) -> str:
    if not slug.startswith("-"):
        return slug
    return "/" + slug[1:].replace("-", "/")


def path_to_slug(path: str) -> str:
    return path.replace("/", "-")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_slug.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cc_history/slug.py tests/test_slug.py
git commit -m "feat: project-slug path conversion utilities"
```

---

## Task 3: Data models

**Files:**
- Create: `src/cc_history/models.py`

No tests — these are pure dataclasses. They get exercised in subsequent tasks.

- [ ] **Step 1: Create models**

```python
# src/cc_history/models.py
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Turn:
    """One turn in a Claude Code conversation."""
    index: int           # ordinal within the session, 0-based
    role: str            # 'user' | 'assistant' | 'system' | 'tool'
    content: str         # text content (tool calls stripped)
    timestamp: Optional[str] = None  # ISO 8601 if present


@dataclass
class Session:
    """A single Claude Code session, derived from one JSONL file."""
    id: str
    project_slug: str
    project_path: str
    file_path: str
    file_mtime: float
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    turn_count: int = 0
    title: Optional[str] = None
    summary: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    title_model: Optional[str] = None
    title_generated_at: Optional[str] = None


@dataclass
class SearchHit:
    """One row in a search result."""
    session: Session
    matched_snippets: list[str]  # FTS5-highlighted snippets, max 3
    rank: float                  # FTS5 bm25 rank; lower = better
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from cc_history.models import Turn, Session, SearchHit; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/cc_history/models.py
git commit -m "feat: data models (Turn, Session, SearchHit)"
```

---

## Task 4: JSONL fixtures for tests

Build realistic JSONL fixtures matching Claude Code's actual on-disk format. These drive every downstream test.

**Files:**
- Create: `tests/fixtures/sample_session_a.jsonl`
- Create: `tests/fixtures/sample_session_b.jsonl`
- Create: `tests/fixtures/malformed.jsonl`

- [ ] **Step 1: Create `sample_session_a.jsonl`**

A short, well-formed session about Gemini Live API. Each line is a complete JSON object.

```jsonl
{"type":"permission-mode","permissionMode":"default","sessionId":"aaaa1111-0000-0000-0000-000000000001"}
{"type":"user","message":{"role":"user","content":"I want to build a real-time voice agent using the Gemini Live API for telephony"},"timestamp":"2026-05-10T09:00:00Z","sessionId":"aaaa1111-0000-0000-0000-000000000001"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Great. The Gemini Live API supports native VAD. For telephony you'll want a Twilio bridge."}]},"timestamp":"2026-05-10T09:00:15Z","sessionId":"aaaa1111-0000-0000-0000-000000000001"}
{"type":"user","message":{"role":"user","content":"What about Indian DLT compliance for outbound calls?"},"timestamp":"2026-05-10T09:01:00Z","sessionId":"aaaa1111-0000-0000-0000-000000000001"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"You'll need DLT registration with one of the indian telecom providers before outbound."}]},"timestamp":"2026-05-10T09:01:30Z","sessionId":"aaaa1111-0000-0000-0000-000000000001"}
```

- [ ] **Step 2: Create `sample_session_b.jsonl`**

A short session on a different topic, for testing search ranking.

```jsonl
{"type":"user","message":{"role":"user","content":"Help me set up FastAPI with pydantic v2"},"timestamp":"2026-05-15T14:00:00Z","sessionId":"bbbb2222-0000-0000-0000-000000000002"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"FastAPI works great with pydantic v2. Install it with pip install fastapi pydantic."}]},"timestamp":"2026-05-15T14:00:10Z","sessionId":"bbbb2222-0000-0000-0000-000000000002"}
{"type":"user","message":{"role":"user","content":"How do I add request validation?"},"timestamp":"2026-05-15T14:01:00Z","sessionId":"bbbb2222-0000-0000-0000-000000000002"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Define a BaseModel and use it as a parameter annotation."}]},"timestamp":"2026-05-15T14:01:20Z","sessionId":"bbbb2222-0000-0000-0000-000000000002"}
```

- [ ] **Step 3: Create `malformed.jsonl`**

A session with one bad line in the middle. Parser must skip it and keep going.

```jsonl
{"type":"user","message":{"role":"user","content":"first valid line"},"timestamp":"2026-05-20T10:00:00Z","sessionId":"cccc3333-0000-0000-0000-000000000003"}
{not json at all
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"third line is valid again"}]},"timestamp":"2026-05-20T10:00:10Z","sessionId":"cccc3333-0000-0000-0000-000000000003"}
```

- [ ] **Step 4: Verify fixtures**

Run: `python -c "import json; [json.loads(l) for l in open('tests/fixtures/sample_session_a.jsonl')]; print('a ok')"`
Run: `python -c "import json; [json.loads(l) for l in open('tests/fixtures/sample_session_b.jsonl')]; print('b ok')"`
Expected: both print `ok`. (The malformed one is expected to fail JSON parsing on line 2 — that's the point.)

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/
git commit -m "test: jsonl fixtures (two well-formed sessions + one malformed)"
```

---

## Task 5: JSONL parser

**Files:**
- Create: `src/cc_history/jsonl_parser.py`
- Test: `tests/test_jsonl_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_jsonl_parser.py
from pathlib import Path

from cc_history.jsonl_parser import parse_session_file


def test_parses_well_formed_session(sample_jsonl_a: Path):
    session, turns = parse_session_file(sample_jsonl_a, project_slug="-Users-x", file_mtime=123.0)

    assert session.id == "aaaa1111-0000-0000-0000-000000000001"
    assert session.project_slug == "-Users-x"
    assert session.project_path == "/Users/x"
    assert session.file_path == str(sample_jsonl_a)
    assert session.file_mtime == 123.0
    assert session.started_at == "2026-05-10T09:00:00Z"
    assert session.ended_at == "2026-05-10T09:01:30Z"
    # 2 user + 2 assistant = 4 indexable turns (permission-mode lines are dropped)
    assert session.turn_count == 4
    assert len(turns) == 4
    assert turns[0].role == "user"
    assert "Gemini Live API" in turns[0].content
    assert turns[1].role == "assistant"


def test_skips_malformed_lines(malformed_jsonl: Path):
    session, turns = parse_session_file(malformed_jsonl, project_slug="-tmp", file_mtime=0.0)
    # 2 valid turns despite the broken middle line
    assert len(turns) == 2
    assert turns[0].content == "first valid line"
    assert turns[1].content == "third line is valid again"


def test_session_id_falls_back_to_filename(tmp_path: Path):
    # A file with no sessionId field — derive from filename stem.
    p = tmp_path / "fallback-id-1234.jsonl"
    p.write_text('{"type":"user","message":{"role":"user","content":"hi"}}\n')
    session, _ = parse_session_file(p, project_slug="-tmp", file_mtime=0.0)
    assert session.id == "fallback-id-1234"


def test_assistant_content_block_list(sample_jsonl_a: Path):
    """Assistant messages store content as a list of typed blocks; we concatenate text blocks."""
    _, turns = parse_session_file(sample_jsonl_a, project_slug="-Users-x", file_mtime=0.0)
    assert "Gemini Live API supports native VAD" in turns[1].content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_jsonl_parser.py -v`
Expected: `ModuleNotFoundError: No module named 'cc_history.jsonl_parser'`

- [ ] **Step 3: Implement `jsonl_parser.py`**

```python
# src/cc_history/jsonl_parser.py
"""Parse Claude Code session JSONL files into typed Turn + Session objects.

Each JSONL line is a JSON event. We only index `user` and `assistant` events
and concatenate their textual content. Tool calls, hook output, permission
notices, and other event types are skipped at index time (they remain
accessible via raw JSONL reads in `get_session`).
"""
import json
from pathlib import Path
from typing import Optional

from cc_history.models import Session, Turn
from cc_history.slug import slug_to_path


INDEXABLE_TYPES = {"user", "assistant"}


def _extract_text(message: dict) -> str:
    """Pull text out of a Claude Code message payload.

    User messages have `content: str`. Assistant messages have
    `content: list[{type, text, ...}]` — we concatenate text blocks.
    """
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return ""


def parse_session_file(
    path: Path,
    *,
    project_slug: str,
    file_mtime: float,
) -> tuple[Session, list[Turn]]:
    turns: list[Turn] = []
    session_id: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate bad lines

            if not isinstance(event, dict):
                continue

            # Capture sessionId from any event that carries it
            if session_id is None and "sessionId" in event:
                session_id = event["sessionId"]

            etype = event.get("type")
            if etype not in INDEXABLE_TYPES:
                continue

            message = event.get("message") or {}
            text = _extract_text(message)
            if not text:
                continue

            ts = event.get("timestamp")
            if started_at is None and ts:
                started_at = ts
            if ts:
                ended_at = ts

            turns.append(Turn(
                index=len(turns),
                role=message.get("role", etype),
                content=text,
                timestamp=ts,
            ))

    if session_id is None:
        session_id = path.stem  # fallback: filename without extension

    session = Session(
        id=session_id,
        project_slug=project_slug,
        project_path=slug_to_path(project_slug),
        file_path=str(path),
        file_mtime=file_mtime,
        started_at=started_at,
        ended_at=ended_at,
        turn_count=len(turns),
    )
    return session, turns
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_jsonl_parser.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cc_history/jsonl_parser.py tests/test_jsonl_parser.py
git commit -m "feat: jsonl parser with malformed-line tolerance"
```

---

## Task 6: SQLite schema and DB module

**Files:**
- Create: `src/cc_history/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db.py
import sqlite3
from pathlib import Path

import pytest

from cc_history.db import open_db, upsert_session, replace_turns, get_indexed_mtime
from cc_history.models import Session, Turn


def test_open_db_creates_schema(tmp_db_path: Path):
    conn = open_db(tmp_db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert "sessions" in tables
    assert "turns_fts" in tables
    assert "index_meta" in tables
    conn.close()


def test_open_db_is_idempotent(tmp_db_path: Path):
    open_db(tmp_db_path).close()
    open_db(tmp_db_path).close()  # opening twice must not raise


def test_upsert_then_lookup(tmp_db_path: Path):
    conn = open_db(tmp_db_path)
    s = Session(
        id="abc-1", project_slug="-tmp", project_path="/tmp",
        file_path="/tmp/abc-1.jsonl", file_mtime=10.0, turn_count=2,
    )
    upsert_session(conn, s)
    row = conn.execute("SELECT id, file_mtime, turn_count FROM sessions WHERE id=?", ("abc-1",)).fetchone()
    assert row == ("abc-1", 10.0, 2)


def test_upsert_updates_existing(tmp_db_path: Path):
    conn = open_db(tmp_db_path)
    s = Session(id="abc-1", project_slug="-tmp", project_path="/tmp",
                file_path="/tmp/abc-1.jsonl", file_mtime=10.0, turn_count=2)
    upsert_session(conn, s)
    s.file_mtime = 20.0
    s.turn_count = 5
    upsert_session(conn, s)
    row = conn.execute("SELECT file_mtime, turn_count FROM sessions WHERE id=?", ("abc-1",)).fetchone()
    assert row == (20.0, 5)


def test_replace_turns_populates_fts(tmp_db_path: Path):
    conn = open_db(tmp_db_path)
    s = Session(id="abc-1", project_slug="-tmp", project_path="/tmp",
                file_path="/tmp/abc-1.jsonl", file_mtime=10.0, turn_count=2)
    upsert_session(conn, s)
    turns = [
        Turn(index=0, role="user", content="hello gemini live api"),
        Turn(index=1, role="assistant", content="hi! the live api supports VAD"),
    ]
    replace_turns(conn, "abc-1", turns)
    rows = conn.execute(
        "SELECT session_id, role, content FROM turns_fts WHERE turns_fts MATCH 'gemini'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "abc-1"


def test_replace_turns_deletes_old_rows(tmp_db_path: Path):
    conn = open_db(tmp_db_path)
    s = Session(id="abc-1", project_slug="-tmp", project_path="/tmp",
                file_path="/tmp/abc-1.jsonl", file_mtime=10.0, turn_count=1)
    upsert_session(conn, s)
    replace_turns(conn, "abc-1", [Turn(index=0, role="user", content="old content")])
    replace_turns(conn, "abc-1", [Turn(index=0, role="user", content="new content")])
    rows = conn.execute("SELECT content FROM turns_fts WHERE session_id='abc-1'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "new content"


def test_get_indexed_mtime_returns_none_for_unknown(tmp_db_path: Path):
    conn = open_db(tmp_db_path)
    assert get_indexed_mtime(conn, "does-not-exist") is None


def test_get_indexed_mtime_returns_stored(tmp_db_path: Path):
    conn = open_db(tmp_db_path)
    s = Session(id="abc-1", project_slug="-tmp", project_path="/tmp",
                file_path="/tmp/abc-1.jsonl", file_mtime=42.5, turn_count=0)
    upsert_session(conn, s)
    assert get_indexed_mtime(conn, "abc-1") == 42.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: `ModuleNotFoundError: No module named 'cc_history.db'`

- [ ] **Step 3: Implement `db.py`**

```python
# src/cc_history/db.py
"""SQLite schema + connection management for the cc-history index."""
import json
import sqlite3
from pathlib import Path
from typing import Optional

from cc_history.models import Session, Turn


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT PRIMARY KEY,
    project_slug        TEXT NOT NULL,
    project_path        TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    file_mtime          REAL NOT NULL,
    started_at          TEXT,
    ended_at            TEXT,
    turn_count          INTEGER DEFAULT 0,
    title               TEXT,
    summary             TEXT,
    tags                TEXT,
    title_model         TEXT,
    title_generated_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    session_id UNINDEXED,
    turn_index UNINDEXED,
    role,
    content,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS index_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def upsert_session(conn: sqlite3.Connection, s: Session) -> None:
    conn.execute(
        """
        INSERT INTO sessions (
            id, project_slug, project_path, file_path, file_mtime,
            started_at, ended_at, turn_count, title, summary, tags,
            title_model, title_generated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            project_slug=excluded.project_slug,
            project_path=excluded.project_path,
            file_path=excluded.file_path,
            file_mtime=excluded.file_mtime,
            started_at=excluded.started_at,
            ended_at=excluded.ended_at,
            turn_count=excluded.turn_count,
            title=COALESCE(excluded.title, sessions.title),
            summary=COALESCE(excluded.summary, sessions.summary),
            tags=COALESCE(excluded.tags, sessions.tags),
            title_model=COALESCE(excluded.title_model, sessions.title_model),
            title_generated_at=COALESCE(excluded.title_generated_at, sessions.title_generated_at)
        """,
        (
            s.id, s.project_slug, s.project_path, s.file_path, s.file_mtime,
            s.started_at, s.ended_at, s.turn_count,
            s.title, s.summary,
            json.dumps(s.tags) if s.tags else None,
            s.title_model, s.title_generated_at,
        ),
    )
    conn.commit()


def replace_turns(conn: sqlite3.Connection, session_id: str, turns: list[Turn]) -> None:
    conn.execute("DELETE FROM turns_fts WHERE session_id = ?", (session_id,))
    conn.executemany(
        "INSERT INTO turns_fts (session_id, turn_index, role, content) VALUES (?,?,?,?)",
        [(session_id, t.index, t.role, t.content) for t in turns],
    )
    conn.commit()


def get_indexed_mtime(conn: sqlite3.Connection, session_id: str) -> Optional[float]:
    row = conn.execute("SELECT file_mtime FROM sessions WHERE id=?", (session_id,)).fetchone()
    return row[0] if row else None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_db.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cc_history/db.py tests/test_db.py
git commit -m "feat: sqlite schema with fts5 turns table and upsert"
```

---

## Task 7: Indexer (orchestration, no titles yet)

The indexer walks `~/.claude/projects/`, decides which files need (re)indexing based on mtime, parses them, writes to the DB. Title generation is wired in Task 9.

**Files:**
- Create: `src/cc_history/indexer.py`
- Test: `tests/test_indexer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_indexer.py
import shutil
from pathlib import Path

from cc_history.db import open_db
from cc_history.indexer import index_all


def _stage_sessions_dir(tmp_path: Path, fixtures_dir: Path) -> Path:
    """Build a fake ~/.claude/projects/ tree with two projects."""
    root = tmp_path / "projects"
    proj_a = root / "-Users-x-ProjectA"
    proj_b = root / "-Users-x-ProjectB"
    proj_a.mkdir(parents=True)
    proj_b.mkdir(parents=True)
    shutil.copy(fixtures_dir / "sample_session_a.jsonl", proj_a / "aaaa1111-0000-0000-0000-000000000001.jsonl")
    shutil.copy(fixtures_dir / "sample_session_b.jsonl", proj_b / "bbbb2222-0000-0000-0000-000000000002.jsonl")
    return root


def test_index_all_indexes_two_sessions(tmp_path: Path, fixtures_dir: Path, tmp_db_path: Path):
    sessions_dir = _stage_sessions_dir(tmp_path, fixtures_dir)
    conn = open_db(tmp_db_path)
    stats = index_all(conn, sessions_dir, generate_titles=False)
    assert stats.indexed == 2
    assert stats.skipped == 0
    rows = conn.execute("SELECT id, project_path FROM sessions ORDER BY id").fetchall()
    assert len(rows) == 2
    assert rows[0]["project_path"] == "/Users/x/ProjectA"


def test_index_all_is_incremental(tmp_path: Path, fixtures_dir: Path, tmp_db_path: Path):
    sessions_dir = _stage_sessions_dir(tmp_path, fixtures_dir)
    conn = open_db(tmp_db_path)
    index_all(conn, sessions_dir, generate_titles=False)
    stats = index_all(conn, sessions_dir, generate_titles=False)
    assert stats.indexed == 0
    assert stats.skipped == 2


def test_index_all_reindexes_after_mtime_change(tmp_path: Path, fixtures_dir: Path, tmp_db_path: Path):
    sessions_dir = _stage_sessions_dir(tmp_path, fixtures_dir)
    conn = open_db(tmp_db_path)
    index_all(conn, sessions_dir, generate_titles=False)

    # Touch one file (bump mtime by 100s into the future)
    import os, time
    target = next((sessions_dir / "-Users-x-ProjectA").glob("*.jsonl"))
    new_time = time.time() + 100
    os.utime(target, (new_time, new_time))

    stats = index_all(conn, sessions_dir, generate_titles=False)
    assert stats.indexed == 1
    assert stats.skipped == 1


def test_index_all_handles_missing_dir(tmp_path: Path, tmp_db_path: Path):
    conn = open_db(tmp_db_path)
    stats = index_all(conn, tmp_path / "does-not-exist", generate_titles=False)
    assert stats.indexed == 0
    assert stats.skipped == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_indexer.py -v`
Expected: `ModuleNotFoundError: No module named 'cc_history.indexer'`

- [ ] **Step 3: Implement `indexer.py`**

```python
# src/cc_history/indexer.py
"""Walks ~/.claude/projects/ and feeds JSONL files into the SQLite index.

Incremental by mtime: if the file's mtime <= the stored file_mtime for that
session id, we skip. Title generation is delegated to `titler` and is
optional (controlled by `generate_titles` flag + presence of api key).
"""
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cc_history.db import get_indexed_mtime, replace_turns, upsert_session
from cc_history.jsonl_parser import parse_session_file


@dataclass
class IndexStats:
    indexed: int = 0
    skipped: int = 0
    failed: int = 0


def index_all(
    conn: sqlite3.Connection,
    sessions_root: Path,
    *,
    generate_titles: bool = False,
    titler=None,  # callable: (Session, list[Turn]) -> Session — wired in Task 9
) -> IndexStats:
    stats = IndexStats()
    if not sessions_root.exists():
        return stats

    for project_dir in sessions_root.iterdir():
        if not project_dir.is_dir():
            continue
        project_slug = project_dir.name
        for jsonl in project_dir.glob("*.jsonl"):
            try:
                mtime = jsonl.stat().st_mtime
                # Use session id from parsed file (fallback path uses filename stem)
                session_id_guess = jsonl.stem
                prev = get_indexed_mtime(conn, session_id_guess)
                if prev is not None and prev >= mtime:
                    stats.skipped += 1
                    continue

                session, turns = parse_session_file(
                    jsonl, project_slug=project_slug, file_mtime=mtime,
                )
                if generate_titles and titler is not None:
                    session = titler(session, turns)
                upsert_session(conn, session)
                replace_turns(conn, session.id, turns)
                stats.indexed += 1
            except Exception:
                stats.failed += 1

    return stats
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_indexer.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cc_history/indexer.py tests/test_indexer.py
git commit -m "feat: incremental jsonl indexer driven by file mtime"
```

---

## Task 8: Search (FTS5 queries + list_recent)

**Files:**
- Create: `src/cc_history/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_search.py
import shutil
from pathlib import Path

from cc_history.db import open_db
from cc_history.indexer import index_all
from cc_history.search import search_history, list_recent, get_session_turns, build_resume_command


def _populate_index(tmp_path: Path, fixtures_dir: Path, db_path: Path):
    sessions_dir = tmp_path / "projects"
    proj_a = sessions_dir / "-Users-x-VoiceAgent"
    proj_b = sessions_dir / "-Users-x-FastAPIDemo"
    proj_a.mkdir(parents=True)
    proj_b.mkdir(parents=True)
    shutil.copy(fixtures_dir / "sample_session_a.jsonl", proj_a / "aaaa1111-0000-0000-0000-000000000001.jsonl")
    shutil.copy(fixtures_dir / "sample_session_b.jsonl", proj_b / "bbbb2222-0000-0000-0000-000000000002.jsonl")
    conn = open_db(db_path)
    index_all(conn, sessions_dir, generate_titles=False)
    return conn


def test_search_returns_matching_session(tmp_path: Path, fixtures_dir: Path, tmp_db_path: Path):
    conn = _populate_index(tmp_path, fixtures_dir, tmp_db_path)
    hits = search_history(conn, "gemini")
    assert len(hits) == 1
    assert hits[0].session.id == "aaaa1111-0000-0000-0000-000000000001"
    assert hits[0].matched_snippets, "expected at least one highlighted snippet"


def test_search_tolerates_prose_query(tmp_path: Path, fixtures_dir: Path, tmp_db_path: Path):
    """A natural-language query is rewritten into an FTS5-safe form."""
    conn = _populate_index(tmp_path, fixtures_dir, tmp_db_path)
    hits = search_history(conn, "the gemini live api thing")
    assert any(h.session.id == "aaaa1111-0000-0000-0000-000000000001" for h in hits)


def test_search_respects_limit(tmp_path: Path, fixtures_dir: Path, tmp_db_path: Path):
    conn = _populate_index(tmp_path, fixtures_dir, tmp_db_path)
    hits = search_history(conn, "the OR pydantic OR gemini", limit=1)
    assert len(hits) == 1


def test_search_filters_by_project(tmp_path: Path, fixtures_dir: Path, tmp_db_path: Path):
    conn = _populate_index(tmp_path, fixtures_dir, tmp_db_path)
    hits = search_history(conn, "api", project="VoiceAgent")
    assert all("VoiceAgent" in h.session.project_path for h in hits)


def test_list_recent_orders_by_started_at(tmp_path: Path, fixtures_dir: Path, tmp_db_path: Path):
    conn = _populate_index(tmp_path, fixtures_dir, tmp_db_path)
    recent = list_recent(conn, days=365)
    assert len(recent) == 2
    # session b started 2026-05-15, a started 2026-05-10 — b is more recent
    assert recent[0].id == "bbbb2222-0000-0000-0000-000000000002"


def test_get_session_turns_reads_raw_jsonl(tmp_path: Path, fixtures_dir: Path, tmp_db_path: Path):
    conn = _populate_index(tmp_path, fixtures_dir, tmp_db_path)
    turns = get_session_turns(conn, "aaaa1111-0000-0000-0000-000000000001", include_tool_calls=False)
    assert len(turns) == 4
    assert "Gemini Live API" in turns[0].content


def test_build_resume_command(tmp_path: Path, fixtures_dir: Path, tmp_db_path: Path):
    conn = _populate_index(tmp_path, fixtures_dir, tmp_db_path)
    cmd = build_resume_command(conn, "aaaa1111-0000-0000-0000-000000000001")
    assert cmd is not None
    assert "claude --resume aaaa1111-0000-0000-0000-000000000001" in cmd["command"]
    assert cmd["project_path"] == "/Users/x/VoiceAgent"


def test_build_resume_command_returns_none_for_unknown(tmp_path: Path, fixtures_dir: Path, tmp_db_path: Path):
    conn = _populate_index(tmp_path, fixtures_dir, tmp_db_path)
    assert build_resume_command(conn, "nonexistent-id") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_search.py -v`
Expected: `ModuleNotFoundError: No module named 'cc_history.search'`

- [ ] **Step 3: Implement `search.py`**

```python
# src/cc_history/search.py
"""Read-side queries: full-text search, recent sessions, raw session reads,
resume-command builder.
"""
import json
import re
import shlex
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from cc_history.jsonl_parser import parse_session_file
from cc_history.models import SearchHit, Session, Turn


# FTS5 reserves these characters; we strip them when accepting prose
_FTS_RESERVED = re.compile(r'[":\(\)\*\^]')


def _to_fts_query(raw: str) -> str:
    """Turn a prose query into a safe FTS5 MATCH expression.

    Strategy: tokenize on whitespace, drop very short / stoppy tokens,
    AND the rest together. This is lossy but predictable.
    """
    cleaned = _FTS_RESERVED.sub(" ", raw).lower()
    # Allow explicit boolean operators users might type
    tokens = [t for t in cleaned.split() if t]
    if not tokens:
        return '""'
    # Pass through if user already typed FTS operators
    if any(op in tokens for op in ("and", "or", "not")):
        return " ".join(tokens)
    # Drop tokens shorter than 3 chars (e.g. "the", "i", "a")
    tokens = [t for t in tokens if len(t) >= 3]
    if not tokens:
        return '""'
    return " AND ".join(tokens)


def _row_to_session(row: sqlite3.Row) -> Session:
    tags = json.loads(row["tags"]) if row["tags"] else []
    return Session(
        id=row["id"],
        project_slug=row["project_slug"],
        project_path=row["project_path"],
        file_path=row["file_path"],
        file_mtime=row["file_mtime"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        turn_count=row["turn_count"],
        title=row["title"],
        summary=row["summary"],
        tags=tags,
        title_model=row["title_model"],
        title_generated_at=row["title_generated_at"],
    )


def search_history(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 5,
    project: Optional[str] = None,
    since_days: Optional[int] = None,
) -> list[SearchHit]:
    fts_query = _to_fts_query(query)
    sql = """
        SELECT
            s.*,
            snippet(turns_fts, 3, '[', ']', '...', 12) AS snip,
            bm25(turns_fts) AS rank
        FROM turns_fts
        JOIN sessions s ON s.id = turns_fts.session_id
        WHERE turns_fts MATCH ?
    """
    params: list = [fts_query]
    if project:
        sql += " AND s.project_path LIKE ?"
        params.append(f"%{project}%")
    if since_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        sql += " AND s.started_at >= ?"
        params.append(cutoff)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit * 5)  # over-fetch then dedupe by session

    seen: dict[str, SearchHit] = {}
    for row in conn.execute(sql, params):
        sid = row["id"]
        if sid not in seen:
            seen[sid] = SearchHit(
                session=_row_to_session(row),
                matched_snippets=[row["snip"]],
                rank=row["rank"],
            )
        elif len(seen[sid].matched_snippets) < 3:
            seen[sid].matched_snippets.append(row["snip"])
        if len(seen) >= limit:
            break

    return list(seen.values())[:limit]


def list_recent(
    conn: sqlite3.Connection,
    *,
    days: int = 7,
    project: Optional[str] = None,
    limit: int = 50,
) -> list[Session]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sql = "SELECT * FROM sessions WHERE started_at >= ?"
    params: list = [cutoff]
    if project:
        sql += " AND project_path LIKE ?"
        params.append(f"%{project}%")
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    return [_row_to_session(r) for r in conn.execute(sql, params)]


def get_session_turns(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    include_tool_calls: bool = False,  # reserved for v1.1
    max_turns: int = 200,
) -> list[Turn]:
    row = conn.execute(
        "SELECT file_path, file_mtime, project_slug FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    if not row:
        return []
    _, turns = parse_session_file(
        Path(row["file_path"]),
        project_slug=row["project_slug"],
        file_mtime=row["file_mtime"],
    )
    return turns[:max_turns]


def build_resume_command(conn: sqlite3.Connection, session_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT project_path, title FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    if not row:
        return None
    cmd = f"cd {shlex.quote(row['project_path'])} && claude --resume {shlex.quote(session_id)}"
    return {
        "command": cmd,
        "project_path": row["project_path"],
        "session_title": row["title"],
    }
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_search.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cc_history/search.py tests/test_search.py
git commit -m "feat: fts5 search, list_recent, get_session, resume command"
```

---

## Task 9: Titler (Haiku call with mocked client)

**Files:**
- Create: `src/cc_history/titler.py`
- Test: `tests/test_titler.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_titler.py
import json
from unittest.mock import MagicMock

from cc_history.models import Session, Turn
from cc_history.titler import build_prompt, parse_response, generate_title


def _sample_session_and_turns():
    s = Session(id="x", project_slug="-tmp", project_path="/tmp",
                file_path="/tmp/x.jsonl", file_mtime=0.0, turn_count=4)
    turns = [
        Turn(0, "user", "Help me set up a voice agent with Gemini Live API"),
        Turn(1, "assistant", "Sure! Gemini Live supports VAD natively."),
        Turn(2, "user", "What about Twilio bridging?"),
        Turn(3, "assistant", "You'd use websockets to bridge Twilio audio."),
    ]
    return s, turns


def test_build_prompt_includes_first_three_turns():
    s, turns = _sample_session_and_turns()
    prompt = build_prompt(s, turns)
    assert "Gemini Live API" in prompt
    assert "Sure!" in prompt
    # Fourth turn must NOT appear (we only sample the first three)
    assert "websockets to bridge" not in prompt


def test_build_prompt_handles_short_sessions():
    s = Session(id="x", project_slug="-tmp", project_path="/tmp",
                file_path="/tmp/x.jsonl", file_mtime=0.0, turn_count=1)
    turns = [Turn(0, "user", "just one turn")]
    prompt = build_prompt(s, turns)
    assert "just one turn" in prompt


def test_parse_response_valid_json():
    payload = json.dumps({
        "title": "Voice Agent Architecture with Gemini Live",
        "summary": "Explored building a telephony voice agent using Gemini Live API.",
        "tags": ["voice-ai", "telephony", "gemini"],
    })
    title, summary, tags = parse_response(payload)
    assert title == "Voice Agent Architecture with Gemini Live"
    assert "telephony" in summary
    assert tags == ["voice-ai", "telephony", "gemini"]


def test_parse_response_strips_code_fences():
    """Models sometimes wrap JSON in ```json ... ``` — handle it."""
    fenced = '```json\n{"title":"T","summary":"S","tags":["a"]}\n```'
    title, summary, tags = parse_response(fenced)
    assert title == "T"
    assert tags == ["a"]


def test_parse_response_returns_none_on_garbage():
    title, summary, tags = parse_response("not json at all")
    assert title is None
    assert summary is None
    assert tags == []


def test_generate_title_with_mock_client():
    s, turns = _sample_session_and_turns()
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "title": "Voice Agent with Gemini Live",
        "summary": "Architecture for a telephony voice agent.",
        "tags": ["voice-ai", "telephony"],
    }))]
    mock_client.messages.create.return_value = mock_response

    updated = generate_title(s, turns, client=mock_client, model="claude-haiku-4-5-20251001")

    assert updated.title == "Voice Agent with Gemini Live"
    assert updated.summary == "Architecture for a telephony voice agent."
    assert updated.tags == ["voice-ai", "telephony"]
    assert updated.title_model == "claude-haiku-4-5-20251001"
    assert updated.title_generated_at is not None


def test_generate_title_returns_unchanged_on_api_failure():
    s, turns = _sample_session_and_turns()
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = RuntimeError("boom")
    updated = generate_title(s, turns, client=mock_client, model="claude-haiku-4-5-20251001")
    assert updated.title is None
    assert updated.title_generated_at is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_titler.py -v`
Expected: `ModuleNotFoundError: No module named 'cc_history.titler'`

- [ ] **Step 3: Implement `titler.py`**

```python
# src/cc_history/titler.py
"""Generate a {title, summary, tags} triple for a session using Claude Haiku.

Designed to be injected as a callable into the indexer. Failures (network,
rate limit, malformed response) leave the session untitled — caller decides
whether to retry on a subsequent index run.
"""
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from cc_history.models import Session, Turn


SYSTEM = (
    "You are titling a Claude Code conversation. Read the first user message and "
    "the first assistant response. Produce JSON only — no commentary, no markdown."
)

USER_TEMPLATE = """Look at this Claude Code session and produce JSON:

{{
  "title": "<8-12 word descriptive title in Title Case>",
  "summary": "<one-sentence summary of what was discussed/decided, <=25 words>",
  "tags": ["<2-5 short lowercase topic tags>"]
}}

CONVERSATION:
{conversation}

Return JSON only.
"""

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def build_prompt(session: Session, turns: list[Turn]) -> str:
    sample = turns[:3]
    body = "\n\n".join(f"[{t.role}]: {t.content}" for t in sample)
    return USER_TEMPLATE.format(conversation=body)


def parse_response(raw: str) -> tuple[Optional[str], Optional[str], list[str]]:
    text = raw.strip()
    fence_match = _CODE_FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None, None, []
    if not isinstance(data, dict):
        return None, None, []
    title = data.get("title") if isinstance(data.get("title"), str) else None
    summary = data.get("summary") if isinstance(data.get("summary"), str) else None
    tags_raw = data.get("tags")
    tags = [t for t in tags_raw if isinstance(t, str)] if isinstance(tags_raw, list) else []
    return title, summary, tags


def generate_title(
    session: Session,
    turns: list[Turn],
    *,
    client,
    model: str,
) -> Session:
    if not turns:
        return session
    prompt = build_prompt(session, turns)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text if resp.content else ""
    except Exception:
        return session

    title, summary, tags = parse_response(raw)
    if title is None:
        return session

    return replace(
        session,
        title=title,
        summary=summary,
        tags=tags,
        title_model=model,
        title_generated_at=datetime.now(timezone.utc).isoformat(),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_titler.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cc_history/titler.py tests/test_titler.py
git commit -m "feat: haiku-backed title/summary/tag generation"
```

---

## Task 10: Config module (env vars)

Tiny module that reads runtime config from env vars. Keeps `server.py` clean.

**Files:**
- Create: `src/cc_history/config.py`

- [ ] **Step 1: Create `config.py`**

```python
# src/cc_history/config.py
"""Runtime configuration sourced from environment variables.

Defaults assume the user is running this as an MCP server spawned by Claude
Code. All paths can be overridden via env vars for testing.
"""
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_TITLE_MODEL = "claude-haiku-4-5-20251001"


@dataclass(frozen=True)
class Config:
    db_path: Path
    sessions_dir: Path
    anthropic_api_key: str | None
    title_model: str

    @property
    def titles_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


def load_config() -> Config:
    db_env = os.environ.get("CC_HISTORY_DB", "~/.cc-history/index.db")
    sessions_env = os.environ.get("CC_HISTORY_SESSIONS_DIR", "~/.claude/projects")
    return Config(
        db_path=Path(os.path.expanduser(db_env)),
        sessions_dir=Path(os.path.expanduser(sessions_env)),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        title_model=os.environ.get("CC_HISTORY_TITLE_MODEL", DEFAULT_TITLE_MODEL),
    )
```

- [ ] **Step 2: Smoke-test the import**

Run: `python -c "from cc_history.config import load_config; print(load_config())"`
Expected: prints a `Config(...)` line without error.

- [ ] **Step 3: Commit**

```bash
git add src/cc_history/config.py
git commit -m "feat: env-var driven runtime config"
```

---

## Task 11: MCP server (FastMCP, 4 tools)

**Files:**
- Create: `src/cc_history/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

The tests exercise the tool functions directly (not over stdio) — `FastMCP` exposes them as regular callables on the server object, which is enough for unit testing.

```python
# tests/test_server.py
import shutil
from pathlib import Path

from cc_history.server import build_server


def _stage_and_build(tmp_path: Path, fixtures_dir: Path, db_path: Path):
    sessions_dir = tmp_path / "projects"
    proj = sessions_dir / "-Users-x-VoiceAgent"
    proj.mkdir(parents=True)
    shutil.copy(fixtures_dir / "sample_session_a.jsonl", proj / "aaaa1111-0000-0000-0000-000000000001.jsonl")
    return build_server(db_path=db_path, sessions_dir=sessions_dir, anthropic_client=None, title_model="x")


def test_search_history_tool_returns_hits(tmp_path, fixtures_dir, tmp_db_path):
    server = _stage_and_build(tmp_path, fixtures_dir, tmp_db_path)
    result = server._tool_search_history(query="gemini", limit=5)
    assert len(result["sessions"]) == 1
    assert result["sessions"][0]["id"] == "aaaa1111-0000-0000-0000-000000000001"


def test_list_recent_tool(tmp_path, fixtures_dir, tmp_db_path):
    server = _stage_and_build(tmp_path, fixtures_dir, tmp_db_path)
    result = server._tool_list_recent(days=365)
    assert result["count"] == 1


def test_get_session_tool(tmp_path, fixtures_dir, tmp_db_path):
    server = _stage_and_build(tmp_path, fixtures_dir, tmp_db_path)
    result = server._tool_get_session(session_id="aaaa1111-0000-0000-0000-000000000001")
    assert result["session_id"] == "aaaa1111-0000-0000-0000-000000000001"
    assert len(result["turns"]) == 4


def test_get_session_tool_unknown_id(tmp_path, fixtures_dir, tmp_db_path):
    server = _stage_and_build(tmp_path, fixtures_dir, tmp_db_path)
    result = server._tool_get_session(session_id="nope")
    assert result["turns"] == []


def test_get_resume_command_tool(tmp_path, fixtures_dir, tmp_db_path):
    server = _stage_and_build(tmp_path, fixtures_dir, tmp_db_path)
    result = server._tool_get_resume_command(session_id="aaaa1111-0000-0000-0000-000000000001")
    assert "claude --resume aaaa1111-0000-0000-0000-000000000001" in result["command"]


def test_get_resume_command_tool_unknown(tmp_path, fixtures_dir, tmp_db_path):
    server = _stage_and_build(tmp_path, fixtures_dir, tmp_db_path)
    result = server._tool_get_resume_command(session_id="nope")
    assert result == {"error": "session not found"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_server.py -v`
Expected: `ModuleNotFoundError: No module named 'cc_history.server'`

- [ ] **Step 3: Implement `server.py`**

```python
# src/cc_history/server.py
"""FastMCP server exposing 4 tools for searching/reading Claude Code history.

This module exposes:
- `build_server(...)` — returns a configured server; used in tests
- `main()` — entrypoint that loads config + runs over stdio

Note: tool callables are also bound as `_tool_*` attributes for direct unit
testing without needing to spin up the MCP stdio transport.
"""
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from cc_history.config import load_config
from cc_history.db import open_db
from cc_history.indexer import index_all
from cc_history.search import (
    build_resume_command,
    get_session_turns,
    list_recent,
    search_history,
)
from cc_history.titler import generate_title


class _Server:
    """Wraps a FastMCP instance plus all wiring; returned by `build_server`."""

    def __init__(self, mcp: FastMCP):
        self.mcp = mcp
        # Attribute placeholders; set in build_server
        self._tool_search_history = None
        self._tool_get_session = None
        self._tool_list_recent = None
        self._tool_get_resume_command = None


def build_server(
    *,
    db_path: Path,
    sessions_dir: Path,
    anthropic_client,
    title_model: str,
) -> _Server:
    mcp = FastMCP("cc-history")
    server = _Server(mcp)

    def _ensure_indexed():
        conn = open_db(db_path)
        titler = None
        if anthropic_client is not None:
            def titler(session, turns):
                return generate_title(session, turns, client=anthropic_client, model=title_model)
        index_all(conn, sessions_dir, generate_titles=titler is not None, titler=titler)
        return conn

    @mcp.tool()
    def search_history_tool(
        query: str,
        limit: int = 5,
        project: Optional[str] = None,
        since_days: Optional[int] = None,
    ) -> dict:
        """Full-text search across all indexed Claude Code sessions."""
        conn = _ensure_indexed()
        hits = search_history(conn, query, limit=limit, project=project, since_days=since_days)
        return {
            "query": query,
            "sessions": [
                {
                    **asdict(h.session),
                    "matched_snippets": h.matched_snippets,
                    "rank": h.rank,
                }
                for h in hits
            ],
        }

    @mcp.tool()
    def get_session_tool(
        session_id: str,
        include_tool_calls: bool = False,
        max_turns: int = 200,
    ) -> dict:
        """Read the full turn-by-turn content of one session."""
        conn = _ensure_indexed()
        turns = get_session_turns(conn, session_id, include_tool_calls=include_tool_calls, max_turns=max_turns)
        return {
            "session_id": session_id,
            "turns": [asdict(t) for t in turns],
        }

    @mcp.tool()
    def list_recent_tool(days: int = 7, project: Optional[str] = None) -> dict:
        """List sessions started within the last N days."""
        conn = _ensure_indexed()
        sessions = list_recent(conn, days=days, project=project)
        return {
            "count": len(sessions),
            "sessions": [asdict(s) for s in sessions],
        }

    @mcp.tool()
    def get_resume_command_tool(session_id: str) -> dict:
        """Return a copy-pasteable shell command to resume the given session."""
        conn = _ensure_indexed()
        cmd = build_resume_command(conn, session_id)
        if cmd is None:
            return {"error": "session not found"}
        return cmd

    # Bind the raw callables for direct unit testing
    server._tool_search_history = search_history_tool
    server._tool_get_session = get_session_tool
    server._tool_list_recent = list_recent_tool
    server._tool_get_resume_command = get_resume_command_tool
    return server


def main() -> None:
    cfg = load_config()
    client = None
    if cfg.anthropic_api_key:
        from anthropic import Anthropic
        client = Anthropic(api_key=cfg.anthropic_api_key)
    server = build_server(
        db_path=cfg.db_path,
        sessions_dir=cfg.sessions_dir,
        anthropic_client=client,
        title_model=cfg.title_model,
    )
    server.mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_server.py -v`
Expected: 6 passed.

- [ ] **Step 5: Smoke-test the entry point**

Run: `python -c "from cc_history.server import build_server; print('import ok')"`
Expected: `import ok`. (We won't run the stdio server interactively — that happens when Claude Code spawns it.)

- [ ] **Step 6: Commit**

```bash
git add src/cc_history/server.py tests/test_server.py
git commit -m "feat: mcp server exposing 4 tools (search/get/list/resume)"
```

---

## Task 12: Plugin manifest files

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.mcp.json`

- [ ] **Step 1: Create `.claude-plugin/plugin.json`**

```json
{
  "name": "cc-history",
  "description": "Search and resume your Claude Code session history from inside any session",
  "version": "0.1.0",
  "author": { "name": "Gaurav Dhir" },
  "homepage": "https://github.com/gauravdhir/cc-history"
}
```

(Replace `gauravdhir` with the actual GitHub username if different.)

- [ ] **Step 2: Create `.mcp.json`**

```json
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

- [ ] **Step 3: Verify JSON validity**

Run:
```bash
python -c "import json; json.load(open('.claude-plugin/plugin.json')); json.load(open('.mcp.json')); print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/plugin.json .mcp.json
git commit -m "feat: plugin manifest and mcp server registration"
```

---

## Task 13: Slash command markdown files

**Files:**
- Create: `commands/history.md`
- Create: `commands/history-recent.md`
- Create: `commands/history-reindex.md`
- Create: `commands/history-retitle.md`
- Create: `commands/history-reset.md`

- [ ] **Step 1: Create `commands/history.md`**

```markdown
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
```

- [ ] **Step 2: Create `commands/history-recent.md`**

```markdown
---
description: Show Claude Code sessions from the last N days
---

Show the user's recent Claude Code sessions.

Steps:
1. Parse $ARGUMENTS as an integer number of days. Default to 7 if empty.
2. Call `cc-history.list_recent_tool` with that `days` value.
3. Render the sessions grouped by project, ordered by date (newest first).
4. For each session show title, summary, and the date.
```

- [ ] **Step 3: Create `commands/history-reindex.md`**

```markdown
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
```

- [ ] **Step 4: Create `commands/history-retitle.md`**

```markdown
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
```

(This is the only command where v1 is intentionally incomplete — documented inline.)

- [ ] **Step 5: Create `commands/history-reset.md`**

```markdown
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
```

- [ ] **Step 6: Commit**

```bash
git add commands/
git commit -m "feat: 5 slash commands (search, recent, reindex, retitle, reset)"
```

---

## Task 14: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with install + usage"
```

---

## Task 15: Live smoke test against the user's real history

This is the v1 acceptance gate. We run the plugin against `~/.claude/projects/` and confirm the success criteria from the spec.

**Files:** (no code changes — manual verification)

- [ ] **Step 1: Build and install the package locally**

Run:
```bash
cd /Users/gauravdhir/Projects/cc-history-search
uv build
uv tool install --force --from dist/*.whl cc-history-mcp
```

Expected: `uvx cc-history-mcp` is now resolvable.

- [ ] **Step 2: Run the MCP server briefly to verify it boots**

Run (in one terminal):
```bash
CC_HISTORY_DB=/tmp/cc-history-test.db \
  CC_HISTORY_SESSIONS_DIR="$HOME/.claude/projects" \
  uvx cc-history-mcp <<< ''
```

Expected: Server initializes, awaits stdio messages, exits cleanly on EOF (no traceback).

- [ ] **Step 3: Drive a search through a one-off script**

Create a temporary script `/tmp/cc-history-smoke.py`:

```python
import os, time
from pathlib import Path
from cc_history.db import open_db
from cc_history.indexer import index_all
from cc_history.search import search_history

db = Path("/tmp/cc-history-smoke.db")
db.unlink(missing_ok=True)
conn = open_db(db)

t0 = time.time()
stats = index_all(conn, Path(os.path.expanduser("~/.claude/projects")), generate_titles=False)
print(f"Indexed {stats.indexed} sessions in {time.time()-t0:.1f}s (skipped={stats.skipped}, failed={stats.failed})")

for q in ["gemini live", "telephony", "mcp server"]:
    hits = search_history(conn, q, limit=3)
    print(f"\n=== '{q}' → {len(hits)} hits ===")
    for h in hits:
        print(f"  {h.session.id[:8]} | {h.session.project_path}")
        print(f"    {h.matched_snippets[0][:120]}")
```

Run: `python /tmp/cc-history-smoke.py`

Expected:
- Indexing completes in <30s for ~40 projects.
- Each of the three queries returns at least one hit.
- The matched snippets actually contain the query terms.

If indexing fails or queries return nothing relevant, debug before moving on.

- [ ] **Step 4: Drive a title generation pass (manual)**

Re-run the script above with `generate_titles=True` and a valid `ANTHROPIC_API_KEY`. Pick 20 random sessions and check the titles by eye.

Acceptance: ≥18/20 titles are on-topic and human-readable.

- [ ] **Step 5: Drive the full MCP install in Claude Code**

In a fresh Claude Code session:
1. `/plugin marketplace add <your-gh-handle>/cc-history` (or use a local file:// URL during dev)
2. `/plugin install cc-history@cc-history`
3. Restart CC.
4. Type: `find the session where I was building the cc-history plugin`
5. Confirm Claude calls `cc-history.search_history_tool` and returns this very session.

- [ ] **Step 6: Final commit (only if anything changed)**

```bash
git status
# If any files changed during smoke test:
git add -A
git commit -m "chore: smoke test fixes"
```

---

## Self-review

- **Spec coverage:**
  - §3 Primary user journeys A, B, D → covered by Tasks 8 (search), 11 (resume tool + get_session)
  - §4 Plugin layout → Tasks 1 + 12 + 13
  - §5 Data model → Task 6
  - §6 4 MCP tools → Task 11
  - §7 5 slash commands → Task 13
  - §8 AI title generation → Task 9
  - §9 Lazy incremental indexing → Task 7
  - §10 Error handling → covered in Task 5 (malformed JSONL), 9 (API failure), 11 (unknown session ID)
  - §11 Testing → TDD throughout
  - §13 Success criteria → Task 15
- **Placeholder scan:** clean — every code step has actual code; `history-retitle.md` explicitly defers full impl to v1.1 (documented gap, not a placeholder).
- **Type consistency:** `Session`, `Turn`, `SearchHit`, `IndexStats` are defined in Tasks 3 + 7 and used consistently afterwards. Tool result dicts use the same field names as the dataclasses via `asdict()`.

Plan is ready to execute.
