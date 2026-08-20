# Sumble direct-mail audience

This skill installs and opens a local Marimo app that builds direct-mail audiences around company
offices. The app uses Sumble for companies and people, Parallel for office research, and public
geocoders for coordinates.

The agent copies a tested, locked application template. It does not generate a new notebook. It
helps you save the two API keys in a local `.env` file, installs the dependencies with `uv`, and
returns a local Marimo URL. Company, persona, seniority, radius, and review choices all happen in
the app.

## Install the skill

```bash
npx skills add SumbleData/sumble-skills-public --skill sumble-direct-mail-audience
```

Start a new agent session and ask:

```text
Use sumble-direct-mail-audience to open the direct-mail audience app.
```

The API-key helper hides your input and writes `.env` with permissions limited to your user. The
skill never asks you to paste a key into chat.

## What the app produces

- `offices.csv` with verified, review-required, and rejected office evidence
- `audience_results.csv` with people inside the selected radius of a verified office

Only verified offices feed the audience match. The app keeps weaker and rejected results visible
so you can audit or download them.
