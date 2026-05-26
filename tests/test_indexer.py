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
