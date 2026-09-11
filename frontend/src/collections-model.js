/* The Collection High-Level sheet's arithmetic, with no React in it.

   Kept apart from the rendering for the same reason the settlement model is:
   these are figures a client reads off a scorecard, and "it looked right on
   screen" is not a way to know a total is correct. */

export const TOTAL = "Total";

/* The sheet's four payment columns, in its order. BOARD REPS and IN HOUSE REPS
   are folded into SETTLEMENT upstream, so what arrives is already these four.
   The order is the sheet's and is not alphabetical - keep it. */
export const PAYMENT_TYPES = ["BILLING", "REBILLING", "APPEAL", "SETTLEMENT"];

/* Written out in full - see format.js, which is the one definition. */
export { weekLabel } from "./format.js";

/* Rows arrive as Group x Week x PaymentType x Payment - one row per cell of
   the grid, with nothing for a combination that saw no money.

   Out comes one row per group with a field per (week, type) and per week
   total, which is the shape the sheet prints: each week of the current month
   opened out into its four payment types and then totalled. */
export function pivotCollections(rows) {
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

  const body = Object.values(byGroup).sort((a, b) => b._total - a._total);
  /* No rows means no table. A Total row on its own reads as data - a month
     that collected nothing - when what actually happened is that the run has
     no collections at all, and the empty state is the honest thing to show. */
  if (!body.length) return { weeks, types, rows: [] };

  /* The Total row is a straight sum here, unlike Settlement's: every cell in
     this grid is money, and money adds up. There is no per cent to get wrong. */
  const total = { group: TOTAL, _total: 0 };
  for (const w of weeks) {
    for (const t of types) {
      total[`w${w}_${t}`] = body.reduce((s, g) => s + (g[`w${w}_${t}`] ?? 0), 0);
    }
    total[`w${w}`] = body.reduce((s, g) => s + (g[`w${w}`] ?? 0), 0);
    total._total += total[`w${w}`];
  }
  return { weeks, types, rows: [...body, total] };
}

/* The Collections Pace block. One row per group, one cell per week - the sheet
   paces a group's whole week, not each payment type separately. */
export function pivotCollectionsPace(pace) {
  const rows = pace ?? [];
  if (!rows.length) return { weeks: [], rows: [] };

  const weeks = [...new Set(rows.map((r) => r.bucket))]
    .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
  const byGroup = {};
  for (const r of rows) (byGroup[r.group] ??= { group: r.group })[r.bucket] = r.pace;

  const last = weeks[weeks.length - 1];
  const body = Object.values(byGroup).sort((a, b) => (b[last] ?? 0) - (a[last] ?? 0));
  const total = { group: TOTAL };
  for (const w of weeks) total[w] = body.reduce((s, g) => s + (g[w] ?? 0), 0);
  return { weeks, rows: [...body, total] };
}

/* The footer the sheet prints under the grid: what came in by payment type,
   across the whole month. */
export function paymentTypeTotals(rows) {
  const by = {};
  for (const r of rows ?? []) by[r.PT] = (by[r.PT] ?? 0) + (Number(r.Payment) || 0);
  const present = PAYMENT_TYPES.filter((t) => t in by);
  if (!present.length) return [];          // same reasoning as the grid above
  const out = present.map((pt) => ({ pt, payment: by[pt] }));
  const sum = out.reduce((s, r) => s + r.payment, 0);
  return [...out, { pt: TOTAL, payment: sum }];
}

/* Where the month is heading. Read off the LAST week alone: each week's pace
   already carries the whole month to date, so summing them counts the same
   money once per week. */
export function collectionsPaceTotal(pace) {
  const rows = pace ?? [];
  if (!rows.length) return null;
  const last = Math.max(...rows.map((r) => Number(r.bucket.slice(1))));
  return rows.filter((r) => Number(r.bucket.slice(1)) === last)
             .reduce((s, r) => s + r.pace, 0);
}

/* This month's collections, all groups, all types. */
export function collectionsToDate(rows) {
  return (rows ?? []).reduce((s, r) => s + (Number(r.Payment) || 0), 0);
}
