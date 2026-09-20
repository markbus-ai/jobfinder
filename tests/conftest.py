"""Ensure the repository root is importable when running pytest from any cwd."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Keep the suite hermetic: never touch a real Groq key, a real .env, or a real
# SQLite database. These must be set before any project module imports
# core.config (whose Settings class reads the environment at class-definition
# time) or database (which builds the engine at import time).
os.environ["GROQ_API_KEY"] = "test-key"
os.environ.pop("GROQ_API_KEYS", None)
_TEST_DB_DIR = tempfile.mkdtemp(prefix="jf-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_DIR}/jobfinder-test.db"


@pytest.fixture
def fresh_db():
    """Recreate the schema on the temporary test database."""
    from sqlmodel import SQLModel

    from database import create_db_and_tables, engine

    SQLModel.metadata.drop_all(engine)
    create_db_and_tables()
    yield
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def cycle_runner(monkeypatch):
    """
    Return a helper that runs ``main.process_jobs_sync`` hermetically.

    Scraping, CV generation, email extraction, sleeps, and the AI analysis call
    are all stubbed, so the test exercises the pipeline decisions (dedup, retry,
    notification) without any network or file I/O.
    """

    def _run(jobs, analyze_job, **settings_overrides):
        import types

        import main

        monkeypatch.setattr(main, "time", types.SimpleNamespace(sleep=lambda *_: None))
        settings_defaults = {
            "SEARCH_TERMS": "python developer",
            "SEARCH_TERMS_REMOTE": "desarrollador backend remoto",
            "REMOTE_SEARCH_LOCATIONS": "Argentina,Uruguay,Chile",
            "SEARCH_SOURCES": "getonboard,linkedin",
            "GETONBOARD_ENABLED": False,
            "REMOTE_SEARCH_ENABLED": False,
            "MIN_MATCH_SCORE": 70,
            "MAX_ANALYSIS_ATTEMPTS": 3,
            "MAX_ENGLISH_LEVEL": "intermediate",
        }
        settings_defaults.update(settings_overrides)
        for key, value in settings_defaults.items():
            if hasattr(main.settings, key):
                monkeypatch.setattr(main.settings, key, value)

        monkeypatch.setattr(main.ai_service, "analyze_job", analyze_job)
        monkeypatch.setattr(main.ai_service, "generate_cv_content", lambda *a, **k: None)
        monkeypatch.setattr(main.ai_service, "extract_company_email", lambda *a, **k: None)
        monkeypatch.setattr(main, "generate_cv", lambda *a, **k: None)
        monkeypatch.setattr(main, "generate_custom_typst", lambda *a, **k: None)

        class _FakeJobService:
            def __init__(self):
                self.calls = []

            def get_latest_jobs(self, **kwargs):
                self.calls.append(kwargs)
                return list(jobs)

        class _FakeGetOnBoardService:
            def get_latest_jobs(self, **kwargs):
                return []

        service = _FakeJobService()
        notifications = main.process_jobs_sync(
            service, _FakeGetOnBoardService(), None
        )
        return service, notifications

    return _run
