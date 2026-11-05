// The Collection High-Level tab.
import { useMemo } from "react";
import { money, weekDays } from "./api";
import { assemble, col } from "./columns";
import { Stat, Stats, TableCard, WeekHead } from "./ui";
import {
  collectionsPaceTotal, collectionsToDate, paymentTypeTotals,
  pivotCollections, pivotCollectionsPace, TOTAL, weekLabel,
} from "./collections-model";

const GROUP = col.label("group", "Group", { width: 186, className: "sticky", sortable: true });

export default function Collections({ rows, pace, monthLabel, spans: weekSpans,
                                      currentMonth, order }) {
  const grid = useMemo(() => pivotCollections(rows, order), [rows, order]);
  const paced = useMemo(() => pivotCollectionsPace(pace, order), [pace, order]);

  const { columns, spans } = useMemo(() => {
    const parts = grid.weeks.map((w) => ({
      span: { label: <WeekHead label={weekLabel(w)}
                               days={weekDays(weekSpans, currentMonth, w)} />,
              span: grid.types.length + 1, className: "current" },
      columns: [
        ...grid.types.map((t) =>
          col.money(`w${w}_${t}`, t, { className: "current" })),
        col.strong(`w${w}`, "Week total", { className: "current" }),
      ],
    }));
    parts.push({
      spanLabel: monthLabel ?? "This month",
      column: col.strong("_total", "Month total"),
    });
    return assemble(GROUP, parts);
  }, [grid, monthLabel, weekSpans, currentMonth]);

  const paceColumns = useMemo(() => [
    GROUP,
    ...paced.weeks.map((w) =>
      col.money(w, <WeekHead label={weekLabel(w.slice(1))}
                             days={weekDays(weekSpans, currentMonth, w.slice(1))} />,
                { className: "current" })),
  ], [paced.weeks, weekSpans, currentMonth]);

  return (
    <>
      <TableCard
        title="Collections"
        sub={`Each week of ${monthLabel ?? "the current month"} opened into its payment types. Earlier months are in Collections history at the bottom of this tab.`}
        empty="No collections for this run."
        columns={columns} spans={spans} rows={grid.rows} />

      {paced.weeks.length > 0 && (
        <TableCard
          title="Collections: Pace"
          sub={`Where ${monthLabel ?? "this month"} lands if the rest of it goes at the rate seen so far. A group's whole week is paced, not each payment type. The sheet does the same, and pacing one payment type would be projecting noise.`}
          columns={paceColumns} rows={paced.rows} />
      )}

    </>
  );
}

// The tiles are the payment-type footer the sheet prints under the grid.
export function CollectionsTiles({ rows, pace, monthLabel }) {
  const total = useMemo(() => collectionsToDate(rows), [rows]);
  const paceTo = useMemo(() => collectionsPaceTotal(pace), [pace]);
  const byType = useMemo(() => paymentTypeTotals(rows), [rows]);
  const label = monthLabel ?? "this month";

  const types = byType.filter((r) => r.pt !== TOTAL);
  const share = (n) => (total ? `${((n / total) * 100).toFixed(2)}% of the month`
                              : "no collections yet");

  return (
    <Stats cols={5}>
      <Stat label={`Collections · ${label}`} value={money(total)}
            foot={paceTo ? `pacing to ${money(paceTo)}` : "settled this month"} />
      {types.map((r) => (
        <Stat key={r.pt} label={r.pt} value={money(r.payment)}
              foot={share(r.payment)} />
      ))}
    </Stats>
  );
}
