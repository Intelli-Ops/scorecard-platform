/* The Settlement sheet's arithmetic, with no React in it.

   Kept apart from the rendering so it can be run and checked on its own - the
   totals here are the numbers a client reads off a scorecard, and "it looked
   right on screen" is not a way to know they are correct. */

export const TOTAL = "Total";

/* Buckets are the pipeline's own: "M5" is the May total, "W2" is week 2 of
   the current month. Months run first in calendar order, then this month's
   weeks - which is exactly the order the columns go in. */
/* The blocks in the order the sheet prints them: In House, then Board, then
   anything else alphabetically. */
const BLOCK_ORDER = ["in house", "board"];
export function sortBlocks(names) {
  const rank = (n) => {
    const i = BLOCK_ORDER.indexOf(String(n).trim().toLowerCase());
    return i < 0 ? BLOCK_ORDER.length : i;
  };
  return [...names].sort((a, b) => rank(a) - rank(b) || String(a).localeCompare(String(b)));
}

export const isWeek = (b) => b.startsWith("W");
export const bucketNum = (b) => Number(b.slice(1));

export function splitBuckets(rows) {
  const all = [...new Set(rows.map((r) => r.bucket))];
  return {
    months: all.filter((b) => !isWeek(b)).sort((a, b) => bucketNum(a) - bucketNum(b)),
    weeks: all.filter(isWeek).sort((a, b) => bucketNum(a) - bucketNum(b)),
  };
}

/* One row per provider group, one cell per bucket, plus the two totals.

   `_month` is the current month: the sum of its weeks, not a bucket of its own
   - the pipeline never emits one, because the sheet builds it by adding the
   week columns up. `_total` is the year.

   The Total row's Settlement % is NOT the sum of the group percentages, and
   not their average either - it is the whole block's settled-plus-paid over
   its billed, which the pipeline works out separately. The amounts are summed
   here; the per cents come from settlement_totals, so nobody can total a
   column and get a different answer from the sheet. */
export function pivot(rows, totals, block) {
  const inBlock = rows.filter((r) => r.block === block);
  const { months, weeks } = splitBuckets(inBlock);

  const byGroup = {};
  for (const r of inBlock) {
    const g = (byGroup[r.group] ??= { group: r.group, _month: 0, _total: 0 });
    g[r.bucket] = (g[r.bucket] ?? 0) + r.amount;
    if (r.settlement_pct != null) g[`${r.bucket}_pct`] = r.settlement_pct;
    g._total += r.amount;
    if (isWeek(r.bucket)) g._month += r.amount;
  }
  const body = Object.values(byGroup).sort((a, b) => b._total - a._total);

  const pctFor = {};
  for (const t of totals ?? []) {
    if (t.block === block) pctFor[t.bucket] = t.settlement_pct;
  }

  const total = { group: TOTAL, _month: 0, _total: 0 };
  for (const b of [...months, ...weeks]) {
    total[b] = body.reduce((s, g) => s + (g[b] ?? 0), 0);
    if (pctFor[b] != null) total[`${b}_pct`] = pctFor[b];
    total._total += total[b];
    if (isWeek(b)) total._month += total[b];
  }
  return { months, weeks, rows: [...body, total] };
}

/* The Pace block: one row per group, one cell per week of the current month.

   Ordered by where the month is heading, which is the question the block is on
   screen to answer. */
export function pivotPace(pace, block) {
  const mine = (pace ?? []).filter((r) => r.block === block);
  if (!mine.length) return { weeks: [], rows: [] };

  const weeks = [...new Set(mine.map((r) => r.bucket))]
    .sort((a, b) => bucketNum(a) - bucketNum(b));
  const byGroup = {};
  for (const r of mine) (byGroup[r.group] ??= { group: r.group })[r.bucket] = r.pace;

  const last = weeks[weeks.length - 1];
  const body = Object.values(byGroup).sort((a, b) => (b[last] ?? 0) - (a[last] ?? 0));
  const total = { group: TOTAL };
  for (const w of weeks) total[w] = body.reduce((s, g) => s + (g[w] ?? 0), 0);
  return { weeks, rows: [...body, total] };
}

/* Where the month is heading, per block, for the tiles.

   Read off the LAST week only. Each week's pace already carries the whole
   month to date, so summing the weeks would count the same money four times. */
export function paceTotals(pace) {
  const latest = {};
  for (const r of pace ?? []) {
    latest[r.block] = Math.max(latest[r.block] ?? 0, bucketNum(r.bucket));
  }
  const out = {};
  for (const r of pace ?? []) {
    if (bucketNum(r.bucket) === latest[r.block]) {
      out[r.block] = (out[r.block] ?? 0) + r.pace;
    }
  }
  return out;
}

/* This month's settled amount per block: the current month is the weeks, so
   the tiles add those and nothing else. */
export function monthToDate(settlement) {
  const out = {};
  for (const r of settlement ?? []) {
    if (isWeek(r.bucket)) out[r.block] = (out[r.block] ?? 0) + r.amount;
  }
  return out;
}
