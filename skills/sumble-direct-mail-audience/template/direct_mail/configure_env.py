from __future__ import annotations

import argparse
import getpass
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from dotenv import dotenv_values, set_key

REQUIRED_KEYS = ("SUMBLE_API_KEY", "PARALLEL_API_KEY")


def configure_env(
    env_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    prompt_secret: Callable[[str], str] = getpass.getpass,
    from_environment: bool = False,
) -> tuple[str, ...]:
    """Write required API keys without returning or printing their values."""
    env_path = env_path.expanduser().resolve()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.touch(mode=0o600, exist_ok=True)
    env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    current = dotenv_values(env_path)
    source_environment = os.environ if environ is None else environ
    configured: list[str] = []

    for key in REQUIRED_KEYS:
        existing = str(current.get(key) or "").strip()
        if from_environment:
            value = str(source_environment.get(key) or "").strip()
            if not value:
                raise ValueError(f"{key} is not set in the current environment.")
        else:
            suffix = " (press Enter to keep the saved value)" if existing else ""
            value = prompt_secret(f"{key}{suffix}: ").strip()
            if not value:
                value = existing
            if not value:
                raise ValueError(f"{key} is required.")

        set_key(env_path, key, value, quote_mode="always")
        configured.append(key)

    env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return tuple(configured)


def _default_env_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".env"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Save API keys to the app's local .env file.")
    parser.add_argument("--env-file", type=Path, default=_default_env_path())
    parser.add_argument(
        "--from-environment",
        action="store_true",
        help="Copy SUMBLE_API_KEY and PARALLEL_API_KEY from the current environment.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        configured = configure_env(args.env_file, from_environment=args.from_environment)
    except ValueError as error:
        print(f"Could not configure .env: {error}")
        return 1

    key_names = " and ".join(configured)
    print(f"Saved {key_names} to {args.env_file.expanduser().resolve()} with mode 0600.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
