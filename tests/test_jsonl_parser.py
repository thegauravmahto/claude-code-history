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
