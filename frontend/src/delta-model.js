/* The Delta Comparison sheet's arithmetic, with no React in it.

   The sheet is a pivot built by hand: paste the delta rows in, drop a pivot
   next to them, set the filters, read the grid. The rows are the evidence and
   the pivot is the answer, which is why they are two tabs here - the pivot
   with its filters, and the rows it was built from.

   Nothing is precomputed by the pipeline: it produces the delta rows and this
   builds the grid from them, so a filter takes effect immediately instead of
   asking the server for another shape. */

export const TOTAL = "Grand Total";

/* The columns the sheet's pivot filters on. Order is the sheet's. A column
   with only one value is not offered - a filter that cannot change anything is
   furniture. */
export const FILTERS = [
  { key: "Group", label: "Group" },
  { key: "Case_Validity", label: "Validity" },
  { key: "Lien Filed", label: "Lien filed" },
  { key: "Closing Order", label: "Closing order" },
  { key: "Type", label: "Type" },
];

const ALL = "(All)";
export { ALL };

/* What each filter can be set to, given the rows. Values are sorted, except
   Aging, which is an ordered scale and must not go alphabetical - "1-30,
   31-60, 61-90, 90+" is the reading order, and sorting it as text puts 90+
   in the middle. */
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

/* Rows that match every filter that is set. A filter left at (All) does not
   constrain - which is what makes the default view the whole sheet. */
export function applyFilters(rows, chosen) {
  const active = Object.entries(chosen ?? {}).filter(([, v]) => v && v !== ALL);
  if (!active.length) return rows ?? [];
  return (rows ?? []).filter((r) =>
    active.every(([key, value]) => String(r[key]) === String(value)));
}

/* Sum of Settlement Amount, Group down the side and Aging across the top -
   the sheet's pivot exactly.

   Aging columns are the buckets PRESENT in the filtered rows, in scale order:
   filtering to 90+ should leave one column, not four with three empty. */
export function pivotDelta(rows, { value = "Settlement_Amount" } = {}) {
  const present = new Set((rows ?? []).map((r) => r.Aging).filter(Boolean));
  const buckets = AGING_ORDER.filter((b) => present.has(b));
  /* Anything the data carries that is not one of the four known buckets still
     gets a column rather than being silently dropped into nothing. */
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
