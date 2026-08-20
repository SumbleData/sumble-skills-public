from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def load_environment(project_dir: Path) -> None:
    """Load public project env files, then optional local development env files."""
    load_dotenv(project_dir / ".env", override=False)
    load_dotenv(project_dir / ".env.local", override=False)

    for variable_name in (
        "DIRECT_MAIL_SUMBLE_ENV_FILE",
        "DIRECT_MAIL_PARALLEL_ENV_FILE",
    ):
        env_path = os.environ.get(variable_name, "").strip()
        if env_path:
            load_dotenv(Path(env_path).expanduser(), override=False)


def masked_key_status(variable_name: str) -> str:
    value = os.environ.get(variable_name, "").strip()
    return "Available" if value else "Missing"
