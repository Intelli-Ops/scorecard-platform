// The KPI High-Level tab.
import { useMemo } from "react";
import { count } from "./api";
import { assemble, col, total } from "./columns";
import { TableCard } from "./ui";
import { kpiBlocks, TOTAL } from "./kpi-model";

export default function Kpi({ kpi, monthLabel, layout }) {
  const blocks = useMemo(() => kpiBlocks(kpi, monthLabel, layout),
                         [kpi, monthLabel, layout]);

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
          col.label("group", "Group", { width: 260, className: "sticky", sortable: true }),
          parts);

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
