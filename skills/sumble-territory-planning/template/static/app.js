/* Sumble territory planning — client.
 *
 * The server hands over the plan + the sheet once; everything after that is
 * computed here. Balance maths is deliberately client-side: accepting a move
 * has to move the bars in the same frame, or a reviewer can't tell whether the
 * change they just approved actually helped.
 *
 * The balance formula mirrors territory_lib.book_stats() exactly — same
 * included categories, same per-segment p75, same population CV. If you change
 * one, change the other.
 */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  plan: null,
  rows: [],
  reps: [],
  segments: [],
  segLabel: {},
  repByName: {},
  tab: "overview",
  filters: new Set(),
  repFilter: "",
  segmentFilter: "",
  search: "",
  page: 0,
  pageSize: 100,
  sort: { key: "score", dir: -1 },
  strongCutoff: 500,   // an account is "strong" if it's in the top N by ICP score
  strongSet: new Set(), // org_ids of the current top-N (rebuilt each render)
  scoreRank: {},        // org_id -> global rank by ICP score (1 = best)
  overviewSegment: "all", // Overview segment filter: "all" = both, else a key
  overviewSort: {         // per-matrix sort; default the summary metric, desc
    strength: { key: "summary", dir: -1 },
    coverage: { key: "summary", dir: -1 },
  },
};

const PAGE_DESCRIPTIONS = {
  overview: "Each rep's book strength by depth — how strong their top accounts are, and how much of each band they're working — plus what needs attention. Click a rep to open their accounts.",
  accounts: "Every account. Assign any account to anyone with the dropdown in the last column — the Overview books update as you go. Filter by a flag, a rep, a segment, or the balancer's suggested moves (accept/reject inline). Click a row for its activity detail.",
  export: "Download the approved changes for your CRM, or the full sheet with every flag and activity count.",
};

// Flags read the EFFECTIVE owner (current + your allocations), so they update
// the moment you assign an account on the Accounts tab.
const FLAGS = [
  { key: "not_worked",       label: "Not being worked",  test: (r) => effectiveOwner(r) && !num(r.worked), cls: "flag-warn",
    help: "Owned, but the owner has had no meeting, call, or outbound email with them in the window." },
  { key: "strong_idle",      label: "Strong but idle",   test: (r) => isStrong(r) && effectiveOwner(r) && !num(r.worked), cls: "flag-bad",
    help: "Among the strongest accounts by ICP score (see the cutoff on the left), owned, and nobody is working it. The most expensive kind of neglect." },
  { key: "strong_unallocated", label: "Strong but unallocated", test: (r) => isStrong(r) && !effectiveOwner(r) && !isWhitespace(r), cls: "flag-bad",
    help: "Among the strongest accounts by ICP score (see the cutoff on the left), and no active rep owns it. Allocating it clears this flag." },
  { key: "segment_misfit",   label: "Wrong segment",     test: (r) => { const o = effectiveOwner(r); return !!o && !!repSegment(o) && !!r.account_segment && repSegment(o) !== r.account_segment; }, cls: "flag-warn",
    help: "The account's size puts it in one segment; its owner sells another." },
  { key: "double_allocated", label: "Double-allocated",  test: (r) => num(r.double_allocated), cls: "flag-bad",
    help: "Two or more reps own CRM records that resolve to the SAME company. Resolve these before rebalancing." },
];

const REASON_LABELS = {
  misfit: "Wrong segment",
  assign_unallocated: "Unallocated — needs an owner",
  assign_whitespace: "Whitespace — new account",
  rebalance: "Rebalance",
  manual: "Manual override",
};

// ---------------------------------------------------------------- helpers

function num(v) { const n = Number(v); return Number.isFinite(n) ? n : 0; }
function isWhitespace(r) {
  return r.account_category === "whitespace" || r.account_category === "whitespace_subsidiary";
}

/** Rank all real (non-whitespace) accounts by ICP score, 1 = best, and mark the
 *  top `state.strongCutoff` as "strong". Rebuilt each render so the sidebar
 *  cutoff takes effect live. */
function computeStrongSet() {
  const ranked = state.rows
    .filter((r) => !isWhitespace(r))
    .sort((a, b) => num(b.score) - num(a.score));
  state.scoreRank = {};
  ranked.forEach((r, i) => { state.scoreRank[String(r.org_id)] = i + 1; });
  state.strongSet = new Set(
    ranked.slice(0, state.strongCutoff).map((r) => String(r.org_id)));
}
function isStrong(r) { return state.strongSet.has(String(r.org_id)); }
function accountRank(r) { return state.scoreRank[String(r.org_id)] || null; }
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmt(n, digits = 0) {
  return Number(n || 0).toLocaleString(undefined, {
    minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function isApproved(r) {
  return (r.proposal_status === "accepted" || r.proposal_status === "manual") && r.proposed_owner;
}
/** Who owns the account once the user's accepted / manual allocations are
 *  applied — the PLANNED owner. Everything on the Overview groups by this, so an
 *  allocation on the Accounts tab flows straight through to the book heatmaps.
 *  Mirrors territory_lib.effective_owner(). */
function effectiveOwner(r) {
  return (r.proposal_status === "accepted" || r.proposal_status === "manual")
    ? (r.proposed_owner || r.owner || "") : (r.owner || "");
}
function repSegment(name) { return (state.repByName[name] || {}).segment || ""; }
// ------------------------------------------------------------- calibration

/** The two knobs that define a territory plan: where the line between segments
 *  sits on the boundary metric, and how many accounts a rep in each segment is
 *  meant to carry. Both are judgement calls, so the panel previews their effect
 *  client-side on every keystroke and only commits when you click Apply. */

function boundaryThresholds() {
  const out = {};
  for (const t of state.plan.boundary?.thresholds || []) out[t.segment] = t.min;
  return out;
}

/** Which segment a size falls in, mirroring territory_lib.segment_for_size:
 *  thresholds are inclusive minimums, highest first; anything below them all
 *  lands in the smallest segment. */
function segmentForSize(size, thresholds) {
  const ordered = [...state.segments].sort((a, b) => b.order - a.order);
  for (const seg of ordered) {
    const min = thresholds[seg.key];
    if (min !== undefined && min !== null && size >= num(min)) return seg.key;
  }
  const smallest = [...state.segments].sort((a, b) => a.order - b.order)[0];
  return smallest ? smallest.key : "";
}

/** Read whatever is currently typed into the panel. */
function calibrateFormValues() {
  const thresholds = {}, capacities = {};
  for (const seg of state.segments) {
    const t = $(`#cal-threshold-${seg.key}`);
    const c = $(`#cal-capacity-${seg.key}`);
    if (t) thresholds[seg.key] = t.value.trim();
    if (c) capacities[seg.key] = c.value.trim();
  }
  return { thresholds, capacities };
}

function renderCalibrate() {
  const saved = boundaryThresholds();
  const metric = state.plan.boundary?.label || state.plan.boundary?.metric || "size";
  const ordered = [...state.segments].sort((a, b) => a.order - b.order);

  const smallest = ordered[0];

  // Only rebuild the inputs when the segment set changes, so typing is not
  // interrupted by a re-render.
  if ($("#calibrate-controls").dataset.built !== "1") {
    // Box 1 — the segment cutoff. One threshold per segment ABOVE the smallest;
    // the smallest segment has no line of its own, it is "everything below".
    const cutoffRows = ordered
      .filter((seg) => seg.key !== smallest.key)
      .map((seg) => {
        const t = saved[seg.key];
        return `<label class="cal-field">
          <span>${esc(seg.label)} at or above</span>
          <input type="number" min="0" step="1" id="cal-threshold-${esc(seg.key)}"
                 class="terr-input" value="${t ?? ""}" />
        </label>`;
      }).join("");

    // Box 2 — target accounts per rep, one per segment.
    const capRows = ordered.map((seg) => `<label class="cal-field">
        <span>${esc(seg.label)}</span>
        <input type="number" min="0" step="1" id="cal-capacity-${esc(seg.key)}"
               class="terr-input" value="${seg.default_capacity ?? ""}"
               placeholder="unlimited" />
      </label>`).join("");

    $("#calibrate-controls").innerHTML = `
      <div class="cal-box">
        <h4 class="cal-box-title">Segment cutoff</h4>
        <p class="cal-box-sub">Where the line falls on ${esc(metric)}.
          ${esc(smallest.label)} is everything below it.</p>
        ${cutoffRows}
        <p class="cal-preview" id="cal-preview-counts"></p>
      </div>
      <div class="cal-box">
        <h4 class="cal-box-title">Target accounts per rep</h4>
        <p class="cal-box-sub">Cap per rep, by segment. Blank means unlimited.</p>
        ${capRows}
        <p class="cal-preview" id="cal-preview-seats"></p>
      </div>`;
    $("#calibrate-controls").dataset.built = "1";
    $$("#calibrate-controls input").forEach((el) => {
      el.oninput = renderCalibratePreview;   // live preview as you type
      el.onchange = applyCalibration;         // commit (blur / Enter) re-runs
    });
  }
  renderCalibratePreview();
}

/** Live, client-side: how many accounts land in each segment at the typed
 *  threshold, and how many the typed capacity can actually hold. The preview is
 *  instant; committing the field (blur / Enter) re-runs the balancer. */
function renderCalibratePreview() {
  const { thresholds } = calibrateFormValues();
  const parsed = {};
  for (const [k, v] of Object.entries(thresholds)) {
    if (String(v).trim() !== "") parsed[k] = num(v);
  }
  const counts = {}, owned = {};
  for (const seg of state.segments) { counts[seg.key] = 0; owned[seg.key] = 0; }
  for (const r of state.rows) {
    const key = segmentForSize(num(r.size_metric), parsed);
    if (counts[key] === undefined) continue;
    counts[key] += 1;
    if (r.owner) owned[key] += 1;
  }
  const repsPerSeg = {};
  for (const seg of state.segments) {
    repsPerSeg[seg.key] = state.reps.filter(
      (rep) => rep.segment === seg.key && rep.in_balance !== false).length;
  }
  const ordered = [...state.segments].sort((a, b) => a.order - b.order);

  // Cutoff box: how the line splits the book right now.
  const countsEl = $("#cal-preview-counts");
  if (countsEl) {
    countsEl.innerHTML = ordered.map((seg) => {
      const unowned = counts[seg.key] - owned[seg.key];
      return `<strong>${esc(seg.label)}</strong> ${fmt(counts[seg.key])} accounts ` +
        `(${fmt(unowned)} unowned)`;
    }).join("<br />");
  }

  // Capacity box: do the seats cover the demand?
  const seatsEl = $("#cal-preview-seats");
  if (seatsEl) {
    seatsEl.innerHTML = ordered.map((seg) => {
      const capEl = $(`#cal-capacity-${seg.key}`);
      const cap = capEl && capEl.value.trim() !== "" ? num(capEl.value) : null;
      const n = repsPerSeg[seg.key];
      if (cap === null) {
        return `<strong>${esc(seg.label)}</strong> ${fmt(n)} rep${n === 1 ? "" : "s"}, no cap`;
      }
      const seats = cap * n;
      let note = `<strong>${esc(seg.label)}</strong> ${fmt(n)} × ${fmt(cap)} = ${fmt(seats)} seats`;
      if (seats < counts[seg.key]) {
        note += ` — <span class="cal-warn">${fmt(counts[seg.key] - seats)} cannot be held</span>`;
      }
      return note;
    }).join("<br />");
  }
}

let calibrating = false;
async function applyCalibration() {
  if (calibrating) return;               // a commit is already in flight
  const { thresholds, capacities } = calibrateFormValues();
  calibrating = true;
  $("#calibrate-status").textContent = "Re-running the balancer…";
  try {
    const res = await fetch("/api/calibrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // Calibration always preserves the user's accept / reject / manual
      // decisions; it only re-derives the pipeline's own suggestions.
      body: JSON.stringify({ thresholds, capacities, reset: false }),
    });
    if (!res.ok) {
      $("#calibrate-status").textContent =
        `Could not apply: ${res.status} ${await res.text()}`;
      return;
    }
    const out = await res.json();
    state.plan = out.plan;
    state.rows = out.rows;
    state.segments = [...out.plan.segments].sort((a, b) => a.order - b.order);
    state.segLabel = Object.fromEntries(state.segments.map((s) => [s.key, s.label]));
    state.reps = out.plan.reps.filter((r) => r.is_rep);
    state.repByName = Object.fromEntries(state.reps.map((r) => [r.name, r]));
    const c = out.report.counts;
    const unrouted = Object.entries(out.report.unrouted || {})
      .map(([k, v]) => `${state.segLabel[k] || k} ${fmt(v)}`).join(", ");
    $("#calibrate-status").innerHTML =
      `Applied. <strong>${fmt(out.report.total)}</strong> proposals — ` +
      `${fmt(c.misfit)} wrong-segment, ${fmt(c.assign_unallocated)} unowned, ` +
      `${fmt(c.rebalance)} rebalance.` +
      (unrouted ? ` <strong>Left unowned at this capacity:</strong> ${unrouted}.` : "") +
      (out.report.frozen ? ` ${fmt(out.report.frozen)} of your own decisions kept.` : "");
    $("#calibrate-controls").dataset.built = "";
    render();
  } finally {
    calibrating = false;
  }
}

// ---------------------------------------------------------------- rendering

function flagPills(r) {
  return FLAGS.filter((f) => f.test(r))
    .map((f) => `<span class="flag-pill ${f.cls}">${esc(f.label)}</span>`).join(" ");
}

/** The Overview is the book-strength matrices per segment (rank + coverage,
 *  coloured by column) followed by the "needs attention" flag cards. */
function renderOverview() {
  const { ranks, sizes } = segmentRanks();
  const parts = [
    `<p class="eval-diag-sub" id="matrices-note">` +
    "<strong>Capture</strong> and <strong>Activation</strong> summarise each book — " +
    "hover their headers for what they mean. The depth cells are the <strong>average " +
    "rank</strong> of the rep's strongest N accounts (1 = best); shading runs green " +
    "(strong) → pale (weak) down each whole column. <strong>Click any header to sort</strong> " +
    "(defaults to Capture / Activation, high first); click a rep to open their accounts.</p>",
  ];

  // Tier weighting for the Capture / Activation summary metrics: an account's
  // weight is by its RANK tier within its segment — top decile ×`decileW`, top
  // quartile ×1, everything else 0 — times its ICP score. Decile ⊂ quartile.
  const decileW = num(state.plan.tier_decile_weight) || 2;
  const tierWeight = (segKey, orgId) => {
    const n = sizes[segKey] || 0;
    const rank = ranks[orgId];
    if (!rank || !n) return 0;
    if (rank <= Math.ceil(0.10 * n)) return decileW;   // top decile
    if (rank <= Math.ceil(0.25 * n)) return 1;          // top quartile (not decile)
    return 0;
  };
  // Each segment's total top-tier value — the denominator for Capture.
  const segTierTotal = {};
  for (const r of state.rows) {
    if (isWhitespace(r)) continue;
    const w = tierWeight(r.account_segment, r.org_id);
    if (w) segTierTotal[r.account_segment] = (segTierTotal[r.account_segment] || 0) + num(r.score) * w;
  }
  const heldTierValue = (book, segKey) =>
    book.reduce((s, r) => s + num(r.score) * tierWeight(segKey, r.org_id), 0);

  // Capture: rep's held top-tier value ÷ the segment's total (a share).
  const captureCol = {
    label: "Capture", better: "high", fmt: (v) => `${fmt(v, 0)}%`,
    help: "Share of the segment's most valuable accounts this rep owns — the top " +
      "10% by ICP score count double, the top 25% single, the rest zero. High = they " +
      "hold a lot of the best value; low = they hold little of it.\n\n" +
      "Balance guide: reps in a segment should have similar Capture — roughly within " +
      "1.5× of each other. One rep at 3–4× another's share is hoarding the best value; " +
      "a rep near 0% is under-supplied (or ramping).",
    value: (book, grp) => {
      const tot = segTierTotal[grp.key] || 0;
      return tot > 0 ? (100 * heldTierValue(book, grp.key)) / tot : null;
    },
  };
  // Activation: of the top-tier value the rep holds, the share being worked.
  const activationCol = {
    label: "Activation", better: "high", fmt: (v) => `${fmt(v, 0)}%`,
    help: "Of the valuable accounts this rep owns (same top-decile-doubled weighting), " +
      "the share they've actually worked in the activity window. 0% = sitting on strong " +
      "accounts without touching them. Independent of book size.",
    value: (book, grp) => {
      const held = heldTierValue(book, grp.key);
      if (held <= 0) return null; // holds no top-tier value — nothing to activate
      const worked = book.reduce((s, r) =>
        s + (num(r.worked) ? num(r.score) * tierWeight(grp.key, r.org_id) : 0), 0);
      return (100 * worked) / held;
    },
  };

  // Only segments that actually have reps; pick a valid selection ("all" shows
  // every segment, the default).
  const segs = state.segments.filter((seg) =>
    state.reps.some((r) => r.segment === seg.key));
  let selKey = state.overviewSegment;
  if (selKey !== "all" && !segs.some((s) => s.key === selKey)) selKey = "all";
  state.overviewSegment = selKey;

  // Segment filter: All (both) + one pill per segment.
  if (segs.length > 1) {
    const pill = (key, label, sub) =>
      `<button class="seg-pill ${key === selKey ? "active" : ""}" data-seg="${esc(key)}">` +
      `${esc(label)}${sub ? `<span class="seg-pill-sub">${sub}</span>` : ""}</button>`;
    parts.push(
      `<div class="seg-filter" role="tablist">` +
      pill("all", "All segments", "") +
      segs.map((s) => pill(s.key, s.label, fmt(sizes[s.key] || 0))).join("") +
      `</div>`);
  }

  // Build one row-group per shown segment — "All" includes every segment, a
  // filter narrows to one. Either way there are exactly TWO tables below.
  const shown = selKey === "all" ? segs : segs.filter((s) => s.key === selKey);
  const groups = shown.map((seg) => ({
    key: seg.key,
    label: seg.label,
    order: seg.order ?? 0,
    size: sizes[seg.key] || 0,
    books: state.reps.filter((r) => r.segment === seg.key).map((rep) => ({
      rep,
      book: inSegmentBook(rep.name, seg.key),
    })).sort((a, b) => {
      // Strongest territory first, by whichever top band both actually fill.
      const ka = avgRankOf(a.book.slice(0, 25), ranks) ?? avgRankOf(a.book, ranks) ?? Infinity;
      const kb = avgRankOf(b.book.slice(0, 25), ranks) ?? avgRankOf(b.book, ranks) ?? Infinity;
      return ka - kb;
    }),
  }));

  if (groups.length) {
    const ctx = groups.length === 1
      ? `${esc(groups[0].label)} · ranked within ${fmt(groups[0].size)} accounts`
      : groups.map((g) => `${esc(g.label)} within ${fmt(g.size)}`).join(" · ");
    const windowDays = fmt(state.plan.activity?.window_days || 90);
    parts.push(
      `<h3 class="terr-h3">Book strength <span class="terr-sub">${ctx}</span></h3>`);
    parts.push(renderMatrix(
      groups, (slice) => avgRankOf(slice, ranks), "low", (v) => fmt(v, 0), captureCol,
      { matrixId: "strength", sort: state.overviewSort.strength }));
    parts.push(
      `<h3 class="terr-h3">Coverage <span class="terr-sub">` +
      `share of each band worked in the last ${windowDays} days</span></h3>`);
    parts.push(renderMatrix(
      groups, (slice) => workedPctOf(slice), "high", (v) => `${fmt(v, 0)}%`, activationCol,
      { matrixId: "coverage", sort: state.overviewSort.coverage }));
  }
  $("#overview-segments").innerHTML = parts.join("");
  $$("#overview-segments .seg-pill").forEach((btn) => {
    btn.onclick = () => { state.overviewSegment = btn.dataset.seg; renderOverview(); };
  });
  $$("#overview-segments th.sortable").forEach((th) => {
    th.onclick = () => {
      const m = th.dataset.matrix, k = th.dataset.key;
      const cur = state.overviewSort[m];
      if (cur.key === k) cur.dir = -cur.dir;   // toggle direction
      else state.overviewSort[m] = { key: k, dir: (k === "rep" || k === "seg") ? 1 : -1 };
      renderOverview();
    };
  });
  $$("#overview-segments tr.rep-row").forEach((tr) => {
    tr.onclick = () => {
      state.repFilter = tr.dataset.rep; state.filters = new Set();
      state.segmentFilter = ""; state.page = 0;
      switchTab("accounts");
    };
  });

  $("#highlight-cards").innerHTML = FLAGS.map((f) => {
    const n = state.rows.filter(f.test).length;
    return `<button class="highlight-card ${n ? "" : "empty"}" data-flag="${f.key}" title="${esc(f.help)}">
      <span class="hc-count">${fmt(n)}</span>
      <span class="hc-label">${esc(f.label)}</span>
      <span class="hc-help">${esc(f.help)}</span>
    </button>`;
  }).join("");

  $$("#highlight-cards .highlight-card").forEach((el) => {
    el.onclick = () => {
      state.filters = new Set([el.dataset.flag]);
      state.repFilter = ""; state.segmentFilter = ""; state.page = 0;
      switchTab("accounts");
    };
  });
}

const WHITESPACE_CATS = new Set(["whitespace", "whitespace_subsidiary"]);

/** Rank every real (non-whitespace) account within its segment by ICP score,
 *  1 = best. Book strength is then "how many top-ranked accounts do you hold",
 *  which is far more legible than a summed score with no units. */
function segmentRanks() {
  const bySeg = {};
  for (const r of state.rows) {
    if (WHITESPACE_CATS.has(r.account_category)) continue;
    (bySeg[r.account_segment] ||= []).push(r);
  }
  const ranks = {}, sizes = {};
  for (const seg of Object.keys(bySeg)) {
    bySeg[seg].sort((a, b) =>
      num(b.score) - num(a.score) || String(a.org_id).localeCompare(String(b.org_id)));
    bySeg[seg].forEach((r, i) => { ranks[r.org_id] = i + 1; });
    sizes[seg] = bySeg[seg].length;
  }
  return { ranks, sizes };
}

// Fixed depth cutoffs (columns of the matrix), same for every rep and segment.
const DEPTH_COLS = [10, 25, 50, 100, 200];

/** A rep's territory within ONE segment: the accounts they own that belong to
 *  that segment, strongest first. Ranking must stay inside a single segment —
 *  a rep's book mixes segment sizes (a big-name account below the line still
 *  sits in Commercial), and averaging ranks drawn from two universes is
 *  meaningless (a Commercial rank of 2 is not comparable to an Enterprise 2). */
function inSegmentBook(repName, segKey) {
  // Group by EFFECTIVE owner so allocations made on the Accounts tab show up
  // here immediately.
  return state.rows
    .filter((r) => effectiveOwner(r) === repName && r.account_segment === segKey &&
      !WHITESPACE_CATS.has(r.account_category))
    .sort((a, b) => num(b.score) - num(a.score));
}

function avgRankOf(slice, ranks) {
  if (!slice.length) return null;
  return slice.reduce((a, r) => a + (ranks[r.org_id] || 0), 0) / slice.length;
}

/** Conditional-formatting background for a value relative to the other values IN
 *  ITS COLUMN — a translucent green whose opacity scales with strength, matching
 *  gtm.sumble.com/account-scores (`rgba(0,166,62, 0.05 + 0.4*t)`). Strongest cell
 *  is the deepest green, weakest is nearly clear, so a weak territory reads as a
 *  pale cell. `better` says which end is strong. A column with fewer than two
 *  distinct values can't be compared, so it stays unshaded. Returns a `style="…"`
 *  attribute string (or ""). */
function heatStyleAttr(val, min, max, better) {
  if (val == null || max === min) return "";
  let t = (val - min) / (max - min);       // 0 at min, 1 at max
  if (better === "low") t = 1 - t;         // now t = 1 is strongest
  const alpha = (0.05 + 0.4 * t).toFixed(3);
  return ` style="background: rgba(0, 166, 62, ${alpha})"`;
}

function workedPctOf(slice) {
  if (!slice.length) return null;
  return (100 * slice.filter((r) => num(r.worked)).length) / slice.length;
}

/** One matrix over one or more segment `groups` — a single table. When more than
 *  one segment is shown, a **Segment column** labels each row. `valueOf(slice)` →
 *  the number a cell shows (or null); `better` is which direction is good;
 *  `fmtVal` formats it. Colours are assigned per COLUMN **within each segment**,
 *  so ranks drawn from different segment universes are never shaded against each
 *  other, even though the rows share one table. */
function renderMatrix(groups, valueOf, better, fmtVal, summary, opts) {
  const showSeg = groups.length > 1;
  const sort = opts.sort;

  // Flatten all segments into one sortable list; the Segment column keeps each
  // row's universe legible once sorting interleaves them.
  const flat = [];
  for (const grp of groups) {
    for (const { rep, book } of grp.books) {
      const vals = {};
      for (const n of DEPTH_COLS) vals[n] = book.length >= n ? valueOf(book.slice(0, n)) : null;
      vals.all = book.length ? valueOf(book) : null;
      vals.summary = summary ? summary.value(book, grp) : null;
      flat.push({ rep, book, grp, vals });
    }
  }

  // Column spec: text columns (Rep, Segment, In-seg) plus heat columns (summary,
  // depth bands, All). `heat` is the vals key + colour source; `dir` its good end.
  const columns = [
    { label: "Rep", key: "rep", text: true },
    ...(showSeg ? [{ label: "Segment", key: "seg", text: true }] : []),
    { label: "In-seg", key: "inseg" },
    ...(summary ? [{ label: summary.label, key: "summary", heat: "summary",
      dir: summary.better, fmtc: summary.fmt, help: summary.help, cls: "summary-cell" }] : []),
    ...DEPTH_COLS.map((n) => ({ label: `Top ${n}`, key: String(n), heat: n, dir: better, fmtc: fmtVal })),
    { label: "All", key: "all", heat: "all", dir: better, fmtc: fmtVal },
  ];

  // Conditional formatting is over the WHOLE column (all rows, both segments),
  // not per segment.
  const bounds = {};
  for (const c of columns) {
    if (!c.heat && c.heat !== 0) continue;
    const vs = flat.map((r) => r.vals[c.heat]).filter((v) => v != null);
    bounds[c.heat] = vs.length ? { min: Math.min(...vs), max: Math.max(...vs) } : null;
  }

  // Sort (nulls always last).
  const sortVal = (row, key) => {
    if (key === "rep") return row.rep.name.toLowerCase();
    if (key === "seg") return row.grp.order;
    if (key === "inseg") return row.book.length;
    if (key === "summary") return row.vals.summary;
    if (key === "all") return row.vals.all;
    return row.vals[Number(key)];
  };
  flat.sort((a, b) => {
    const av = sortVal(a, sort.key), bv = sortVal(b, sort.key);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (av < bv) return -sort.dir;
    if (av > bv) return sort.dir;
    return a.rep.name.localeCompare(b.rep.name);
  });

  const head = `<tr>${columns.map((c) => {
    const active = sort.key === c.key;
    const arrow = active ? (sort.dir === -1 ? " ▾" : " ▴") : "";
    // Intuition lives on an info icon, not a bare header title — more
    // discoverable, and it won't clash with the sort click.
    const info = c.help ? ` <span class="col-info" title="${esc(c.help)}">ⓘ</span>` : "";
    return `<th class="sortable ${c.text ? "" : "num"}${active ? " sorted" : ""}" ` +
      `data-matrix="${esc(opts.matrixId)}" data-key="${esc(c.key)}">` +
      `${esc(c.label)}${arrow}${info}</th>`;
  }).join("")}</tr>`;

  const body = flat.map(({ rep, book, grp, vals }) => {
    const cells = columns.map((c) => {
      if (c.key === "rep") return `<td>${esc(rep.name)}</td>`;
      if (c.key === "seg") return `<td class="seg-cell">${esc(grp.label)}</td>`;
      if (c.key === "inseg") return `<td class="num">${fmt(book.length)}</td>`;
      const v = vals[c.heat];
      if (v == null) return `<td class="num matrix-empty ${c.cls || ""}">—</td>`;
      const b = bounds[c.heat];
      const bg = heatStyleAttr(v, b.min, b.max, c.dir);
      return `<td class="num ${c.cls || ""}"${bg}>${c.fmtc(v)}</td>`;
    }).join("");
    return `<tr class="rep-row" data-rep="${esc(rep.name)}">${cells}</tr>`;
  }).join("");

  return `<div class="table-wrap"><table class="matrix-table">
    <thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}

function filteredRows() {
  const q = state.search.trim().toLowerCase();
  return state.rows.filter((r) => {
    if (state.filters.size) {
      const preds = [...state.filters].map((key) =>
        key === "suggested"
          ? (row) => row.proposal_status === "suggested"
          : (FLAGS.find((f) => f.key === key)?.test || (() => false)));
      if (!preds.some((p) => p(r))) return false;
    }
    if (state.repFilter && r.owner !== state.repFilter && r.proposed_owner !== state.repFilter) return false;
    if (state.segmentFilter && r.account_segment !== state.segmentFilter) return false;
    if (q) {
      const hay = `${r.name} ${r.domain} ${r.owner} ${r.proposed_owner}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  }).sort((a, b) => {
    const k = state.sort.key;
    let av, bv;
    if (k === "name" || k === "owner") { av = String(a[k] || ""); bv = String(b[k] || ""); }
    else if (k === "rank") { av = accountRank(a) ?? Infinity; bv = accountRank(b) ?? Infinity; }
    else { av = num(a[k]); bv = num(b[k]); }
    if (av < bv) return -state.sort.dir;
    if (av > bv) return state.sort.dir;
    return String(a.org_id).localeCompare(String(b.org_id));
  });
}

/** The "Assign to" cell — ONE owner dropdown per row does everything: allocate
 *  to anyone, or take the balancer's suggestion. When a move is suggested, that
 *  owner sits at the top of the menu marked "suggested" (picking it = accept),
 *  the closed control is tinted, and a tiny "dismiss" link rejects it. No
 *  separate accept/reject buttons. Sentinel value `__accept__` = take the
 *  suggestion (preserves its reason); any rep name = a manual move. */
function assignCell(r) {
  const eff = effectiveOwner(r);
  const st = r.proposal_status || "";
  const suggesting = st === "suggested" && r.proposed_owner;

  const repOptions = state.reps.map((rep) => {
    const seg = state.segLabel[rep.segment] || rep.segment;
    return `<option value="${esc(rep.name)}" ${rep.name === eff ? "selected" : ""}>` +
      `${esc(rep.name)} · ${esc(seg)}</option>`;
  }).join("");

  const head = suggesting
    ? `<option value="__accept__">✨ ${esc(r.proposed_owner)} — suggested</option>` +
      `<option disabled>──────────</option>`
    : "";
  const options = head +
    `<option value="" ${!eff ? "selected" : ""}>— unassigned —</option>` + repOptions;

  const cls = "assign-select terr-select" +
    (suggesting ? " has-suggestion" : (isApproved(r) ? " changed" : ""));
  const select = `<select class="${cls}" data-id="${esc(r.org_id)}">${options}</select>`;

  // One tiny inline affordance, contextual to state — never more than a link.
  let note = "";
  if (suggesting) {
    note = `<a class="decide-btn undo-link" data-id="${esc(r.org_id)}"
      data-status="rejected" title="Dismiss this suggestion (won't be re-proposed)">dismiss</a>`;
  } else if (st === "accepted") {
    note = `<a class="decide-btn undo-link" data-id="${esc(r.org_id)}"
      data-status="" title="Revert to the balancer's suggestion">undo</a>`;
  } else if (st === "manual") {
    note = `<a class="decide-btn undo-link" data-id="${esc(r.org_id)}"
      data-status="manual" title="Clear this allocation">undo</a>`;
  } else if (st === "rejected") {
    note = `<span class="cell-sub">dismissed · <a class="decide-btn undo-link"
      data-id="${esc(r.org_id)}" data-status="">undo</a></span>`;
  }
  return `<div class="assign-wrap">${select}${note}</div>`;
}

function renderAccounts() {
  const suggested = state.rows.filter((r) => r.proposal_status === "suggested").length;
  $("#account-filters").innerHTML =
    `<button class="cat-chip ${state.filters.size ? "" : "active"}" data-flag="">All
       <span class="cat-count">${fmt(state.rows.length)}</span></button>` +
    FLAGS.map((f) => {
      const n = state.rows.filter(f.test).length;
      return `<button class="cat-chip ${state.filters.has(f.key) ? "active" : ""}"
        data-flag="${f.key}" title="${esc(f.help)}">${esc(f.label)}
        <span class="cat-count">${fmt(n)}</span></button>`;
    }).join("") +
    `<button class="cat-chip cat-chip-move ${state.filters.has("suggested") ? "active" : ""}"
       data-flag="suggested"
       title="Accounts the balancer has proposed a new owner for — accept or reject them in the last column.">Suggested move
       <span class="cat-count">${fmt(suggested)}</span></button>`;
  $$("#account-filters .cat-chip").forEach((el) => {
    el.onclick = () => {
      const key = el.dataset.flag;
      if (!key) state.filters = new Set();
      else if (state.filters.has(key)) state.filters.delete(key);
      else state.filters.add(key);
      state.page = 0;
      render();
    };
  });

  const cols = [
    { key: "rank", label: "Rank", num: true },
    { key: "name", label: "Account" },
    { key: "account_segment", label: "Segment" },
    { key: "size_metric", label: sizeLabel(), num: true },
    { key: "score", label: "Score", num: true },
    { key: "owner", label: "Current owner" },
    { key: "activity", label: "Activity", num: true },
    { key: "flags", label: "Flags" },
    { key: "assign", label: "Assign to" },
  ];
  $("#accounts-table thead").innerHTML = `<tr>${cols.map((c) =>
    `<th class="${c.num ? "num" : ""} ${["flags", "assign", "activity"].includes(c.key) ? "" : "sortable"}"
        data-key="${c.key}">${esc(c.label)}${state.sort.key === c.key
        ? (state.sort.dir === -1 ? " ▾" : " ▴") : ""}</th>`).join("")}</tr>`;
  $$("#accounts-table th.sortable").forEach((th) => {
    th.onclick = () => {
      const k = th.dataset.key;
      state.sort = state.sort.key === k
        ? { key: k, dir: -state.sort.dir }
        : { key: k, dir: (k === "name" || k === "owner" || k === "rank") ? 1 : -1 };
      render();
    };
  });

  const rows = filteredRows();
  const pages = Math.max(1, Math.ceil(rows.length / state.pageSize));
  state.page = Math.min(state.page, pages - 1);
  const slice = rows.slice(state.page * state.pageSize, (state.page + 1) * state.pageSize);

  $("#accounts-table tbody").innerHTML = slice.map((r) => {
    const acts = num(r.meetings) + num(r.calls) + num(r.emails_out);
    return `<tr data-id="${esc(r.org_id)}">
      <td class="num">${accountRank(r) ? fmt(accountRank(r)) : "—"}</td>
      <td>${r.sumble_url
        ? `<a href="${esc(r.sumble_url)}" target="_blank" rel="noopener">${esc(r.name)}</a>`
        : esc(r.name)}<span class="cell-sub">${esc(r.domain)}</span></td>
      <td>${esc(state.segLabel[r.account_segment] || r.account_segment || "—")}</td>
      <td class="num">${fmt(r.size_metric)}</td>
      <td class="num">${fmt(r.score, 1)}</td>
      <td>${esc(r.owner || "—")}${num(r.double_allocated)
        ? `<span class="cell-sub">also: ${esc(r.other_owners)}</span>` : ""}</td>
      <td class="num" title="${num(r.meetings)} meetings · ${num(r.calls)} calls · ${num(r.emails_out)} emails out">
        ${acts ? fmt(acts) : `<span class="zero">0</span>`}</td>
      <td>${flagPills(r)}</td>
      <td class="assign-cell">${assignCell(r)}</td>
    </tr>`;
  }).join("");
  $$("#accounts-table tbody tr").forEach((tr) => {
    tr.onclick = () => showDetail(tr.dataset.id);
  });
  // The assign dropdown and accept/reject live in the last column; stop the
  // click bubbling up to the row (which would open the detail panel).
  $$("#accounts-table .assign-select").forEach((sel) => {
    sel.onclick = (e) => e.stopPropagation();
    sel.onchange = (e) => {
      e.stopPropagation();
      if (sel.value === "__accept__") decide(sel.dataset.id, "accepted");
      else decide(sel.dataset.id, "manual", sel.value);
    };
  });
  $$("#accounts-table .decide-btn").forEach((btn) => {
    btn.onclick = (e) => { e.stopPropagation(); decide(btn.dataset.id, btn.dataset.status); };
  });

  $("#page-info").textContent = rows.length
    ? `${fmt(state.page * state.pageSize + 1)}–${fmt(Math.min((state.page + 1) * state.pageSize, rows.length))} of ${fmt(rows.length)}`
    : "no matching accounts";
  $("#page-prev").disabled = state.page <= 0;
  $("#page-next").disabled = state.page >= pages - 1;
}

function sizeLabel() {
  return state.rows[0]?.size_metric_name || "Size";
}

function renderExport() {
  const approved = state.rows.filter(isApproved);
  const pending = state.rows.filter((r) => r.proposal_status === "suggested").length;
  $("#export-summary").innerHTML = `
    <p><strong>${fmt(approved.length)}</strong> approved change${approved.length === 1 ? "" : "s"} ready to export.
    ${pending ? `<strong>${fmt(pending)}</strong> proposal${pending === 1 ? " is" : "s are"} still undecided.` : ""}</p>
    <p class="eval-diag-sub">actions.csv lists one row per owner change (from → to, with the reason
      and the evidence). Nothing is written to your CRM by this app — the export is the hand-off.</p>`;

  const cols = ["Account", "Segment", "From", "To", "Reason", "Score", ""];
  $("#export-table thead").innerHTML = `<tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr>`;
  $("#export-table tbody").innerHTML = approved.length ? approved.map((r) => `<tr>
      <td>${esc(r.name)}<span class="cell-sub">${esc(r.domain)}</span></td>
      <td>${esc(state.segLabel[r.account_segment] || r.account_segment)}</td>
      <td>${esc(r.owner || "(unassigned)")}</td>
      <td>${esc(r.proposed_owner)}</td>
      <td>${esc(REASON_LABELS[r.proposal_reason] || r.proposal_reason)}</td>
      <td class="num">${fmt(r.score, 1)}</td>
      <td class="num"><button class="dismiss-change btn-link" data-id="${esc(r.org_id)}"
        data-status="${esc(r.proposal_status)}"
        title="Drop this change from the export (reverts the account)">Dismiss</button></td>
    </tr>`).join("")
    : `<tr><td colspan="${cols.length}" class="empty-state">Nothing approved yet — accept a
        suggestion or assign an owner on the Accounts tab.</td></tr>`;

  $$("#export-table .dismiss-change").forEach((btn) => {
    btn.onclick = () => {
      // A manual assignment is cleared (blank owner); an accepted suggestion is
      // rejected so it won't be re-proposed. Either way it leaves the export.
      if (btn.dataset.status === "manual") decide(btn.dataset.id, "manual", "");
      else decide(btn.dataset.id, "rejected");
    };
  });
}

function showDetail(orgId) {
  const r = state.rows.find((x) => String(x.org_id) === String(orgId));
  if (!r) return;
  $("#detail-name").textContent = r.name;
  $("#detail-meta").innerHTML =
    `${esc(r.domain)} · ${esc(state.segLabel[r.account_segment] || "")} ·
     ${esc(sizeLabel())} ${fmt(r.size_metric)} · score ${fmt(r.score, 1)}
     ${r.sumble_url ? ` · <a href="${esc(r.sumble_url)}" target="_blank" rel="noopener">Sumble profile ↗</a>` : ""}`;

  const acts = [
    ["Meetings", r.meetings], ["Calls", r.calls],
    ["Emails out", r.emails_out], ["Emails in", r.emails_in],
  ];
  const total = acts.reduce((a, [, v]) => a + num(v), 0);
  // Reassign from ANY account, not only rows the balancer proposed. Same
  // /api/decide "manual" path as the Moves tab; picking the blank entry (or
  // the current owner) clears the override. All active reps are offered — a
  // deliberate human move may cross segments; the balancer's lanes only
  // constrain the automatic suggestions.
  const ownerOptions = state.reps
    .map((rep) => {
      const seg = state.segLabel[rep.segment] || rep.segment;
      const sel = rep.name === (r.proposed_owner || "") ? "selected" : "";
      return `<option value="${esc(rep.name)}" ${sel}>${esc(rep.name)} (${esc(seg)})</option>`;
    })
    .join("");
  $("#detail-body").innerHTML = `
    <div class="detail-section">
      <h3>Owner</h3>
      <p>${esc(r.owner || "Nobody — this account is unallocated.")}
        ${num(r.double_allocated) ? `<br /><span class="flag-pill flag-bad">Also owned by ${esc(r.other_owners)}</span>` : ""}
        ${r.proposed_owner ? `<br />Proposed: <strong>${esc(r.proposed_owner)}</strong>
          (${esc(REASON_LABELS[r.proposal_reason] || r.proposal_reason)}, ${esc(r.proposal_status)})` : ""}</p>
      <p class="detail-reassign">
        <label for="detail-owner-select">Move to</label>
        <select id="detail-owner-select" class="terr-select">
          <option value="">${r.proposed_owner ? "(clear this move)" : `(keep ${esc(r.owner || "unassigned")})`}</option>
          ${ownerOptions}
        </select>
      </p>
      ${num(r.worked) ? `<p class="eval-diag-sub">⚠ ${esc(r.owner)} has worked this account in the window —
        the balancer would never move it, so a move here is deliberately your call.</p>` : ""}
    </div>
    <div class="detail-section">
      <h3>Activity with this owner · last ${fmt(state.plan.activity?.window_days || 90)} days</h3>
      ${total ? `<table class="detail-table"><tbody>${acts.map(([k, v]) =>
        `<tr><td>${k}</td><td class="num">${fmt(v)}</td></tr>`).join("")}
        <tr><td>Last touch</td><td class="num">${esc(r.last_activity_date || "—")}</td></tr>
        <tr><td>Sources</td><td class="num">${esc((r.activity_sources || "").split("|").join(", ") || "—")}</td></tr>
        </tbody></table>`
        : `<p class="empty-state">No recorded activity between this owner and this account.
           That is what makes it eligible to be reassigned.</p>`}
      <p class="eval-diag-sub">Counts are between <em>this owner</em> and this account only —
        not the whole team.</p>
    </div>
    <div class="detail-section">
      <h3>Flags</h3>
      <p>${flagPills(r) || "<span class='eval-diag-sub'>None — owned, in the right segment, and being worked.</span>"}</p>
    </div>`;
  const sel = $("#detail-owner-select");
  if (sel) {
    sel.onchange = async () => {
      await decide(r.org_id, "manual", sel.value);
      showDetail(r.org_id); // re-render the panel with the new state
    };
  }
  $("#detail-panel").classList.remove("hidden");
}

// ---------------------------------------------------------------- actions

async function decide(orgId, status, proposedOwner) {
  const row = state.rows.find((r) => String(r.org_id) === String(orgId));
  if (!row) return;
  const body = { org_id: orgId, status };
  if (status === "manual") body.proposed_owner = proposedOwner || "";
  const res = await fetch("/api/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    alert(`Could not save that decision: ${res.status} ${res.statusText}`);
    return;
  }
  const out = await res.json();
  Object.assign(row, out.row);
  render();
}

function switchTab(tab) {
  state.tab = tab;
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  $$(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${tab}`));
  $("#tab-description").textContent = PAGE_DESCRIPTIONS[tab] || "";
  render();
}

function render() {
  computeStrongSet();  // refresh the "strong" set for the attention flags
  renderCalibrate(); // the sidebar is always visible, independent of the tab
  if (state.tab === "overview") renderOverview();
  else if (state.tab === "accounts") renderAccounts();
  else if (state.tab === "export") renderExport();
}

async function init() {
  const res = await fetch("/api/plan");
  const data = await res.json();
  state.plan = data.plan;
  state.rows = data.rows;
  state.segments = (data.plan.segments || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
  state.segLabel = Object.fromEntries(state.segments.map((s) => [s.key, s.label]));
  state.reps = (data.plan.reps || []).filter((r) => r.is_rep);
  state.repByName = Object.fromEntries(state.reps.map((r) => [r.name, r]));
  state.strongCutoff = num(data.plan.strong_cutoff) || 500;

  const company = (data.plan.company || {}).name || "Territory";
  $("#customer-name").textContent = `${company} territory plan`;
  const owned = state.rows.filter((r) => r.owner).length;
  $("#row-summary").textContent =
    `${fmt(state.rows.length)} accounts · ${fmt(state.reps.length)} reps · ${fmt(owned)} allocated`;

  $("#rep-filter").innerHTML = `<option value="">All reps</option>` +
    state.reps.map((r) => `<option value="${esc(r.name)}">${esc(r.name)}</option>`).join("");
  $("#segment-filter").innerHTML = `<option value="">All segments</option>` +
    state.segments.map((s) => `<option value="${esc(s.key)}">${esc(s.label)}</option>`).join("");

  $$(".tab").forEach((t) => { t.onclick = () => switchTab(t.dataset.tab); });
  $("#calibrate-reset-fields").onclick = () => {
    // Put every field back to the plan's saved values: the segment/capacity
    // inputs (rebuilt from the plan) and the strong-account cutoff.
    state.strongCutoff = num(state.plan.strong_cutoff) || 500;
    $("#strong-cutoff").value = state.strongCutoff;
    $("#calibrate-controls").dataset.built = "";
    $("#calibrate-status").textContent = "";
    render();
  };
  $("#strong-cutoff").value = state.strongCutoff;
  $("#strong-cutoff").oninput = (e) => {
    state.strongCutoff = Math.max(1, num(e.target.value) || 500);
    state.page = 0;
    render();
  };
  $("#search-input").oninput = (e) => { state.search = e.target.value; state.page = 0; render(); };
  $("#rep-filter").onchange = (e) => { state.repFilter = e.target.value; state.page = 0; render(); };
  $("#segment-filter").onchange = (e) => { state.segmentFilter = e.target.value; state.page = 0; render(); };
  $("#page-prev").onclick = () => { state.page = Math.max(0, state.page - 1); render(); };
  $("#page-next").onclick = () => { state.page += 1; render(); };
  $("#detail-close").onclick = () => $("#detail-panel").classList.add("hidden");
  const dl = (url) => { window.location.href = url; };
  $("#export-actions").onclick = () => dl("/api/export");
  $("#export-actions-2").onclick = () => dl("/api/export");
  $("#export-sheet").onclick = () => dl("/api/territory.csv");
  $("#export-sheet-2").onclick = () => dl("/api/territory.csv");
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== $("#search-input")) {
      if (state.tab !== "accounts") switchTab("accounts");
      e.preventDefault(); $("#search-input").focus();
    }
    if (e.key === "Escape") $("#detail-panel").classList.add("hidden");
  });

  switchTab("overview");
}

init();
