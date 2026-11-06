// The All Providers Delta Comparison sheet, without React.
import { TOTAL, inSheetOrder, sumOf } from "./layout.js";

export { TOTAL };

// Each month's three columns, as the sheet heads them, and the key each is kept under.
export const MEASURES = [
  { key: "total", label: "Total Settlement", year: "Total Settlements",
    from: "Total Settlement" },
  { key: "yes", label: "Pay Received - YES", year: "Total Pay Received - YES",
    from: "Pay Received - YES" },
  { key: "no", label: "Pay Received - NO", year: "Total Pay Received - NO",
    from: "Pay Received - NO" },
];

// Rows arrive as Group x Month x the three measures. Out come one row per group, the months
// January to `upTo` (or the last month with figures) across, the year's three totals, and a
// Total row. Groups follow the workbook's `order` when the build recorded one.
export function pivotDeltaComparison(rows, { order = [], upTo = 0 } = {}) {
  const all = rows ?? [];
  const last = Math.max(Number(upTo) || 0, ...all.map((r) => Number(r.Month) || 0));
  const months = Array.from({ length: last }, (_, i) => i + 1);

  const blank = (group) => ({ group, _total: 0, _yes: 0, _no: 0 });
  const byGroup = {};
  for (const r of all) {
    const g = (byGroup[r.Group] ??= blank(r.Group));
    for (const m of MEASURES) {
      const v = Number(r[m.from]) || 0;
      g[`m${r.Month}_${m.key}`] = (g[`m${r.Month}_${m.key}`] ?? 0) + v;
      g[`_${m.key}`] += v;
    }
  }
  if (!Object.keys(byGroup).length) return { months, rows: [] };

  const body = inSheetOrder(
    Object.values(byGroup).sort((a, b) => String(a.group).localeCompare(String(b.group))),
    order, blank);

  const total = { group: TOTAL };
  for (const key of [...months.flatMap((mo) => MEASURES.map((m) => `m${mo}_${m.key}`)),
                     ...MEASURES.map((m) => `_${m.key}`)]) {
    total[key] = sumOf(body, key);
  }
  return { months, rows: [...body, total] };
}
