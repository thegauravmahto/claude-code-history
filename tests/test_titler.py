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
