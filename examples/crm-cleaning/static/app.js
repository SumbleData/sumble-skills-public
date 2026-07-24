/* CRM-cleaning review UI. Vanilla JS, no build step.
   State: findings (read-only, from analyze.py) + decisions (persisted via
   POST /api/decide on every click). */

"use strict";

const state = {
  findings: null,
  decisions: {},
  tab: "duplicates",
  confidence: new Set(), // empty = all
  status: new Set(), // empty = all; values: undecided|accept|reject|skip
  subtab: {}, // per-tab active sub-tab key (duplicates, parent_not_in_crm)
  search: "",
};

// Duplicate-cluster resolution buckets (set by analyze.py). Ordered hardest →
// easiest, matching the default finding order; one sub-tab each.
const CATEGORIES = [
  ["multi_owner", "Multiple owners"],
  ["split_activity", "Split activity"],
  ["concentrated", "Concentrated"],
];

// One-line work-queue description per bucket, shown under the sub-tab bar.
const CATEGORY_DESC = {
  multi_owner:
    "Different reps own the records — needs manual review and delicate " +
    "handling: decide who keeps the account before any merge.",
  split_activity:
    "One owner but CRM activity on more than one record — likely merge " +
    "candidates: merge into the primary so no history is lost.",
  concentrated:
    "One owner and activity on at most one record — the obvious delete " +
    "case: keep the populated record, drop the empty shells.",
};

// Sub-tabs inside Parents-not-in-CRM: conventional parent/subsidiary
// roll-ups vs private-equity portfolio roll-ups.
const PARENT_SUBTABS = [
  ["conventional", "Parent/sub roll-ups"],
  ["pe", "PE roll-ups"],
];
const PARENT_SUBTAB_DESC = {
  conventional:
    "Conventional parent/subsidiary roll-ups — the parent company is " +
    "missing from the CRM; accept to create it and link the children.",
  pe:
    "Private-equity portfolio roll-ups — the owning PE firm is not in the " +
    "CRM. Portfolio companies usually run as independent accounts; create " +
    "the parent only if you sell across the whole portfolio.",
};

const $ = (sel) => document.querySelector(sel);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

async function init() {
  const resp = await fetch("/api/data");
  const data = await resp.json();
  state.findings = data.findings;
  state.decisions = data.decisions || {};
  const company = state.findings.meta.company;
  if (company) $("#company-name").textContent = company;
  else {
    $("#company-name").remove();
    $("#company-dot").remove();
  }
  renderSummary();
  renderChips();
  bindToolbar();
  renderSubtabs();
  render();
}

/* ---------- data helpers ---------- */

function tabItems(tab) {
  const f = state.findings;
  if (tab === "duplicates") return f.duplicates;
  if (tab === "parent_sub") return f.parent_sub;
  if (tab === "parent_not_in_crm") return f.parent_not_in_crm;
  return f.unmatched.map((a, i) => ({
    id: `um_${i}`,
    confidence: "info",
    accounts: [a],
    unmatched: true,
  }));
}

/* Sub-tab definitions for the tabs that split into sub-lists: Duplicates by
   resolution bucket, Parents-not-in-CRM by conventional vs PE roll-up.
   Returns [key, label, count] triples; empty buckets are dropped, and a tab
   with no populated buckets shows no sub-tab bar at all (e.g. an old
   findings.json without categories, or a default run with no PE parents). */
function subtabsFor(tab) {
  const defs =
    tab === "duplicates" ? CATEGORIES : tab === "parent_not_in_crm" ? PARENT_SUBTABS : [];
  return defs
    .map(([key, label]) => [key, label, subtabItems(tab, key).length])
    .filter(([, , n]) => n);
}

function subtabItems(tab, sub) {
  const items = tabItems(tab);
  if (!sub) return items;
  if (tab === "duplicates") return items.filter((d) => d.category === sub);
  if (tab === "parent_not_in_crm")
    return items.filter((g) =>
      sub === "pe" ? g.parent_org.is_pe_firm : !g.parent_org.is_pe_firm
    );
  return items;
}

function activeSubtab(tab) {
  const subs = subtabsFor(tab);
  if (!subs.length) return null;
  const cur = state.subtab[tab];
  return subs.some(([key]) => key === cur) ? cur : subs[0][0];
}

function decisionOf(id) {
  const d = state.decisions[id] || {};
  // Duplicates have no accept/reject/skip — their status is derived from the
  // per-record actions: a chosen primary = resolved, "not a duplicate" =
  // dismissed. Other tabs still use an explicit decision.
  if (typeof id === "string" && id.startsWith("dup_")) {
    if (d.dismissed) return "reject";
    const ra = d.record_actions || {};
    return Object.values(ra).includes("primary") ? "accept" : "undecided";
  }
  return d.decision || "undecided";
}

function reviewable() {
  const f = state.findings;
  return [...f.duplicates, ...f.parent_sub, ...f.parent_not_in_crm];
}

function findingText(item) {
  const parts = [];
  const push = (a) => {
    if (!a) return;
    parts.push(
      a.crm_account_id, a.crm_name, a.crm_domain, a.sumble_name,
      a.crm_city, a.crm_state, a.crm_country
    );
  };
  (item.accounts || []).forEach(push);
  push(item.child);
  push(item.suggested_parent);
  push(item.current_parent);
  if (item.parent_org) parts.push(item.parent_org.name, item.parent_org.domain);
  (item.children || []).forEach(push);
  return parts.join(" ").toLowerCase();
}

/* ---------- rendering ---------- */

function renderSummary() {
  const m = state.findings.meta;
  const peCount = subtabItems("parent_not_in_crm", "pe").length;
  const cards = [
    [m.accounts_total, "CRM accounts"],
    [m.accounts_matched, "matched to Sumble"],
    [m.duplicate_clusters, "duplicate clusters"],
    [m.parent_sub_findings, "hierarchy gaps"],
    [subtabItems("parent_not_in_crm", "conventional").length, "parents not in CRM"],
    ...(peCount ? [[peCount, "PE roll-ups"]] : []),
    [m.accounts_unmatched, "unmatched"],
  ];
  $("#summary").innerHTML = cards
    .map(
      ([num, label]) =>
        `<div class="card"><div class="num">${num}</div>` +
        `<div class="label">${label}</div></div>`
    )
    .join("");
  document.querySelectorAll(".tab").forEach((btn) => {
    if (btn.dataset.tab === "export") return; // the review tab carries no count
    const n = tabItems(btn.dataset.tab).length;
    btn.innerHTML = `${btn.textContent.replace(/\d+$/, "")}` +
      `<span class="count">${n}</span>`;
  });
  renderProgress();
}

function renderProgress() {
  const all = reviewable();
  const done = all.filter((f) => decisionOf(f.id) !== "undecided").length;
  $("#progress").textContent = `${done} of ${all.length} reviewed`;
}

function renderChips() {
  // Only offer the confidence levels that actually occur in the findings.
  // "high" is the default state and "info" just marks the FYI tabs, so
  // neither gets a chip — filter to the exceptions (medium/low) instead.
  const present = new Set(
    ["duplicates", "parent_sub", "parent_not_in_crm", "unmatched"]
      .flatMap((t) => tabItems(t))
      .map((item) => item.confidence)
  );
  const conf = ["medium", "low"].filter((c) => present.has(c));
  $("#confidence-chips").innerHTML = conf
    .map((c) => `<button class="chip" data-conf="${c}">${c}</button>`)
    .join("");
  const stat = ["undecided", "accept", "reject", "skip"];
  $("#status-chips").innerHTML = stat
    .map((s) => `<button class="chip" data-status="${s}">${s}</button>`)
    .join("");
}

/* Sub-tab bar for the tabs that split into sub-lists, with a one-line
   description of the active sub-tab underneath. Hidden on tabs without
   sub-lists. */
function renderSubtabs() {
  const box = $("#subtabs");
  const subs = subtabsFor(state.tab);
  if (!subs.length) {
    box.innerHTML = "";
    box.style.display = "none";
    return;
  }
  const active = activeSubtab(state.tab);
  const desc =
    state.tab === "duplicates"
      ? CATEGORY_DESC[active]
      : PARENT_SUBTAB_DESC[active];
  box.style.display = "";
  box.innerHTML =
    `<div class="subtab-row">` +
    subs
      .map(
        ([key, label, n]) =>
          `<button class="subtab cat-${key}${key === active ? " active" : ""}" ` +
          `data-subtab="${key}">${label}<span class="count">${n}</span></button>`
      )
      .join("") +
    `</div>` +
    (desc ? `<div class="subtab-desc">${desc}</div>` : "");
}

function bindToolbar() {
  document.querySelectorAll(".tab").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.tab = btn.dataset.tab;
      document
        .querySelectorAll(".tab")
        .forEach((b) => b.classList.toggle("active", b === btn));
      renderSubtabs();
      render();
    })
  );
  $("#subtabs").addEventListener("click", (e) => {
    const s = e.target.closest(".subtab")?.dataset?.subtab;
    if (!s) return;
    state.subtab[state.tab] = s;
    renderSubtabs();
    render();
  });
  $("#confidence-chips").addEventListener("click", (e) => {
    const c = e.target.dataset?.conf;
    if (!c) return;
    state.confidence.has(c) ? state.confidence.delete(c) : state.confidence.add(c);
    e.target.classList.toggle("active");
    render();
  });
  $("#status-chips").addEventListener("click", (e) => {
    const s = e.target.dataset?.status;
    if (!s) return;
    state.status.has(s) ? state.status.delete(s) : state.status.add(s);
    e.target.classList.toggle("active");
    render();
  });
  $("#search").addEventListener("input", (e) => {
    state.search = e.target.value.toLowerCase();
    render();
  });
  $("#export-btn").addEventListener("click", () => {
    window.location.href = "/api/export";
  });
}

function render() {
  // The review tab is a different beast — an inventory of the changes to export,
  // not a finding queue — so the finding filters don't apply to it.
  const isExport = state.tab === "export";
  const toolbar = $(".toolbar");
  if (toolbar) toolbar.style.display = isExport ? "none" : "";
  if (isExport) {
    renderExport();
    return;
  }
  const items = subtabItems(state.tab, activeSubtab(state.tab)).filter((item) => {
    if (state.confidence.size && !state.confidence.has(item.confidence)) return false;
    if (!item.unmatched && state.status.size && !state.status.has(decisionOf(item.id)))
      return false;
    if (state.search && !findingText(item).includes(state.search)) return false;
    return true;
  });
  const main = $("#findings");
  if (!items.length) {
    main.innerHTML = `<div class="empty">Nothing to show with the current filters.</div>`;
    return;
  }
  main.innerHTML = items.map(renderFinding).join("");
  bindFindingEvents(main);
}

/* ---------- review / export inventory ---------- */

// How each action row reads in the inventory. `detail(row)` renders the
// target/new-parent for that action type.
const ACTION_META = {
  merge: {
    label: "Merge",
    cls: "act-merge",
    detail: (a) => `→ into <b>${esc(a.target_account_name)}</b>` +
      `<span class="dim"> ${esc(a.target_account_id)}</span>`,
  },
  delete: {
    label: "Delete",
    cls: "act-delete",
    detail: () => `<span class="dim">remove this record</span>`,
  },
  set_parent: {
    label: "Set parent",
    cls: "act-parent",
    detail: (a) => `→ parent <b>${esc(a.target_account_name)}</b>` +
      `<span class="dim"> ${esc(a.target_account_id)}</span>`,
  },
  create_parent_and_link: {
    label: "Create parent + link",
    cls: "act-create",
    detail: (a) => `→ new parent <b>${esc(a.suggested_new_account_name)}</b>` +
      (a.suggested_new_account_domain
        ? `<span class="dim"> (${esc(a.suggested_new_account_domain)})</span>` : ""),
  },
};

/* Inventory every CRM change the accepted findings imply — the exact rows
   actions.csv will contain — so the user can see and sanity-check the whole
   plan in one place before exporting. Nothing here writes to the CRM. */
async function renderExport() {
  const main = $("#findings");
  main.innerHTML = `<div class="empty">Gathering changes…</div>`;
  let actions = [];
  try {
    const resp = await fetch("/api/actions");
    actions = (await resp.json()).actions || [];
  } catch (e) {
    main.innerHTML = `<div class="empty">Could not load changes: ${esc(String(e))}</div>`;
    return;
  }
  if (state.tab !== "export") return; // user switched away while fetching

  const byType = {};
  actions.forEach((a) => { byType[a.action] = (byType[a.action] || 0) + 1; });
  const chips = Object.entries(byType)
    .map(([t, n]) => `<span class="act-tag ${ACTION_META[t]?.cls || ""}">` +
      `${esc(ACTION_META[t]?.label || t)} <b>${n}</b></span>`)
    .join("");

  const head =
    `<div class="export-head">` +
    `<div><h2 class="export-title">${actions.length} CRM change` +
    `${actions.length === 1 ? "" : "s"} to make</h2>` +
    `<p class="dim">One row per change implied by the findings you accepted — ` +
    `the exact contents of actions.csv. This app never writes to your CRM; the ` +
    `export is the hand-off.</p>` +
    (chips ? `<div class="act-tags">${chips}</div>` : "") + `</div>` +
    `<button class="btn-download" id="export-btn-2">Download actions.csv</button>` +
    `</div>`;

  if (!actions.length) {
    main.innerHTML = head +
      `<div class="empty">No changes yet — accept a duplicate resolution or a ` +
      `hierarchy fix on the other tabs and they'll appear here.</div>`;
    $("#export-btn-2").addEventListener("click", () => { window.location.href = "/api/export"; });
    return;
  }

  const order = ["merge", "delete", "set_parent", "create_parent_and_link"];
  actions.sort((a, b) =>
    (order.indexOf(a.action) - order.indexOf(b.action)) ||
    String(a.account_name).localeCompare(String(b.account_name)));

  const rows = actions.map((a) => {
    const m = ACTION_META[a.action] || { label: a.action, cls: "", detail: () => "" };
    return `<tr>` +
      `<td><span class="act-tag ${m.cls}">${esc(m.label)}</span></td>` +
      `<td><b>${esc(a.account_name)}</b><div class="dim">${esc(a.account_id)}</div></td>` +
      `<td>${m.detail(a)}</td>` +
      `<td class="dim">${esc(a.confidence || "")}</td>` +
      `<td class="dim">${esc(a.note || "")}</td>` +
      `</tr>`;
  }).join("");

  main.innerHTML = head +
    `<div class="export-table-wrap"><table class="acct-table export-table">` +
    `<tr><th>Change</th><th>CRM account</th><th>Detail</th><th>Confidence</th>` +
    `<th>Note</th></tr>${rows}</table></div>`;
  $("#export-btn-2").addEventListener("click", () => { window.location.href = "/api/export"; });
}

/* One line under the finding head listing every DISTINCT Sumble org the
   finding's accounts matched — org name links to sumble_url, Sumble's own
   domain in parens. Keeps the table CRM-only while the match stays visible. */
function sumbleMatchLine(item) {
  const accts = [
    ...(item.accounts || []),
    item.child,
    item.suggested_parent,
    item.current_parent,
    ...(item.children || []),
  ].filter(Boolean);
  const orgs = new Map();
  let unmatched = 0;
  accts.forEach((a) => {
    if (a.org_id) {
      if (!orgs.has(a.org_id)) orgs.set(a.org_id, a);
    } else unmatched += 1;
  });
  if (!orgs.size) return "";
  const parts = [...orgs.values()].map((a) => {
    const name = a.sumble_url
      ? `<a href="${esc(a.sumble_url)}" target="_blank" rel="noopener">` +
        `${esc(a.sumble_name)} ↗</a>`
      : esc(a.sumble_name);
    const nameChip = altChip(a.sumble_name_alternates, "Also known as", false);
    const dom = a.sumble_domain
      ? ` <span class="dim">(${esc(a.sumble_domain)}` +
        `${altChip(a.sumble_url_alternates, "Alternate domains", true)})</span>`
      : altChip(a.sumble_url_alternates, "Alternate domains", true);
    return `<span>${name}${nameChip}${dom}</span>`;
  });
  const tail = unmatched
    ? ` <span class="dim">· ${unmatched} account${unmatched > 1 ? "s" : ""} not matched</span>`
    : "";
  const label = orgs.size > 1 ? "Sumble matches" : "Sumble match";
  return `<div class="sumble-match">${label}: ${parts.join(" · ")}${tail}</div>`;
}

/* Alternate names/domains Sumble knows for a matched org (from the optional
   org_alternates.json sidecar): a "+N" chip that reveals the FULL list in a
   popover on hover/focus — domains rendered as links. */
function altChip(list, label, linkify) {
  if (!list || !list.length) return "";
  const items = list
    .map((v) => {
      if (!linkify) return `<li>${esc(v)}</li>`;
      const href = /^https?:\/\//i.test(v) ? v : `https://${v}`;
      return (
        `<li><a href="${esc(href)}" target="_blank" rel="noopener">` +
        `${esc(v)} ↗</a></li>`
      );
    })
    .join("");
  return (
    `<span class="alt-pop"><button type="button" class="alt-chip" ` +
    `aria-label="${list.length} ${esc(label).toLowerCase()}">+${list.length}</button>` +
    `<div class="alt-list"><div class="alt-list-label">${esc(label)}</div>` +
    `<ul>${items}</ul></div></span>`
  );
}

function acctCells(a) {
  const emp = a.employee_count_int
    ? Number(a.employee_count_int).toLocaleString()
    : "";
  const loc = [a.crm_city, a.crm_state, a.crm_country].filter(Boolean).join(", ");
  const mod = (a.crm_last_modified || "").slice(0, 10);
  const li = a.crm_linkedin_url
    ? `<a href="${esc(a.crm_linkedin_url)}" target="_blank" rel="noopener">LinkedIn ↗</a>`
    : "";
  const metaLine =
    li || mod
      ? `<div class="dim">${li}${li && mod ? " · " : ""}` +
        `${mod ? `modified ${esc(mod)}` : ""}</div>`
      : "";
  const name = a.crm_url
    ? `<a href="${esc(a.crm_url)}" target="_blank" rel="noopener">` +
      `<b>${esc(a.crm_name)}</b> ↗</a>`
    : `<b>${esc(a.crm_name)}</b>`;
  const fp = state.findings.meta.has_crm_counts
    ? `<td class="dim">${footprintText(a)}</td>`
    : "";
  const locCell = state.findings.meta.has_crm_meta
    ? `<td class="dim">${esc(loc)}</td>`
    : "";
  return (
    `<td>${name}` +
    `<div class="dim">${esc(a.crm_account_id)}</div>${metaLine}</td>` +
    `<td class="dim">${esc(a.crm_domain)}</td>` +
    locCell +
    `<td class="dim">${esc(a.owner || "")}${a.is_customer ? " · customer" : ""}</td>` +
    fp +
    `<td class="dim">${emp}</td>` +
    `<td class="dim">${esc(a.headquarters_country)}</td>`
  );
}

/* How much CRM history a record carries — the signal for "which record is
   primary" when merging. Zeros are dropped; all-zero shows a dash. */
function footprintText(a) {
  const n = (v) => Number(v) || 0;
  const parts = [];
  if (n(a.contact_count))
    parts.push(`${n(a.contact_count)} contact${n(a.contact_count) > 1 ? "s" : ""}`);
  if (n(a.opportunity_count))
    parts.push(`${n(a.opportunity_count)} opp${n(a.opportunity_count) > 1 ? "s" : ""}`);
  if (n(a.activity_count))
    parts.push(
      `${n(a.activity_count)} activit${n(a.activity_count) > 1 ? "ies" : "y"}`
    );
  return parts.join(" · ") || "—";
}

function acctHead() {
  const fp = state.findings.meta.has_crm_counts ? `<th>CRM footprint</th>` : "";
  const loc = state.findings.meta.has_crm_meta ? `<th>CRM location</th>` : "";
  return (
    `<tr><th>CRM account</th><th>CRM domain</th>${loc}<th>Owner</th>` +
    fp + `<th>Employees</th><th>Sumble HQ</th></tr>`
  );
}

function renderFinding(item) {
  if (state.tab === "unmatched") return renderUnmatched(item);
  const dec = decisionOf(item.id);
  const head =
    `<div class="finding-head">` +
    (item.confidence === "info"
      ? ""
      : `<span class="badge ${item.confidence}">${item.confidence}</span>`) +
    `<span class="finding-title">${titleOf(item)}</span>` +
    (item.evidence || [])
      .map((e) => `<span class="badge evidence">${esc(e)}</span>`)
      .join("") +
    `<span class="finding-id">${item.id}</span></div>`;
  const note = item.note
    ? `<div class="note-line">${esc(item.note)}</div>`
    : "";
  let body = "";
  let footer = "";
  if (state.tab === "duplicates") {
    body = dupBody(item);
    footer = dupFooter(item, dec);
  } else if (state.tab === "parent_sub") {
    body = psBody(item);
    footer = decideRow(item, dec);
  } else {
    body = pxBody(item);
    footer = decideRow(item, dec);
  }
  return (
    `<div class="finding decided-${dec}" data-id="${item.id}">` +
    head + sumbleMatchLine(item) + note + body + footer + `</div>`
  );
}

function titleOf(item) {
  if (state.tab === "duplicates")
    return `${item.accounts.length} accounts look like the same company`;
  if (state.tab === "parent_sub")
    return item.type === "parent_conflict"
      ? "CRM parent conflicts with Sumble hierarchy"
      : "Missing parent link";
  if (item.parent_org?.is_pe_firm)
    return `PE-firm parent not in CRM — ${esc(item.parent_org.name)}`;
  return `Parent company not in CRM — ${esc(item.parent_org.name)}`;
}

function dupBody(item) {
  const actions = (state.decisions[item.id] || {}).record_actions || {};
  const primaryId = Object.keys(actions).find((k) => actions[k] === "primary") || "";
  const hasPrimary = !!primaryId;
  const suggested = item.suggested_survivor_crm_id;
  const rows = item.accounts
    .map((a) => {
      const cid = a.crm_account_id;
      const act = actions[cid] || "";
      const isPrimary = act === "primary";
      const sugg =
        !hasPrimary && cid === suggested
          ? `<div class="dim sugg">suggested primary</div>`
          : "";
      // Primary is pickable until one is chosen; once a primary exists, only
      // the other records can be merged or deleted.
      const mk = (val, label, enabled, title) =>
        `<button type="button" class="rec-act rec-${val}` +
        `${act === val ? " on" : ""}"${enabled ? "" : " disabled"} ` +
        `data-act="${val}" title="${esc(title)}">${label}</button>`;
      const primaryEnabled = !hasPrimary || isPrimary;
      const mdEnabled = hasPrimary && !isPrimary;
      return (
        `<tr><td><div class="rec-actions" data-cid="${esc(cid)}">` +
        mk("primary", "Primary", primaryEnabled, "Keep this record as the survivor") +
        mk("merge", "Merge", mdEnabled, "Merge this record into the primary") +
        mk("delete", "Delete", mdEnabled, "Delete this record outright") +
        `</div>${sugg}</td>` +
        acctCells(a) +
        `</tr>`
      );
    })
    .join("");
  const help = hasPrimary
    ? `Each other record will <b>merge</b> into the primary — switch any to ` +
      `<b>Delete</b> to remove it instead.`
    : `Pick the record to keep as <b>Primary</b>; the others then become ` +
      `merge or delete.`;
  return (
    `<table class="acct-table"><tr><th title="What to do with each record">` +
    `Action</th>` +
    acctHead().slice(4) + rows + `</table>` +
    `<div class="dim chain">${dupCategoryHint(item)} ${help}</div>`
  );
}

/* One-line triage hint per resolution bucket, shown above the record actions. */
function dupCategoryHint(item) {
  if (!item.category) return ""; // older findings.json without categories
  if (item.category === "multi_owner") {
    const owners = (item.owners || []).join(", ");
    return (
      `<b>Multiple owners</b>${owners ? ` (${esc(owners)})` : ""} — decide who ` +
      `keeps the account before merging.`
    );
  }
  if (item.category === "split_activity")
    return (
      `<b>Split activity</b> — CRM history sits on more than one record; merge ` +
      `into the primary so none is lost.`
    );
  return (
    `<b>Concentrated</b> — history sits on one record; keep it and drop the ` +
    `empty shells.`
  );
}

function dupFooter(item, dec) {
  const note = esc((state.decisions[item.id] || {}).note || "");
  return (
    `<div class="decide">` +
    `<button class="btn dismiss ${dec === "reject" ? "on" : ""}" ` +
    `data-dismiss title="These are not actually the same company">` +
    `Not a duplicate</button>` +
    `<input class="note-input" placeholder="Note (optional)" value="${note}" />` +
    `</div>`
  );
}

function psBody(item) {
  const rows = [
    ["child", "Child", item.child],
    ["parent", "Suggested parent", item.suggested_parent],
    ["conflict", "Current CRM parent", item.current_parent],
  ]
    .filter(([, , a]) => a)
    .map(
      ([cls, label, a]) =>
        `<tr><td><span class="role-tag ${cls}">${label}</span></td>` +
        acctCells(a) + `</tr>`
    )
    .join("");
  const chain = item.chain && item.chain.length
    ? `<div class="chain">Sumble hierarchy: <b>${item.chain.map(esc).join(" → ")}</b></div>`
    : "";
  return `${chain}<table class="acct-table"><tr><th></th>${acctHead().slice(4)}${rows}</table>`;
}

function pxBody(item) {
  const p = item.parent_org;
  const emp = p.employee_count_int
    ? Number(p.employee_count_int).toLocaleString()
    : "";
  const head =
    `<div class="chain">Suggested new parent account: <b>${esc(p.name)}</b>` +
    altChip(p.name_alternates, "Also known as", false) +
    ` (${esc(p.domain)}${altChip(p.url_alternates, "Alternate domains", true)}` +
    `${emp ? `, ${emp} employees` : ""}) ` +
    (p.sumble_url
      ? `<a href="${esc(p.sumble_url)}" target="_blank" rel="noopener">Sumble ↗</a>`
      : "") +
    `</div>`;
  const rows = item.children
    .map(
      (a) =>
        `<tr><td><span class="role-tag child">Child</span></td>` +
        acctCells(a) + `</tr>`
    )
    .join("");
  return `${head}<table class="acct-table"><tr><th></th>${acctHead().slice(4)}${rows}</table>`;
}

function renderUnmatched(item) {
  const a = item.accounts[0];
  const name = a.crm_url
    ? `<a href="${esc(a.crm_url)}" target="_blank" rel="noopener">` +
      `${esc(a.crm_name)} ↗</a>`
    : esc(a.crm_name);
  return (
    `<div class="finding"><div class="finding-head">` +
    `<span class="badge info">no match</span>` +
    `<span class="finding-title">${name}</span>` +
    `<span class="finding-id">${esc(a.crm_account_id)}</span></div>` +
    `<div class="dim chain">${esc(a.crm_domain || "no domain")} — not matched to ` +
    `any Sumble org (often shells, typos, or very small entities; also worth a ` +
    `look when cleaning).</div></div>`
  );
}

function decideRow(item, dec) {
  const note = esc((state.decisions[item.id] || {}).note || "");
  return (
    `<div class="decide">` +
    `<button class="btn accept ${dec === "accept" ? "on" : ""}" data-d="accept">Accept</button>` +
    `<button class="btn reject ${dec === "reject" ? "on" : ""}" data-d="reject">Reject</button>` +
    `<button class="btn skip ${dec === "skip" ? "on" : ""}" data-d="skip">Skip</button>` +
    `<input class="note-input" placeholder="Note (optional)" value="${note}" />` +
    `</div>`
  );
}

/* ---------- events ---------- */

function bindFindingEvents(main) {
  main.querySelectorAll(".finding[data-id]").forEach((el) => {
    const id = el.dataset.id;
    el.querySelectorAll(".decide .btn[data-d]").forEach((btn) =>
      btn.addEventListener("click", () => {
        const current = decisionOf(id);
        const next = current === btn.dataset.d ? null : btn.dataset.d;
        decide(id, { decision: next });
      })
    );
    const dismissBtn = el.querySelector(".decide .btn[data-dismiss]");
    if (dismissBtn)
      dismissBtn.addEventListener("click", () => {
        const dismiss = decisionOf(id) !== "reject";
        decide(id, dismiss ? { dismissed: true, record_actions: {} } : { dismissed: false });
      });
    const noteEl = el.querySelector(".note-input");
    if (noteEl)
      noteEl.addEventListener("change", () =>
        decide(id, { note: noteEl.value }, false)
      );
    el.querySelectorAll(".rec-act").forEach((btn) =>
      btn.addEventListener("click", () => {
        if (btn.disabled) return;
        const cid = btn.closest(".rec-actions").dataset.cid;
        setRecordAction(id, cid, btn.dataset.act);
      })
    );
  });
}

/* Set a duplicate record's action. Picking Primary makes that record the
   survivor and defaults every other record to Merge; re-clicking the active
   Primary clears the whole cluster (back to undecided). With a primary set,
   the other records toggle between Merge and Delete. */
function setRecordAction(fid, cid, act) {
  const dup = (state.findings.duplicates || []).find((d) => d.id === fid);
  const ids = dup ? dup.accounts.map((a) => a.crm_account_id) : [cid];
  let cur = { ...((state.decisions[fid] || {}).record_actions || {}) };
  if (act === "primary") {
    if (cur[cid] === "primary") cur = {};
    else {
      cur = {};
      ids.forEach((id) => (cur[id] = id === cid ? "primary" : "merge"));
    }
  } else {
    cur[cid] = act; // merge / delete (only reachable once a primary exists)
  }
  decide(fid, { record_actions: cur, dismissed: false });
}

async function decide(id, payload, rerender = true) {
  if (payload.decision === "undecided") payload.decision = null;
  const resp = await fetch("/api/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ finding_id: id, ...payload }),
  });
  const data = await resp.json();
  if (data.decisions) state.decisions = data.decisions;
  renderProgress();
  if (rerender) render();
}

init();
