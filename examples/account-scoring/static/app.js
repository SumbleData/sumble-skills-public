// Sumble account-scoring UI.
// Fetches /api/data once; recomputes scores client-side on slider change.
// Top-level: category sliders sum to 100%.
// Within each category (accordion): signal sliders sum to 100% of that category.
// Score per signal = (cat_pct/100) * (within_pct/100) * norm_value
// Final score = (sum of contributions) * (1 - sum(penalty_pct * flag)) * 100

const PAGE_SIZE = 100;

// Weights form a 3-level hierarchy when config.sections is defined:
//   section% (sum to 100 across sections)
//     category% (sum to 100 within each section)
//       signal% (sum to 100 within each category)
//   effective per-signal weight = section × category × signal / 10000
// When sections is absent, sectionPct stays empty and category% sums to 100 globally.
//
// UI-side: when a section has exactly one category, we collapse its
// rendering to a 2-level hierarchy (section -> signals) — the lone
// category's slider would always be 100% with nothing to redistribute
// against, so the third level adds noise. The category still exists in
// state.catPct (value pinned to 100) so the scoring formula above is
// unchanged; only the accordion is skipped. Sections with 2+ categories
// keep the full 3-level UI.
const state = {
  config: null,
  rows: [],
  sectionPct: {},    // section_key -> % (sums to 100)
  catPct: {},        // category_key -> % within its section (or % of total if no sections)
  withinPct: {},     // category_key -> { signal_key -> % within that category }
  // Pin state, parallel to the three % maps above. A pinned entry keeps its
  // exact value while its pool siblings redistribute (see redistribute()).
  sectionPinned: {}, // section_key -> bool
  catPinned: {},     // category_key -> bool
  withinPinned: {},  // category_key -> { signal_key -> bool }
  multPct: {},       // multiplier_column -> %
  tagMult: [],       // [{tag, pct, direction: "penalty"|"boost"}]
  availableTags: [], // [{tag, count}] universe-wide tag inventory
  expanded: {},      // category_key -> bool
  sectionExpanded: {}, // section_key -> bool (default collapsed)
  selectedId: null,
  tab: "accounts",
  hiddenCategories: new Set(), // account_category values toggled OFF (filtered out)
  evalBuckets: 10,
  search: "",
  sizeMin: null, // employee_count_int >= this; null = no lower bound
  sizeMax: null, // employee_count_int <= this; null = no upper bound
  page: 0,
  savedWeights: null, // weights loaded from account-scoring-weights.json
};

// Column used by the employee-size filter. If the loaded data lacks this
// column, the filter widget is hidden in setup() — see SIZE_FILTER_COL.
const SIZE_FILTER_COL = "employee_count_int";

const TAB_DESCRIPTIONS = {
  accounts: "Accounts ranked by fit.",
  whitespace: "Accounts ranked by fit.",
  eval: "How the score behaves across your accounts. The first table shows where each account category (customers, rep-allocated, unallocated, whitespace) lands in the overall ranking — customers should sit near the top, and whitespace surfaces your best net-new targets. Below, accounts are split into equal-size score buckets (top bucket = highest-scoring): “Gold-set lift by bucket” shows how many of your known customers each bucket captures (lift > 1.0 = better than picking at random), and the size / attribute mixes show how firmographics shift from high to low scorers.",
};

// account_category → display label. The Category column + filter chips appear
// only when ≥2 distinct categories are present (config.has_categories).
const CATEGORY_LABELS = {
  customer: "Customer / gold",
  allocated: "Allocated to rep",
  unallocated: "CRM, unallocated",
  whitespace: "Whitespace",
  whitespace_subsidiary: "Whitespace (parent in CRM)",
};
const CATEGORY_ORDER = [
  "customer", "allocated", "unallocated", "whitespace", "whitespace_subsidiary",
];

function rowCategory(row) {
  if (isGold(row)) return "customer";
  return String(row.account_category || "");
}

// Pretty display for tag-multiplier tags. `industry__hospital_health_care` →
// "Industry: Hospital Health Care"; common attribute tags get a clean label;
// everything else shows the raw slug.
const TAG_DISPLAY = {
  b2b: "B2B",
  b2c: "B2C",
  digital_native: "Digital-native",
  is_ai_native: "AI-native",
  it_services: "IT services",
  professional_services: "Professional services",
};
function tagLabel(tag) {
  const t = String(tag || "");
  if (t.startsWith("industry__")) {
    const words = t.slice("industry__".length).split("_").filter(Boolean);
    const titled = words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
    return "Industry: " + titled;
  }
  return TAG_DISPLAY[t] || t;
}

// ---------- DOM helpers ----------

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") {
      e.addEventListener(k.slice(2).toLowerCase(), v);
    } else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}

function fmtInt(x) {
  return x == null || Number.isNaN(x) ? "—" : Math.round(x).toLocaleString();
}

function fmtFloat(x, d = 1) {
  return x == null || Number.isNaN(x) ? "—" : Number(x).toFixed(d);
}

// Weights display/entry at one-decimal granularity (internal floats untouched)
function fmtW(v) {
  return Math.round(v * 10) / 10;
}

function fmtPct(x) {
  // Growth is stored as a ratio (0.5 = +50% YoY, 33 = +3300%); show as percent.
  if (x == null || Number.isNaN(x)) return "—";
  const pct = Number(x) * 100;
  return (pct > 0 ? "+" : "") + pct.toFixed(0) + "%";
}

function fmtRaw(x, fmt) {
  if (fmt === "int") return fmtInt(x);
  if (fmt === "pct") return fmtPct(x);
  return fmtFloat(x);
}

// Build a deep link to a Sumble org page from a signal's sumble_link spec.
// spec shape: { path: "/people", filters: { job_function: ["Sales"], ... } }
// The filters are emitted as Sumble's advanced-search `as=` JSON:
// AND of one OR-group per field. Each group has the shape
// { operator: "OR", fields: { <field>: { include: [...], exclude: [] } } }.
// Job functions use display names ("Sales Development Representative");
// technology/project use slugs ("zoominfo", "digital_transformation").
function buildSumbleLink(base, slug, spec) {
  if (!spec || !slug) return null;
  const path = spec.path || "";
  const url = `${base}${slug}${path}`;
  const filters = spec.filters || {};
  const groups = [];
  for (const [field, values] of Object.entries(filters)) {
    if (!Array.isArray(values) || values.length === 0) continue;
    groups.push({
      operator: "OR",
      fields: { [field]: { include: values, exclude: [] } },
    });
  }
  if (groups.length === 0) return url;
  const as = { operator: "AND", children: groups };
  const params = new URLSearchParams();
  params.set("as", JSON.stringify(as));
  // Append the page's canonical sort. /jobs has no default sort.
  if (path.includes("people")) {
    params.set("sort", "Sumble Lead Score");
    params.set("desc", "1");
  } else if (path === "/teams") {
    params.set("sort", "Tech jobs");
    params.set("desc", "1");
  }
  return `${url}?${params.toString()}`;
}

// ---------- Category index ----------

function signalsByCategory() {
  const out = {};
  for (const catKey of Object.keys(state.config.categories || {})) {
    out[catKey] = [];
  }
  for (const [key, spec] of Object.entries(state.config.signals)) {
    const cat = spec.category || "first_party";
    (out[cat] ||= []).push({ key, spec });
  }
  return out;
}

// ---------- Constrained-sum slider math ----------

// Adjust `values[key]` to `next`. Redistribute the delta among the
// other keys, proportional to their current values. Sum stays at total.
// Keys for which `isPinned(k)` is true never absorb any of the delta: the
// moved value is clamped so pinned keys keep their exact share, and only the
// unpinned others rescale. Directly editing a pinned key is allowed — its own
// pin only matters when a sibling moves.
// Returns the actual new value (may be clamped if neighbours can't absorb the delta).
function redistribute(values, key, next, total = 100, isPinned = () => false) {
  const keys = Object.keys(values);
  if (keys.length <= 1) {
    values[key] = total;
    return total;
  }
  const others = keys.filter((k) => k !== key);
  const free = others.filter((k) => !isPinned(k));
  const pinnedSum = others.reduce(
    (s, k) => s + (isPinned(k) ? values[k] ?? 0 : 0),
    0,
  );
  if (free.length === 0) {
    // Every other key is pinned: the only value consistent with the pool
    // total is whatever the pinned keys leave over — snap to it.
    const snapped = Math.round(Math.max(0, total - pinnedSum) * 10) / 10;
    values[key] = snapped;
    return snapped;
  }
  const cur = values[key] ?? 0;
  let nxt = Math.max(0, Math.min(total - pinnedSum, Number(next)));
  let delta = nxt - cur;
  if (delta === 0) return cur;

  const freeSum = free.reduce((s, k) => s + (values[k] ?? 0), 0);

  if (delta < 0) {
    const give = -delta;
    if (freeSum === 0) {
      const each = give / free.length;
      for (const k of free) values[k] = (values[k] ?? 0) + each;
    } else {
      for (const k of free) values[k] = (values[k] ?? 0) + give * ((values[k] ?? 0) / freeSum);
    }
  } else {
    if (freeSum === 0) {
      nxt = cur;
      delta = 0;
    } else if (delta >= freeSum) {
      nxt = cur + freeSum;
      for (const k of free) values[k] = 0;
    } else {
      for (const k of free) values[k] = (values[k] ?? 0) - delta * ((values[k] ?? 0) / freeSum);
    }
  }
  values[key] = nxt;
  // Round to 0.1 and re-fix to sum (numeric drift)
  for (const k of keys) values[k] = Math.round(values[k] * 10) / 10;
  const sum = keys.reduce((s, k) => s + values[k], 0);
  if (Math.abs(sum - total) > 0.05 && keys.length > 1) {
    // Push drift onto the UNPINNED "other" with the largest share, so
    // pinned values stay exactly as set.
    const bestOther = free.reduce((a, b) => (values[a] >= values[b] ? a : b), free[0]);
    values[bestOther] += total - sum;
    values[bestOther] = Math.round(values[bestOther] * 10) / 10;
  }
  return values[key];
}

// ---------- Scoring ----------

// True only when ≥2 sections are configured. With a single section the
// section wrapper is redundant (it'd be a fixed 100% slider above one
// category pool), so we render categories flat and treat section_weight
// as 1.0 in the scoring formula — same behaviour as a no-sections config.
function hasSections() {
  const s = state.config && state.config.sections;
  return !!(s && Object.keys(s).length > 1);
}

function sectionOf(catKey) {
  return (state.config.categories || {})[catKey]?.section;
}

// Sibling category keys that share a 100% pool with this category.
// With sections defined: only categories in the same section.
// Without sections: all categories.
function poolForCategory(catKey) {
  if (!hasSections()) return state.catPct;
  const sec = sectionOf(catKey);
  if (!sec) return state.catPct;
  const sub = {};
  for (const [k, v] of Object.entries(state.catPct)) {
    if (sectionOf(k) === sec) sub[k] = v;
  }
  return sub;
}

function rowScore(row) {
  let score = 0;
  const sec = hasSections();
  for (const [key, spec] of Object.entries(state.config.signals)) {
    const cat = spec.category || "first_party";
    const sectionPct = sec ? (state.sectionPct[sectionOf(cat)] || 0) / 100 : 1;
    const catPct = (state.catPct[cat] || 0) / 100;
    const withinPct = ((state.withinPct[cat] || {})[key] || 0) / 100;
    const norm = row[`norm_${key}`] || 0;
    score += sectionPct * catPct * withinPct * norm;
  }
  for (const m of state.config.multipliers || []) {
    const pct = (state.multPct[m.column] || 0) / 100;
    if (pct > 0 && row[m.column]) score *= 1 - pct;
  }
  // Per-tag multipliers. row.tags is a pipe-delimited string (e.g.
  // "b2b|digital_native"). For each active multiplier whose tag is
  // present on the row, apply (1 - pct/100) for penalty or (1 + pct/100)
  // for boost. Direction stored on the multiplier entry; default = penalty.
  if (state.tagMult.length) {
    const rowTags = parseRowTags(row);
    if (rowTags.size) {
      for (const entry of state.tagMult) {
        if (!entry.tag) continue;
        if (!rowTags.has(entry.tag)) continue;
        const pct = (Number(entry.pct) || 0) / 100;
        if (pct <= 0) continue;
        score *= entry.direction === "boost" ? 1 + pct : 1 - pct;
      }
    }
  }
  return score * 100;
}

function parseRowTags(row) {
  if (row._tagSet) return row._tagSet;
  const raw = row.tags;
  const set = new Set();
  if (raw) {
    for (const t of String(raw).split("|")) {
      const tt = t.trim();
      if (tt) set.add(tt);
    }
  }
  // Cache on the row so we don't re-split on every score recompute.
  Object.defineProperty(row, "_tagSet", { value: set, enumerable: false });
  return set;
}

function rankedRows() {
  // Rank ALL accounts together (one global rank), so a customer's rank reflects
  // its position among everything — the same rank the Evaluation tab reports.
  // Category chips + search then filter the displayed slice without renumbering.
  const ranked = state.rows
    .map((r) => ({ row: r, score: rowScore(r) }))
    .sort((a, b) => b.score - a.score);
  ranked.forEach((entry, i) => {
    entry.rank = i + 1;
  });
  return ranked;
}

function filteredRanked() {
  const ranked = rankedRows();
  const q = (state.search || "").trim().toLowerCase();
  const cols = state.config.table_columns || [];
  const sMin = state.sizeMin;
  const sMax = state.sizeMax;
  const sizeActive = sMin != null || sMax != null;
  const hidden = state.config.has_categories ? state.hiddenCategories : null;
  const catActive = hidden && hidden.size > 0;
  if (!q && !sizeActive && !catActive) return ranked;
  return ranked.filter(({ row }) => {
    if (catActive && hidden.has(rowCategory(row))) return false;
    if (sizeActive) {
      const emp = Number(row[SIZE_FILTER_COL]);
      if (!Number.isFinite(emp)) return false;
      if (sMin != null && emp < sMin) return false;
      if (sMax != null && emp > sMax) return false;
    }
    if (!q) return true;
    for (const c of cols) {
      const v = row[c];
      if (v != null && String(v).toLowerCase().includes(q)) return true;
    }
    return false;
  });
}

// ---------- Render: category accordion ----------

// Build one signal-row (label + within-category slider). Used both
// inside a category-card body and (when a section has exactly one
// category) directly inside a section-body — the latter collapses
// the redundant 100%-only category accordion into a 2-level
// section -> signal hierarchy.
function makeSignalRow(catKey, signal, totalSignalsInCat) {
  const { key, spec } = signal;
  const within = (state.withinPct[catKey] || {})[key] || 0;

  // Shared by the slider and the number box so both feed the exact same
  // redistribute -> rerender path. Returns the (possibly clamped) value.
  const applyWithin = (v) => {
    state.withinPct[catKey] ||= {};
    const actual = redistribute(
      state.withinPct[catKey],
      key,
      v,
      100,
      (k) => !!(state.withinPinned[catKey] || {})[k],
    );
    renderWithinPcts(catKey);
    renderTable();
    if (state.selectedId) updateBreakdown();
    scheduleAutoSave();
    return actual;
  };

  const wNum = el("input", {
    type: "number",
    class: "weight-num",
    min: "0",
    max: "100",
    step: "0.1",
    value: fmtFloat(within, 1),
    oninput: (e) => {
      const v = Number(e.target.value);
      if (e.target.value === "" || !Number.isFinite(v)) return; // mid-typing
      applyWithin(Math.max(0, Math.min(100, v)));
    },
    onblur: (e) => {
      // Normalize after typing (clamps, fills an emptied box).
      e.target.value = fmtFloat((state.withinPct[catKey] || {})[key] || 0, 1);
    },
  });
  const wPin = el(
    "button",
    {
      type: "button",
      class: "pin-btn" + ((state.withinPinned[catKey] || {})[key] ? " pinned" : ""),
      title: "Pin: keep this weight fixed when sibling sliders rebalance",
      onclick: (e) => {
        state.withinPinned[catKey] ||= {};
        state.withinPinned[catKey][key] = !state.withinPinned[catKey][key];
        e.target.classList.toggle("pinned", state.withinPinned[catKey][key]);
      },
    },
    "📌",
  );
  const wPct = el("span", { class: "signal-pct" }, wPin, wNum, "%");

  const wSlider = el("input", {
    type: "range",
    min: "0",
    max: "100",
    step: "0.5",
    value: String(fmtW(within)),
    oninput: (e) => {
      e.target.value = String(fmtW(applyWithin(Number(e.target.value))));
    },
  });
  if (totalSignalsInCat <= 1) {
    wSlider.disabled = true;
    wNum.disabled = true;
    wPin.disabled = true;
  }

  // Flag signals that can't be reproduced from the public Sumble API.
  // They still count in the app's full model, but a public-API-only
  // production scorer drops them and re-normalises weights.
  const labelChildren = [el("span", { class: "label-text" }, spec.label)];
  if (spec.api_supported === false) {
    const reason =
      (spec.source && spec.source.api_unsupported_reason) ||
      spec.api_unsupported_reason ||
      "No public Sumble API endpoint exposes this — calibration only, not reproducible by the API-only production scorer.";
    labelChildren.push(
      el("span", { class: "api-badge", title: reason }, "SQL-only"),
    );
  }
  labelChildren.push(wPct);

  return el(
    "div",
    { class: "signal-row", "data-cat": catKey, "data-signal": key },
    el("label", {}, ...labelChildren),
    wSlider,
  );
}

// Build one category accordion card. Used inside a section that has
// 2+ categories; sections with a single category bypass this and
// render signals directly via makeSignalRow.
function makeCategoryCard(catKey, catSpec, grouped) {
  const signals = grouped[catKey] || [];
  const isEmpty = signals.length === 0;
  const expanded = !!state.expanded[catKey];

  // Shared by the slider and the number box so both feed the exact same
  // redistribute -> rerender path. Returns the (possibly clamped) value.
  const applyCatPct = (v) => {
    const pool = poolForCategory(catKey);
    const actual = redistribute(pool, catKey, v, 100, (k) => !!state.catPinned[k]);
    if (pool !== state.catPct) {
      for (const [k, val] of Object.entries(pool)) state.catPct[k] = val;
    }
    renderCategoryPcts();
    renderTable();
    if (state.selectedId) updateBreakdown();
    scheduleAutoSave();
    return actual;
  };

  const pctNum = el("input", {
    type: "number",
    class: "weight-num",
    min: "0",
    max: "100",
    step: "0.1",
    value: fmtFloat(state.catPct[catKey] || 0, 1),
    oninput: (e) => {
      const v = Number(e.target.value);
      if (e.target.value === "" || !Number.isFinite(v)) return; // mid-typing
      applyCatPct(Math.max(0, Math.min(100, v)));
    },
    onblur: (e) => {
      // Normalize after typing (clamps, fills an emptied box).
      e.target.value = fmtFloat(state.catPct[catKey] || 0, 1);
    },
    // Stop the click on the box from toggling collapse.
    onclick: (e) => e.stopPropagation(),
  });
  const pctPin = el(
    "button",
    {
      type: "button",
      class: "pin-btn" + (state.catPinned[catKey] ? " pinned" : ""),
      title: "Pin: keep this weight fixed when sibling sliders rebalance",
      onclick: (e) => {
        // Stop the click from toggling collapse.
        e.stopPropagation();
        state.catPinned[catKey] = !state.catPinned[catKey];
        e.target.classList.toggle("pinned", state.catPinned[catKey]);
      },
    },
    "📌",
  );
  const pctSpan = el("span", { class: "category-pct" }, pctPin, pctNum, "%");

  const header = el(
    "div",
    {
      class: "category-header",
      onclick: () => {
        if (isEmpty) return;
        state.expanded[catKey] = !state.expanded[catKey];
        renderCategories();
      },
    },
    el("span", { class: "disclosure" }),
    el("span", { class: "category-title" }, catSpec.label || catKey),
    pctSpan,
  );

  // Category slider redistributes within its section's pool (or globally
  // when no sections are defined). Either way the pool sums to 100.
  const slider = el("input", {
    type: "range",
    min: "0",
    max: "100",
    step: "0.5",
    value: String(fmtW(state.catPct[catKey] || 0)),
    oninput: (e) => {
      e.target.value = String(fmtW(applyCatPct(Number(e.target.value))));
    },
  });
  if (isEmpty) {
    slider.disabled = true;
    pctNum.disabled = true;
    pctPin.disabled = true;
  }

  const sliderWrap = el("div", { class: "category-slider-wrap" }, slider);

  const body = el("div", { class: "category-body" });
  if (catSpec.description) {
    body.appendChild(el("p", { class: "category-desc" }, catSpec.description));
  }

  for (const signal of signals) {
    body.appendChild(makeSignalRow(catKey, signal, signals.length));
  }

  return el(
    "div",
    {
      class: "category" + (expanded ? " expanded" : ""),
      "data-cat": catKey,
      "data-empty": isEmpty ? "true" : "false",
    },
    header,
    sliderWrap,
    body,
  );
}

function renderCategories() {
  const grouped = signalsByCategory();
  const cats = state.config.categories || {};
  const sections = state.config.sections;
  const container = document.getElementById("categories");
  container.innerHTML = "";

  const hasSecs = hasSections();
  if (hasSecs) {
    // Top-level section sliders (sum to 100). Each section is a
    // collapsible card; categories inside sum to 100% of that section.
    // Sections default to collapsed so the panel opens compact.
    // (A single section is treated as no sections; see hasSections().)
    const placed = new Set();
    for (const [secKey, secSpec] of Object.entries(sections)) {
      const expanded = !!state.sectionExpanded[secKey];
      const group = el("div", {
        class: "section-group" + (expanded ? " expanded" : ""),
        "data-section": secKey,
      });

      // Shared by the slider and the number box so both feed the exact same
      // redistribute -> rerender path. Returns the (possibly clamped) value.
      const applySectionPct = (v) => {
        const actual = redistribute(
          state.sectionPct,
          secKey,
          v,
          100,
          (k) => !!state.sectionPinned[k],
        );
        renderSectionPcts();
        renderTable();
        if (state.selectedId) updateBreakdown();
        scheduleAutoSave();
        return actual;
      };

      const secNum = el("input", {
        type: "number",
        class: "weight-num",
        min: "0",
        max: "100",
        step: "0.1",
        value: fmtFloat(state.sectionPct[secKey] || 0, 1),
        oninput: (e) => {
          const v = Number(e.target.value);
          if (e.target.value === "" || !Number.isFinite(v)) return; // mid-typing
          applySectionPct(Math.max(0, Math.min(100, v)));
        },
        onblur: (e) => {
          // Normalize after typing (clamps, fills an emptied box).
          e.target.value = fmtFloat(state.sectionPct[secKey] || 0, 1);
        },
        // Stop the click on the box from toggling collapse.
        onclick: (e) => e.stopPropagation(),
      });
      const secPin = el(
        "button",
        {
          type: "button",
          class: "pin-btn" + (state.sectionPinned[secKey] ? " pinned" : ""),
          title: "Pin: keep this weight fixed when sibling sliders rebalance",
          onclick: (e) => {
            // Stop the click from toggling collapse.
            e.stopPropagation();
            state.sectionPinned[secKey] = !state.sectionPinned[secKey];
            e.target.classList.toggle("pinned", state.sectionPinned[secKey]);
          },
        },
        "📌",
      );
      const secPct = el("span", { class: "section-pct" }, secPin, secNum, "%");

      group.appendChild(
        el(
          "div",
          {
            class: "section-header",
            onclick: () => {
              state.sectionExpanded[secKey] = !expanded;
              renderCategories();
            },
          },
          el("span", { class: "disclosure" }),
          el("span", { class: "section-title" }, secSpec.label || secKey),
          secPct,
        ),
      );

      const sectionSlider = el("input", {
        type: "range",
        min: "0",
        max: "100",
        step: "0.5",
        value: String(fmtW(state.sectionPct[secKey] || 0)),
        oninput: (e) => {
          // Stop the click on the slider from toggling collapse.
          e.stopPropagation();
          e.target.value = String(fmtW(applySectionPct(Number(e.target.value))));
        },
        onclick: (e) => e.stopPropagation(),
      });
      group.appendChild(el("div", { class: "section-slider-wrap" }, sectionSlider));

      const body = el("div", { class: "section-body" });
      if (secSpec.description) {
        body.appendChild(el("p", { class: "section-desc" }, secSpec.description));
      }
      // Auto-collapse: if a section has exactly one category, the
      // category slider would be a fixed-100% no-op (a third level
      // with nothing to redistribute). Render its signals directly
      // inside section-body as a 2-level hierarchy. Sections with
      // 2+ categories keep the full 3-level accordion.
      const secCats = Object.entries(cats).filter(
        ([, c]) => c.section === secKey,
      );
      if (secCats.length === 1) {
        const [catKey] = secCats[0];
        placed.add(catKey);
        const signals = grouped[catKey] || [];
        for (const signal of signals) {
          body.appendChild(makeSignalRow(catKey, signal, signals.length));
        }
      } else {
        for (const [catKey, catSpec] of secCats) {
          placed.add(catKey);
          body.appendChild(makeCategoryCard(catKey, catSpec, grouped));
        }
      }
      group.appendChild(body);
      container.appendChild(group);
    }
    // Categories with a missing/unknown section render ungrouped at the end.
    for (const [catKey, catSpec] of Object.entries(cats)) {
      if (placed.has(catKey)) continue;
      container.appendChild(makeCategoryCard(catKey, catSpec, grouped));
    }
  } else {
    for (const [catKey, catSpec] of Object.entries(cats)) {
      container.appendChild(makeCategoryCard(catKey, catSpec, grouped));
    }
  }

  renderCategoryPcts();
}

function renderCategoryPcts() {
  for (const [catKey, pct] of Object.entries(state.catPct)) {
    const card = document.querySelector(`.category[data-cat="${catKey}"]`);
    if (!card) continue;
    const num = card.querySelector(".category-pct input");
    if (num && document.activeElement !== num) num.value = fmtFloat(pct, 1);
    const slider = card.querySelector('.category-slider-wrap input[type="range"]');
    if (slider && document.activeElement !== slider) slider.value = String(fmtW(pct));
  }
  renderSectionPcts();
}

// Update each section header's % label + slider from state.sectionPct.
function renderSectionPcts() {
  if (!hasSections()) return;
  for (const [secKey, pct] of Object.entries(state.sectionPct)) {
    const group = document.querySelector(
      `.section-group[data-section="${secKey}"]`,
    );
    if (!group) continue;
    const num = group.querySelector(".section-pct input");
    if (num && document.activeElement !== num) num.value = fmtFloat(pct, 1);
    const slider = group.querySelector('.section-slider-wrap input[type="range"]');
    if (slider && document.activeElement !== slider) slider.value = String(fmtW(pct));
  }
}

function renderWithinPcts(catKey) {
  // Scope by data-cat + data-signal directly rather than under a
  // .category[data-cat="..."] wrapper — sections collapsed to a
  // 2-level hierarchy have no .category card, but signal-rows always
  // carry both data attributes regardless of which wrapper holds them.
  const withins = state.withinPct[catKey] || {};
  for (const [signalKey, pct] of Object.entries(withins)) {
    const row = document.querySelector(
      `.signal-row[data-cat="${catKey}"][data-signal="${signalKey}"]`,
    );
    if (!row) continue;
    const num = row.querySelector(".signal-pct input");
    if (num && document.activeElement !== num) num.value = fmtFloat(pct, 1);
    const slider = row.querySelector('input[type="range"]');
    if (slider && document.activeElement !== slider) slider.value = String(fmtW(pct));
  }
}

// ---------- Render: multipliers ----------

function renderTagMultipliers() {
  // Picker datalist — refresh from available_tags so the user can search
  // by typing partial tag names (datalist handles substring match natively).
  const list = document.getElementById("tag-mult-list");
  if (list) {
    list.innerHTML = "";
    // Skip tags already added so they don't get added twice from the picker.
    const taken = new Set(state.tagMult.map((m) => m.tag));
    for (const t of state.availableTags) {
      if (taken.has(t.tag)) continue;
      list.appendChild(el("option", { value: t.tag, label: `${tagLabel(t.tag)} (${t.count})` }));
    }
  }

  const wrap = document.getElementById("tag-multipliers");
  if (!wrap) return;
  wrap.innerHTML = "";
  state.tagMult.forEach((entry, idx) => {
    // Single signed slider: negative = penalize, positive = amplify, 0 = no
    // effect. We persist {pct, direction} (pct is the unsigned magnitude) for
    // save-file compatibility; the signed value is just the UI representation.
    const signed = () => (entry.direction === "boost" ? entry.pct : -entry.pct);
    const labelFor = (v) =>
      v > 0 ? `Amplify +${v}%` : v < 0 ? `Penalize −${Math.abs(v)}%` : "No effect";
    const classFor = (v) =>
      v > 0 ? "multiplier-pct amplify" : v < 0 ? "multiplier-pct penalize" : "multiplier-pct neutral";
    const valueSpan = el("span", { class: classFor(signed()) }, labelFor(signed()));
    const slider = el("input", {
      type: "range",
      min: "-75",
      max: "75",
      step: "5",
      value: String(signed()),
      class: "tag-mult-slider",
      oninput: (e) => {
        const v = Number(e.target.value);
        entry.direction = v < 0 ? "penalty" : "boost";
        entry.pct = Math.abs(v);
        valueSpan.textContent = labelFor(v);
        valueSpan.className = classFor(v);
        renderTable();
        if (state.selectedId) updateBreakdown();
        scheduleAutoSave();
      },
    });
    const removeBtn = el("button", {
      type: "button",
      class: "btn-tag-remove",
      title: "Remove this tag multiplier",
      onclick: () => {
        state.tagMult.splice(idx, 1);
        renderTagMultipliers();
        renderTable();
        if (state.selectedId) updateBreakdown();
        scheduleAutoSave();
      },
    }, "×");
    wrap.appendChild(
      el(
        "div",
        { class: "multiplier-row tag-mult-row" },
        el("label", {},
          el("span", { class: "tag-mult-chip", title: entry.tag }, tagLabel(entry.tag)),
          valueSpan,
        ),
        slider,
        el("div", { class: "tag-mult-actions" }, removeBtn),
      ),
    );
  });
}

function renderMultipliers() {
  const section = document.getElementById("multipliers-section");
  const wrap = document.getElementById("multipliers");
  wrap.innerHTML = "";
  const mults = state.config.multipliers || [];
  if (mults.length === 0) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");
  for (const m of mults) {
    const maxPct = m.max_pct ?? 75;

    // Shared by the slider and the number box so both feed the exact same
    // update -> rerender path.
    const applyMult = (v) => {
      state.multPct[m.column] = v;
      renderTable();
      if (state.selectedId) updateBreakdown();
      scheduleAutoSave();
    };

    const num = el("input", {
      type: "number",
      class: "weight-num",
      min: "0",
      max: String(maxPct),
      step: "5",
      value: String(fmtW(state.multPct[m.column])),
      oninput: (e) => {
        const v = Number(e.target.value);
        if (e.target.value === "" || !Number.isFinite(v)) return; // mid-typing
        const clamped = Math.max(0, Math.min(maxPct, v));
        applyMult(clamped);
        if (document.activeElement !== slider) slider.value = String(fmtW(clamped));
      },
      onblur: (e) => {
        // Normalize after typing (clamps, fills an emptied box).
        e.target.value = String(fmtW(state.multPct[m.column]));
      },
    });
    const slider = el("input", {
      type: "range",
      min: "0",
      max: String(maxPct),
      step: "5",
      value: String(fmtW(state.multPct[m.column])),
      oninput: (e) => {
        applyMult(Number(e.target.value));
        if (document.activeElement !== num) num.value = e.target.value;
      },
    });
    wrap.appendChild(
      el(
        "div",
        { class: "multiplier-row" },
        el("label", {}, el("span", {}, m.label), el("span", { class: "multiplier-pct" }, num, "%")),
        slider,
      ),
    );
  }
}

// ---------- Render: results table ----------

function isGold(row) {
  const v = row.is_icp_gold;
  return v === 1 || v === true || v === "1" || v === "True" || v === "true";
}

// Employee-size bands for the eval diagnostics (ordered large -> small).
// Each band: { key, label, test(employee_count_int) }. Cut points match
// Sumble's CTFP page (sumble.com /company/<x>/ctfp): SMB / Mid-Market /
// Enterprise.
const SIZE_BANDS = [
  { key: "enterprise", label: "Enterprise (1,001+)", test: (e) => e >= 1001 },
  { key: "mid_market", label: "Mid-Market (201–1,000)", test: (e) => e >= 201 && e <= 1000 },
  { key: "smb", label: "SMB (1–200)", test: (e) => e >= 1 && e <= 200 },
];

// Attributes for the eval diagnostics. Tag-based ones read the row's
// pipe-delimited tags; flag-based ones read 0/1 penalty-flag columns
// (falling back to the same-named tag if the column is absent).
const EVAL_ATTRS = [
  { key: "ai_native", label: "AI-native", tag: "is_ai_native", flag: "is_ai_native" },
  {
    key: "digital_native",
    label: "Digital-native",
    tag: "digital_native",
    flag: "is_digital_native",
  },
  { key: "b2b", label: "B2B", tag: "b2b", flag: "is_b2b" },
  { key: "b2c", label: "B2C", tag: "b2c", flag: "is_b2c" },
  { key: "it_services", label: "IT services", tag: "it_services", flag: "is_it_services" },
  {
    key: "professional_services",
    label: "Professional services",
    tag: "professional_services",
    flag: "is_professional_services",
  },
];

function sizeBandKey(row) {
  const e = Number(row[SIZE_FILTER_COL]);
  if (!Number.isFinite(e)) return null;
  for (const b of SIZE_BANDS) if (b.test(e)) return b.key;
  return null;
}

function rowHasAttr(row, attr) {
  if (attr.flag && Number(row[attr.flag]) > 0) return true;
  return attr.tag ? parseRowTags(row).has(attr.tag) : false;
}

// Build a "% of each bucket" diagnostic table: one row per bucket,
// one column per category, cell = share of the bucket in that category.
function renderBucketComposition(tableId, buckets, columns, classify) {
  const thead = document.querySelector(`#${tableId} thead`);
  const tbody = document.querySelector(`#${tableId} tbody`);
  thead.innerHTML = "";
  tbody.innerHTML = "";

  const trh = el("tr");
  trh.appendChild(el("th", { class: "num" }, "Bucket"));
  trh.appendChild(el("th", { class: "num" }, "Accounts"));
  for (const c of columns) trh.appendChild(el("th", { class: "num" }, c.label));
  thead.appendChild(trh);

  for (const b of buckets) {
    const counts = {};
    for (const c of columns) counts[c.key] = 0;
    for (const x of b.slice) {
      const hits = classify(x.row); // array of column keys this row belongs to
      for (const k of hits) if (k in counts) counts[k] += 1;
    }
    const tr = el("tr");
    tr.appendChild(el("td", { class: "num" }, String(b.idx)));
    tr.appendChild(el("td", { class: "num" }, fmtInt(b.n)));
    for (const c of columns) {
      const pct = b.n > 0 ? (100 * counts[c.key]) / b.n : 0;
      const cell = el("td", { class: "num" }, pct.toFixed(0) + "%");
      // Subtle heat: stronger text as share rises.
      if (pct >= 50) cell.style.fontWeight = "600";
      if (pct === 0) cell.style.color = "#bbb";
      tr.appendChild(cell);
    }
    tbody.appendChild(tr);
  }
}

// --- rank-distribution summary statistics, per account category ------------

function _quantile(sorted, q) {
  if (!sorted.length) return 0;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

function _rankStats(ranks, total) {
  const n = ranks.length;
  const sorted = ranks.slice().sort((a, b) => a - b);
  const mean = ranks.reduce((s, r) => s + r, 0) / n;
  const variance = ranks.reduce((s, r) => s + (r - mean) ** 2, 0) / n;
  // Mean percentile from the top (100 = always ranked #1; higher is better).
  const denom = Math.max(1, total - 1);
  const meanPct =
    (ranks.reduce((s, r) => s + (1 - (r - 1) / denom), 0) / n) * 100;
  return {
    n,
    mean,
    median: _quantile(sorted, 0.5),
    std: Math.sqrt(variance),
    p25: _quantile(sorted, 0.25),
    p75: _quantile(sorted, 0.75),
    best: sorted[0],
    worst: sorted[sorted.length - 1],
    meanPct,
  };
}

// Where each account category lands in the GLOBAL ranking (all rows scored
// together). Lets you see at a glance that customers cluster near the top and
// whitespace/unallocated sit where they should. `scored` is sorted best-first.
function renderRankByCategory(scored) {
  const section = document.getElementById("eval-category-section");
  if (!section) return;
  if (!state.config.has_categories) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");
  const total = scored.length;
  const ranksByCat = {};
  scored.forEach((x, i) => {
    const c = rowCategory(x.row);
    (ranksByCat[c] ||= []).push(i + 1);
  });

  const thead = document.querySelector("#eval-category-table thead");
  const tbody = document.querySelector("#eval-category-table tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";
  const heads = ["Category", "N", "Median", "P25", "Best"];
  const trh = el("tr");
  trh.appendChild(el("th", {}, heads[0]));
  for (const h of heads.slice(1)) trh.appendChild(el("th", { class: "num" }, h));
  thead.appendChild(trh);

  for (const key of state.config.categories_present || []) {
    const ranks = ranksByCat[key];
    if (!ranks || !ranks.length) continue;
    const s = _rankStats(ranks, total);
    const tr = el("tr");
    tr.appendChild(
      el("td", {}, el("span", { class: "cat-pill cat-" + key }, CATEGORY_LABELS[key] || key)),
    );
    tr.appendChild(el("td", { class: "num" }, fmtInt(s.n)));
    tr.appendChild(el("td", { class: "num" }, fmtInt(Math.round(s.median))));
    tr.appendChild(el("td", { class: "num" }, fmtInt(Math.round(s.p25))));
    tr.appendChild(el("td", { class: "num" }, fmtInt(s.best)));
    tbody.appendChild(tr);
  }
}

function renderEval() {
  document.getElementById("results-table").classList.add("hidden");
  document.getElementById("eval-view").classList.remove("hidden");

  const scored = state.rows
    .map((r) => ({ row: r, score: rowScore(r), gold: isGold(r) ? 1 : 0 }))
    .sort((a, b) => b.score - a.score);
  const total = scored.length;
  const totalGold = scored.reduce((s, x) => s + x.gold, 0);
  const baseline = total > 0 ? totalGold / total : 0;

  const N_BUCKETS = Math.max(2, Math.min(100, state.evalBuckets || 10));
  const buckets = [];
  let cumGold = 0;
  for (let i = 0; i < N_BUCKETS; i++) {
    const start = Math.floor((i * total) / N_BUCKETS);
    const end = Math.floor(((i + 1) * total) / N_BUCKETS);
    const slice = scored.slice(start, end);
    const n = slice.length;
    const gold = slice.reduce((s, x) => s + x.gold, 0);
    cumGold += gold;
    const hitRate = n > 0 ? gold / n : 0;
    const cumRecall = totalGold > 0 ? cumGold / totalGold : 0;
    const lift = baseline > 0 ? hitRate / baseline : 0;
    buckets.push({ idx: i + 1, n, gold, hitRate, cumRecall, lift, start, end, slice });
  }

  const hasGold = totalGold > 0;
  const goldSection = document.getElementById("eval-gold-section");
  if (goldSection) goldSection.classList.toggle("hidden", !hasGold);

  const summary = document.getElementById("eval-summary");
  summary.textContent = hasGold
    ? `${total.toLocaleString()} scored · ${totalGold} gold (is_icp_gold=1) · ` +
      `baseline gold rate ${(baseline * 100).toFixed(2)}%`
    : `${total.toLocaleString()} scored · no gold set loaded — ` +
      `gold-lift table hidden; size & attribute diagnostics below apply to all rows`;

  const thead = document.querySelector("#eval-table thead");
  thead.innerHTML = "";
  const trh = el("tr");
  trh.appendChild(el("th", { class: "num" }, "Bucket"));
  trh.appendChild(el("th", { class: "num" }, "Rank range"));
  trh.appendChild(el("th", { class: "num" }, "Accounts"));
  trh.appendChild(el("th", { class: "num" }, "Gold"));
  trh.appendChild(el("th", { class: "num" }, "% gold"));
  trh.appendChild(el("th", { class: "num" }, "Cum. recall"));
  trh.appendChild(el("th", { class: "num" }, "Lift"));
  thead.appendChild(trh);

  const tbody = document.querySelector("#eval-table tbody");
  tbody.innerHTML = "";
  for (const b of buckets) {
    const tr = el("tr");
    tr.appendChild(el("td", { class: "num" }, String(b.idx)));
    tr.appendChild(el("td", { class: "num" }, `${b.start + 1}–${b.end}`));
    tr.appendChild(el("td", { class: "num" }, fmtInt(b.n)));
    tr.appendChild(el("td", { class: "num" }, fmtInt(b.gold)));
    tr.appendChild(el("td", { class: "num" }, (b.hitRate * 100).toFixed(2) + "%"));
    tr.appendChild(el("td", { class: "num" }, (b.cumRecall * 100).toFixed(1) + "%"));
    const liftCell = el("td", { class: "num" }, fmtFloat(b.lift, 2) + "×");
    if (b.lift >= 2) liftCell.style.color = "var(--accent, #16A34A)";
    if (b.lift < 1) liftCell.style.color = "#999";
    tr.appendChild(liftCell);
    tbody.appendChild(tr);
  }

  // Diagnostic 0: where each account category lands in the global ranking.
  renderRankByCategory(scored);

  // Diagnostic 1: employee-size mix by bucket.
  renderBucketComposition("eval-size-table", buckets, SIZE_BANDS, (row) => {
    const k = sizeBandKey(row);
    return k ? [k] : [];
  });

  // Diagnostic 2: attribute mix by bucket (a row can hit multiple).
  renderBucketComposition("eval-attr-table", buckets, EVAL_ATTRS, (row) =>
    EVAL_ATTRS.filter((a) => rowHasAttr(row, a)).map((a) => a.key),
  );

  document.getElementById("tab-description").textContent =
    TAB_DESCRIPTIONS[state.tab] || "";
  document.getElementById("row-summary").textContent =
    `${total.toLocaleString()} accounts · ${totalGold} gold · bucket evaluation`;
}

function renderTable() {
  const catFilter = document.getElementById("category-filter");
  if (state.tab === "eval") {
    document.getElementById("search-wrap").classList.add("hidden");
    document.getElementById("pagination").classList.add("hidden");
    // Category chips don't filter the eval diagnostics, so hide them here.
    if (catFilter) catFilter.classList.add("hidden");
    return renderEval();
  }
  document.getElementById("results-table").classList.remove("hidden");
  document.getElementById("search-wrap").classList.remove("hidden");
  document.getElementById("pagination").classList.remove("hidden");
  if (catFilter && state.config.has_categories) catFilter.classList.remove("hidden");
  const evalView = document.getElementById("eval-view");
  if (evalView) evalView.classList.add("hidden");

  const ranked = filteredRanked();
  const total = ranked.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (state.page >= totalPages) state.page = totalPages - 1;
  if (state.page < 0) state.page = 0;
  const start = state.page * PAGE_SIZE;
  const end = Math.min(start + PAGE_SIZE, total);
  const slice = ranked.slice(start, end);

  const thead = document.querySelector("#results-table thead");
  const tbody = document.querySelector("#results-table tbody");

  if (!thead.dataset.built) {
    const tr = el("tr");
    tr.appendChild(el("th", { class: "num" }, "Rank"));
    if (state.config.has_categories) tr.appendChild(el("th", {}, "Category"));
    for (const col of state.config.table_columns) tr.appendChild(el("th", {}, col));
    tr.appendChild(el("th", { class: "num" }, state.config.score_label || "Score"));
    thead.appendChild(tr);
    thead.dataset.built = "1";
  }

  tbody.innerHTML = "";
  slice.forEach(({ row, score, rank }) => {
    const tr = el("tr", {
      "data-id": String(row[state.config.id_column]),
      onclick: () => selectRow(row),
    });
    if (state.selectedId === String(row[state.config.id_column])) tr.classList.add("selected");
    tr.appendChild(el("td", { class: "num rank-cell" }, String(rank)));
    if (state.config.has_categories) {
      const cat = rowCategory(row);
      tr.appendChild(
        el(
          "td",
          {},
          el("span", { class: "cat-pill cat-" + (cat || "none") }, CATEGORY_LABELS[cat] || "—"),
        ),
      );
    }
    state.config.table_columns.forEach((col) => {
      let val = row[col];
      if ((col === "url" || col === "crm_url") && val) {
        // bare-domain → clickable external link in a new tab
        const href = /^https?:\/\//i.test(String(val)) ? String(val) : "https://" + String(val);
        const cell = el("td");
        cell.appendChild(el("a", {
          href, target: "_blank", rel: "noopener noreferrer", class: "row-url",
        }, String(val)));
        tr.appendChild(cell);
        return;
      }
      if (typeof val === "number") val = Number.isInteger(val) ? fmtInt(val) : fmtFloat(val);
      else if (val == null) val = "";
      const cell = el("td", {}, String(val));
      tr.appendChild(cell);
    });
    tr.appendChild(el("td", { class: "num score-cell" }, fmtFloat(score, 1)));
    tbody.appendChild(tr);
  });

  document.getElementById("tab-description").textContent =
    TAB_DESCRIPTIONS[state.tab] || "";

  const pageInfo = document.getElementById("page-info");
  if (total === 0) {
    pageInfo.textContent = "no results";
  } else {
    pageInfo.textContent =
      `${(start + 1).toLocaleString()}–${end.toLocaleString()} of ` +
      `${total.toLocaleString()} · page ${state.page + 1} of ${totalPages}`;
  }
  document.getElementById("page-prev").disabled = state.page <= 0;
  document.getElementById("page-next").disabled = state.page >= totalPages - 1;

  const crmCount = state.rows.filter((r) => r.in_crm).length;
  const sizeActive = state.sizeMin != null || state.sizeMax != null;
  const filterActive = state.search || sizeActive;
  const filteredNote = filterActive ? ` · filtered: ${total.toLocaleString()}` : "";
  const summary = state.config.has_crm
    ? `${state.rows.length.toLocaleString()} accounts · ${crmCount.toLocaleString()} in CRM${filteredNote}`
    : `${state.rows.length.toLocaleString()} accounts${filteredNote}`;
  document.getElementById("row-summary").textContent = summary;
}

// ---------- Render: per-row breakdown ----------

function findRow(id) {
  return state.rows.find((r) => String(r[state.config.id_column]) === String(id));
}

function selectRow(row) {
  state.selectedId = String(row[state.config.id_column]);
  document.querySelectorAll("#results-table tbody tr").forEach((tr) => {
    tr.classList.toggle("selected", tr.dataset.id === state.selectedId);
  });
  updateBreakdown();
}

function updateBreakdown() {
  const row = findRow(state.selectedId);
  if (!row) return;
  const panel = document.getElementById("breakdown-panel");
  panel.classList.remove("hidden");

  const nameCol = state.config.name_column;
  const slugCol = state.config.slug_column;
  document.getElementById("breakdown-name").textContent = row[nameCol] || "(unknown)";

  const score = rowScore(row);
  const metaBits = [];
  for (const col of state.config.table_columns) {
    if (col === nameCol) continue;
    const v = row[col];
    if (v != null && v !== "") metaBits.push(String(v));
  }
  metaBits.push(`Score ${fmtFloat(score, 1)}`);
  if (row.in_crm) metaBits.push("in CRM");

  const meta = document.getElementById("breakdown-meta");
  meta.textContent = metaBits.join(" · ");
  if (slugCol && row[slugCol]) {
    meta.appendChild(el("br"));
    meta.appendChild(
      el("a", {
        href: row.sumble_url || `${state.config.sumble_url_base}${row[slugCol]}`,
        target: "_blank",
        rel: "noopener",
      }, "Open in Sumble →"),
    );
  }

  const items = [];
  const sec = hasSections();
  const slug = row[state.config.slug_column];
  const sumbleBase = state.config.sumble_url_base || "https://sumble.com/orgs/";
  for (const [key, spec] of Object.entries(state.config.signals)) {
    const cat = spec.category || "first_party";
    const sectionPct = sec ? (state.sectionPct[sectionOf(cat)] || 0) : 100;
    const catPct = state.catPct[cat] || 0;
    const withinPct = (state.withinPct[cat] || {})[key] || 0;
    // section% × cat% × within% / 10000, scaled to 0-100 absolute.
    const weightAbs = (sectionPct / 100) * (catPct / 100) * withinPct;
    const raw = row[`raw_${key}`] || 0;
    const norm = row[`norm_${key}`] || 0;
    const contrib = weightAbs * norm; // already in 0-100 scaled
    // Per-signal deep link comes straight from the API ({column}_link in data).
    const href = row[`${spec.column}_link`] || null;
    items.push({
      label: spec.label,
      unit: spec.unit || "",
      raw,
      rawFmt: fmtRaw(raw, spec.fmt) + (spec.unit ? " " + spec.unit : ""),
      weight: weightAbs,
      contrib,
      href,
    });
  }
  items.sort((a, b) => b.contrib - a.contrib);
  const maxContrib = Math.max(...items.map((i) => i.contrib), 0.01);

  const tbody = document.querySelector("#breakdown-table tbody");
  tbody.innerHTML = "";
  for (const it of items) {
    const barWidth = Math.max(2, (it.contrib / maxContrib) * 80);
    const labelCell = it.href
      ? el(
          "td",
          {},
          el(
            "a",
            {
              href: it.href,
              target: "_blank",
              rel: "noopener",
              class: "breakdown-link",
            },
            it.label,
          ),
        )
      : el("td", {}, it.label);
    tbody.appendChild(
      el(
        "tr",
        {},
        labelCell,
        el("td", { class: "num" }, it.rawFmt),
        el("td", { class: "num" }, fmtFloat(it.weight, 1) + "%"),
        el(
          "td",
          { class: "num" },
          el(
            "div",
            { class: "contrib-bar-cell" },
            el("span", { class: "contrib-bar", style: `width:${barWidth}px;` }),
            fmtFloat(it.contrib, 2),
          ),
        ),
      ),
    );
  }
}

// ---------- Render: category filter chips ----------

// Multi-select category filter: each chip toggles its category in/out (filter
// any combination). A chip is "active" (highlighted) when shown; click to hide
// it. The "All" chip clears the filter (shows everything). Per-category counts
// are static (membership doesn't change with weights), so this renders once.
function renderCategoryChips() {
  const wrap = document.getElementById("category-filter");
  if (!wrap) return;
  if (!state.config.has_categories) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");
  wrap.innerHTML = "";
  const counts = {};
  for (const r of state.rows) {
    const c = rowCategory(r);
    counts[c] = (counts[c] || 0) + 1;
  }
  const present = state.config.categories_present || [];

  // "All" — active when nothing is hidden; click resets the filter.
  const allActive = state.hiddenCategories.size === 0;
  wrap.appendChild(
    el(
      "button",
      {
        type: "button",
        class: "cat-chip cat-chip-all" + (allActive ? " active" : ""),
        title: "Show every category",
        onclick: () => {
          state.hiddenCategories.clear();
          state.page = 0;
          renderCategoryChips();
          renderTable();
        },
      },
      `All (${state.rows.length.toLocaleString()})`,
    ),
  );

  for (const key of present) {
    const shown = !state.hiddenCategories.has(key);
    wrap.appendChild(
      el(
        "button",
        {
          type: "button",
          class: "cat-chip cat-" + key + (shown ? " active" : ""),
          title: shown ? "Click to hide this category" : "Click to show this category",
          onclick: () => {
            if (state.hiddenCategories.has(key)) state.hiddenCategories.delete(key);
            else state.hiddenCategories.add(key);
            state.page = 0;
            renderCategoryChips();
            renderTable();
          },
        },
        `${CATEGORY_LABELS[key] || key} (${(counts[key] || 0).toLocaleString()})`,
      ),
    );
  }
}

// ---------- Render: tabs ----------

function setTab(tab) {
  state.tab = tab;
  state.page = 0;
  document.querySelectorAll(".tabs .tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.tab === tab);
  });
  renderTable();
}

function setupTabs() {
  const hasCrm = !!state.config.has_crm;
  const crmCount = state.rows.filter((r) => r.in_crm).length;
  const whitespaceCount = state.rows.length - crmCount;
  const goldCount = state.rows.filter(isGold).length;

  const visible = {
    // One unified accounts sheet: CRM + whitespace rows live together,
    // separated by the Category column + filter chips (not by tabs). The legacy
    // second "whitespace" tab is retired (kept in markup but always hidden).
    accounts: true,
    whitespace: false,
    // Eval tab is ALWAYS shown: it carries gold-independent bucket
    // diagnostics (employee-size mix + attribute mix) in addition to the
    // gold-lift evaluation. The gold-lift table is skipped inside
    // renderEval when no gold set is loaded, but the tab itself never hides.
    eval: true,
  };

  document.querySelectorAll(".tabs .tab").forEach((t) => {
    if (!visible[t.dataset.tab]) {
      t.classList.add("hidden");
    } else {
      t.classList.remove("hidden");
      t.addEventListener("click", () => setTab(t.dataset.tab));
    }
  });
  if (!visible[state.tab]) {
    state.tab = Object.keys(visible).find((k) => visible[k]) || "accounts";
  }
  setTab(state.tab);
}

// ---------- Reset / init ----------

function resetDefaults() {
  state.sectionPct = {};
  state.catPct = {};
  state.withinPct = {};
  state.sectionPinned = {};
  state.catPinned = {};
  state.withinPinned = {};
  state.expanded = {};
  state.sectionExpanded = {};

  const grouped = signalsByCategory();
  const cats = state.config.categories || {};
  const sections = state.config.sections || {};
  // Match hasSections(): only treat as multi-section when ≥2 are present,
  // otherwise state.sectionPct stays empty and categories sum to 100 globally.
  const hasSecs = Object.keys(sections).length > 1;

  // Section weights from config.sections.X.default_pct; normalise to 100.
  if (hasSecs) {
    const rawSec = {};
    for (const [secKey, secSpec] of Object.entries(sections)) {
      rawSec[secKey] = Number(secSpec.default_pct || 0);
    }
    const secTotal = Object.values(rawSec).reduce((s, v) => s + v, 0);
    for (const [secKey, pct] of Object.entries(rawSec)) {
      state.sectionPct[secKey] = secTotal > 0
        ? Math.round((pct / secTotal) * 1000) / 10
        : Math.round((100 / Object.keys(sections).length) * 10) / 10;
    }
  }

  // Category weights. With sections: normalise to 100 WITHIN each section.
  // Without sections: normalise to 100 globally (legacy behaviour).
  // Empty categories (no signals) get 0; their share redistributes to siblings.
  const groupsBySection = hasSecs
    ? Object.fromEntries(
        Object.keys(sections).map((secKey) => [
          secKey,
          Object.entries(cats).filter(([, cs]) => cs.section === secKey),
        ]),
      )
    : { _all: Object.entries(cats) };

  for (const [, entries] of Object.entries(groupsBySection)) {
    const raw = {};
    let live = 0;
    for (const [catKey, catSpec] of entries) {
      const pct = Number(catSpec.default_pct || 0);
      raw[catKey] = (grouped[catKey] || []).length > 0 ? pct : 0;
      live += raw[catKey];
    }
    for (const [catKey, pct] of Object.entries(raw)) {
      state.catPct[catKey] = live > 0
        ? Math.round((pct / live) * 1000) / 10
        : 0;
    }
  }

  // Within-category defaults from signal.default_within; normalise to 100
  for (const [catKey, signals] of Object.entries(grouped)) {
    if (signals.length === 0) continue;
    state.withinPct[catKey] = {};
    const sum = signals.reduce((s, { spec }) => s + (Number(spec.default_within) || 0), 0);
    if (sum > 0) {
      for (const { key, spec } of signals) {
        const share = (Number(spec.default_within) || 0) / sum;
        state.withinPct[catKey][key] = Math.round(share * 1000) / 10;
      }
    } else {
      const each = 100 / signals.length;
      for (const { key } of signals) state.withinPct[catKey][key] = Math.round(each * 10) / 10;
    }
  }

  state.multPct = {};
  for (const m of state.config.multipliers || []) {
    state.multPct[m.column] = Number(m.default_pct ?? 0);
  }
  // Tag multipliers persist in config.tag_multipliers (mutated on Save).
  // Filter against availableTags so a tag that has left the universe
  // doesn't surface in the picker.
  const knownTags = new Set((state.availableTags || []).map((t) => t.tag));
  state.tagMult = (state.config.tag_multipliers || [])
    .filter((e) => e && e.tag && knownTags.has(e.tag))
    .map((e) => ({
      tag: String(e.tag),
      pct: Number(e.pct) || 0,
      direction: e.direction === "boost" ? "boost" : "penalty",
    }));

  renderCategories();
  renderMultipliers();
  renderTagMultipliers();
  renderTable();
  if (state.selectedId) updateBreakdown();
}

// ---------- Save / restore weights ----------

// ---------- Download: data.csv with current scores -----------------------

function downloadCsv() {
  // Download the SCORE SHEET (mirrors score.csv): rank (far left) -> identity ->
  // score -> one CONTRIBUTION column per signal (points, scaled so they SUM to
  // score) -> deep links (org page + one per signal) on the far right, from the
  // CURRENT sliders. Zero-contribution signals dropped. Sorted by rank.
  const rows = state.rows;
  if (!rows.length) return;

  const sec = hasSections();
  const signals = state.config.signals || {};
  const keys = Object.keys(signals);
  const r4 = (x) => Math.round((Number(x) || 0) * 1e4) / 1e4;
  const base = state.config.sumble_url_base || "https://sumble.com/orgs/";
  const slugCol = state.config.slug_column || "slug";

  // Per-signal contribution, scaled by the row's multiplier factor so the
  // contributions sum to the final score (which includes multipliers).
  const contrib = rows.map(() => ({}));
  const totals = {};
  const scores = rows.map((row, i) => {
    const raw = {};
    let b = 0;
    for (const key of keys) {
      const cat = signals[key].category || "first_party";
      const secPct = sec ? (state.sectionPct[sectionOf(cat)] || 0) / 100 : 1;
      const catPct = (state.catPct[cat] || 0) / 100;
      const wPct = ((state.withinPct[cat] || {})[key] || 0) / 100;
      const c = secPct * catPct * wPct * (row[`norm_${key}`] || 0) * 100;
      raw[key] = c;
      b += c;
    }
    const score = rowScore(row); // includes multipliers
    const factor = b > 0 ? score / b : 0;
    for (const key of keys) {
      const cc = raw[key] * factor;
      contrib[i][key] = cc;
      totals[key] = (totals[key] || 0) + cc;
    }
    return score;
  });

  // Keep signals with nonzero total contribution; most-impactful first.
  const live = keys
    .filter((k) => Math.abs(totals[k] || 0) > 1e-9)
    .sort((a, b) => totals[b] - totals[a]);
  const linkKeys = live.filter((k) => signals[k].sumble_link);

  // Identity columns present on the row (matches score_sheet.py).
  const IDENT = [
    "org_id", "name", "url", "account_category", "employee_count_int",
    "headquarters_country", "industry", "list_type", "crm_parent_name",
  ];
  const sample = rows[0];
  const ident = IDENT.filter((c) => c in sample);
  // Company Sumble page link sits in the identity block, after the company's
  // own url (or after name). Sentinel "sumble_url" -> org link at output time.
  const left = [];
  for (const c of ident) {
    left.push(c);
    if (c === "url") left.push("sumble_url");
  }
  if (!left.includes("sumble_url")) {
    const pos = left.includes("name") ? left.indexOf("name") + 1 : left.length;
    left.splice(pos, 0, "sumble_url");
  }

  // Contribution headers = signal label (dedupe collisions with [key]).
  const used = new Set();
  const labelFor = {};
  for (const k of live) {
    let lab = signals[k].label || k;
    if (used.has(lab)) lab = `${lab} [${k}]`;
    used.add(lab);
    labelFor[k] = lab;
  }
  const cols = [
    "rank", ...left, "score",
    ...live.map((k) => labelFor[k]),
    ...linkKeys.map((k) => `${labelFor[k]} link`),
  ];

  // CSV escape per RFC 4180.
  const esc = (v) => {
    if (v === null || v === undefined) return "";
    let s = String(v);
    if (s.includes('"')) s = s.replace(/"/g, '""');
    if (s.includes(",") || s.includes('"') || s.includes("\n") || s.includes("\r")) {
      s = `"${s}"`;
    }
    return s;
  };

  // Rank by score desc over all rows.
  const order = rows.map((_, i) => i).sort((a, b) => scores[b] - scores[a]);

  const lines = [cols.map(esc).join(",")];
  order.forEach((idx, r) => {
    const row = rows[idx];
    const slug = row[slugCol] || "";
    const orgUrl = row.sumble_url || (slug ? `${base}${slug}` : "");
    const leftVals = left.map((c) => esc(c === "sumble_url" ? orgUrl : row[c]));
    const out = [esc(r + 1), ...leftVals, esc(r4(scores[idx]))];
    for (const k of live) out.push(esc(r4(contrib[idx][k])));
    // Per-signal links come from the API ({column}_link), not a hand-built URL.
    for (const k of linkKeys) out.push(esc(row[`${signals[k].column}_link`] || ""));
    lines.push(out.join(","));
  });

  const customer = (state.config.customer_name || "accounts")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_");
  const stamp = new Date().toISOString().slice(0, 10);
  const fname = `${customer}_score_sheet_${stamp}.csv`;

  const blob = new Blob([lines.join("\n") + "\n"], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fname;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke after a short tick so the browser has time to start the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function buildWeightsPayload() {
  // Flatten within-category weights to a single signal_key -> % map.
  const signals = {};
  for (const within of Object.values(state.withinPct)) {
    for (const [sig, pct] of Object.entries(within)) signals[sig] = pct;
  }
  return {
    sections: { ...state.sectionPct },
    categories: { ...state.catPct },
    signals,
    multipliers: { ...state.multPct },
    tag_multipliers: state.tagMult.map((e) => ({
      tag: e.tag,
      pct: Number(e.pct) || 0,
      direction: e.direction === "boost" ? "boost" : "penalty",
    })),
  };
}

async function saveWeights() {
  const status = document.getElementById("save-status");
  const payload = buildWeightsPayload();
  if (status) status.textContent = "Saving…";
  try {
    const resp = await fetch("/api/save-weights", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const result = await resp.json();
    state.config.saved_at = result.saved_at;
    if (status) status.textContent = "Saved";
  } catch (err) {
    if (status) status.textContent = "Save failed: " + err.message;
  }
}

// Manual-save model: mutations no longer auto-save. scheduleAutoSave() is kept
// as the dirty-marker (so every existing mutation call site still flips the
// status), but it only marks "Unsaved changes" — nothing is written until the
// user clicks Save, which calls saveAll().
function scheduleAutoSave() {
  state.dirty = true;
  const status = document.getElementById("save-status");
  if (status) status.textContent = "Unsaved changes";
}

// Retained for callers that used to flush a pending auto-save; saving is manual
// now, so there is nothing to flush.
async function flushAutoSave() {}

// One score+rank per UNIQUE Sumble org (duplicate org_ids collapse, highest
// score wins) — mirrors the app's dedup so the saved data.csv matches the view.
function computeScoredRows() {
  const scored = state.rows
    .map((r) => ({ id: r[state.config.id_column], score: rowScore(r) }))
    .sort((a, b) => b.score - a.score);
  const seen = new Set();
  const out = [];
  for (const s of scored) {
    const id = String(s.id);
    if (seen.has(id)) continue;
    seen.add(id);
    out.push({ id, score: Math.round(s.score * 100) / 100, rank: out.length + 1 });
  }
  return out;
}

// Explicit Save: persist the weights (account-scoring-weights.json) AND data.csv
// (with score + rank columns) in one server write.
async function saveAll() {
  const status = document.getElementById("save-status");
  const payload = buildWeightsPayload();
  payload.scores = computeScoredRows();
  if (status) status.textContent = "Saving…";
  try {
    const resp = await fetch("/api/save-weights", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const result = await resp.json();
    state.config.saved_at = result.saved_at;
    state.dirty = false;
    const extra =
      result.rows_scored != null ? ` · ${result.rows_scored} rows → data.csv` : "";
    if (status) status.textContent = "Saved" + extra;
  } catch (err) {
    if (status) status.textContent = "Save failed: " + err.message;
  }
}

function downloadConfig() {
  // Build a stand-alone scoring spec by overlaying the current slider
  // values onto a deep clone of state.config. Mirrors what the server
  // writes on /api/save-weights so a coding agent can re-implement the
  // score from this single file.
  const spec = JSON.parse(JSON.stringify(state.config));
  // Strip client-only fields that aren't part of the persisted spec.
  delete spec.available_tags;
  delete spec.has_crm;

  for (const [k, v] of Object.entries(spec.sections || {})) {
    if (state.sectionPct[k] !== undefined) {
      v.default_pct = Math.round(Number(state.sectionPct[k]) * 100) / 100;
    }
  }
  for (const [k, v] of Object.entries(spec.categories || {})) {
    if (state.catPct[k] !== undefined) {
      v.default_pct = Math.round(Number(state.catPct[k]) * 100) / 100;
    }
  }
  // signal default_within lives in state.withinPct[catKey][sigKey].
  for (const within of Object.values(state.withinPct)) {
    for (const [sig, pct] of Object.entries(within)) {
      if (spec.signals && spec.signals[sig]) {
        spec.signals[sig].default_within = Math.round(Number(pct) * 100) / 100;
      }
    }
  }
  if (Array.isArray(spec.multipliers)) {
    for (const m of spec.multipliers) {
      if (state.multPct[m.column] !== undefined) {
        m.default_pct = Math.round(Number(state.multPct[m.column]) * 100) / 100;
      }
    }
  }
  spec.tag_multipliers = state.tagMult.map((e) => ({
    tag: e.tag,
    pct: Math.round(Number(e.pct || 0) * 100) / 100,
    direction: e.direction === "boost" ? "boost" : "penalty",
  }));
  spec.saved_at = new Date().toISOString().replace(/\.\d+Z$/, "+00:00");

  const customer = (spec.customer_name || "scoring")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_");
  const stamp = new Date().toISOString().slice(0, 10);
  const fname = `${customer}_scoring_config_${stamp}.json`;

  const blob = new Blob([JSON.stringify(spec, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fname;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function init() {
  let data;
  try {
    const resp = await fetch("/api/data");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (err) {
    document.getElementById("row-summary").textContent = "Failed to load data: " + err.message;
    return;
  }
  state.config = data.config;
  state.rows = data.rows;
  state.availableTags = data.config.available_tags || [];

  document.getElementById("customer-name").textContent =
    state.config.customer_name || "Account scoring";
  document.title = state.config.customer_name
    ? `${state.config.customer_name} · account scoring`
    : "Account scoring";

  if (state.config.branding) {
    const root = document.documentElement.style;
    if (state.config.branding.primary_color)
      root.setProperty("--primary", state.config.branding.primary_color);
    if (state.config.branding.accent_color)
      root.setProperty("--accent", state.config.branding.accent_color);
    if (state.config.branding.logo) {
      // index.html ships the Sumble brand-icon + wordmark; per-customer
      // branding.logo (if set) replaces the icon, leaving the wordmark.
      const icon = document.querySelector(".brand-icon");
      if (icon) icon.src = "/" + state.config.branding.logo;
    }
  }

  if (state.config.sections && Object.keys(state.config.sections).length) {
    const sub = document.querySelector(".panel-sub");
    if (sub) {
      sub.textContent =
        "Sections sum to 100%. Inside each, categories sum to 100% of " +
        "that section; signals sum to 100% of their category.";
    }
  }

  resetDefaults();
  state.dirty = false;
  const status = document.getElementById("save-status");
  if (status) status.textContent = state.config.saved_at ? "Saved" : "";
  setupTabs();
  renderCategoryChips();

  // Wire up the tag-multiplier picker. The combobox is a native datalist
  // input; on Add we look the typed value up against availableTags
  // (case-insensitive prefix/exact), append to state.tagMult, and re-render.
  const tagInput = document.getElementById("tag-mult-input");
  const tagAddBtn = document.getElementById("tag-mult-add");
  if (tagInput && tagAddBtn) {
    const addCurrent = () => {
      const value = (tagInput.value || "").trim();
      if (!value) return;
      const taken = new Set(state.tagMult.map((m) => m.tag));
      if (taken.has(value)) return;
      // Validate against availableTags so typos don't slip in. Allow exact
      // match OR a single-prefix match if the user only typed a few letters.
      const exact = state.availableTags.find((t) => t.tag === value);
      let resolved = null;
      if (exact) resolved = exact.tag;
      else {
        const lower = value.toLowerCase();
        const prefixMatches = state.availableTags.filter((t) =>
          t.tag.toLowerCase().startsWith(lower),
        );
        if (prefixMatches.length === 1) resolved = prefixMatches[0].tag;
      }
      if (!resolved) return;
      state.tagMult.push({ tag: resolved, pct: 25, direction: "penalty" });
      tagInput.value = "";
      renderTagMultipliers();
      renderTable();
      if (state.selectedId) updateBreakdown();
      scheduleAutoSave();
    };
    tagAddBtn.addEventListener("click", addCurrent);
    tagInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addCurrent();
      }
    });
  }

  document.getElementById("reset-defaults").addEventListener("click", () => {
    resetDefaults();
    scheduleAutoSave();
  });
  const saveBtn = document.getElementById("save-btn");
  if (saveBtn) saveBtn.addEventListener("click", saveAll);
  // Manual-save: warn before leaving with unsaved slider changes.
  window.addEventListener("beforeunload", (e) => {
    if (state.dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  const downloadBtn = document.getElementById("download-csv");
  if (downloadBtn) downloadBtn.addEventListener("click", downloadCsv);
  const downloadCfgBtn = document.getElementById("download-config");
  if (downloadCfgBtn) {
    downloadCfgBtn.addEventListener("click", async () => {
      // Make sure any pending debounced save has flushed first so the
      // exported file on disk matches what we just downloaded.
      await flushAutoSave();
      downloadConfig();
    });
  }

  const searchInput = document.getElementById("search-input");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      state.search = e.target.value;
      state.page = 0;
      renderTable();
    });
    // "/" focuses the search box, unless the user is already typing in a field.
    document.addEventListener("keydown", (e) => {
      if (e.key !== "/") return;
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) {
        return;
      }
      const wrap = document.getElementById("search-wrap");
      if (wrap && wrap.classList.contains("hidden")) return;
      e.preventDefault();
      searchInput.focus();
      searchInput.select();
    });
  }

  // Employee-size filter (min/max range, hides rows; scores stay
  // normalized across the full universe). Hidden if the data lacks
  // an employee_count_int column.
  const sizeFilter = document.getElementById("size-filter");
  const sizeMin = document.getElementById("size-min");
  const sizeMax = document.getElementById("size-max");
  const sizeClear = document.getElementById("size-clear");
  const hasSizeCol = state.rows.some((r) => r[SIZE_FILTER_COL] != null);
  if (sizeFilter && !hasSizeCol) sizeFilter.classList.add("hidden");
  const applySize = () => {
    state.page = 0;
    renderTable();
  };
  if (sizeMin) {
    sizeMin.addEventListener("input", (e) => {
      const v = e.target.value.trim();
      state.sizeMin = v === "" ? null : Number(v);
      if (state.sizeMin != null && !Number.isFinite(state.sizeMin)) {
        state.sizeMin = null;
      }
      applySize();
    });
  }
  if (sizeMax) {
    sizeMax.addEventListener("input", (e) => {
      const v = e.target.value.trim();
      state.sizeMax = v === "" ? null : Number(v);
      if (state.sizeMax != null && !Number.isFinite(state.sizeMax)) {
        state.sizeMax = null;
      }
      applySize();
    });
  }
  if (sizeClear) {
    sizeClear.addEventListener("click", () => {
      state.sizeMin = null;
      state.sizeMax = null;
      if (sizeMin) sizeMin.value = "";
      if (sizeMax) sizeMax.value = "";
      applySize();
    });
  }
  document.getElementById("page-prev").addEventListener("click", () => {
    if (state.page > 0) {
      state.page--;
      renderTable();
    }
  });
  document.getElementById("page-next").addEventListener("click", () => {
    state.page++;
    renderTable();
  });

  const bucketSlider = document.getElementById("eval-buckets-slider");
  const bucketValue = document.getElementById("eval-buckets-value");
  if (bucketSlider && bucketValue) {
    bucketSlider.addEventListener("input", (e) => {
      const n = Number(e.target.value);
      state.evalBuckets = n;
      bucketValue.textContent = String(n);
      if (state.tab === "eval") renderEval();
    });
  }
  document.getElementById("breakdown-close").addEventListener("click", () => {
    document.getElementById("breakdown-panel").classList.add("hidden");
    state.selectedId = null;
    document.querySelectorAll("#results-table tbody tr.selected").forEach((tr) =>
      tr.classList.remove("selected"),
    );
  });
}

init();
