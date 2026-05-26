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
