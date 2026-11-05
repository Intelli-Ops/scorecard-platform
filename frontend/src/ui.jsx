// The tile row and the table card most tabs are built from.
import { Children, cloneElement, isValidElement } from "react";

import { Card, DataTable, Stat } from "./components";
import { TOTAL, toneAt } from "./columns";

// A row of them.
export function Stats({ children, cols = 4 }) {
  const toned = Children.map(children, (child, i) =>
    (isValidElement(child)
      ? cloneElement(child, { tone: child.props.tone ?? toneAt(i) })
      : child));
  return <div className={`grid cols-${cols} stats`}>{toned}</div>;
}

// One table in one card, which is how every table in the app is presented.
export function TableCard({ title, sub, right, columns, rows, spans,
                            empty, isTotal, rowClass, groupBy, section }) {
  return (
    <Card flush title={title} sub={sub} right={right}>
      <DataTable
        columns={columns} rows={rows} spans={spans}
        empty={empty ?? "Nothing to show"}
        isTotal={isTotal ?? ((r) => r.group === TOTAL || r.month === TOTAL)}
        rowClass={rowClass} groupBy={groupBy} section={section}
      />
    </Card>
  );
}

// A week's heading, with the days it covers on a line of their own beneath it.
export function WeekHead({ label, days }) {
  if (!days) return label;
  return (
    <span className="week-head">
      <span className="week-name">{label}</span>
      <span className="week-days">{days}</span>
    </span>
  );
}

export { Stat };
