"""Save (or check for) your Sumble API key so the pipeline can read it.

Across sessions the key persists in `~/.config/sumble/api_key` (chmod 0600), so
you only enter it once — later runs of `fetch_data.py` / `score_accounts.py`
pick it up automatically.

Usage:
  python set_api_key.py            # use a saved key if present, else prompt
  python set_api_key.py --check    # report whether a key is configured (exit 0/1)
  python set_api_key.py --force    # re-enter / replace an already-saved key

The resolver also accepts `export SUMBLE_API_KEY=...` or `--env-file path/to/.env`,
so saving to disk is optional. Get a key at https://sumble.com/account.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

import sumble_v6


def main() -> None:
    ap = argparse.ArgumentParser(description="Save or check the Sumble API key.")
    ap.add_argument(
        "--check",
        action="store_true",
        help="report whether a key is already configured, then exit (0=yes, 1=no)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="prompt and overwrite even if a key is already configured",
    )
    args = ap.parse_args()

    if args.check:
        if sumble_v6.resolve_api_key(allow_prompt=False):
            print("Sumble API key already configured — the pipeline will use it.")
            sys.exit(0)
        print("No Sumble API key configured yet. Run `python set_api_key.py` to add one.")
        sys.exit(1)

    # Skip only when a key is already PERSISTED to disk (env vars don't carry
    # across sessions, so an env-only key is still saved below).
    if sumble_v6.saved_key() and not args.force:
        print("A Sumble API key is already saved — the pipeline will use it.")
        print("Re-run with --force to replace it.")
        return

    key = os.environ.get("SUMBLE_API_KEY")
    if not key:
        print("Get your Sumble API key at https://sumble.com/account (Account → API key).")
        try:
            key = getpass.getpass("Paste it here (input hidden): ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit("\nNo key entered — nothing saved. Get one at https://sumble.com/account")
    if not key:
        sys.exit("No key entered — nothing saved. Get one at https://sumble.com/account")
    dest = sumble_v6.save_api_key(key)
    print(f"Saved to {dest} (permissions 0600).")
    print("fetch_data.py and score_accounts.py will now find it automatically.")


if __name__ == "__main__":
    main()
