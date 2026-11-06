// The year's collections month by month (the table under the Collections tab), without React.
import { TOTAL, inSheetOrder, sumOf } from "./layout.js";
import { PAYMENT_TYPES } from "./collections-model.js";

export { TOTAL };

// One row per group: `m10` is a month's total, `m10w2` a week's, `m10w2_BILLING` a payment
// type's within that week, `_total` the year so far. Only months taken from a build have
// weeks (`weeksOf`) and types (`typesOf`, keyed "10-2"); the uploaded file's months are
// totals alone. Groups follow the sheet's `order`, then any others biggest first.
export function pivotHistory(h) {
  const months = (h?.months ?? []).map((m) => m.month).sort((a, b) => a - b);
  const blank = (group) => ({ group, _total: 0 });
  const byGroup = {};
  for (const t of h?.totals ?? []) {
    const g = (byGroup[t.group] ??= blank(t.group));
    g[`m${t.month}`] = (g[`m${t.month}`] ?? 0) + t.amount;
    g._total += t.amount;
  }

  const weeks = {};
  const types = {};
  for (const w of h?.weeks ?? []) {
    const g = (byGroup[w.group] ??= blank(w.group));
    const key = `m${w.month}w${w.week}`;
    g[key] = (g[key] ?? 0) + w.payment;
    g[`${key}_${w.pt}`] = (g[`${key}_${w.pt}`] ?? 0) + w.payment;
    (weeks[w.month] ??= new Set()).add(w.week);
    (types[`${w.month}-${w.week}`] ??= new Set()).add(w.pt);
  }
  const weeksOf = Object.fromEntries(Object.entries(weeks)
    .map(([m, set]) => [m, [...set].sort((a, b) => a - b)]));
  const typesOf = Object.fromEntries(Object.entries(types)
    .map(([k, set]) => [k, [...PAYMENT_TYPES.filter((t) => set.has(t)),
                            ...[...set].filter((t) => !PAYMENT_TYPES.includes(t)).sort()]]));

  if (!Object.keys(byGroup).length) return { months, weeksOf, typesOf, rows: [] };
  const body = inSheetOrder(
    Object.values(byGroup).sort((a, b) => b._total - a._total), h?.order ?? [], blank);

  const total = { group: TOTAL };
  const keys = new Set(body.flatMap((g) => Object.keys(g)).filter((k) => k !== "group"));
  for (const k of keys) total[k] = sumOf(body, k);
  return { months, weeksOf, typesOf, rows: [...body, total] };
}
