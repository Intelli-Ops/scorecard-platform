// KPI High-Level arithmetic, without React.
import { monthName } from "./format.js";
import { TOTAL, inSheetOrder, rowsOf, sumOf } from "./layout.js";

export { TOTAL };

// The block order for a build that recorded none.
const ORDER = ["sbr", "pmr", "ddel", "ntp", "medical index", "dor",
               "med legal", "enforcement of agreement", "dde"];

function ranker(layout) {
  const sheet = rowsOf(layout, "kpi").map((n) => String(n).trim().toLowerCase());
  if (sheet.length) {
    return (name) => {
      const i = sheet.indexOf(String(name).trim().toLowerCase());
      return i < 0 ? sheet.length : i;
    };
  }
  return (name) => {
    const n = String(name).trim().toLowerCase();
    const i = ORDER.indexOf(/\(ddel\)/.test(n) ? "ddel" : n);
    return i < 0 ? ORDER.length : i;
  };
}

// A run's KPI figures may carry a month.
function monthsOf(rows, fallback) {
  const named = [...new Set(rows.map((r) => r.month).filter((m) => m != null))];
  if (!named.length) return [{ key: "value", label: fallback ?? "Value" }];
  return named.sort((a, b) => a - b)
    .map((m) => ({ key: `m${m}`, label: monthName(m), month: m }));
}

// One table per block, each with a Total row. Blocks and their rows follow the workbook
// when the build recorded its layout; otherwise rows go biggest first.
export function kpiBlocks(kpi, monthLabel, layout = []) {
  const by = {};
  for (const k of kpi ?? []) (by[k.block] ??= []).push(k);
  const rank = ranker(layout);

  return Object.entries(by).map(([name, values]) => {
    const months = monthsOf(values, monthLabel);

    const byGroup = {};
    for (const v of values) {
      const g = (byGroup[v.group] ??= { group: v.group, _total: 0 });
      const key = v.month != null ? `m${v.month}` : "value";
      g[key] = (g[key] ?? 0) + v.value;
      g._total += v.value;
    }
    const body = inSheetOrder(
      Object.values(byGroup).sort((a, b) => b._total - a._total),
      rowsOf(layout, `kpi/${name}`), (group) => ({ group, _total: 0 }));

    const total = { group: TOTAL, _total: 0 };
    for (const m of months) {
      total[m.key] = sumOf(body, m.key);
      total._total += total[m.key];
    }

    return { name, months, rows: [...body, total],
             total: total._total, groups: body.filter((g) => g._total).length };
  }).sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name));
}
