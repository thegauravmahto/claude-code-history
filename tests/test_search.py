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
