# A step by step guide to world class account scoring in under two hours

**Skill:** [`sumble-account-scoring`](../SKILL.md). Run it in Claude Code, Codex, or Cursor.

*Part 2 of 2.* Part 1 — [Account Scoring Should Explain, Not Just Rank](01-account-score-should-tell-a-rep-what-to-do.md) — lays out the method; this is how to put it in action.

## TLDR
- The skill interviews you about personas, technologies, projects, and first-party attributes.
- It calibrates against your won deals, then gives you sliders to tune the score by hand.
- Every attribute deep-links back into Sumble, so reps can move from rank to people, teams, jobs, and talking points.
- When you save, you get portable JSON weights and a scorer you can run against your whole book.

Part 1 argued that a good account score is the start of a prospecting conversation: every number backed by people and teams a rep can see and act on. This guide shows how to build one against your own ICP using the Sumble account-scoring skill, which runs in Claude Code, Codex, or Cursor. One skill, three objectives: score the accounts in your CRM, find whitespace (strong-fit orgs you don't yet have), or both in one ranked sheet. You talk to it, it pulls the data, it calibrates to your closed-won, and you tune with sliders. Zero-dependency Python: if `python app.py` runs, you're done.

## What you need

- One of three coding agents: **Claude Code**, **OpenAI Codex**, or **Cursor**. If you're new to these tools, each has a plain-English setup appendix at the end of this page; start there.
- The **Sumble account-scoring skill**, installed in step 1 below with one `npx skills` command or by copying a folder.
- A **Sumble account + API key** ([sumble.com/account](https://sumble.com/account)) and the **Sumble MCP** connected ([docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp)).
- To score your own accounts: your **CRM accounts** (at least `name` and `domain`), provided either as a **CSV** (exported from your CRM, a spreadsheet, or a warehouse) or pulled directly from a connected **MCP / API** source. The skill can use up to three things, and you can hand them over as **one table with flag columns** or as **separate lists**:
  - your **whole CRM universe** (every account),
  - which accounts are **allocated to a rep** (an owner column, or a separate list), and
  - your **closed-won / customers** (a flag, or a separate list).

  None are required (with nothing, the skill scores Sumble's universe), but closed-won is the one worth digging up: it powers the evaluation that checks your known-good accounts rise to the top. Rep allocation lets the skill flag accounts that should be owned but aren't.

**Want to see an example final output?** Explore the [account scoring calibration demo](https://account-scoring-demo.sumble.com/): the end output of the skill, with sliders to retune the weights and per-attribute deep links on a sample book.

## 1. Install the skill

A skill is just a folder of instructions your coding agent reads. There are two ways to get it.

If you have `npx` (it ships with [Node.js](https://nodejs.org)), one command installs the skill into whichever agents you choose:

```bash
npx skills add SumbleData/sumble-skills-public --skill sumble-account-scoring
```

The installer detects your coding agents and asks where to install. For a no-prompt global install into one agent, add `-g -a claude-code -y`, `-g -a codex -y`, or the matching agent name.

No `npx` or git? Install it by hand:

1. Download the skills repo as a ZIP (no git needed): [github.com/SumbleData/sumble-skills-public → Code → Download ZIP](https://github.com/SumbleData/sumble-skills-public/archive/refs/heads/main.zip), then unzip it.
2. Copy the `skills/sumble-account-scoring` folder into your agent's skills directory (`~` is your home folder; create the directory if it doesn't exist):
   - **Claude Code:** `~/.claude/skills/sumble-account-scoring`
   - **OpenAI Codex:** `~/.codex/skills/sumble-account-scoring`
   - **Cursor:** `~/.cursor/skills/sumble-account-scoring`

Either way, start a **new agent session** so the skill is picked up, then run it: on Claude Code type `/sumble-account-scoring`; on Codex or Cursor, ask it to use the sumble-account-scoring skill.

## 2. The interview

The interview is short and scripted. It pulls a first draft of your **ICP** (personas, technologies, projects) from your Sumble profile, and you edit it in plain English until it's right. Funding deliberately isn't part of the default model: funding data only exists for venture-backed companies, so scoring it artificially boosts them (see [part 1](01-account-score-should-tell-a-rep-what-to-do.md)).

It also proposes the score's **segments**, the top-level lenses it breaks the number into. The default is three: **Size** (how big the opportunity is), **Growth & momentum** (whether now is the time), and **Concentration** (how strong the fit is), with a starting blend of ~50/30/20. That blend is a starting point, not the final weighting: the skill fits it to your closed-won deals later (step 4). Keep them, reweight them, or redefine them; the skill will suggest a **business-unit breakdown** if you sell distinct product lines (e.g. an OCI-fit segment and an Apps-fit segment, each scored on its own personas and tech). An attribute can sit in more than one segment when it belongs to both.

This is also where you fold in your **first-party data** if you have it: marketing engagement (webinars, whitepapers, events) and PLG usage of your free product. Point the skill at a CSV (or a connected source) keyed by account and those become weighted factors alongside the Sumble attributes, woven into whichever segment fits, or a segment of their own.

## 3. Which accounts to score

Every account lands in one **category**: `customer` (closed-won), `allocated` (in CRM, owned by a rep), `unallocated` (in CRM, no owner), or `whitespace` (a strong-fit org not in your CRM). The app shows that category as a column and lets you filter on it, so one ranked list serves territory planning, allocation gaps, and net-new all at once.

- **Score everything, or a sample.** For a small or mid-size list, score it all. For a large CRM, where most accounts are stale and scoring all of them just burns credits, narrow it: the rep-allocated accounts, a subset you specify, or a **stratified sample** the skill draws for you (≈30% closed-won, 40% rep-allocated, 30% unallocated) that oversamples the accounts that matter and still gives the evaluation a representative mix. It shows the credit estimate before any large pull.
- **Whitespace, optionally folded in:** say yes and the same skill, run in whitespace mode, ranks strong-fit orgs that aren't in your CRM (resolving your whole CRM universe to exclude what you already have) and drops them into the same sheet tagged `whitespace`, so you can filter to net-new without leaving the app. It defaults to **10,000** candidates, and the ranking itself is free (only the final enriched pool costs credits), drawn from a **diversified preselection**: a mix of orgs hiring for your key technologies, running your key projects, dense in your ICP personas, and growing those personas fastest, so the pool isn't just the biggest companies. Candidates whose **parent** is already a CRM account are flagged as land-and-expand rather than cold net-new. Whitespace runs the Sumble-only half of your model (a stranger has no first-party attributes to join, so those weights drop and the rest re-normalize), and the same gold-set calibration carries straight over.
- **No lists at all:** it scores Sumble's universe against your ICP.

It shows a credit estimate before any large pull, then builds the app.

## 4. Tune and click through

```bash
cd account_scoring/<your-company>
python app.py        # http://localhost:8001
```

Drag the sliders and the ranking re-sorts instantly. Open any account for a per-attribute breakdown. This is where the score becomes actionable: each attribute deep-links into Sumble, filtered to the entities behind it. "DevOps engineer headcount" opens the actual engineers; "teams using Jenkins" opens those teams; the buying-window attribute opens the recent job posts. A rep goes from score to named contacts and talking points in two clicks.

If you loaded CRM lists, the **category chips** above the table filter to customers, allocated, unallocated, or whitespace in one click, so you can pull up "high-scoring accounts with no rep" (allocation gaps) or "top whitespace" without exporting anything. The slider weights you choose apply across every category at once.

**Which way to lean.** By default account scores tilt toward big companies: they have more of every attribute, so raw counts float them up. The sliders are split so you can correct that on purpose. If you sell into small, fast-growing companies, turn the growth sliders up, especially ICP-persona growth. Fast growers cross new scale points often, and each one is a moment they outgrow a tool and start looking; a large, flat company often isn't in enough pain to switch. If you want accounts where your product is central rather than incidental, turn concentration up: a high share of your ICP persona, or of teams on the relevant tech, means you're core to how the company runs. Then check the Evaluation tab to see whether the tilt pulled your won deals up.

**It fits to your wins, carefully.** Mark your closed-won accounts as your *gold* set and the skill calibrates to them automatically, two ways. First it learns **tag multipliers** from your Sumble org tags: whatever's over-represented among your wins (digital-native or AI-native companies) earns a boost, whatever's under-represented (IT-services or professional-services firms, which are usually partners not buyers) a penalty. These are applied by default; the app opens with them on, and you can tune or drop any in the per-tag widget, or add ones the gold set is too small to find ("we don't sell to Defense, penalize it"). Calibration runs over your org tags, not a per-industry multiplier; whole industries you obviously don't sell to are handled by excluding or penalizing them during the interview rather than as learned industry weights. Second it **fits the weights themselves**: the skill makes a first guess at the starting weights, then a small solver takes a deliberately light pass, nudging only the segment blend and category weights so your gold accounts separate better. It stays coarse on purpose to avoid overfitting: it never tunes at the most granular level (the individual job functions, technologies, and projects keep their default within-segment weighting), shrinks every change back toward the defaults, cross-validates on held-out wins, and keeps the result only if it generalizes; on a thin gold set it doesn't move at all. The sliders open at those values as a starting point; there may be good reasons to override them, and they're entirely yours to tune. The **Evaluation tab** shows the payoff: it buckets the scored sample and reports how many gold accounts land near the top (a *lift* above 1.0 beats random). It also breaks down where each category lands in the overall ranking (mean, median, and spread of rank for customers, allocated, unallocated, and whitespace) so you can confirm at a glance that your customers cluster near the top and see how your whitespace and unallocated accounts stack up against them. Drag, watch the gold rise, then **Save**: it writes your tuned weights and one complete `score.csv`: every account's data, score, rank, category, per-attribute contributions, and deep links in a single file (the raw `data.csv` stays untouched as the archive). Nothing auto-saves.

## 5. Score your whole book and keep it fresh

Two artifacts come out of tuning:

- **`account-scoring-weights.json`**: your model as plain JSON: every weight, the normalization parameters, and each attribute's mapping back to the Sumble data. It's human- and LLM-readable (the appendix below walks the formula), so a data team or a coding agent can re-implement it anywhere.
- **`score_accounts.py`**: a zero-dependency runner that reads that JSON and scores any list of accounts.

**For a one-off score across your whole book,** run the portable scorer against Sumble's public API:

```bash
python score_accounts.py --accounts my_full_list.csv --out scored.csv
```

It reads your saved config, looks each account up through the public API, and writes a ranked CSV. It runs anywhere with Python, needs nothing but an API key, and matches what you tuned. No contract, no setup: the right tool for a first full run or an occasional refresh.

**For daily, set-and-forget scoring, don't keep paying per API call.** Sumble's public API is metered for ad-hoc enrichment, so re-pulling the same attributes for every account every night is the expensive way to stay current. The cheaper, lighter path is to have Sumble feed the underlying attributes, the very columns your score reads, straight into your **data warehouse** (Snowflake, BigQuery, Databricks) or **CRM** (Salesforce, HubSpot) on a daily refresh, under an enterprise data agreement. It's lightweight to set up, and once the data lands internally your scheduled scoring job never touches the metered API again.

From there, scoring is just a query over data you already have:

1. **Land the Sumble attributes daily** in your warehouse or CRM, the same fields the model uses.
2. **Recompute the score on a schedule** and write the `rank` back where reps see it.

How you wire step 2 depends on how much engineering you have:

- **A data team and a warehouse.** Re-implement the formula in SQL (the JSON config plus the appendix give you everything) and run it as a nightly **dbt** model, or an **Airflow / Dagster / Prefect** task, reading the daily Sumble feed. Push the scored table into the CRM with **reverse ETL** (**Census**, **Hightouch**).
- **A cloud and a little Python.** A **Cloud Scheduler** cron firing a **Cloud Run job** (or **Cloud Function**) that recomputes the score over the warehouse feed and writes the ranked output back (AWS equivalent: **EventBridge Scheduler → Lambda**). With no infra at all, a **GitHub Actions scheduled workflow** does the same on cron.
- **No-code, owned by go-to-market.** **Clay**, **n8n**, **Make**, or **Zapier** can run the scoring on a schedule and sync the rank straight into your CRM.

The point of the daily job isn't that accounts swing overnight; most weeks they barely move. It's that nobody has to remember to refresh anything. Set it up once and the rank stays current on its own.

What you hand reps is the **rank**, not the raw score: "your #3 account" beats "an 82" every time. And rank within territories (SMB / Enterprise / Strategic, or by geography) so every rep has a clear top of their own book instead of a few owning all the whales. The output carries a `rank` column for exactly this; segment it by the size band or territory that matches how you cover the market.

## The payoff

Say you sell a platform-engineering tool to DevOps and infrastructure teams. Run the skill against your CRM and within an afternoon you can see that your customers skew digital-native and recently-funded, that Kubernetes footprint predicts fit better than headcount, and that a recent raise plus an active cloud-migration initiative is your strongest "buy now" combination. You tune until the Evaluation tab confirms it, Save, and run the portable scorer across all 90,000 accounts in one run.

And because every attribute links straight into the people, teams, and jobs behind it, the ranked list is a prospecting queue with the next action already attached. The same skill, run in whitespace mode, turns it on the accounts you're not selling to yet: same model, minus the first-party attributes a stranger can't have.

---

## Appendix: the scoring mathematics

This is the exact formula the skill implements, written so an LLM (or a data team) can reproduce the score from scratch. The web app, the portable `score_accounts.py`, and any warehouse re-implementation all compute the same thing. Notation: `i` indexes an attribute, `a` an account.

### Step 1 — Raw attributes

Every account gets a vector of **raw attribute values** `xᵢ(a) ≥ 0`. There are three shapes, all pulled from one call to `POST https://api.sumble.com/v6/organizations`:

- **Counts**: `people_count` for a persona (job function), `team_count` for a technology, `job_post_count` for an intent query. Raw non-negative integers.
- **Concentrations**: size-neutral shares, read from the API's own concentration
  metrics so numerator and denominator always cover the same population (both are
  rolled up across the org's subsidiaries — dividing by a plain org attribute
  instead would make a holding company read "4200% of teams"):
  - persona share, from `people_concentration` (people in the function ÷ people in the org)
  - tech hiring share, from `job_post_concentration` (matching job posts ÷ all job posts)

  Each is reported as the **Wilson 95% lower confidence bound** rather than the
  raw ratio — the lowest share consistent with what was observed. A raw ratio
  scores 1-of-1 and 900-of-900 identically at "100%", which lets barely-measured
  orgs saturate the attribute and crowd out real ICP accounts; the bound pulls
  thin evidence toward 0 (1/1 → 21%) and leaves well-measured orgs alone
  (266/3630 → 6.5%, raw 7.3%).
- **Growth**: persona `people_count_growth_1y`, returned by the API as a percent (e.g. `50.0`) and stored as a ratio (`× 0.01`). This is the one attribute that can be negative.

Intent attributes are **windowed**: `job_post_count` is filtered to the last ~90 days (`since = run_date − 90d`), recomputed at scoring time so the window tracks *now*, not the build date.

### Step 2 — Normalize each attribute (p99 exponential saturation)

Raw counts are unbounded and right-skewed, so each attribute is squashed into `[0, 1]` against the population's 99th percentile. Two parts:

**(a) Transform.** Compress count-like attributes with `log1p`; leave ratio-like attributes (concentration, growth) linear:

```text
x̃ᵢ(a) = ln(1 + max(xᵢ(a), 0))    if transformᵢ = "log"     (counts)
x̃ᵢ(a) = xᵢ(a)                     if transformᵢ = "linear"  (concentration, growth)
```

**(b) Saturate against p99.** Let `pᵢ` = the 99th percentile of `x̃ᵢ` taken over *only the accounts where the raw value is positive* (zeros excluded so the scale isn't dragged down), floored at `1e-9`. Then:

```text
nᵢ(a) = clamp( (1 − exp(−x̃ᵢ(a) / pᵢ)) / (1 − exp(−1)),  0,  1 )
```

The `(1 − exp(−1))` divisor rescales so an account sitting exactly at p99 scores `1.0` (without it, p99 would saturate at `1 − 1/e ≈ 0.632`). The outer clamp absorbs the top ~1% above p99 and pins any negative growth to `0`. This is why "2 vs 20 DevOps engineers" moves the score far more than "200 vs 400", and why a single outlier can't peg the scale.

### Step 3 — Weight hierarchy

Weights are a three-level tree. Every level's children sum to 100%, so the leaf weights automatically form a probability distribution; no global re-normalization is needed when you drag one slider.

```text
Segment            Size 50%        |  Growth & momentum 30%  |  Concentration 20%
  Category         persona count,     persona growth           persona concentration,
                   tech team count,                            tech team concentration
                   project×tech/persona jobs
                                                  (each a % of its segment)
    Attribute         one persona / one tech / one project   (each a % of its category)
```

The **effective weight** of attribute `i` is the product of its three fractions:

```text
wᵢ = (segmentPct[seg(i)] / 100) · (catPct[cat(i)] / 100) · (withinPct[i] / 100)
```

with `Σ wᵢ = 1`. Defaults the skill ships with:

- **Segments:** Size 50 / Growth & momentum 30 / Concentration 20.
- **Size categories** (% of Size, before renormalizing over those present): persona count 45, tech team count 30, project×tech jobs 15, project×persona jobs 10.
- **Concentration categories** (% of Concentration): persona concentration 60, tech team concentration 40.
- **Growth & momentum categories** (% of segment): persona YoY growth 100.
- **Within a category**, multiple personas/techs/projects get **decaying** weights (geometric, ratio `0.98`), so the 1st-listed persona slightly outweighs the 5th rather than all being equal. "Other"-tier techs are additionally dropped by a factor of `0.6` below the key-tier techs.

(Categories absent for your spec, such as project×* with no projects, drop out and the rest renormalize to 100 within their segment. The whole taxonomy is overridable: rename, reweight, or recut the segments, including a per-business-unit split, and an attribute may appear in more than one segment.)

(When `score_accounts.py` runs against the public API, any attribute the API can't reproduce (e.g. tech-team concentration, which needs an org-total team count) is dropped and the surviving `wᵢ` are re-normalized to sum to 1. So API scores rank-correlate strongly with the app but aren't byte-identical.)

### Step 4 — Calibration multipliers (lift over your won deals)

Categorical **org tags** (like `b2b`, `b2c`, `digital_native`, `is_ai_native`, `it_services`, `professional_services`) aren't normalized attributes; they're **multipliers** learned from your gold set (closed-won accounts). Calibration runs over the org's Sumble tags only (`professional_services` is itself a native org tag); whole industries are *not* synthesized into tags and calibrated. Industries you obviously don't sell to are excluded or penalized during the interview instead. For each tag, compare its prevalence among gold accounts to the broader population:

```text
lift = P(tag | gold) / P(tag | universe)
```

Map lift to a signed percentage, with guards against small samples:

- `lift ≥ 1.2` → **boost**, `pct = min(50, round((lift − 1) · 30))`
- `lift ≤ 0.8` → **penalty**, `pct = min(50, round((1 − lift) · 50))`
- `0.8 < lift < 1.2` → neutral (no multiplier)
- Too few gold positives (`< 3`) or too rare in the universe (`< 5`) → neutral.
- A special case: `0` gold occurrences but a `≥ 10%` universe baseline → a full `50%` penalty (the tag is well-represented yet your customers never have it).

### Step 5 — Final score

Multiply the weighted, normalized attributes by the calibration multipliers, scale to 0–100:

```text
score(a) = 100 · ( Σᵢ wᵢ · nᵢ(a) )
                 · Πₚ (1 − penaltyₚ/100)        for each plain penalty flag p set on a
                 · Πₜ (1 ± multₜ/100)            for each tag t on a: (1+) boost, (1−) penalty
```

Because `Σ wᵢ = 1` and each `nᵢ ∈ [0,1]`, the weighted sum is in `[0,1]` and the pre-multiplier score is in `[0,100]`. Multipliers can push it outside that range, which is fine: the score is only ever used to **order** accounts, never read as an absolute.

### Step 6 — Rank (the interface)

The raw `score(a)` is the engine; what reps see is the **rank**: accounts sorted by score descending. Rank is computed *within a territory* (size band, geography) when one is chosen, so the model still scores every account globally but the ordering is reset per territory. The exported `score.csv` carries `score`, `rank`, and each account's `account_category` alongside the raw data and per-attribute contributions.

### How the default weights are set (a regularized fit to gold)

The default weights are thoughtful priors, nudged toward your closed-won (`is_icp_gold`) accounts by a small solver built to avoid overfitting:

- Only the **segment blend and category weights** are fit; the within-category attribute weights stay frozen, which caps the degrees of freedom (a handful of parameters, not dozens).
- The objective is `AUC(gold) − λ · ‖w − w_default‖²`: a ranking fit shrunk toward the priors, so a weight moves only when the gold evidence is strong enough.
- Each weight is **box-bounded** (±10 pts per category, ±15 pts on the blend), so the model stays recognizable.
- λ is chosen by **k-fold cross-validation on held-out gold**, and the fit is **adopted only if held-out AUC beats the priors** by ≥ 0.01. With fewer than ~20 gold accounts it doesn't run at all.

The result is the app's *starting* slider positions: the formula above is unchanged; only the weights `wᵢ` inherit from this fit, and you can still tune them by hand.

### Worked micro-example

One attribute, "DevOps engineer headcount" (log transform). Population p99 of `ln(1+engineers)` is `pᵢ = ln(1+40) ≈ 3.71`. An account with 12 DevOps engineers:

```text
x̃ = ln(1+12) = 2.565
n  = (1 − exp(−2.565/3.71)) / (1 − exp(−1)) = (1 − 0.500) / 0.632 = 0.791
```

If that attribute's effective weight is `wᵢ = 0.50 (Size) · 0.45 (persona count) = 0.225` and it were the only attribute, its contribution is `100 · 0.225 · 0.791 = 17.8` points. A `digital_native` tag with lift `1.5` adds a boost of `round((1.5−1)·30) = 15%`, taking the score to `17.8 · 1.15 = 20.5`.

### Reference constants

| Constant | Value | Role |
|---|---|---|
| Segment blend | Size 50 / Growth & momentum 30 / Concentration 20 | top-level lenses (overridable; empty segments drop + renormalize) |
| Saturation divisor | `1 − exp(−1) ≈ 0.632` | makes p99 map to exactly 1.0 |
| p99 floor | `1e-9` | avoids divide-by-zero when no positives exist |
| Persona/tech within-decay | `0.98` (geometric) | ranks listed entities instead of equal-weighting |
| "Other"-tier tech drop | `0.6` | demotes secondary technologies |
| Neutral lift band | `0.8 – 1.2` | no multiplier inside this band |
| Boost scale / cap | `30` / `50%` | `min(50, (lift−1)·30)` |
| Penalty scale / cap | `50` / `50%` | `min(50, (1−lift)·50)` |
| Min gold positives | `3` | below this, tag is neutral |
| Min universe positives | `5` | below this, tag is neutral |
| Intent window | `90 days` | recency window for job-post intent attributes |
| Weight-fit scope | segment blend + category weights | within-category weights frozen |
| Weight-fit objective | `AUC(gold) − λ·‖w − w₀‖²` | ranking fit, shrunk to priors |
| Category / blend bands | `±10` / `±15` pts | max drift of a fitted weight from default |
| Weight-fit adopt margin | `+0.01` held-out AUC | else keep the priors |
| Min gold to fit weights | `~20` | below this, skip the fit entirely |

---

## Appendix: Get set up (no prior experience needed)

These coding agents are just chat apps that can run commands and edit files on your computer; you talk to them in plain English. To use the account-scoring skill you (1) install one of them, (2) install the skill with `npx skills`, and (3) connect Sumble. Pick **one** tool and follow its section. Do the shared steps first.

### Shared steps (once, for any tool)

1. **Create a Sumble account and get your API key.** Sign up at [sumble.com](https://sumble.com), then copy your key from [sumble.com/account](https://sumble.com/account). Keep it handy; the skill will ask for it once and save it securely, so you never paste it into a file.
2. **Install Python 3.10+** (only needed to run the finished app). On a Mac it's usually already installed: open Terminal and run `python3 --version`. Otherwise grab it from [python.org](https://python.org).
3. **Install the skill** with `npx skills`:
   ```bash
   npx skills add SumbleData/sumble-skills-public --skill sumble-account-scoring
   ```
   The installer detects your coding agents and asks where to install. For a no-prompt global install into one agent, add `-g -a claude-code -y`, `-g -a codex -y`, or the matching agent name. No `npx` (or no git)? Step 1 above shows the manual install: download the repo ZIP and copy the `skills/sumble-account-scoring` folder into your agent's skills directory.
4. **Have your account list ready** (recommended): a spreadsheet saved as a `.csv` with at least `name` and `domain` columns, plus, if you can, a column flagging your **customers** and one for the **account owner / rep**.

### Claude Code

1. **Install it.** Follow [Anthropic's Claude Code install guide](https://docs.claude.com/en/docs/claude-code). It runs in your terminal (or inside VS Code).
2. **Connect the Sumble MCP.** Follow [docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp). It gives you the exact command to register Sumble with Claude Code.
3. **Run it.** Start a new Claude Code session and type `/sumble-account-scoring`. Answer the short interview and it builds your app.

### OpenAI Codex

1. **Install it.** Install the [Codex CLI](https://developers.openai.com/codex/cli): `npm install -g @openai/codex`, then run `codex`.
2. **Connect the Sumble MCP.** Add the Sumble server to your Codex config (`~/.codex/config.toml`) using the connection details at [docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp).
3. **Run it.** Start Codex in the folder where you want the app created, and ask it: *"Use the sumble-account-scoring skill to build an account score."* Codex loads the skill and runs the same interview.

### Cursor

1. **Install it.** Download [Cursor](https://cursor.com/downloads), a code editor with a built-in AI agent.
2. **Open a project folder** (File → Open Folder) where you want the app to live.
3. **Connect the Sumble MCP.** In **Cursor Settings → MCP**, add the Sumble server using the details at [docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp).
4. **Run it.** Open the Agent (chat) panel and ask it: *"Follow the sumble-account-scoring skill to build an account score."*

### When it's done (any tool)

The skill tells you how to start your app. It's always:

```bash
cd account_scoring/<your-company>
python app.py        # then open http://localhost:8001 in your browser
```

No installs, no extra setup. Drag the sliders and your ranking updates live.
