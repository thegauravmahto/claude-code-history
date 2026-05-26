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
    assert tuple(row) == ("abc-1", 10.0, 2)


def test_upsert_updates_existing(tmp_db_path: Path):
    conn = open_db(tmp_db_path)
    s = Session(id="abc-1", project_slug="-tmp", project_path="/tmp",
                file_path="/tmp/abc-1.jsonl", file_mtime=10.0, turn_count=2)
    upsert_session(conn, s)
    s.file_mtime = 20.0
    s.turn_count = 5
    upsert_session(conn, s)
    row = conn.execute("SELECT file_mtime, turn_count FROM sessions WHERE id=?", ("abc-1",)).fetchone()
    assert tuple(row) == (20.0, 5)


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
