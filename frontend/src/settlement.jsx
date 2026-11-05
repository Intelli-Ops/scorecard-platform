// The Settlement High-Level tab.
import { useMemo, useState } from "react";
import { bucketLabel, money, weekDays } from "./api";
import { TOTAL, amountPctPair, col } from "./columns";
import { Stat, Stats, TableCard, WeekHead } from "./ui";
import { bucketNum, monthToDate, paceTotals, pivot, pivotPace, sortBlocks,
         withMonthWeeks } from "./settlement-model";

const GROUP = col.label("group", "Group", { width: 186, className: "sticky" });
const MONTH_FULL = ["", "January", "February", "March", "April", "May", "June", "July",
                    "August", "September", "October", "November", "December"];

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
    const isOpen = (m) => open.has(m) && p.weeksOf[m]?.length > 0;

    // A closed month's name, with the round + (or -) that opens it into its weeks.
    const monthHead = (m, label) => {
      if (!p.weeksOf[m]?.length) return label;
      const shut = !open.has(m);
      const say = shut ? `Open ${MONTH_FULL[bucketNum(m)]} into its weeks`
                       : `Close ${MONTH_FULL[bucketNum(m)]} back to its total`;
      return (
        <span className="month-head">
          <span>{label}</span>
          <button type="button" className={`expand-month${shut ? "" : " open"}`}
                  onClick={() => toggle(m)} aria-expanded={!shut}
                  aria-label={say} title={say}>
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
              <path d={shut ? "M5 1.8v6.4M1.8 5h6.4" : "M1.8 5h6.4"} fill="none"
                    stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </button>
        </span>
      );
    };

    // With a month open, the headings take two rows: the month over all its weeks on
    // the first, each week (and the month's total) beneath it on the second. Every
    // other heading stands the height of both.
    const twoRows = p.months.some(isOpen);
    const tall = twoRows ? 2 : 1;
    const columns = [GROUP];
    const first = [{ label: "", span: 1, rowSpan: tall, className: "lead" }];
    const second = [];
    const add = ({ span, columns: cols }, extra = "") => {
      columns.push(...cols);
      first.push({ ...span, rowSpan: tall,
                   className: [span.className, extra].filter(Boolean).join(" ") });
    };

    for (const m of p.months) {
      if (!isOpen(m)) { add(amountPctPair(m, monthHead(m, bucketLabel(m)))); continue; }
      const weeks = p.weeksOf[m];
      first.push({ label: monthHead(m, `${MONTH_FULL[bucketNum(m)]}`),
                   span: 2 * (weeks.length + 1), className: "opened month-group" });
      for (const w of weeks) {
        const pair = amountPctPair(`${m}${w}`, null);
        columns.push(...pair.columns.map((c) => ({ ...c, className: "opened" })));
        second.push({ label: week(w, bucketNum(m)), span: 2, className: "opened" });
      }
      const total = amountPctPair(m, null);
      columns.push(...total.columns.map((c) => ({ ...c, className: "opened opened-total" })));
      second.push({ label: `${bucketLabel(m)} total`, span: 2,
                    className: "opened opened-total" });
    }
    for (const w of p.weeks) {
      add(amountPctPair(w, week(w, currentMonth), { current: true }));
    }
    if (p.weeks.length) {
      columns.push(col.strong("_month", "Month total", { className: "current" }));
      first.push({ label: monthLabel ?? "This month", span: 1, rowSpan: tall,
                   className: "current" });
    }
    columns.push(col.strong("_total", "Year to date"));
    first.push({ label: "Grand total", span: 1, rowSpan: tall });
    return { columns, spans: twoRows ? [first, second] : first };
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
