// Settlement High-Level arithmetic, without React.
import { TOTAL, inSheetOrder, sumOf } from "./layout.js";

export { TOTAL };

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

// One row per provider group, one cell per bucket, plus the two totals. Biggest first,
// or the workbook's `order` (see layout.js) when the build recorded one.
export function pivot(rows, totals, block, order = []) {
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
  const body = inSheetOrder(
    Object.values(byGroup).sort((a, b) => b._total - a._total), order,
    (group) => ({ group, _month: 0, _total: 0 }));

  const pctFor = {};
  for (const t of totals ?? []) {
    if (t.block === block) pctFor[t.bucket] = t.settlement_pct;
  }

  const total = { group: TOTAL, _month: 0, _total: 0 };
  for (const b of [...months, ...weeks]) {
    total[b] = sumOf(body, b);
    if (pctFor[b] != null) total[`${b}_pct`] = pctFor[b];
    total._total += total[b];
    if (isWeek(b)) total._month += total[b];
  }
  return { months, weeks, rows: [...body, total] };
}

// A closed month's weeks, for the months kept week by week: each row of `p` gains M10W1, M10W1_pct and so on, and `weeksOf` names each month's weeks.
export function withMonthWeeks(p, monthWeeks, block) {
  const mine = (monthWeeks ?? []).filter((r) => r.block === block);
  const weeksOf = {};
  for (const r of mine) (weeksOf[`M${r.month}`] ??= new Set()).add(r.bucket);
  for (const m of Object.keys(weeksOf)) {
    weeksOf[m] = [...weeksOf[m]].sort((a, b) => bucketNum(a) - bucketNum(b));
  }
  if (!mine.length) return { ...p, weeksOf };

  const byGroup = Object.fromEntries(p.rows.map((r) => [r.group, { ...r }]));
  const total = byGroup[TOTAL];
  for (const r of mine) {
    const key = `M${r.month}${r.bucket}`;
    const row = r.group == null ? total : byGroup[r.group];
    if (!row) continue;
    if (r.group != null) row[key] = (row[key] ?? 0) + r.amount;
    if (r.settlement_pct != null) row[`${key}_pct`] = r.settlement_pct;
  }
  if (total) {
    for (const [m, weeks] of Object.entries(weeksOf)) {
      for (const w of weeks) {
        total[`${m}${w}`] = p.rows.reduce(
          (s, g) => (g.group === TOTAL ? s : s + (byGroup[g.group][`${m}${w}`] ?? 0)), 0);
      }
    }
  }
  return { ...p, weeksOf, rows: p.rows.map((r) => byGroup[r.group]) };
}

// The Pace block: one row per group, one cell per week of the current month.
export function pivotPace(pace, block, order = []) {
  const mine = (pace ?? []).filter((r) => r.block === block);
  if (!mine.length) return { weeks: [], rows: [] };

  const weeks = [...new Set(mine.map((r) => r.bucket))]
    .sort((a, b) => bucketNum(a) - bucketNum(b));
  const byGroup = {};
  for (const r of mine) (byGroup[r.group] ??= { group: r.group })[r.bucket] = r.pace;

  const last = weeks[weeks.length - 1];
  const body = inSheetOrder(
    Object.values(byGroup).sort((a, b) => (b[last] ?? 0) - (a[last] ?? 0)), order,
    (group) => ({ group }));
  const total = { group: TOTAL };
  for (const w of weeks) total[w] = sumOf(body, w);
  return { weeks, rows: [...body, total] };
}

// CP Settled Cases as the All Providers workbook lays it out: one row, called `label`,
// with each month across the top as # of Cases, Outstanding and Settlement Amount, then
// the year's totals.
export function cpAcross(cp, label) {
  const mine = [...(cp ?? [])].sort((a, b) => a.month - b.month);
  if (!mine.length) return { months: [], rows: [] };
  const row = { group: label, _cases: 0, _outstanding: 0, _settled: 0 };
  for (const r of mine) {
    row[`m${r.month}_cases`] = r.cases;
    row[`m${r.month}_outstanding`] = r.outstanding;
    row[`m${r.month}_settled`] = r.settled;
    row._cases += r.cases;
    row._outstanding += r.outstanding;
    row._settled += r.settled;
  }
  return { months: mine.map((r) => r.month), rows: [row] };
}

// Where the month is heading, per block, for the tiles.
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

// This month's settled amount per block.
export function monthToDate(settlement) {
  const out = {};
  for (const r of settlement ?? []) {
    if (isWeek(r.bucket)) out[r.block] = (out[r.block] ?? 0) + r.amount;
  }
  return out;
}
