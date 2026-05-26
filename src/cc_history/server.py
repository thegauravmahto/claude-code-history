"""FastMCP server exposing 4 tools for searching/reading Claude Code history.

This module exposes:
- `build_server(...)` -- returns a configured server; used in tests
- `main()` -- entrypoint that loads config + runs over stdio

Note: tool callables are also bound as `_tool_*` attributes for direct unit
testing without needing to spin up the MCP stdio transport.
"""
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from cc_history.config import load_config
from cc_history.db import open_db
from cc_history.indexer import index_all
from cc_history.search import (
    build_resume_command,
    get_session_turns,
    list_recent,
    search_history,
)
from cc_history.titler import generate_title


class _Server:
    """Wraps a FastMCP instance plus all wiring; returned by `build_server`."""

    def __init__(self, mcp: FastMCP):
        self.mcp = mcp
        # Attribute placeholders; set in build_server
        self._tool_search_history = None
        self._tool_get_session = None
        self._tool_list_recent = None
        self._tool_get_resume_command = None


def build_server(
    *,
    db_path: Path,
    sessions_dir: Path,
    anthropic_client,
    title_model: str,
) -> _Server:
    mcp = FastMCP("cc-history")
    server = _Server(mcp)

    def _ensure_indexed():
        conn = open_db(db_path)
        titler = None
        if anthropic_client is not None:
            def titler(session, turns):
                return generate_title(session, turns, client=anthropic_client, model=title_model)
        index_all(conn, sessions_dir, generate_titles=titler is not None, titler=titler)
        return conn

    @mcp.tool()
    def search_history_tool(
        query: str,
        limit: int = 5,
        project: Optional[str] = None,
        since_days: Optional[int] = None,
    ) -> dict:
        """Full-text search across all indexed Claude Code sessions."""
        conn = _ensure_indexed()
        hits = search_history(conn, query, limit=limit, project=project, since_days=since_days)
        return {
            "query": query,
            "sessions": [
                {
                    **asdict(h.session),
                    "matched_snippets": h.matched_snippets,
                    "rank": h.rank,
                }
                for h in hits
            ],
        }

    @mcp.tool()
    def get_session_tool(
        session_id: str,
        include_tool_calls: bool = False,
        max_turns: int = 200,
    ) -> dict:
        """Read the full turn-by-turn content of one session."""
        conn = _ensure_indexed()
        turns = get_session_turns(conn, session_id, include_tool_calls=include_tool_calls, max_turns=max_turns)
        return {
            "session_id": session_id,
            "turns": [asdict(t) for t in turns],
        }

    @mcp.tool()
    def list_recent_tool(days: int = 7, project: Optional[str] = None) -> dict:
        """List sessions started within the last N days."""
        conn = _ensure_indexed()
        sessions = list_recent(conn, days=days, project=project)
        return {
            "count": len(sessions),
            "sessions": [asdict(s) for s in sessions],
        }

    @mcp.tool()
    def get_resume_command_tool(session_id: str) -> dict:
        """Return a copy-pasteable shell command to resume the given session."""
        conn = _ensure_indexed()
        cmd = build_resume_command(conn, session_id)
        if cmd is None:
            return {"error": "session not found"}
        return cmd

    # Bind the raw callables for direct unit testing
    server._tool_search_history = search_history_tool
    server._tool_get_session = get_session_tool
    server._tool_list_recent = list_recent_tool
    server._tool_get_resume_command = get_resume_command_tool
    return server


def main() -> None:
    cfg = load_config()
    client = None
    if cfg.anthropic_api_key:
        from anthropic import Anthropic
        client = Anthropic(api_key=cfg.anthropic_api_key)
    server = build_server(
        db_path=cfg.db_path,
        sessions_dir=cfg.sessions_dir,
        anthropic_client=client,
        title_model=cfg.title_model,
    )
    server.mcp.run()


if __name__ == "__main__":
    main()
