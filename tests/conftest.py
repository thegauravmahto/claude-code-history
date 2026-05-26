import json
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_index.db"


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_jsonl_a(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample_session_a.jsonl"


@pytest.fixture
def sample_jsonl_b(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample_session_b.jsonl"


@pytest.fixture
def malformed_jsonl(fixtures_dir: Path) -> Path:
    return fixtures_dir / "malformed.jsonl"
