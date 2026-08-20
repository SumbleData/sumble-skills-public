from __future__ import annotations

import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import dotenv_values

from direct_mail.configure_env import configure_env


def _prompt(values: Iterator[str]) -> str:
    return next(values)


def test_configure_env_writes_both_keys_without_exposing_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    values = iter(("sumble-secret", "parallel-secret"))

    configured = configure_env(env_path, prompt_secret=lambda _: _prompt(values))

    saved = dotenv_values(env_path)
    assert configured == ("SUMBLE_API_KEY", "PARALLEL_API_KEY")
    assert saved["SUMBLE_API_KEY"] == "sumble-secret"
    assert saved["PARALLEL_API_KEY"] == "parallel-secret"
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_configure_env_preserves_saved_values_on_empty_input(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        'SUMBLE_API_KEY="saved-sumble"\nPARALLEL_API_KEY="saved-parallel"\n',
        encoding="utf-8",
    )
    values = iter(("", ""))

    configure_env(env_path, prompt_secret=lambda _: _prompt(values))

    saved = dotenv_values(env_path)
    assert saved["SUMBLE_API_KEY"] == "saved-sumble"
    assert saved["PARALLEL_API_KEY"] == "saved-parallel"


def test_configure_env_copies_exported_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"

    configure_env(
        env_path,
        environ={"SUMBLE_API_KEY": "sumble-export", "PARALLEL_API_KEY": "parallel-export"},
        from_environment=True,
    )

    saved = dotenv_values(env_path)
    assert saved["SUMBLE_API_KEY"] == "sumble-export"
    assert saved["PARALLEL_API_KEY"] == "parallel-export"


def test_configure_env_rejects_a_missing_exported_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PARALLEL_API_KEY"):
        configure_env(
            tmp_path / ".env",
            environ={"SUMBLE_API_KEY": "sumble-export"},
            from_environment=True,
        )
