import { useMemo } from "react";
import { count } from "./api";
import { assemble, col } from "./columns";
import { TableCard } from "./ui";

/* KPI High-Level, one table per category.

   No tiles on this tab. A tile is for a figure the whole page is about, and
   this page is about eight categories at once - a headline over them would
   have to pick one, or add them together, and the sum of an SBR count and a
   DDE count is not a number that means anything.

   The sheet runs a column per MONTH across each block, January to the month
   being reported, with a Grand Total at the end. That is the shape here, built
   from whatever months the run actually carries: today the pipeline computes
   the current month only, because the SQL document log it reads holds one
   month, so one column is what there is. When the earlier months become
   available the columns appear beside it and nothing here changes.

   There is no Share column. It was taking most of the width to say something
   the counts beside it already said, and a month is a better use of that
   space than a bar. */

const TOTAL = "Total";

/* A run's KPI figures may carry a month; the ones built before they did are
   simply the run's own month. Either way a block is grouped into columns. */
function monthsOf(rows, fallback) {
  const named = [...new Set(rows.map((r) => r.month).filter((m) => m != null))];
  if (!named.length) return [{ key: "value", label: fallback ?? "Value" }];
  return named.sort((a, b) => a - b)
    .map((m) => ({ key: `m${m}`, label: MONTHS[m] ?? String(m), month: m }));
}

const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function Kpi({ kpi, monthLabel }) {
  const blocks = useMemo(() => {
    const by = {};
    for (const k of kpi ?? []) (by[k.block] ??= []).push(k);

    return Object.entries(by).map(([name, values]) => {
      const months = monthsOf(values, monthLabel);

      /* One row per group, one cell per month, ordered by the total across
         the row - which is the order the sheet prints and the order that puts
         the groups worth reading at the top. */
      const byGroup = {};
      for (const v of values) {
        const g = (byGroup[v.group] ??= { group: v.group, _total: 0 });
        const key = v.month != null ? `m${v.month}` : "value";
        g[key] = (g[key] ?? 0) + v.value;
        g._total += v.value;
      }
      const body = Object.values(byGroup).sort((a, b) => b._total - a._total);

      const total = { group: TOTAL, _total: 0 };
      for (const m of months) {
        total[m.key] = body.reduce((s, g) => s + (g[m.key] ?? 0), 0);
        total._total += total[m.key];
      }

      return { name, months, rows: [...body, total],
               total: total._total, groups: body.length };
    }).sort((a, b) => b.total - a.total);
  }, [kpi, monthLabel]);

  if (!blocks.length) {
    return <div className="empty">This run recorded no KPI blocks.</div>;
  }

  return (
    <div className="stack">
      {blocks.map((b) => {
        /* A single month needs no Grand Total column repeating it. */
        const parts = b.months.map((m) => ({
          spanLabel: m.label, column: col.count(m.key, m.label, { width: 120 }),
        }));
        if (b.months.length > 1) {
          parts.push({ spanLabel: "Grand Total",
                       column: col.count("_total", "Grand Total", { strong: true }) });
        }
        const { columns } = assemble(
          col.label("group", "Group", { width: 260, className: "sticky" }), parts);

        return (
          <TableCard key={b.name} title={b.name}
            sub={`${count(b.total)} across ${b.groups} groups`}
            right={<span className="pill">{count(b.total)}</span>}
            columns={columns} rows={b.rows}
            isTotal={(r) => r.group === TOTAL} />
        );
      })}
    </div>
  );
}
