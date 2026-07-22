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
};

const PAGE_DESCRIPTIONS = {
  overview: "How evenly the books are split, and what needs attention. Balance is measured on total account score per rep, so a rep with fewer but stronger accounts still reads as a full book.",
  reps: "One row per rep. Coverage is the share of their book they have actually touched in the activity window.",
  accounts: "Every account in the plan. Filter by a flag, a rep, or a segment; click a row for its activity detail.",
  moves: "Proposed owner changes, least disruptive first. Accepting one updates the balance bars immediately. Nothing is written to your CRM until you export.",
  export: "Download the approved changes for your CRM, or the full sheet with every flag and activity count.",
};

const FLAGS = [
  { key: "not_worked",       label: "Not being worked",  test: (r) => r.owner && !num(r.worked), cls: "flag-warn",
    help: "Owned, but the owner has had no meeting, call, or outbound email with them in the window." },
  { key: "strong_idle",      label: "Strong but idle",   test: (r) => num(r.strong_idle), cls: "flag-bad",
    help: "Top-quartile score for its segment, and nobody is working it. The most expensive kind of neglect." },
  { key: "segment_misfit",   label: "Wrong segment",     test: (r) => num(r.segment_misfit), cls: "flag-warn",
    help: "The account's size puts it in one segment; its owner sells another." },
  { key: "unallocated",      label: "Unallocated",       test: (r) => num(r.unallocated), cls: "flag-info",
    help: "No active rep owns it — nobody, a queue, or someone who has left." },
  { key: "double_allocated", label: "Double-allocated",  test: (r) => num(r.double_allocated), cls: "flag-bad",
    help: "Two or more reps own CRM records that resolve to the SAME company. Resolve these before rebalancing." },
  { key: "whitespace",       label: "Whitespace",        test: (r) => isWhitespace(r), cls: "flag-new",
    help: "Net-new accounts carried over from an account-scoring whitespace run." },
];

const REASON_LABELS = {
  misfit: "Wrong segment",
  assign_unallocated: "Unallocated — needs an owner",
  assign_whitespace: "Whitespace — new account",
  rebalance: "Rebalance",
  manual: "Manual override",
};
const REASON_HELP = {
  misfit: "The account's size belongs to another segment and its current owner is not working it.",
  assign_unallocated: "Nobody owns this today. It goes to the lightest book in its segment.",
  assign_whitespace: "A net-new account with no CRM record, routed to the lightest book in its segment.",
  rebalance: "Moved purely to even out the books. Only accounts with no activity are ever eligible.",
  manual: "You picked this owner by hand.",
};

// ---------------------------------------------------------------- helpers

function num(v) { const n = Number(v); return Number.isFinite(n) ? n : 0; }
function isWhitespace(r) {
  return r.account_category === "whitespace" || r.account_category === "whitespace_subsidiary";
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmt(n, digits = 0) {
  return Number(n || 0).toLocaleString(undefined, {
    minimumFractionDigits: digits, maximumFractionDigits: digits });
}
/** Owner once the user's approved decisions are applied. Mirrors
 *  suggest_moves.effective_owner(). */
function effectiveOwner(r) {
  return (r.proposal_status === "accepted" || r.proposal_status === "manual")
    ? (r.proposed_owner || r.owner) : r.owner;
}
function isApproved(r) {
  return (r.proposal_status === "accepted" || r.proposal_status === "manual") && r.proposed_owner;
}
function percentile(sorted, p) {
  if (!sorted.length) return 0;
  const i = Math.max(0, Math.min(sorted.length - 1, Math.round(p * (sorted.length - 1))));
  return sorted[i];
}
function cv(values) {
  if (values.length < 2) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  if (mean <= 0) return 0;
  const varr = values.reduce((a, v) => a + (v - mean) ** 2, 0) / values.length;
  return Math.sqrt(varr) / mean;
}
function balanceLabel(v) {
  const b = state.plan.balance || {};
  if (v <= (b.cv_balanced ?? 0.15)) return "balanced";
  if (v <= (b.cv_uneven ?? 0.35)) return "uneven";
  return "imbalanced";
}

/** Per-segment book stats. `ownerFn` selects which allocation to measure, so
 *  the same code produces both the "today" and the "if approved" view. */
function bookStats(ownerFn) {
  const cats = new Set(state.plan.balance?.include_categories || ["allocated", "unallocated"]);
  const out = {};
  for (const seg of state.segments) {
    out[seg.key] = { reps: {}, cv: 0, label: "balanced", mean: 0 };
    for (const rep of state.reps) {
      if (rep.segment === seg.key) {
        out[seg.key].reps[rep.name] = {
          name: rep.name, n_accounts: 0, sum_score: 0, worked: 0,
          top_quartile: 0, sum_pipeline: 0,
        };
      }
    }
  }
  const scored = state.rows.filter((r) => cats.has(r.account_category))
    .map((r) => num(r.score)).sort((a, b) => a - b);
  const p75 = percentile(scored, 0.75);

  for (const r of state.rows) {
    if (!cats.has(r.account_category)) continue;
    const owner = ownerFn(r);
    if (!owner) continue;
    const rep = state.repByName[owner];
    if (!rep) continue;
    const book = out[rep.segment]?.reps[owner];
    if (!book) continue;
    book.n_accounts += 1;
    book.sum_score += num(r.score);
    book.sum_pipeline += num(r.pipeline_value);
    if (num(r.worked)) book.worked += 1;
    if (num(r.score) >= p75) book.top_quartile += 1;
  }
  for (const seg of Object.values(out)) {
    const sums = Object.values(seg.reps).map((b) => b.sum_score);
    seg.cv = cv(sums);
    seg.label = balanceLabel(seg.cv);
    seg.mean = sums.length ? sums.reduce((a, b) => a + b, 0) / sums.length : 0;
    seg.max = sums.length ? Math.max(...sums) : 0;
    for (const b of Object.values(seg.reps)) {
      b.worked_pct = b.n_accounts ? (100 * b.worked) / b.n_accounts : 0;
    }
  }
  return out;
}

// ---------------------------------------------------------------- rendering

function flagPills(r) {
  return FLAGS.filter((f) => f.test(r))
    .map((f) => `<span class="flag-pill ${f.cls}">${esc(f.label)}</span>`).join(" ");
}

function renderOverview() {
  const now = bookStats((r) => r.owner);
  const after = bookStats(effectiveOwner);
  const approved = state.rows.filter(isApproved).length;

  $("#overview-segments").innerHTML = state.segments.map((seg) => {
    const b = now[seg.key], a = after[seg.key];
    const reps = Object.values(b.reps).sort((x, y) => y.sum_score - x.sum_score);
    if (!reps.length) {
      return `<div class="seg-card"><h3 class="terr-h3">${esc(seg.label)}</h3>
        <p class="eval-diag-sub">No reps assigned to this segment.</p></div>`;
    }
    const sums = reps.map((r) => r.sum_score);
    const ratio = Math.min(...sums) > 0 ? Math.max(...sums) / Math.min(...sums) : 0;
    const scale = Math.max(b.max, a.max, 1);
    const changed = approved > 0 && Math.abs(a.cv - b.cv) > 1e-9;

    const bars = reps.map((rep) => {
      const af = a.reps[rep.name] || { sum_score: 0, n_accounts: 0, worked: 0 };
      const workedShare = rep.sum_score > 0
        ? (100 * workedScore(rep.name, (r) => r.owner)) / rep.sum_score : 0;
      const w = (100 * rep.sum_score) / scale;
      const wA = (100 * af.sum_score) / scale;
      const delta = af.sum_score - rep.sum_score;
      return `<div class="bar-row">
        <div class="bar-label" title="${esc(rep.name)}">${esc(rep.name)}</div>
        <div class="bar-track">
          <div class="bar-fill" style="width:${w.toFixed(2)}%">
            <div class="bar-worked" style="width:${workedShare.toFixed(2)}%"></div>
          </div>
          ${changed ? `<div class="bar-ghost" style="width:${wA.toFixed(2)}%"></div>` : ""}
        </div>
        <div class="bar-value">${fmt(rep.sum_score)}
          <span class="bar-sub">${fmt(rep.n_accounts)} accts · ${fmt(rep.worked_pct, 0)}% worked</span>
          ${changed && Math.abs(delta) > 0.01
            ? `<span class="bar-delta ${delta > 0 ? "up" : "down"}">${delta > 0 ? "+" : ""}${fmt(delta)}</span>` : ""}
        </div>
      </div>`;
    }).join("");

    return `<div class="seg-card">
      <div class="seg-head">
        <h3 class="terr-h3">${esc(seg.label)}</h3>
        <span class="balance-badge balance-${b.label}">${b.label}</span>
        ${changed ? `<span class="balance-badge balance-${a.label} ghost-badge"
            title="After the moves you have approved">→ ${a.label}</span>` : ""}
      </div>
      <p class="eval-diag-sub">
        Spread across ${reps.length} reps: CV ${b.cv.toFixed(2)}${changed ? ` → ${a.cv.toFixed(2)}` : ""}
        ${ratio > 0 ? ` · the biggest book is ${ratio.toFixed(1)}× the smallest` : ""}.
        The darker part of each bar is the score the rep has actually worked.
      </p>
      <div class="bars">${bars}</div>
    </div>`;
  }).join("");

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

/** Total score of one rep's accounts that they HAVE worked (for the bar's
 *  darker inner segment). */
function workedScore(repName, ownerFn) {
  const cats = new Set(state.plan.balance?.include_categories || ["allocated", "unallocated"]);
  return state.rows.reduce((acc, r) =>
    acc + (ownerFn(r) === repName && cats.has(r.account_category) && num(r.worked)
      ? num(r.score) : 0), 0);
}

function renderReps() {
  const now = bookStats((r) => r.owner);
  const after = bookStats(effectiveOwner);
  const cats = (state.plan.balance?.include_categories || []).join(" + ");
  $("#reps-note").textContent =
    `Books counted over ${cats} accounts (customers are excluded — a renewal book isn't a workload to rebalance). ` +
    `"After" reflects the moves you have approved.`;

  const cols = ["Rep", "Segment", "Accounts", "Total score", "After", "Top-quartile", "Worked", "Pipeline"];
  $("#reps-table thead").innerHTML =
    `<tr>${cols.map((c, i) => `<th class="${i > 1 ? "num" : ""}">${c}</th>`).join("")}</tr>`;

  const body = [];
  for (const seg of state.segments) {
    const reps = Object.values(now[seg.key].reps).sort((a, b) => b.sum_score - a.sum_score);
    if (!reps.length) continue;
    body.push(`<tr class="group-row"><td colspan="${cols.length}">${esc(seg.label)}</td></tr>`);
    for (const rep of reps) {
      const af = after[seg.key].reps[rep.name] || rep;
      const delta = af.sum_score - rep.sum_score;
      body.push(`<tr class="rep-row" data-rep="${esc(rep.name)}">
        <td>${esc(rep.name)}</td>
        <td>${esc(state.segLabel[seg.key] || seg.key)}</td>
        <td class="num">${fmt(rep.n_accounts)}</td>
        <td class="num">${fmt(rep.sum_score)}</td>
        <td class="num">${fmt(af.sum_score)}${Math.abs(delta) > 0.01
          ? ` <span class="bar-delta ${delta > 0 ? "up" : "down"}">${delta > 0 ? "+" : ""}${fmt(delta)}</span>` : ""}</td>
        <td class="num">${fmt(rep.top_quartile)}</td>
        <td class="num">${fmt(rep.worked_pct, 0)}%</td>
        <td class="num">${rep.sum_pipeline ? fmt(rep.sum_pipeline) : "—"}</td>
      </tr>`);
    }
  }
  $("#reps-table tbody").innerHTML = body.join("");
  $$("#reps-table .rep-row").forEach((tr) => {
    tr.onclick = () => {
      state.repFilter = tr.dataset.rep; state.filters = new Set();
      state.segmentFilter = ""; state.page = 0;
      switchTab("accounts");
    };
  });
}

function filteredRows() {
  const q = state.search.trim().toLowerCase();
  return state.rows.filter((r) => {
    if (state.filters.size) {
      const active = FLAGS.filter((f) => state.filters.has(f.key));
      if (!active.some((f) => f.test(r))) return false;
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
    const av = k === "name" || k === "owner" ? String(a[k] || "") : num(a[k]);
    const bv = k === "name" || k === "owner" ? String(b[k] || "") : num(b[k]);
    if (av < bv) return -state.sort.dir;
    if (av > bv) return state.sort.dir;
    return String(a.org_id).localeCompare(String(b.org_id));
  });
}

function renderAccounts() {
  $("#account-filters").innerHTML =
    `<button class="cat-chip ${state.filters.size ? "" : "active"}" data-flag="">All
       <span class="cat-count">${fmt(state.rows.length)}</span></button>` +
    FLAGS.map((f) => {
      const n = state.rows.filter(f.test).length;
      return `<button class="cat-chip ${state.filters.has(f.key) ? "active" : ""}"
        data-flag="${f.key}" title="${esc(f.help)}">${esc(f.label)}
        <span class="cat-count">${fmt(n)}</span></button>`;
    }).join("");
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
    { key: "name", label: "Account" },
    { key: "account_segment", label: "Segment" },
    { key: "size_metric", label: sizeLabel(), num: true },
    { key: "score", label: "Score", num: true },
    { key: "owner", label: "Owner" },
    { key: "activity", label: "Activity", num: true },
    { key: "flags", label: "Flags" },
    { key: "proposed", label: "Proposed owner" },
  ];
  $("#accounts-table thead").innerHTML = `<tr>${cols.map((c) =>
    `<th class="${c.num ? "num" : ""} ${["flags", "proposed", "activity"].includes(c.key) ? "" : "sortable"}"
        data-key="${c.key}">${esc(c.label)}${state.sort.key === c.key
        ? (state.sort.dir === -1 ? " ▾" : " ▴") : ""}</th>`).join("")}</tr>`;
  $$("#accounts-table th.sortable").forEach((th) => {
    th.onclick = () => {
      const k = th.dataset.key;
      state.sort = state.sort.key === k
        ? { key: k, dir: -state.sort.dir } : { key: k, dir: k === "name" || k === "owner" ? 1 : -1 };
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
      <td>${r.proposed_owner
        ? `<span class="proposed ${esc(r.proposal_status)}">${esc(r.proposed_owner)}</span>
           <span class="cell-sub">${esc(r.proposal_status)}</span>` : "—"}</td>
    </tr>`;
  }).join("");
  $$("#accounts-table tbody tr").forEach((tr) => {
    tr.onclick = () => showDetail(tr.dataset.id);
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

function renderMoves() {
  const now = bookStats((r) => r.owner);
  const after = bookStats(effectiveOwner);
  $("#moves-balance").innerHTML = state.segments.map((seg) => {
    const b = now[seg.key], a = after[seg.key];
    if (!Object.keys(b.reps).length) return "";
    return `<div class="mini-balance">
      <span class="mini-seg">${esc(seg.label)}</span>
      <span class="balance-badge balance-${b.label}">now ${b.cv.toFixed(2)} ${b.label}</span>
      <span class="mini-arrow">→</span>
      <span class="balance-badge balance-${a.label}">approved ${a.cv.toFixed(2)} ${a.label}</span>
    </div>`;
  }).join("");

  const groups = [];

  // The double-allocation queue comes first: two reps on one company is a
  // data problem that changes who "owns" what, so resolving it before
  // rebalancing keeps the balance maths honest.
  const dupes = state.rows.filter((r) => num(r.double_allocated));
  if (dupes.length) {
    groups.push(`<div class="move-group">
      <h3 class="terr-h3">Double-allocated — resolve first
        <span class="group-count">${fmt(dupes.length)}</span></h3>
      <p class="eval-diag-sub">These CRM records resolve to the SAME company under different reps.
        The owner shown is whoever has the most activity; the others are listed beside them.
        Merge or reassign in your CRM — the balancer leaves these alone until you do.</p>
      <div class="table-wrap"><table class="move-table"><tbody>
        ${dupes.map((r) => `<tr>
          <td>${esc(r.name)}<span class="cell-sub">${esc(r.domain)}</span></td>
          <td>${esc(state.segLabel[r.account_segment] || "")}</td>
          <td class="num">${fmt(r.score, 1)}</td>
          <td>keeps <strong>${esc(r.owner || "—")}</strong>
            <span class="cell-sub">also owned by ${esc(r.other_owners || "—")}</span></td>
        </tr>`).join("")}
      </tbody></table></div></div>`);
  }

  for (const reason of ["misfit", "assign_unallocated", "assign_whitespace", "rebalance", "manual"]) {
    const rows = state.rows.filter((r) => r.proposal_reason === reason && r.proposed_owner);
    if (!rows.length) continue;
    rows.sort((a, b) => num(b.score) - num(a.score));
    const pending = rows.filter((r) => r.proposal_status === "suggested").length;
    groups.push(`<div class="move-group">
      <h3 class="terr-h3">${esc(REASON_LABELS[reason] || reason)}
        <span class="group-count">${fmt(rows.length)}</span>
        ${pending ? `<span class="group-pending">${fmt(pending)} undecided</span>` : ""}</h3>
      <p class="eval-diag-sub">${esc(REASON_HELP[reason] || "")}</p>
      <div class="table-wrap"><table class="move-table"><tbody>
        ${rows.map((r) => moveRow(r)).join("")}
      </tbody></table></div></div>`);
  }

  $("#moves-groups").innerHTML = groups.length ? groups.join("")
    : `<p class="empty-state">No moves proposed. Either the books are already balanced, or
        every out-of-balance account is being actively worked — which the planner will not touch.</p>`;

  $$("#moves-groups .decide-btn").forEach((btn) => {
    btn.onclick = (e) => { e.stopPropagation(); decide(btn.dataset.id, btn.dataset.status); };
  });
  $$("#moves-groups .owner-select").forEach((sel) => {
    sel.onchange = (e) => { e.stopPropagation(); decide(sel.dataset.id, "manual", sel.value); };
  });
  $$("#moves-groups .move-name").forEach((el) => {
    el.onclick = () => showDetail(el.dataset.id);
  });
}

function moveRow(r) {
  const st = r.proposal_status || "suggested";
  const acts = num(r.meetings) + num(r.calls) + num(r.emails_out);
  const options = state.reps
    .filter((rep) => rep.segment === r.account_segment)
    .map((rep) => `<option value="${esc(rep.name)}" ${rep.name === r.proposed_owner ? "selected" : ""}>${esc(rep.name)}</option>`)
    .join("");
  return `<tr class="move-row status-${esc(st)}">
    <td class="move-name" data-id="${esc(r.org_id)}">
      ${esc(r.name)}<span class="cell-sub">${esc(r.domain)} · score ${fmt(r.score, 1)} ·
      ${acts ? `${fmt(acts)} touches` : "no activity"}</span></td>
    <td class="move-arrow">${esc(r.owner || "unassigned")} <span class="arrow">→</span></td>
    <td>
      <select class="owner-select terr-select" data-id="${esc(r.org_id)}">
        <option value="">(keep ${esc(r.owner || "unassigned")})</option>
        ${options}
      </select>
    </td>
    <td class="move-actions">
      <button class="decide-btn btn-accept ${st === "accepted" ? "on" : ""}"
              data-id="${esc(r.org_id)}" data-status="${st === "accepted" ? "" : "accepted"}">Accept</button>
      <button class="decide-btn btn-reject ${st === "rejected" ? "on" : ""}"
              data-id="${esc(r.org_id)}" data-status="${st === "rejected" ? "" : "rejected"}">Reject</button>
    </td>
  </tr>`;
}

function renderExport() {
  const approved = state.rows.filter(isApproved);
  const pending = state.rows.filter((r) => r.proposal_status === "suggested").length;
  $("#export-summary").innerHTML = `
    <p><strong>${fmt(approved.length)}</strong> approved change${approved.length === 1 ? "" : "s"} ready to export.
    ${pending ? `<strong>${fmt(pending)}</strong> proposal${pending === 1 ? " is" : "s are"} still undecided.` : ""}</p>
    <p class="eval-diag-sub">actions.csv lists one row per owner change (from → to, with the reason
      and the evidence). Nothing is written to your CRM by this app — the export is the hand-off.</p>`;

  const cols = ["Account", "Segment", "From", "To", "Reason", "Score"];
  $("#export-table thead").innerHTML = `<tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr>`;
  $("#export-table tbody").innerHTML = approved.length ? approved.map((r) => `<tr>
      <td>${esc(r.name)}<span class="cell-sub">${esc(r.domain)}</span></td>
      <td>${esc(state.segLabel[r.account_segment] || r.account_segment)}</td>
      <td>${esc(r.owner || "(unassigned)")}</td>
      <td>${esc(r.proposed_owner)}</td>
      <td>${esc(REASON_LABELS[r.proposal_reason] || r.proposal_reason)}</td>
      <td class="num">${fmt(r.score, 1)}</td>
    </tr>`).join("")
    : `<tr><td colspan="${cols.length}" class="empty-state">Nothing approved yet — accept a move on the Moves tab.</td></tr>`;
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
  $("#detail-body").innerHTML = `
    <div class="detail-section">
      <h3>Owner</h3>
      <p>${esc(r.owner || "Nobody — this account is unallocated.")}
        ${num(r.double_allocated) ? `<br /><span class="flag-pill flag-bad">Also owned by ${esc(r.other_owners)}</span>` : ""}
        ${r.proposed_owner ? `<br />Proposed: <strong>${esc(r.proposed_owner)}</strong>
          (${esc(REASON_LABELS[r.proposal_reason] || r.proposal_reason)}, ${esc(r.proposal_status)})` : ""}</p>
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
  const proposals = state.rows.filter((r) => r.proposal_status === "suggested").length;
  $("#moves-badge").textContent = proposals ? String(proposals) : "";
  $("#moves-badge").classList.toggle("hidden", !proposals);
  if (state.tab === "overview") renderOverview();
  else if (state.tab === "reps") renderReps();
  else if (state.tab === "accounts") renderAccounts();
  else if (state.tab === "moves") renderMoves();
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
