// The All Providers Delta Comparison tab, laid out as the client's Delta Comparison sheet.
import { useMemo } from "react";
import { monthFull } from "./api";
import { col, total } from "./columns";
import { useToggleSet } from "./hooks";
import { OpenableHead, TableCard } from "./ui";
import { MEASURES, pivotDeltaComparison, TOTAL } from "./deltaComparison-model";

// A closed month shows its Total Settlement alone; its + opens it into Total Settlement,
// Pay Received - YES and Pay Received - NO. The month being reported starts open.
export default function DeltaComparison({ rows, order, currentMonth, year }) {
  const grid = useMemo(() => pivotDeltaComparison(rows, { order, upTo: currentMonth }),
                       [rows, order, currentMonth]);
  const [open, toggle] = useToggleSet(currentMonth ? [currentMonth] : []);

  const { columns, spans } = useMemo(() => {
    const columns = [col.label("group", "PAPER",
                               { width: 190, className: "sticky", sortable: true })];
    const spans = [{ label: "", span: 1, className: "lead" }];
    for (const mo of grid.months) {
      const current = mo === currentMonth ? "current" : undefined;
      const isOpen = open.has(mo);
      const label = (
        <OpenableHead label={`${monthFull(mo)}${year ? ` ${year}` : ""}`}
                      open={isOpen} onClick={() => toggle(mo)}
                      say={isOpen ? `Close ${monthFull(mo)} back to its Total Settlement`
                                  : `Open ${monthFull(mo)} into Pay Received YES and NO`} />
      );
      const shown = isOpen ? MEASURES : MEASURES.slice(0, 1);
      spans.push({ label, span: shown.length,
                   className: [current, isOpen && !current ? "opened month-group" : ""]
                     .filter(Boolean).join(" ") || undefined });
      const className = current ?? (isOpen ? "opened" : undefined);
      columns.push(...shown.map((m) => col.money(`m${mo}_${m.key}`, m.label, { className })));
    }
    spans.push({ label: "Year to date", span: MEASURES.length });
    columns.push(...MEASURES.map((m) => total(col.money(`_${m.key}`, m.year))));
    return { columns, spans };
  }, [grid.months, currentMonth, year, open, toggle]);

  return (
    <TableCard
      title="Delta Comparison"
      sub={"Settlements by provider group and month. A closed month shows its Total "
           + "Settlement; + opens it into Pay Received YES and NO."}
      empty="This run produced no delta rows."
      columns={columns} spans={spans} rows={grid.rows}
      isTotal={(r) => r.group === TOTAL} />
  );
}
