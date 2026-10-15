// The Settlement High-Level tab.
import { useMemo } from "react";
import { bucketLabel, money } from "./api";
import { TOTAL, amountPctPair, assemble, col } from "./columns";
import { Stat, Stats, TableCard } from "./ui";
import { monthToDate, paceTotals, pivot, pivotPace, sortBlocks } from "./settlement-model";

const GROUP = col.label("group", "Group", { width: 186, className: "sticky" });

function Block({ title, sub, rows, totals, block, monthLabel, pace }) {
  const p = useMemo(() => pivot(rows, totals, block), [rows, totals, block]);
  const paced = useMemo(() => pivotPace(pace, block), [pace, block]);

  const { columns, spans } = useMemo(() => {
    const parts = [
      ...p.months.map((m) => amountPctPair(m, bucketLabel(m))),
      ...p.weeks.map((w) => amountPctPair(w, bucketLabel(w), { current: true })),
    ];
    if (p.weeks.length) {
      parts.push({
        spanLabel: monthLabel ?? "This month", spanClass: "current",
        column: col.strong("_month", "Month total", { className: "current" }),
      });
    }
    parts.push({
      spanLabel: "Grand total",
      column: col.strong("_total", "Year to date"),
    });
    return assemble(GROUP, parts);
  }, [p, monthLabel]);

  const paceColumns = useMemo(() => [
    GROUP,
    ...paced.weeks.map((w) => col.money(w, bucketLabel(w), { className: "current" })),
  ], [paced.weeks]);

  return (
    <>
      <TableCard title={title} sub={sub}
                 columns={columns} spans={spans} rows={p.rows} />

      {paced.weeks.length > 0 && (
        <TableCard
          title={`${title}: Pace`}
          sub={`Where ${monthLabel ?? "this month"} lands if the rest of it goes at the rate seen so far: what has banked up to each week, spread across the month's working days. The last week of a finished month paces to what it actually did.`}
          columns={paceColumns} rows={paced.rows} />
      )}
    </>
  );
}

export default function Settlement({ settlement, totals, pace, cp, monthLabel }) {
  const blocks = useMemo(
    () => sortBlocks(new Set(settlement.map((r) => r.block))), [settlement]);

  const cpRows = useMemo(() => {
    if (!cp?.length) return [];
    const sum = (k) => cp.reduce((s, r) => s + r[k], 0);
    return [
      ...cp.map((r) => ({ ...r, label: bucketLabel(`M${r.month}`) })),
      { month: TOTAL, label: TOTAL, cases: sum("cases"),
        outstanding: sum("outstanding"), settled: sum("settled") },
    ];
  }, [cp]);

  return (
    <>
      {blocks.map((b) => (
        <Block key={b} block={b} title={`Settlements (${b})`}
               sub={monthLabel
                 ? `Closed months are single totals; ${monthLabel} is opened out into its weeks.`
                 : "Monthly totals for the year so far."}
               rows={settlement} totals={totals} pace={pace}
               monthLabel={monthLabel} />
      ))}

      <TableCard
        title="CP Settled Cases"
        sub="Cases settled, what settled on them, and what is still outstanding, by month."
        empty="No CP settled cases for this run."
        columns={[
          col.label("label", "Month", { width: 140, className: "sticky" }),
          col.count("cases", "# of Cases"),
          col.money("outstanding", "Outstanding"),
          col.money("settled", "Settlement Amount"),
        ]}
        rows={cpRows} />
    </>
  );
}

// The tiles: this month, because that is the month being reported on.
export function SettlementTiles({ settlement, pace, cp, monthLabel, currentMonth }) {
  const thisMonth = useMemo(() => monthToDate(settlement), [settlement]);
  const paceTo = useMemo(() => paceTotals(pace), [pace]);

  const month = (cp ?? []).find((r) => r.month === currentMonth);
  const blocks = sortBlocks(Object.keys(thisMonth));
  const label = monthLabel ?? "this month";

  return (
    <Stats cols={5}>
      {blocks.map((b) => (
        <Stat key={b} label={`${b} · ${label}`}
              value={money(thisMonth[b])}
              foot={paceTo[b] ? `pacing to ${money(paceTo[b])}` : "settled this month"} />
      ))}
      <Stat label={`CP cases · ${label}`}
            value={month ? String(month.cases) : "-"}
            foot="settled this month" />
      <Stat label={`CP settled · ${label}`}
            value={month ? money(month.settled) : "-"}
            foot="settlement amount" />
      <Stat label={`CP outstanding · ${label}`}
            value={month ? money(month.outstanding) : "-"}
            foot="still owed on those cases" />
    </Stats>
  );
}
