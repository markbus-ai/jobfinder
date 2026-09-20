"""
Startup validation of MAX_ENGLISH_LEVEL.

A typo ("banana", "Intermediate ", "FLUENT") would otherwise make every row fail
the English gate closed and silently disable ALL notifications. The settings
module must log a loud ERROR naming the bad value and fall back to the safe
default instead of crashing.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from services.EnglishPolicy import english_allowed


@pytest.mark.parametrize("raw", ["banana", "Intermediate ", "intermediate ", "FLUENT", ""])
def test_invalid_max_english_level_falls_back_and_logs(monkeypatch, caplog, raw):
    import core.config as config

    monkeypatch.setenv("MAX_ENGLISH_LEVEL", raw)
    with caplog.at_level(logging.ERROR, logger="core.config"):
        resolved = config._resolve_max_english_level()

    assert resolved == "intermediate"
    assert raw in caplog.text
    assert "'none', 'basic', 'intermediate', 'fluent'" in caplog.text


def test_valid_max_english_level_is_kept_without_error(monkeypatch, caplog):
    import core.config as config

    monkeypatch.setenv("MAX_ENGLISH_LEVEL", "fluent")
    with caplog.at_level(logging.ERROR, logger="core.config"):
        assert config._resolve_max_english_level() == "fluent"
    assert caplog.text == ""


def test_invalid_max_english_level_fallback_keeps_intermediate_notifiable(monkeypatch):
    import core.config as config

    monkeypatch.setenv("MAX_ENGLISH_LEVEL", "banana")
    ceiling = config._resolve_max_english_level()
    assert ceiling == "intermediate"
    assert english_allowed("intermediate", ceiling) is True
    assert english_allowed("fluent", ceiling) is False


def test_invalid_max_english_level_is_validated_at_import():
    # End-to-end startup proof: importing the settings module with a typo must not
    # crash, must log an ERROR naming the bad value, and must keep the safe default.
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, MAX_ENGLISH_LEVEL="banana", GROQ_API_KEY="test-key")
    env.pop("GROQ_API_KEYS", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import core.config as c; print('VALUE=' + c.settings.MAX_ENGLISH_LEVEL)",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    assert "VALUE=intermediate" in proc.stdout
    assert "Invalid MAX_ENGLISH_LEVEL" in proc.stderr
    assert "banana" in proc.stderr
