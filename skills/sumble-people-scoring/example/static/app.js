/* People scoring — client-side scoring + UI */

let _config = null;
let _rows = [];
let _selectedOrgId = null;
let _selectedPersonId = null;
let _skillFilter = "";
let _contactFilter = "all";
let _evalBuckets = 10;

// ---------- Flag helpers ---------------------------------------------------

function flagTrue(v) {
  return v === 1 || v === true || v === "1" || v === "true" || v === "True";
}

function isCrmContact(row) {
  const col = _config.flags?.crm_contact_column || "is_crm_contact";
  return flagTrue(row[col]);
}

function isGold(row) {
  const col = _config.flags?.gold_column || "is_icp_gold";
  return flagTrue(row[col]);
}

function hasCrmData() {
  return _rows.some((r) => isCrmContact(r));
}

function hasGoldData() {
  return _rows.some((r) => isGold(r));
}

// ---------- Scoring --------------------------------------------------------

function weightFor(key) {
  const w = _config.weights[key];
  if (!w) return 0;
  return (w.current ?? w.default ?? 0) / 100;
}

function scoreRow(row, config) {
  const { job_function_ranges, default_jf_range, skill_cap } = config;
  const jfSlug = row.job_function_slug || "";
  const jfRange = job_function_ranges[jfSlug] || default_jf_range || { min: 0.5, max: 0.85 };

  const maxRank = row.max_job_level_rank || 19;
  const rank = row.job_level_rank || 0;
  const senFrac = maxRank > 0 ? rank / maxRank : 0;

  const jfScore = jfRange.min + (jfRange.max - jfRange.min) * senFrac;
  const skillScore = Math.min(row.skill_count || 0, skill_cap || 5) / (skill_cap || 5);

  const wJf = weightFor("jf");
  const wSkill = weightFor("skills");

  let total = wJf * jfScore + wSkill * skillScore;

  // 1P signal factors — norm columns are pre-normalised 0–1 in data.csv.
  const oneP = [];
  for (const sig of config.one_p_signals || []) {
    const w = weightFor(sig.weight_key);
    const norm = Number(row[sig.norm_column]) || 0;
    const raw = Number(row[sig.raw_column]) || 0;
    total += w * norm;
    oneP.push({ sig, w, norm, raw });
  }

  return { total, jfScore, skillScore, wJf, wSkill, jfRange, oneP };
}

function fmtScore(s) {
  return (s * 100).toFixed(1);
}

// ---------- Accounts tab ---------------------------------------------------

function renderAccounts() {
  const tbody = document.getElementById("accounts-tbody");
  const ap = _config.account_picker || {};
  const domainCol = ap.domain_column || "domain";
  const nameCol = ap.org_name_column || "org_name";
  const rankCol = ap.account_rank_column || null;
  const scoreCol = ap.account_score_column || null;
  const hasAccountScore = rankCol && _rows.some((r) => r[rankCol] != null && r[rankCol] !== "");

  // Sync table header with account-score column presence
  const thead = document.querySelector("#accounts-table thead tr");
  if (hasAccountScore) {
    thead.innerHTML = `
      <th>Account</th>
      <th>Domain</th>
      <th class="num">People</th>
      <th class="num">Acct score</th>
      <th class="num">Top people score</th>
    `;
  } else {
    thead.innerHTML = `
      <th>Account</th>
      <th>Domain</th>
      <th class="num">People</th>
      <th class="num">Top score</th>
    `;
  }

  // Group rows by org
  const orgMap = new Map();
  for (const row of _rows) {
    const key = row[domainCol] || row.org_id;
    if (!orgMap.has(key)) {
      orgMap.set(key, {
        domain: row[domainCol],
        org_name: row[nameCol],
        org_id: row.org_id,
        account_rank: rankCol && row[rankCol] != null && row[rankCol] !== "" ? Number(row[rankCol]) : null,
        account_score: scoreCol && row[scoreCol] != null && row[scoreCol] !== "" ? Number(row[scoreCol]) : null,
        rows: [],
      });
    }
    orgMap.get(key).rows.push(row);
  }

  // Score and sort
  const orgs = Array.from(orgMap.values()).map((org) => {
    const scores = org.rows.map((r) => scoreRow(r, _config).total);
    return { ...org, count: org.rows.length, topScore: Math.max(...scores) };
  });

  if (hasAccountScore) {
    // Primary: account_rank ascending (1 = best); null ranks go last
    orgs.sort((a, b) => {
      if (a.account_rank == null && b.account_rank == null) return b.topScore - a.topScore;
      if (a.account_rank == null) return 1;
      if (b.account_rank == null) return -1;
      return a.account_rank - b.account_rank;
    });
  } else {
    orgs.sort((a, b) => b.topScore - a.topScore);
  }

  tbody.innerHTML = "";
  for (const org of orgs) {
    const tr = document.createElement("tr");
    if (_selectedOrgId !== null && org.org_id === _selectedOrgId) tr.classList.add("selected");
    if (hasAccountScore) {
      const acctScoreHtml = org.account_score != null
        ? `<span class="score-pill">${org.account_score.toFixed(1)}</span>`
        : "—";
      tr.innerHTML = `
        <td class="name-cell">${esc(org.org_name || org.domain || "—")}</td>
        <td class="domain-cell">${esc(org.domain || "")}</td>
        <td class="num">${org.count}</td>
        <td class="num">${acctScoreHtml}</td>
        <td class="num">${fmtScore(org.topScore)}</td>
      `;
    } else {
      tr.innerHTML = `
        <td class="name-cell">${esc(org.org_name || org.domain || "—")}</td>
        <td class="domain-cell">${esc(org.domain || "")}</td>
        <td class="num">${org.count}</td>
        <td class="num"><span class="score-pill">${fmtScore(org.topScore)}</span></td>
      `;
    }
    tr.addEventListener("click", () => {
      _selectedOrgId = org.org_id;
      _selectedPersonId = null;
      switchTab("people");
      renderPeople();
      renderAccounts();
      hideBreakdown();
    });
    tbody.appendChild(tr);
  }

  document.getElementById("topbar-meta").innerHTML =
    `<span style="color:var(--fg);font-weight:600">${esc(_config.customer_name || "")}</span>` +
    `<span class="dot">·</span>` +
    `<span>${_rows.length.toLocaleString()} people</span>` +
    `<span class="dot">·</span>` +
    `<span>${orgs.length} accounts</span>`;
}

// ---------- People tab -----------------------------------------------------

function personBadges(row) {
  let html = "";
  if (isCrmContact(row)) html += `<span class="badge badge-crm">CRM</span>`;
  if (isGold(row)) html += `<span class="badge badge-gold">Gold</span>`;
  return html;
}

function renderPeople() {
  const tbody = document.getElementById("people-tbody");
  const ctx = document.getElementById("people-context");
  const nameCol = _config.account_picker?.org_name_column || "org_name";

  let rows = _rows;
  if (_selectedOrgId !== null) {
    rows = rows.filter((r) => r.org_id === _selectedOrgId);
    const orgName = rows[0]?.[nameCol] || `org ${_selectedOrgId}`;
    ctx.innerHTML = `
      <button class="back-link" id="back-btn">← All accounts</button>
      <span style="margin-left:8px;font-weight:600">${esc(orgName)}</span>
      <span style="color:var(--fg-dim)"> (${rows.length} people)</span>
    `;
    document.getElementById("back-btn").addEventListener("click", () => {
      _selectedOrgId = null;
      _selectedPersonId = null;
      renderPeople();
      renderAccounts();
      hideBreakdown();
    });
  } else {
    ctx.textContent = `All people (${rows.length.toLocaleString()})`;
  }

  // Skill filter
  if (_skillFilter) {
    rows = rows.filter((r) =>
      (r.matched_skills || "").split(",").map((s) => s.trim()).includes(_skillFilter)
    );
  }

  // Contact filter (CRM contact vs whitespace)
  if (_contactFilter === "crm") {
    rows = rows.filter((r) => isCrmContact(r));
  } else if (_contactFilter === "whitespace") {
    rows = rows.filter((r) => !isCrmContact(r));
  }

  // Score and sort
  const scored = rows.map((r) => ({ row: r, s: scoreRow(r, _config) }));
  scored.sort((a, b) => b.s.total - a.s.total);

  tbody.innerHTML = "";
  for (const { row, s } of scored) {
    const tr = document.createElement("tr");
    if (row[_config.id_column] === _selectedPersonId) tr.classList.add("selected");
    const skills = (row.matched_skills || "")
      .split(",")
      .filter(Boolean)
      .map((sk) => `<span class="chip">${esc(sk.trim())}</span>`)
      .join("");
    tr.innerHTML = `
      <td class="name-cell">${esc(row.name || "—")}${personBadges(row)}</td>
      <td>${esc(row[nameCol] || "—")}</td>
      <td>${esc(row.current_title || "—")}</td>
      <td>${esc(row.job_function_name || "—")}</td>
      <td>${esc(row.job_level || "—")}</td>
      <td><div class="skill-chips">${skills || "—"}</div></td>
      <td>${esc(row.location || "—")}</td>
      <td class="num"><span class="score-pill">${fmtScore(s.total)}</span></td>
    `;
    tr.addEventListener("click", () => {
      _selectedPersonId = row[_config.id_column];
      renderPeople();
      renderBreakdown(row, s);
    });
    tbody.appendChild(tr);
  }

  populateSkillFilter();
}

function populateSkillFilter() {
  const sel = document.getElementById("skill-filter");
  const current = sel.value;
  const skills = new Set();
  for (const row of _rows) {
    for (const sk of (row.matched_skills || "").split(",").map((s) => s.trim()).filter(Boolean)) {
      skills.add(sk);
    }
  }
  sel.innerHTML = `<option value="">All skills</option>`;
  for (const sk of Array.from(skills).sort()) {
    const opt = document.createElement("option");
    opt.value = sk;
    opt.textContent = sk;
    if (sk === current) opt.selected = true;
    sel.appendChild(opt);
  }
}

// ---------- Evaluation tab -------------------------------------------------

function renderEval() {
  const tbody = document.getElementById("eval-tbody");
  const scored = _rows
    .map((r) => ({ score: scoreRow(r, _config).total, gold: isGold(r) ? 1 : 0 }))
    .sort((a, b) => b.score - a.score);
  const total = scored.length;
  const totalGold = scored.reduce((sum, x) => sum + x.gold, 0);
  const baseline = total > 0 ? totalGold / total : 0;

  document.getElementById("eval-summary").textContent =
    `${total.toLocaleString()} people scored · ` +
    `${totalGold.toLocaleString()} gold contacts · ` +
    `baseline gold rate ${(baseline * 100).toFixed(2)}%`;

  const n = Math.max(2, Math.min(100, _evalBuckets || 10));
  tbody.innerHTML = "";
  let cumGold = 0;
  for (let i = 0; i < n; i++) {
    const start = Math.floor((i * total) / n);
    const end = Math.floor(((i + 1) * total) / n);
    const slice = scored.slice(start, end);
    const size = slice.length;
    const gold = slice.reduce((sum, x) => sum + x.gold, 0);
    cumGold += gold;
    const hitRate = size > 0 ? gold / size : 0;
    const cumRecall = totalGold > 0 ? cumGold / totalGold : 0;
    const lift = baseline > 0 ? hitRate / baseline : 0;
    const liftClass = lift >= 1 ? "lift-good" : "lift-bad";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="num">${i + 1}</td>
      <td class="num">${size.toLocaleString()}</td>
      <td class="num">${gold.toLocaleString()}</td>
      <td class="num">${(hitRate * 100).toFixed(1)}%</td>
      <td class="num">${(cumRecall * 100).toFixed(1)}%</td>
      <td class="num"><span class="${liftClass}">${lift.toFixed(2)}×</span></td>
    `;
    tbody.appendChild(tr);
  }
}

// ---------- Breakdown panel ------------------------------------------------

function renderBreakdown(row, s) {
  document.getElementById("breakdown-panel").classList.remove("hidden");
  document.getElementById("bd-name").textContent = row.name || "—";

  const tags = [];
  if (isCrmContact(row)) tags.push("CRM contact");
  if (isGold(row)) tags.push("Gold");
  const metaParts = [row.current_title, row.org_name, row.location].filter(Boolean);
  document.getElementById("bd-meta").textContent =
    metaParts.join(" · ") + (tags.length ? `  ·  ${tags.join(" · ")}` : "");

  const fa = _config.filters_applied || {};
  document.getElementById("bd-filters").textContent =
    `Filtered to: ${fa.seniority_floor_label || ""} · ` +
    `${fa.icp_job_function_count || 0} ICP job functions · ` +
    `${fa.icp_skill_count || 0} skills`;

  const jfLabel =
    (_config.job_function_ranges[row.job_function_slug || ""] || {}).label ||
    row.job_function_name || row.job_function_slug || "—";
  const jfRange = _config.job_function_ranges[row.job_function_slug || ""] ||
    _config.default_jf_range || { min: 0.5, max: 0.85 };

  const tbody = document.getElementById("bd-tbody");
  tbody.innerHTML = "";

  const rows = [
    {
      factor: `Job Function — ${jfLabel}`,
      detail: `range [${jfRange.min.toFixed(2)}, ${jfRange.max.toFixed(2)}]`,
      score: s.jfScore,
      weight: s.wJf,
    },
    {
      factor: `Skills — ${row.skill_count || 0} matched`,
      detail: (row.matched_skills || "none"),
      score: s.skillScore,
      weight: s.wSkill,
    },
  ];

  // One row per 1P signal factor
  for (const op of s.oneP || []) {
    const unit = op.sig.unit ? ` ${op.sig.unit}` : "";
    rows.push({
      factor: op.sig.label || op.sig.weight_key,
      detail: `raw ${op.raw.toLocaleString()}${unit} · norm ${op.norm.toFixed(2)}`,
      score: op.norm,
      weight: op.w,
    });
  }

  const maxContrib = Math.max(...rows.map((r) => r.score * r.weight), 1e-9);
  for (const r of rows) {
    const contrib = r.score * r.weight;
    const barPct = maxContrib > 0 ? (contrib / maxContrib) * 60 : 0;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>
        <div style="font-weight:500">${esc(r.factor)}</div>
        <div style="font-size:10px;color:var(--fg-dim)">${esc(r.detail)}</div>
      </td>
      <td class="num">${fmtScore(r.score)}</td>
      <td class="num">${(r.weight * 100).toFixed(0)}%</td>
      <td class="num">
        <div class="contrib-bar-cell">
          <span class="contrib-bar" style="width:${barPct.toFixed(1)}px"></span>
          <strong>${fmtScore(contrib)}</strong>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  }

  document.getElementById("bd-total").textContent = `Total: ${fmtScore(s.total)} / 100`;

  document.getElementById("bd-linkedin").href = row.linkedin_url || "#";
  document.getElementById("bd-sumble").href = row.sumble_url || "#";
}

function hideBreakdown() {
  document.getElementById("breakdown-panel").classList.add("hidden");
  _selectedPersonId = null;
}

// ---------- Sliders --------------------------------------------------------

// Moving one slider rebalances all the others proportionally so the weights
// always sum to 100. A slider at 0 stays at 0 (it has nothing to scale) —
// unless the moved slider leaves no non-zero others, in which case the
// remainder is split equally. Internally weights stay float; display rounds.
function rebalanceWeights(movedKey, movedVal, src) {
  const keys = Object.keys(_config.weights);
  const cur = (k) => _config.weights[k].current ?? _config.weights[k].default ?? 0;
  const isPinned = (k) => !!_config.weights[k].pinned;
  const others = keys.filter((k) => k !== movedKey);
  // PINNED weights never take pro-rata adjustments: only the unpinned others
  // absorb the change, and the moved value is capped so pinned weights keep
  // their share (sum stays 100). Directly editing a pinned weight is allowed.
  const pinnedSum = others.filter(isPinned).reduce((s, k) => s + cur(k), 0);
  const free = others.filter((k) => !isPinned(k));
  const requested = movedVal;
  movedVal = Math.max(0, Math.min(movedVal, 100 - pinnedSum));
  if (!free.length) movedVal = 100 - pinnedSum; // nothing can absorb a change
  const rest = Math.max(0, 100 - movedVal - pinnedSum);
  const oldRest = free.reduce((s, k) => s + cur(k), 0);
  _config.weights[movedKey].current = movedVal;
  for (const k of free) {
    _config.weights[k].current =
      oldRest > 0 ? (cur(k) * rest) / oldRest : rest / free.length;
  }
  // Sync both controls for every weight — except the control the user is
  // actively using (clobbering a number box mid-typing loses the caret).
  // If the request was clamped (pins limit the range), snap that control too.
  const clamped = movedVal !== requested;
  for (const k of keys) {
    const shown = fmtW(cur(k));
    const slider = document.getElementById(`ws-${k}`);
    const num = document.getElementById(`wn-${k}`);
    const active = k === movedKey && !clamped;
    if (slider && !(src === "slider" && active)) slider.value = shown;
    if (num && !(src === "num" && active)) num.value = shown;
  }
}

// Weights display/entry at one-decimal granularity (internal floats untouched)
function fmtW(v) {
  return Math.round(v * 10) / 10;
}

function renderWeightSliders() {
  const container = document.getElementById("weight-sliders");
  // Keep the job-function range sliders alive across re-renders: if a prior
  // render nested them inside this container, park them outside before we wipe.
  const jfSliders = document.getElementById("jf-range-sliders");
  if (jfSliders && jfSliders.parentElement === container) container.after(jfSliders);
  container.innerHTML = "";
  for (const [key, spec] of Object.entries(_config.weights)) {
    const val = spec.current ?? spec.default;
    const div = document.createElement("div");
    div.className = "weight-slider-row";
    div.id = "weight-row-" + key;
    div.innerHTML = `
      <div class="slider-label">
        <span>${esc(spec.label)}</span>
        <span class="slider-controls">
          <button class="pin-btn${spec.pinned ? " pinned" : ""}" id="wp-${key}"
                  title="Pin: keep this weight fixed when other sliders rebalance">📌</button>
          <input type="number" class="weight-num" id="wn-${key}"
                 min="${spec.min}" max="${spec.max}" step="0.1"
                 value="${fmtW(val)}" />
        </span>
      </div>
      <input type="range" id="ws-${key}" min="${spec.min}" max="${spec.max}"
             value="${fmtW(val)}" step="0.1" />
    `;
    container.appendChild(div);

    div.querySelector(`#wp-${key}`).addEventListener("click", (e) => {
      spec.pinned = !spec.pinned;
      e.target.classList.toggle("pinned", spec.pinned);
    });

    div.querySelector(`#ws-${key}`).addEventListener("input", (e) => {
      rebalanceWeights(key, fmtW(parseFloat(e.target.value)), "slider");
      rerenderScores();
    });
    const num = div.querySelector(`#wn-${key}`);
    num.addEventListener("input", (e) => {
      const v = parseFloat(e.target.value);
      if (!Number.isFinite(v)) return; // mid-typing (empty box)
      rebalanceWeights(key, fmtW(Math.max(0, Math.min(100, v))), "num");
      rerenderScores();
    });
    num.addEventListener("blur", (e) => {
      // Normalize the box after typing (clamps, fills an emptied box)
      e.target.value = fmtW(
        _config.weights[key].current ?? _config.weights[key].default ?? 0
      );
    });
  }
  // Put the per-function Min/Max range sliders directly under the Job Function
  // weight row, collapsed behind a disclosure arrow ON that row (so the ranges
  // read as a detail of the Job Function weight — no separate heading).
  const jfRow = document.getElementById("weight-row-jf");
  if (jfRow && jfSliders) {
    jfRow.after(jfSliders);
    jfSliders.style.marginLeft = "12px";
    jfSliders.style.display = "none"; // collapsed by default
    const labelSpan = jfRow.querySelector(".slider-label > span");
    if (labelSpan && !labelSpan.querySelector(".jf-disclosure")) {
      const arrow = document.createElement("button");
      arrow.type = "button";
      arrow.className = "jf-disclosure";
      arrow.textContent = "▶";
      arrow.title = "Show/hide per-function score ranges";
      arrow.style.cssText =
        "background:none;border:none;cursor:pointer;padding:0;" +
        "margin-right:4px;font-size:10px;color:#64748b;line-height:1;";
      arrow.addEventListener("click", () => {
        const show = jfSliders.style.display === "none";
        jfSliders.style.display = show ? "" : "none";
        arrow.textContent = show ? "▼" : "▶";
      });
      labelSpan.prepend(arrow, " ");
    }
  }
}

function renderJfRangeSliders() {
  const container = document.getElementById("jf-range-sliders");
  container.innerHTML = "";
  for (const [slug, spec] of Object.entries(_config.job_function_ranges)) {
    const div = document.createElement("div");
    div.className = "slider-label";
    div.style.marginBottom = "4px";
    div.style.fontWeight = "500";
    div.style.fontSize = "12px";
    div.textContent = spec.label || slug;
    container.appendChild(div);

    const rangeRow = document.createElement("div");
    rangeRow.className = "range-row";

    for (const which of ["min", "max"]) {
      const half = document.createElement("div");
      half.className = "range-half";
      const labelEl = document.createElement("div");
      labelEl.className = "range-label";
      labelEl.textContent = which === "min" ? "Min (IC)" : "Max (CXO)";
      const valEl = document.createElement("div");
      valEl.className = "range-val";
      valEl.id = `jfv-${slug}-${which}`;
      valEl.textContent = spec[which].toFixed(2);
      const input = document.createElement("input");
      input.type = "range";
      input.min = "0";
      input.max = "1";
      input.step = "0.05";
      input.value = spec[which];
      input.addEventListener("input", (e) => {
        _config.job_function_ranges[slug][which] = parseFloat(e.target.value);
        valEl.textContent = parseFloat(e.target.value).toFixed(2);
        rerenderScores();
      });
      half.appendChild(labelEl);
      half.appendChild(valEl);
      half.appendChild(input);
      rangeRow.appendChild(half);
    }
    container.appendChild(rangeRow);
  }
}

function rerenderScores() {
  const activeTab = document.querySelector(".tab.active")?.dataset?.tab;
  if (activeTab === "accounts") renderAccounts();
  else if (activeTab === "eval") renderEval();
  else renderPeople();
  if (_selectedPersonId !== null) {
    const row = _rows.find((r) => r[_config.id_column] === _selectedPersonId);
    if (row) renderBreakdown(row, scoreRow(row, _config));
  }
}

// ---------- Tabs -----------------------------------------------------------

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.getElementById("tab-accounts").classList.toggle("hidden", name !== "accounts");
  document.getElementById("tab-people").classList.toggle("hidden", name !== "people");
  document.getElementById("tab-eval").classList.toggle("hidden", name !== "eval");
}

// ---------- Helpers --------------------------------------------------------

function esc(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------- Init -----------------------------------------------------------

async function init() {
  const resp = await fetch("/api/data");
  const data = await resp.json();
  _config = data.config;
  _rows = data.rows;

  // Who this scoring run is FOR — page heading + browser tab title.
  const who = _config.customer_name || "";
  document.getElementById("page-title").textContent = who ? `People scoring for ${who}` : "People scoring";
  document.title = who ? `${who} · People Scoring · Sumble` : "People Scoring · Sumble";

  // Filters strip
  const fa = _config.filters_applied || {};
  document.getElementById("filters-strip").textContent =
    `Filtered to: ${fa.seniority_floor_label || "Manager+"} · ` +
    `${fa.icp_job_function_count || 0} ICP job functions · ` +
    `${fa.icp_skill_count || 0} ICP skills`;

  // Show the contact filter / Evaluation tab only when the data supports it
  document.getElementById("contact-filter-wrap").classList.toggle("hidden", !hasCrmData());
  document.getElementById("tab-btn-eval").classList.toggle("hidden", !hasGoldData());

  renderWeightSliders();
  renderJfRangeSliders();
  renderAccounts();
  renderPeople();

  // Tab switching
  document.getElementById("tabs").addEventListener("click", (e) => {
    const tab = e.target.closest(".tab");
    if (!tab) return;
    const name = tab.dataset.tab;
    switchTab(name);
    if (name === "accounts") renderAccounts();
    else if (name === "eval") renderEval();
    else renderPeople();
  });

  // Skill filter
  document.getElementById("skill-filter").addEventListener("change", (e) => {
    _skillFilter = e.target.value;
    renderPeople();
  });

  // Contact filter
  document.getElementById("contact-filter").addEventListener("change", (e) => {
    _contactFilter = e.target.value;
    renderPeople();
  });

  // Evaluation bucket count
  const bucketSlider = document.getElementById("eval-buckets");
  bucketSlider.addEventListener("input", (e) => {
    _evalBuckets = parseInt(e.target.value, 10);
    document.getElementById("eval-buckets-value").textContent = String(_evalBuckets);
    if (document.querySelector(".tab.active")?.dataset?.tab === "eval") renderEval();
  });

  // Reset
  document.getElementById("reset-btn").addEventListener("click", () => {
    for (const [key, spec] of Object.entries(_config.weights)) {
      spec.current = spec.default;
      spec.pinned = false;
      const slider = document.getElementById(`ws-${key}`);
      const num = document.getElementById(`wn-${key}`);
      const pin = document.getElementById(`wp-${key}`);
      if (slider) slider.value = fmtW(spec.default);
      if (num) num.value = fmtW(spec.default);
      if (pin) pin.classList.remove("pinned");
    }
    for (const [slug, spec] of Object.entries(_config.job_function_ranges)) {
      for (const which of ["min", "max"]) {
        const valEl = document.getElementById(`jfv-${slug}-${which}`);
        if (valEl) valEl.textContent = spec[which].toFixed(2);
      }
    }
    rerenderScores();
  });

  // Save — writes people-scoring-weights.json AND regenerates score.csv
  // server-side from the current sliders. Returns true on success so the
  // Download button can reuse it.
  async function saveWeights() {
    const status = document.getElementById("save-status");
    status.textContent = "Saving…";
    try {
      const resp = await fetch("/api/save-weights", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(_config),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      status.textContent = data.saved_to ? `Saved → ${data.saved_to} ✓` : "Saved ✓";
      setTimeout(() => { status.textContent = ""; }, 4000);
      return true;
    } catch {
      status.textContent = "Save failed";
      return false;
    }
  }
  document.getElementById("save-btn").addEventListener("click", saveWeights);

  // Download score sheet — save first (regenerates score.csv from the current
  // sliders), then fetch the file the server just wrote.
  const downloadBtn = document.getElementById("download-btn");
  if (downloadBtn) {
    downloadBtn.addEventListener("click", async () => {
      if (await saveWeights()) window.location.href = "/score.csv";
    });
  }

  // Close breakdown
  document.getElementById("bd-close").addEventListener("click", hideBreakdown);
}

document.addEventListener("DOMContentLoaded", init);
