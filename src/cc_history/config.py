"""Runtime configuration sourced from environment variables.

Defaults assume the user is running this as an MCP server spawned by Claude
Code. All paths can be overridden via env vars for testing.
"""
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_TITLE_MODEL = "claude-haiku-4-5-20251001"


@dataclass(frozen=True)
class Config:
    db_path: Path
    sessions_dir: Path
    anthropic_api_key: str | None
    title_model: str

    @property
    def titles_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


def load_config() -> Config:
    db_env = os.environ.get("CC_HISTORY_DB", "~/.cc-history/index.db")
    sessions_env = os.environ.get("CC_HISTORY_SESSIONS_DIR", "~/.claude/projects")
    return Config(
        db_path=Path(os.path.expanduser(db_env)),
        sessions_dir=Path(os.path.expanduser(sessions_env)),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        title_model=os.environ.get("CC_HISTORY_TITLE_MODEL", DEFAULT_TITLE_MODEL),
    )
