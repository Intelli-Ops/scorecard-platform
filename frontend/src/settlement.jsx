// The Settlement High-Level tab.
import { useMemo, useState } from "react";
import { bucketLabel, money, weekDays } from "./api";
import { TOTAL, amountPctPair, assemble, col } from "./columns";
import { Stat, Stats, TableCard, WeekHead } from "./ui";
import { bucketNum, monthToDate, paceTotals, pivot, pivotPace, sortBlocks,
         withMonthWeeks } from "./settlement-model";

const GROUP = col.label("group", "Group", { width: 186, className: "sticky" });

function Block({ title, sub, rows, totals, block, monthLabel, pace, monthWeeks,
                 spans: weekSpans, currentMonth }) {
  const p = useMemo(() => withMonthWeeks(pivot(rows, totals, block), monthWeeks, block),
                    [rows, totals, block, monthWeeks]);
  const paced = useMemo(() => pivotPace(pace, block), [pace, block]);
  const [open, setOpen] = useState(() => new Set());

  const toggle = (m) => setOpen((was) => {
    const next = new Set(was);
    if (next.has(m)) next.delete(m); else next.add(m);
    return next;
  });

  const { columns, spans } = useMemo(() => {
    const week = (w, month) => (
      <WeekHead label={bucketLabel(w)} days={weekDays(weekSpans, month, bucketNum(w))} />);
    const monthHead = (m) => {
      const weeks = p.weeksOf[m];
      if (!weeks?.length) return bucketLabel(m);
      const shut = !open.has(m);
      return (
        <>
          {bucketLabel(m)}{shut ? "" : " total"}
          <button type="button" className="expand-month" onClick={() => toggle(m)}
                  aria-expanded={!shut}
                  title={shut ? `Open ${bucketLabel(m)} into its weeks`
                              : `Close ${bucketLabel(m)} back to its total`}>
            {shut ? "+" : "−"}
          </button>
        </>
      );
    };
    const parts = [
      ...p.months.flatMap((m) => [
        ...(open.has(m) ? p.weeksOf[m] ?? [] : []).map((w) => {
          const pair = amountPctPair(`${m}${w}`, week(w, bucketNum(m)));
          return { ...pair, span: { ...pair.span, className: "opened" } };
        }),
        amountPctPair(m, monthHead(m)),
      ]),
      ...p.weeks.map((w) => amountPctPair(w, week(w, currentMonth), { current: true })),
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
  }, [p, monthLabel, open, weekSpans, currentMonth]);

  const paceColumns = useMemo(() => [
    GROUP,
    ...paced.weeks.map((w) => col.money(w, (
      <WeekHead label={bucketLabel(w)}
                days={weekDays(weekSpans, currentMonth, bucketNum(w))} />
    ), { className: "current" })),
  ], [paced.weeks, weekSpans, currentMonth]);

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

export default function Settlement({ settlement, totals, pace, cp, monthLabel,
                                     monthWeeks, spans, currentMonth }) {
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
                   + (monthWeeks?.length
                     ? " From October 2026, + beside a closed month opens it into its weeks."
                     : "")
                 : "Monthly totals for the year so far."}
               rows={settlement} totals={totals} pace={pace}
               monthLabel={monthLabel} monthWeeks={monthWeeks}
               spans={spans} currentMonth={currentMonth} />
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
