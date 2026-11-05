// The All Providers Delta Comparison tab, laid out as the client's Delta Comparison sheet.
import { useMemo } from "react";
import { col, total } from "./columns";
import { TableCard } from "./ui";
import { MEASURES, pivotDeltaComparison, TOTAL } from "./deltaComparison-model";

const MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"];

export default function DeltaComparison({ rows, order, currentMonth, year }) {
  const grid = useMemo(() => pivotDeltaComparison(rows, { order, upTo: currentMonth }),
                       [rows, order, currentMonth]);

  const { columns, spans } = useMemo(() => {
    const columns = [col.label("group", "PAPER",
                               { width: 190, className: "sticky", sortable: true })];
    const spans = [{ label: "", span: 1, className: "lead" }];
    for (const mo of grid.months) {
      const current = mo === currentMonth ? "current" : undefined;
      spans.push({ label: `${MONTHS[mo]}${year ? ` ${year}` : ""}`, span: MEASURES.length,
                   className: current });
      columns.push(...MEASURES.map((m) =>
        col.money(`m${mo}_${m.key}`, m.label, { className: current })));
    }
    spans.push({ label: "Year to date", span: MEASURES.length });
    columns.push(...MEASURES.map((m) => total(col.money(`_${m.key}`, m.year))));
    return { columns, spans };
  }, [grid.months, currentMonth, year]);

  return (
    <TableCard
      title="Delta Comparison"
      sub="Settlements by provider group and month, split by whether payment has been received."
      empty="This run produced no delta rows."
      columns={columns} spans={spans} rows={grid.rows}
      isTotal={(r) => r.group === TOTAL} />
  );
}
