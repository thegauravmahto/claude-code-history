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
