// The KPI High-Level tab.
import { useMemo } from "react";
import { count } from "./api";
import { assemble, col, total } from "./columns";
import { TableCard } from "./ui";

const TOTAL = "Total";

const ORDER = ["sbr", "pmr", "ddel", "ntp", "medical index", "dor",
               "med legal", "enforcement of agreement", "dde"];
function rank(name) {
  const n = String(name).trim().toLowerCase();
  const i = ORDER.indexOf(/\(ddel\)/.test(n) ? "ddel" : n);
  return i < 0 ? ORDER.length : i;
}

// A run's KPI figures may carry a month.
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
    }).sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name));
  }, [kpi, monthLabel]);

  if (!blocks.length) {
    return <div className="empty">This run recorded no KPI blocks.</div>;
  }

  return (
    <div className="stack">
      {blocks.map((b) => {
        const parts = b.months.map((m) => ({
          spanLabel: m.label, column: col.count(m.key, m.label, { width: 120 }),
        }));
        if (b.months.length > 1) {
          parts.push({ spanLabel: "Grand Total",
                       column: total(col.count("_total", "Grand Total")) });
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
