// Delta Comparison pivot arithmetic, without React.
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
    out.push({ ...f, values: [ALL, ...values] });
  }
  return out;
}

// Rows that match every filter that is set.
export function applyFilters(rows, chosen) {
  const active = Object.entries(chosen ?? {}).filter(([, v]) => v && v !== ALL);
  if (!active.length) return rows ?? [];
  return (rows ?? []).filter((r) =>
    active.every(([key, value]) => String(r[key]) === String(value)));
}

// Sum of Settlement Amount, Group down the side and Aging across the top.
export function pivotDelta(rows, { value = "Settlement_Amount" } = {}) {
  const present = new Set((rows ?? []).map((r) => r.Aging).filter(Boolean));
  const buckets = AGING_ORDER.filter((b) => present.has(b));
  for (const b of present) if (!buckets.includes(b)) buckets.push(b);

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
  for (const b of buckets) total[b] = body.reduce((s, g) => s + (g[b] ?? 0), 0);
  total._total = body.reduce((s, g) => s + g._total, 0);
  total._cases = body.reduce((s, g) => s + g._cases, 0);

  return { buckets, rows: [...body, total] };
}
