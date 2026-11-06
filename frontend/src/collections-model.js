// Collection High-Level arithmetic, without React.
import { TOTAL, inSheetOrder, sumOf } from "./layout.js";

export { TOTAL };

export const PAYMENT_TYPES = ["BILLING", "REBILLING", "APPEAL", "SETTLEMENT"];

export { weekLabel } from "./format.js";

// Rows arrive as Group x Week x PaymentType x Payment. Biggest first, or the
// workbook's `order` (see layout.js) when the build recorded one.
export function pivotCollections(rows, order = []) {
  const weeks = [...new Set((rows ?? []).map((r) => Number(r.Week)))]
    .sort((a, b) => a - b);
  const types = PAYMENT_TYPES.filter((t) =>
    (rows ?? []).some((r) => r.PT === t));

  const byGroup = {};
  for (const r of rows ?? []) {
    const g = (byGroup[r.Group] ??= { group: r.Group, _total: 0 });
    const payment = Number(r.Payment) || 0;
    g[`w${r.Week}_${r.PT}`] = (g[`w${r.Week}_${r.PT}`] ?? 0) + payment;
    g[`w${r.Week}`] = (g[`w${r.Week}`] ?? 0) + payment;      // the week's total
    g._total += payment;
  }

  if (!Object.keys(byGroup).length) return { weeks, types, rows: [] };
  const body = inSheetOrder(
    Object.values(byGroup).sort((a, b) => b._total - a._total), order,
    (group) => ({ group, _total: 0 }));

  const total = { group: TOTAL, _total: 0 };
  for (const w of weeks) {
    for (const t of types) {
      total[`w${w}_${t}`] = sumOf(body, `w${w}_${t}`);
    }
    total[`w${w}`] = sumOf(body, `w${w}`);
    total._total += total[`w${w}`];
  }
  return { weeks, types, rows: [...body, total] };
}

// The Collections Pace block.
export function pivotCollectionsPace(pace, order = []) {
  const rows = pace ?? [];
  if (!rows.length) return { weeks: [], rows: [] };

  const weeks = [...new Set(rows.map((r) => r.bucket))]
    .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
  const byGroup = {};
  for (const r of rows) (byGroup[r.group] ??= { group: r.group })[r.bucket] = r.pace;

  const last = weeks[weeks.length - 1];
  const body = inSheetOrder(
    Object.values(byGroup).sort((a, b) => (b[last] ?? 0) - (a[last] ?? 0)), order,
    (group) => ({ group }));
  const total = { group: TOTAL };
  for (const w of weeks) total[w] = sumOf(body, w);
  return { weeks, rows: [...body, total] };
}

// The footer the sheet prints under the grid.
export function paymentTypeTotals(rows) {
  const by = {};
  for (const r of rows ?? []) by[r.PT] = (by[r.PT] ?? 0) + (Number(r.Payment) || 0);
  const present = PAYMENT_TYPES.filter((t) => t in by);
  if (!present.length) return [];          // same reasoning as the grid above
  const out = present.map((pt) => ({ pt, payment: by[pt] }));
  const sum = sumOf(out, "payment");
  return [...out, { pt: TOTAL, payment: sum }];
}

// Where the month is heading.
export function collectionsPaceTotal(pace) {
  const rows = pace ?? [];
  if (!rows.length) return null;
  const last = Math.max(...rows.map((r) => Number(r.bucket.slice(1))));
  return rows.filter((r) => Number(r.bucket.slice(1)) === last)
             .reduce((s, r) => s + r.pace, 0);
}

// This month's collections, all groups, all types.
export function collectionsToDate(rows) {
  return (rows ?? []).reduce((s, r) => s + (Number(r.Payment) || 0), 0);
}
