# `data.csv` column schema

One row per person. snake_case throughout. `config.json` references
these column names so `app.py` stays generic.

**Identity:** `person_id` (int, PK), `name`, `current_title`,
`linkedin_url`, `sumble_url` (`https://sumble.com/people/<linkedin_slug>`),
`location`, `country_code` (ISO-2).

**Org linkage:** `org_id`, `org_name`, `org_slug`, `domain`.

**Job function:** `job_function_id`, `job_function_slug`, `job_function_name`.

**Seniority:** `job_level`, `job_level_rank` (1 = IC),
`max_job_level_rank` (universe max, repeated on every row so the app
normalises without re-aggregating).

**Skills:** `matched_skills` (comma-separated ICP slugs; empty when none),
`skill_count` (0 when none).

**First-party flags (always present, default 0):**
- `is_crm_contact` — matched to the uploaded CRM contact/lead list.
- `is_icp_gold` — matched to the gold-contact set. Drives the
  Evaluation tab.

**Account score (optional — present when the interview connected one):**
- `account_rank` (int, lower = better; nullable)
- `account_score` (float; nullable)

**1P signal columns (one raw + one norm per signal, present only when
the interview connected 1P signals; 0 for unmatched people):**
- `<signal>_raw` (float) — raw value
- `<signal>_norm` (float, 0–1) — p99-saturation-normalised; the scorer
  consumes this directly (see `template/README.md` → Scoring).

Columns referenced by `config.json` that aren't present in `data.csv`
must raise a startup error — never silently default to zero.
