// How the Pace tables are worked out, written once for each week of the month.
import { weekDays, weekLabel } from "./api";
import { col } from "./columns";
import { TableCard } from "./ui";

export default function PaceFormula({ meta, monthLabel }) {
  const m = meta?.[0];
  if (!m?.pace_days?.length || !m.business_days) return null;
  const days = m.business_days;
  const label = monthLabel ?? "the month";

  const rows = m.pace_days.map((p) => ({
    week: weekLabel(p.week),
    days: weekDays(m.week_spans, m.current_month, p.week) || "-",
    elapsed: p.elapsed,
    formula: `month to date ÷ ${p.elapsed} × ${days}`,
  }));

  return (
    <TableCard
      title="How pace is worked out"
      sub={`Pace = what was settled or collected from the 1st to the end of the week ÷ the working days that have passed by then × the working days in ${label} (${days}). A working day is a weekday that is not a holiday.`}
      columns={[
        col.label("week", "Week", { width: 120 }),
        col.text("days", "Days"),
        col.count("elapsed", "Working days passed"),
        col.text("formula", "Pace for the week"),
      ]}
      rows={rows} isTotal={() => false} />
  );
}
