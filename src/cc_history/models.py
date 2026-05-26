from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Turn:
    """One turn in a Claude Code conversation."""
    index: int           # ordinal within the session, 0-based
    role: str            # 'user' | 'assistant' | 'system' | 'tool'
    content: str         # text content (tool calls stripped)
    timestamp: Optional[str] = None  # ISO 8601 if present


@dataclass
class Session:
    """A single Claude Code session, derived from one JSONL file."""
    id: str
    project_slug: str
    project_path: str
    file_path: str
    file_mtime: float
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    turn_count: int = 0
    title: Optional[str] = None
    summary: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    title_model: Optional[str] = None
    title_generated_at: Optional[str] = None


@dataclass
class SearchHit:
    """One row in a search result."""
    session: Session
    matched_snippets: list[str]  # FTS5-highlighted snippets, max 3
    rank: float                  # FTS5 bm25 rank; lower = better
