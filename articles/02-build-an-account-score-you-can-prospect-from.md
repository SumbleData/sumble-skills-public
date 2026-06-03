# Build an account score you can prospect from — in an afternoon

*Part 2 of 3.* Part 1 — [An account score should tell a rep what to do](01-account-score-should-tell-a-rep-what-to-do.md) — lays out the method; this is how to put it in action. Part 3 — [Find your next accounts (whitespace)](03-find-your-next-accounts-whitespace.md).

Part 1 argued that a good account score is the start of a prospecting conversation, not a verdict — every number backed by people and teams a rep can see and act on. Here's how to build one against your own ICP using the Sumble account-scoring skill, which runs in Claude Code, Codex, or Cursor. You talk to it, it pulls the data, you tune with sliders. Zero-dependency Python: if `python app.py` runs, you're done.

## What you need

- One of three coding agents: **Claude Code**, **OpenAI Codex**, or **Cursor**. New to these tools? Each has a plain-English, **step-by-step setup appendix at the end of this page** — start there.
- The **Sumble account-scoring skill** — download it, drop the folder into your agent's skills folder (the appendix shows exactly where for each tool).
- A **Sumble account + API key** ([sumble.com/account](https://sumble.com/account)) and the **Sumble MCP** connected ([docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp)).
- To score your own accounts: an **account list** (a CSV with `name` and `domain`) exported from your CRM, a spreadsheet, or a warehouse. If you can, add two more columns — a flag marking your **customers**, and the **account owner / rep** — so the skill focuses its calibration sample on the accounts you actually work (and skips the dead tail of the CRM).

Once your tool is set up, open it and run the skill: on Claude Code type `/sumble-account-scoring`; on Codex or Cursor, ask it to use the sumble-account-scoring skill.

## 1. The interview

Short and scripted. It pulls a first draft of your **ICP** — personas, technologies, projects — from your Sumble profile, and you edit it in plain English until it's right. The score blends fit/size with buying-window intent by default — that's the baked-in best practice, so there's nothing to choose. Just say "include funding signals" if a recent raise tends to precede buying in your market.

This is also where you fold in your **first-party data** if you have it — marketing engagement (webinars, whitepapers, events) and PLG usage of your free product. Point the skill at a CSV (or a connected source) keyed by account and those become weighted factors right alongside the Sumble signals.

## 2. Your accounts, or net-new?

- **Score your accounts:** point it at your list. It calibrates on a focused sample, not the whole CRM — most of a large CRM is stale accounts nobody works, so scoring all of it just to tune weights is wasted effort. If your export flags customers and which accounts are assigned to a rep, it samples ~5,000 (about a third your customers, the rest rep-assigned accounts); if it can't tell real targets from junk, it falls back to a larger ~10,000-account random sample. Either way you oversample the accounts that matter and don't score the whole list just to tune the weights.
- **Find net-new:** the companion `/sumble-account-whitespace` ranks Sumble's universe by your ICP and removes the accounts you already have.

It shows a credit estimate before any large pull, then builds the app.

## 3. Tune — and click through

```bash
cd account_scoring/<your-company>
python app.py        # http://localhost:8001
```

Drag the sliders and the ranking re-sorts instantly. Open any account for a per-signal breakdown — and this is where the score becomes actionable: **each signal deep-links into Sumble**, filtered to the entities behind it. "DevOps engineer headcount" → the actual engineers. "Teams using Jenkins" → those teams. The buying-window signal → the recent job posts. A rep goes from score to named contacts and talking points in two clicks.

**Which way to lean.** By default account scores tilt toward big companies — they have more of every signal, so raw counts float them up. The sliders are split exactly so you can correct that on purpose. Selling into small, fast-growing companies? Turn the *growth* sliders up — especially ICP-persona growth. Fast growers cross new scale points often, and each one is a moment they outgrow a tool and start looking; a large, flat company usually isn't in enough pain to switch. Want accounts where your product is central rather than incidental? Turn *concentration* up — a high share of your ICP persona, or of teams on the relevant tech, means you're core to how the company runs, not a rounding error. Then let the Evaluation tab tell you whether the tilt actually pulled your won deals up.

**It fits to your wins — carefully.** Mark your closed-won accounts as your *gold* set and the skill calibrates to them automatically, two ways. It sets the **attribute multipliers** — whatever's over-represented among your wins (digital-native, say) earns a boost, whatever's under-represented (IT-services partners) a penalty. And it **fits the weights themselves**: starting from a thoughtful set of defaults, a small solver nudges the section blend and category weights to separate your gold accounts better. It's built *not* to overfit — it only touches the high-level weights (the per-signal weights stay frozen), shrinks every change back toward the defaults, cross-validates on held-out wins, and keeps the result only if it generalizes; on a thin gold set it doesn't move at all. The sliders open at those fitted values — a warm start, still entirely yours to tune. The **Evaluation tab** shows the payoff: it buckets the scored sample and reports how many gold accounts land near the top (a *lift* above 1.0 beats random). Drag, watch the gold rise, then **Save** — it writes your tuned weights and a `data.csv` with every account's score and rank. Nothing auto-saves.

## 4. Score your whole book — and keep it fresh

Two artifacts come out of tuning:

- **`account-scoring-weights.json`** — your model as plain JSON: every weight, the normalization parameters, and each signal's mapping back to the Sumble data. It's human- and LLM-readable (the appendix below walks the formula), so a data team — or a coding agent — can re-implement it anywhere.
- **`score_accounts.py`** — a zero-dependency runner that reads that JSON and scores any list of accounts.

**For a one-off score across your whole book,** run the portable scorer against Sumble's public API:

```bash
python score_accounts.py --accounts my_full_list.csv --out scored.csv
```

It reads your saved config, looks each account up through the public API, and writes a ranked CSV — runs anywhere with Python, needs nothing but an API key, and matches what you tuned. No contract, no setup: the right tool for a first full run or an occasional refresh.

**For daily, set-and-forget scoring, don't keep paying per API call.** Sumble's public API is metered for ad-hoc enrichment, so re-pulling the same signals for every account every night is the expensive way to stay current. The cheaper, lighter path is to have Sumble feed the underlying signals — the very columns your score reads — straight into your **data warehouse** (Snowflake, BigQuery, Databricks) or **CRM** (Salesforce, HubSpot) on a daily refresh, under an enterprise data agreement. It's lightweight to set up, and once the data lands internally your scheduled scoring job never touches the metered API again.

From there, scoring is just a query over data you already have:

1. **Land the Sumble signals daily** in your warehouse or CRM — the same fields the model uses.
2. **Recompute the score on a schedule** and write the `rank` back where reps see it.

How you wire step 2 depends on how much engineering you have:

- **A data team and a warehouse.** Re-implement the formula in SQL — the JSON config plus the appendix give you everything — and run it as a nightly **dbt** model, or an **Airflow / Dagster / Prefect** task, reading the daily Sumble feed. Push the scored table into the CRM with **reverse ETL** (**Census**, **Hightouch**).
- **A cloud and a little Python.** A **Cloud Scheduler** cron firing a **Cloud Run job** (or **Cloud Function**) that recomputes the score over the warehouse feed and writes the ranked output back — AWS equivalent: **EventBridge Scheduler → Lambda**. No infra at all? A **GitHub Actions scheduled workflow** does the same on cron.
- **No-code, owned by go-to-market.** **Clay**, **n8n**, **Make**, or **Zapier** can run the scoring on a schedule and sync the rank straight into your CRM.

The point of the daily job isn't that accounts swing overnight — most weeks they barely move — it's that nobody has to remember to refresh anything. Set it up once and the rank stays current on its own.

What you hand reps is the **rank**, not the raw score — "your #3 account" beats "an 82" every time. And rank *within segments* (SMB / Enterprise / Strategic, or by territory) so every rep has a clear top of their own book instead of a few owning all the whales. The output carries a `rank` column for exactly this; segment it by the size band or territory that matches how you cover the market.

## The payoff

Say you sell a platform-engineering tool to DevOps and infrastructure teams. Run the skill against your CRM and within an afternoon you can see that your customers skew digital-native and recently-funded, that Kubernetes footprint predicts fit better than headcount, and that a recent raise plus an active cloud-migration initiative is your strongest "buy now" combination. You tune until the Evaluation tab confirms it, Save, and run the portable scorer across all 90,000 accounts in one run.

And because every signal links straight into the people, teams, and jobs behind it, the ranked list isn't a leaderboard — it's a prospecting queue with the next action already attached.

**[Part 3 — Use the same model to find the best accounts you're *not* selling to →](03-find-your-next-accounts-whitespace.md)**

---

## Appendix: the scoring mathematics

This is the exact formula the skill implements, written so an LLM (or a data team) can reproduce the score from scratch. The web app, the portable `score_accounts.py`, and any warehouse re-implementation all compute the same thing. Notation: `i` indexes a signal, `a` an account.

### Step 1 — Raw signals

Every account gets a vector of **raw signal values** `xᵢ(a) ≥ 0`. There are three shapes, all pulled from one call to `POST https://api.sumble.com/v6/organizations`:

- **Counts** — `people_count` for a persona (job function), `team_count` for a technology, `job_post_count` for an intent query. Raw non-negative integers.
- **Concentrations** — derived ratios, size-neutral:
  - persona share `= 100 · persona_people / employee_count`
  - tech share `= 100 · tech_teams / teams_count`
- **Growth** — persona `people_count_growth_1y`, returned by the API as a percent (e.g. `50.0`) and stored as a ratio (`× 0.01`). This is the one signal that can be negative.

Intent signals are **windowed**: `job_post_count` is filtered to the last ~90 days (`since = run_date − 90d`), recomputed at scoring time so the window tracks *now*, not the build date.

### Step 2 — Normalize each signal (p99 exponential saturation)

Raw counts are unbounded and right-skewed, so each signal is squashed into `[0, 1]` against the population's 99th percentile. Two parts:

**(a) Transform.** Compress count-like signals with `log1p`; leave ratio-like signals (concentration, growth) linear:

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

Weights are a three-level tree. Every level's children sum to 100%, so the leaf weights automatically form a probability distribution — no global re-normalization needed when you drag one slider.

```text
Section            ACV (size+fit) 60%     |  Intent (buying window) 40%
  Category         persona count, persona growth, persona concentration,
                   tech team count, tech team concentration   (each a % of its section)
    Signal         one persona / one tech / one project       (each a % of its category)
```

The **effective weight** of signal `i` is the product of its three fractions:

```text
wᵢ = (sectionPct[sec(i)] / 100) · (catPct[cat(i)] / 100) · (withinPct[i] / 100)
```

with `Σ wᵢ = 1`. Defaults the skill ships with:

- **Sections:** ACV 60 / Intent 40.
- **ACV categories** (% of ACV): persona count 39, persona growth 16.25, persona concentration 9.75, tech team count 24.5, tech team concentration 10.5.
- **Intent categories** (% of Intent): project×tech jobs 60, project×persona jobs 40.
- **Within a category**, multiple personas/techs/projects get **decaying** weights (geometric, ratio `0.98`), so the 1st-listed persona slightly outweighs the 5th rather than all being equal. "Other"-tier techs are additionally dropped by a factor of `0.6` below the key-tier techs.

(When `score_accounts.py` runs against the public API, any signal the API can't reproduce — e.g. tech-team *concentration*, which needs an org-total team count — is dropped and the surviving `wᵢ` are re-normalized to sum to 1. So API scores rank-correlate strongly with the app but aren't byte-identical.)

### Step 4 — Calibration multipliers (lift over your won deals)

Categorical attributes (tags like `b2b`, `digital_native`, `it_services`, `professional_services`, …) aren't normalized signals — they're **multipliers** learned from your gold set (closed-won accounts). For each attribute, compare its prevalence among gold accounts to the broader population:

```text
lift = P(attr | gold) / P(attr | universe)
```

Map lift to a signed percentage, with guards against small samples:

- `lift ≥ 1.2` → **boost**, `pct = min(50, round((lift − 1) · 30))`
- `lift ≤ 0.8` → **penalty**, `pct = min(50, round((1 − lift) · 50))`
- `0.8 < lift < 1.2` → neutral (no multiplier)
- Too few gold positives (`< 3`) or too rare in the universe (`< 5`) → neutral.
- A special case: `0` gold occurrences but a `≥ 10%` universe baseline → a full `50%` penalty (the attribute is well-represented yet your customers never have it).

### Step 5 — Final score

Multiply the weighted, normalized signals by the calibration multipliers, scale to 0–100:

```text
score(a) = 100 · ( Σᵢ wᵢ · nᵢ(a) )
                 · Πₚ (1 − penaltyₚ/100)        for each plain penalty flag p set on a
                 · Πₜ (1 ± multₜ/100)            for each tag t on a: (1+) boost, (1−) penalty
```

Because `Σ wᵢ = 1` and each `nᵢ ∈ [0,1]`, the weighted sum is in `[0,1]` and the pre-multiplier score is in `[0,100]`. Multipliers can push it outside that range, which is fine — the score is only ever used to **order** accounts, never read as an absolute.

### Step 6 — Rank (the interface)

The raw `score(a)` is the engine; what reps see is the **rank** — accounts sorted by score descending. Rank is computed *within segments* (size band, territory) when one is chosen, so the model still scores every account globally but the ordering is reset per segment. The exported `data.csv` carries both `score` and `rank`.

### How the default weights are set (a regularized fit to gold)

The default weights aren't hand-typed guesses — they're thoughtful priors, then nudged toward your closed-won (`is_icp_gold`) accounts by a small solver built to avoid overfitting:

- Only the **section blend and category weights** are fit; the within-category signal weights stay frozen — that caps the degrees of freedom (≈6 parameters, not dozens).
- The objective is `AUC(gold) − λ · ‖w − w_default‖²` — a ranking fit *shrunk toward the priors*, so a weight moves only when the gold evidence is strong enough.
- Each weight is **box-bounded** (±10 pts per category, ±15 pts on the blend), so the model stays recognizable.
- λ is chosen by **k-fold cross-validation on held-out gold**, and the fit is **adopted only if held-out AUC beats the priors** by ≥ 0.01. With fewer than ~40 gold accounts it doesn't run at all.

The result is the app's *starting* slider positions: the formula above is unchanged — only the weights `wᵢ` inherit from this fit, and you can still tune them by hand.

### Worked micro-example

One signal, "DevOps engineer headcount" (log transform). Population p99 of `ln(1+engineers)` is `pᵢ = ln(1+40) ≈ 3.71`. An account with 12 DevOps engineers:

```text
x̃ = ln(1+12) = 2.565
n  = (1 − exp(−2.565/3.71)) / (1 − exp(−1)) = (1 − 0.500) / 0.632 = 0.791
```

If that signal's effective weight is `wᵢ = 0.39 · 0.60 = 0.234` and it were the only signal, its contribution is `100 · 0.234 · 0.791 = 18.5` points. A `digital_native` tag with lift `1.5` adds a boost of `round((1.5−1)·30) = 15%`, taking the score to `18.5 · 1.15 = 21.3`.

### Reference constants

| Constant | Value | Role |
|---|---|---|
| Section blend | ACV 60 / Intent 40 | top-level split of "how big" vs "how now" |
| Saturation divisor | `1 − exp(−1) ≈ 0.632` | makes p99 map to exactly 1.0 |
| p99 floor | `1e-9` | avoids divide-by-zero when no positives exist |
| Persona/tech within-decay | `0.98` (geometric) | ranks listed entities instead of equal-weighting |
| "Other"-tier tech drop | `0.6` | demotes secondary technologies |
| Neutral lift band | `0.8 – 1.2` | no multiplier inside this band |
| Boost scale / cap | `30` / `50%` | `min(50, (lift−1)·30)` |
| Penalty scale / cap | `50` / `50%` | `min(50, (1−lift)·50)` |
| Min gold positives | `3` | below this, attribute is neutral |
| Min universe positives | `5` | below this, attribute is neutral |
| Intent window | `90 days` | recency window for job-post intent signals |
| Weight-fit scope | section blend + category weights | within-category weights frozen |
| Weight-fit objective | `AUC(gold) − λ·‖w − w₀‖²` | ranking fit, shrunk to priors |
| Category / blend bands | `±10` / `±15` pts | max drift of a fitted weight from default |
| Weight-fit adopt margin | `+0.01` held-out AUC | else keep the priors |
| Min gold to fit weights | `~40` | below this, skip the fit entirely |

---

## Appendix: Get set up (no prior experience needed)

These coding agents are just chat apps that can run commands and edit files on your computer — you talk to them in plain English. To use the account-scoring skill you (1) install one of them, (2) connect Sumble, and (3) drop in the skill. Pick **one** tool and follow its section. Do the shared steps first.

### Shared steps (once, for any tool)

1. **Create a Sumble account and get your API key.** Sign up at [sumble.com](https://sumble.com), then copy your key from [sumble.com/account](https://sumble.com/account). Keep it handy — the skill will ask for it once and save it securely, so you never paste it into a file.
2. **Install Python 3.10+** (only needed to run the finished app). On a Mac it's usually already installed — open Terminal and run `python3 --version`. Otherwise grab it from [python.org](https://python.org).
3. **Download the skill** from [github.com/SumbleData/sumble-skills](https://github.com/SumbleData/sumble-skills) (the green **Code → Download ZIP** button) and unzip it. You'll find the skill at `skills/sumble-account-scoring`. The commands below assume it's at `~/Downloads/sumble-account-scoring`, so adjust the path if yours differs.
4. **Have your account list ready** (recommended): a spreadsheet saved as a `.csv` with at least `name` and `domain` columns — plus, if you can, a column flagging your **customers** and one for the **account owner / rep**.

### Claude Code

1. **Install it.** Follow [Anthropic's Claude Code install guide](https://docs.claude.com/en/docs/claude-code). It runs in your terminal (or inside VS Code).
2. **Add the skill** to your personal skills folder:
   ```bash
   mkdir -p ~/.claude/skills
   cp -r ~/Downloads/sumble-account-scoring ~/.claude/skills/
   ```
3. **Connect the Sumble MCP.** Follow [docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp) — it gives you the exact command to register Sumble with Claude Code.
4. **Run it.** Start a new Claude Code session and type `/sumble-account-scoring`. Answer the short interview and it builds your app.

### OpenAI Codex

1. **Install it.** Install the [Codex CLI](https://developers.openai.com/codex/cli): `npm install -g @openai/codex`, then run `codex`.
2. **Add the skill** to Codex's skills folder:
   ```bash
   mkdir -p ~/.codex/skills
   cp -r ~/Downloads/sumble-account-scoring ~/.codex/skills/
   ```
3. **Connect the Sumble MCP.** Add the Sumble server to your Codex config (`~/.codex/config.toml`) using the connection details at [docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp).
4. **Run it.** Start Codex in the folder where you want the app created, and ask it: *"Use the sumble-account-scoring skill to build an account score."* Codex loads the skill and runs the same interview.

### Cursor

1. **Install it.** Download [Cursor](https://cursor.com/downloads) — a code editor with a built-in AI agent.
2. **Open a project folder** (File → Open Folder) where you want the app to live, then add the skill to it:
   ```bash
   mkdir -p .cursor/skills
   cp -r ~/Downloads/sumble-account-scoring .cursor/skills/
   ```
   (Or just drag the `sumble-account-scoring` folder into the project in Cursor's sidebar.)
3. **Connect the Sumble MCP.** In **Cursor Settings → MCP**, add the Sumble server using the details at [docs.sumble.com/api/mcp](https://docs.sumble.com/api/mcp).
4. **Run it.** Open the Agent (chat) panel and ask it: *"Follow the sumble-account-scoring skill to build an account score."* If it doesn't pick the skill up automatically, tell it: *"Read `.cursor/skills/sumble-account-scoring/SKILL.md` and follow it."*

### When it's done (any tool)

The skill tells you how to start your app — it's always:

```bash
cd account_scoring/<your-company>
python app.py        # then open http://localhost:8001 in your browser
```

No installs, no extra setup — drag the sliders and your ranking updates live.
