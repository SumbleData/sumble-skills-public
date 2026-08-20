---
name: sumble-direct-mail-audience
description: Install and launch the supplied Marimo app for building direct-mail audiences near company offices. Use when a user wants to research company offices with Sumble and Parallel, select job functions and seniority, filter people by distance, or run the direct-mail audience notebook. Copies the fixed app template, helps save API keys to a local .env file, installs locked dependencies with uv, and returns a local Marimo URL.
---

# Direct-mail audience builder

Deliver the complete Marimo app in `template/`. The template is the product. Do not recreate,
rewrite, or simplify the notebook or its Python package.

The app collects company, persona, seniority, and distance inputs. Do not interview the user for
campaign parameters in chat.

## Set up and launch

1. Choose the output directory. Use a path the user supplied. Otherwise use
   `direct_mail_audience` under the current project directory.
2. Copy the complete contents of `template/` into that directory, including dotfiles. Do not
   overwrite an existing project unless the user asked to replace it.
3. Check that `uv` is available. If it is missing, direct the user to
   https://docs.astral.sh/uv/getting-started/installation/ and wait until installation succeeds.
4. Run `uv sync --locked` in the output directory. This creates an isolated `.venv` and installs
   the Python, Marimo, and package versions from `uv.lock`.
5. Help the user create `.env` as described below.
6. Start the committed notebook with:

   ```bash
   uv run marimo run app.py --host 127.0.0.1 --port 2718
   ```

   Use a persistent terminal process supported by the current agent. If port 2718 is occupied,
   use another local port and report that port.
7. Wait until the server responds, then give the user the local URL. Completion means a working
   Marimo URL, not a generated project or a set of setup instructions.

## API keys

The app requires `SUMBLE_API_KEY` and `PARALLEL_API_KEY` in the output project's `.env` file.

Never ask the user to paste a key into chat. Never print, inspect, summarize, or commit `.env`.
The template ignores `.env` in Git.

After `uv sync`, run this in a user-visible interactive terminal:

```bash
uv run python -m direct_mail.configure_env
```

The helper accepts both keys without echoing them and writes `.env` with mode `0600`. It preserves
an existing key when the user submits an empty response. If the current process already has both
keys exported, use this instead:

```bash
uv run python -m direct_mail.configure_env --from-environment
```

Do not search unrelated repositories, shell history, or home-directory files for credentials. If
the agent cannot provide a shared interactive terminal, give the user the first command to run in
the output directory and wait for confirmation.

## Boundaries

- Keep `app.py`, `direct_mail/`, `tests/`, `pyproject.toml`, and `uv.lock` unchanged during setup.
- Do not substitute an internal Sumble endpoint. The template uses the public Sumble API.
- Do not send API keys, downloaded CSVs, cached geocodes, or campaign inputs anywhere except the
  services the app names in its interface.
- Do not treat `review_required` or `rejected` offices as audience-matching inputs. The committed
  app enforces this rule.
