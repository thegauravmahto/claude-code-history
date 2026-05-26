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
