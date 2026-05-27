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


# FTS5 reserves these characters; we strip them when accepting prose.
# `-` is a NOT operator in FTS5, so a bare query like "cc-history plugin" parses
# as "cc NOT history plugin". Replace it with whitespace so hyphenated terms
# become two AND/OR-able tokens.
_FTS_RESERVED = re.compile(r'[":\(\)\*\^\-]')


def _to_fts_query(raw: str) -> str:
    """Turn a prose query into a safe FTS5 MATCH expression.

    Strategy: tokenize on whitespace, drop very short / stoppy tokens,
    OR the rest together. Prose recall is preferred over precision; the
    bm25 ranker handles ordering. If the user already typed boolean
    operators (AND/OR/NOT), pass them through (uppercased for FTS5).
    """
    cleaned = _FTS_RESERVED.sub(" ", raw)
    raw_tokens = [t for t in cleaned.split() if t]
    if not raw_tokens:
        return '""'
    # If the user wrote explicit boolean operators, normalize them to
    # uppercase (FTS5 requires uppercase) and pass through.
    if any(t.lower() in ("and", "or", "not") for t in raw_tokens):
        out: list[str] = []
        for t in raw_tokens:
            if t.lower() in ("and", "or", "not"):
                out.append(t.upper())
            else:
                out.append(t.lower())
        return " ".join(out)
    tokens = [t.lower() for t in raw_tokens]
    # Drop tokens shorter than 3 chars (e.g. "the", "i", "a")
    tokens = [t for t in tokens if len(t) >= 3]
    if not tokens:
        return '""'
    return " OR ".join(tokens)


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
