"""Generate a {title, summary, tags} triple for a session using Claude Haiku.

Designed to be injected as a callable into the indexer. Failures (network,
rate limit, malformed response) leave the session untitled — caller decides
whether to retry on a subsequent index run.
"""
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from cc_history.models import Session, Turn


SYSTEM = (
    "You are titling a Claude Code conversation. Read the first user message and "
    "the first assistant response. Produce JSON only — no commentary, no markdown."
)

USER_TEMPLATE = """Look at this Claude Code session and produce JSON:

{{
  "title": "<8-12 word descriptive title in Title Case>",
  "summary": "<one-sentence summary of what was discussed/decided, <=25 words>",
  "tags": ["<2-5 short lowercase topic tags>"]
}}

CONVERSATION:
{conversation}

Return JSON only.
"""

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def build_prompt(session: Session, turns: list[Turn]) -> str:
    sample = turns[:3]
    body = "\n\n".join(f"[{t.role}]: {t.content}" for t in sample)
    return USER_TEMPLATE.format(conversation=body)


def parse_response(raw: str) -> tuple[Optional[str], Optional[str], list[str]]:
    text = raw.strip()
    fence_match = _CODE_FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None, None, []
    if not isinstance(data, dict):
        return None, None, []
    title = data.get("title") if isinstance(data.get("title"), str) else None
    summary = data.get("summary") if isinstance(data.get("summary"), str) else None
    tags_raw = data.get("tags")
    tags = [t for t in tags_raw if isinstance(t, str)] if isinstance(tags_raw, list) else []
    return title, summary, tags


def generate_title(
    session: Session,
    turns: list[Turn],
    *,
    client,
    model: str,
) -> Session:
    if not turns:
        return session
    prompt = build_prompt(session, turns)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text if resp.content else ""
    except Exception:
        return session

    title, summary, tags = parse_response(raw)
    if title is None:
        return session

    return replace(
        session,
        title=title,
        summary=summary,
        tags=tags,
        title_model=model,
        title_generated_at=datetime.now(timezone.utc).isoformat(),
    )
