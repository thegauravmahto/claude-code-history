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
