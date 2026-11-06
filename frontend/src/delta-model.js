// Delta Comparison pivot arithmetic, without React.
import { sumOf } from "./layout.js";
export const TOTAL = "Grand Total";

export const FILTERS = [
  { key: "Group", label: "Group" },
  { key: "Case_Validity", label: "Validity" },
  { key: "Lien Filed", label: "Lien filed" },
  { key: "Closing Order", label: "Closing order" },
  { key: "Type", label: "Type" },
];

const ALL = "(All)";
export { ALL };

const AGING_ORDER = ["1-30", "31-60", "61-90", "90+"];

export function filterOptions(rows) {
  const out = [];
  for (const f of FILTERS) {
    const values = [...new Set((rows ?? []).map((r) => r[f.key])
      .filter((v) => v != null && v !== ""))];
    if (values.length < 2) continue;          // nothing to choose between
    values.sort(f.key === "Aging"
      ? (a, b) => AGING_ORDER.indexOf(a) - AGING_ORDER.indexOf(b)
      : (a, b) => String(a).localeCompare(String(b)));
    out.push({ ...f, values });
  }
  return out;
}

// A filter's chosen values as strings: one value or a list; (All) or nothing chooses none.
const wanted = (v) => (Array.isArray(v) ? v : v == null || v === "" ? [] : [v])
  .filter((x) => x !== ALL).map(String);

// Rows that match every filter that is set. A filter with several values keeps rows
// matching any one of them.
export function applyFilters(rows, chosen) {
  const active = Object.entries(chosen ?? {})
    .map(([key, v]) => [key, new Set(wanted(v))])
    .filter(([, values]) => values.size);
  if (!active.length) return rows ?? [];
  return (rows ?? []).filter((r) =>
    active.every(([key, values]) => values.has(String(r[key]))));
}

// Sum of Settlement Amount, Group down the side and Aging across the top.
export function pivotDelta(rows, { value = "Settlement_Amount" } = {}) {
  const buckets = agingBrackets(rows);

  const byGroup = {};
  for (const r of rows ?? []) {
    const group = r.Group ?? "(blank)";
    const g = (byGroup[group] ??= { group, _total: 0, _cases: 0 });
    const amount = Number(r[value]) || 0;
    g[r.Aging] = (g[r.Aging] ?? 0) + amount;
    g._total += amount;
    g._cases += 1;
  }

  const body = Object.values(byGroup).sort((a, b) => b._total - a._total);
  if (!body.length) return { buckets, rows: [] };

  const total = { group: TOTAL, _total: 0, _cases: 0 };
  for (const k of [...buckets, "_total", "_cases"]) total[k] = sumOf(body, k);

  return { buckets, rows: [...body, total] };
}

// The second pivot on the Delta Comparison sheet: Sum of Settlement Amount by Ongoing DOR
// Status, filtered on Aging. The workbook keeps that filter on 90+.
export const DOR = "Ongoing DOR Status";
export const DOR_AGING = ["90+"];
const BLANK = "(blank)";

// The Aging brackets these rows have, youngest first.
export function agingBrackets(rows) {
  const present = new Set((rows ?? []).map((r) => r.Aging).filter(Boolean));
  return [...AGING_ORDER.filter((b) => present.has(b)),
          ...[...present].filter((b) => !AGING_ORDER.includes(b)).sort()];
}

// One row per status with money in the chosen brackets (all of them when none is chosen),
// in the workbook's `order`; statuses it doesn't list follow A to Z, and (blank) comes last,
// as in Excel. Then the Grand Total.
export function pivotDor(rows, aging, order = [], { value = "Settlement_Amount" } = {}) {
  const keep = new Set(aging ?? []);
  const byStatus = new Map();
  for (const r of rows ?? []) {
    if (keep.size && !keep.has(r.Aging)) continue;
    const name = String(r[DOR] ?? "").trim() || BLANK;
    const row = byStatus.get(name) ?? { status: name, amount: 0, _cases: 0 };
    row.amount += Number(r[value]) || 0;
    row._cases += 1;
    byStatus.set(name, row);
  }
  if (!byStatus.size) return [];

  const key = (s) => String(s).split(/\s+/).filter(Boolean).join(" ").toLowerCase();
  const rank = new Map(order.map((s, i) => [key(s), i]));
  const place = (s) => (s === BLANK ? Infinity : rank.get(key(s)) ?? order.length);
  const body = [...byStatus.values()].sort((a, b) =>
    place(a.status) - place(b.status) || a.status.localeCompare(b.status));
  const total = { status: TOTAL, amount: 0, _cases: 0 };
  for (const r of body) { total.amount += r.amount; total._cases += r._cases; }
  return [...body, total];
}
