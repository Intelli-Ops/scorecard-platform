// Collections history: the year month by month, under the Collections tab.
import { useMemo, useState } from "react";
import { api, weekLabel } from "./api";
import { col } from "./columns";
import { ErrorBox, Loading } from "./components";
import { TableCard } from "./ui";
import { useLoad } from "./hooks";
import { pivotHistory } from "./collectionsHistory-model";

const MONTH_FULL = ["", "January", "February", "March", "April", "May", "June", "July",
                    "August", "September", "October", "November", "December"];
const GROUP = col.label("group", "Group", { width: 186, className: "sticky", sortable: true });

// The round + (or -) that opens a month into its weeks, or a week into its payment types.
function Opener({ open, say, onClick }) {
  return (
    <button type="button" className={`expand-month${open ? " open" : ""}`}
            onClick={onClick} aria-expanded={open} aria-label={say} title={say}>
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
        <path d={open ? "M1.8 5h6.4" : "M5 1.8v6.4M1.8 5h6.4"} fill="none"
              stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    </button>
  );
}

const flip = (set, key) => {
  const next = new Set(set);
  if (next.has(key)) next.delete(key); else next.add(key);
  return next;
};

export default function CollectionsHistory({ runId }) {
  const { data, error } = useLoad(() => api.collectionsHistory(runId), [runId]);
  const grid = useMemo(() => pivotHistory(data), [data]);
  const [openMonths, setOpenMonths] = useState(() => new Set());
  const [openWeeks, setOpenWeeks] = useState(() => new Set());

  const { columns, spans } = useMemo(() => {
    const hasWeeks = (m) => (grid.weeksOf[m] ?? []).length > 0;
    const monthOpen = (m) => openMonths.has(m) && hasWeeks(m);
    const tall = grid.months.some(monthOpen) ? 2 : 1;

    const head = (label, opener) => (
      opener ? <span className="month-head"><span>{label}</span>{opener}</span> : label);
    const monthHead = (m) => head(MONTH_FULL[m], hasWeeks(m) && (
      <Opener open={openMonths.has(m)}
              say={openMonths.has(m) ? `Close ${MONTH_FULL[m]} back to its total`
                                     : `Open ${MONTH_FULL[m]} into its weeks`}
              onClick={() => setOpenMonths((s) => flip(s, m))} />));

    const columns = [GROUP];
    const first = [{ label: "", span: 1, rowSpan: tall, className: "lead" }];
    const second = [];
    for (const m of grid.months) {
      if (!monthOpen(m)) {
        columns.push(col.money(`m${m}`, "Total"));
        first.push({ label: monthHead(m), span: 1, rowSpan: tall });
        continue;
      }
      let width = 0;
      for (const w of grid.weeksOf[m]) {
        const key = `m${m}w${w}`;
        const open = openWeeks.has(key);
        const label = head(weekLabel(w), (
          <Opener open={open}
                  say={open ? `Close ${weekLabel(w)} back to its total`
                            : `Open ${weekLabel(w)} into its payment types`}
                  onClick={() => setOpenWeeks((s) => flip(s, key))} />));
        if (open) {
          const types = grid.typesOf[`${m}-${w}`] ?? [];
          columns.push(...types.map((t) => col.money(`${key}_${t}`, t, { className: "opened" })),
                       col.strong(key, "Week total", { className: "opened" }));
          second.push({ label, span: types.length + 1, className: "opened" });
          width += types.length + 1;
        } else {
          columns.push(col.money(key, "Total", { className: "opened" }));
          second.push({ label, span: 1, className: "opened" });
          width += 1;
        }
      }
      columns.push(col.strong(`m${m}`, "Total", { className: "opened opened-total" }));
      second.push({ label: `${MONTH_FULL[m]} total`, span: 1,
                    className: "opened opened-total" });
      first.push({ label: monthHead(m), span: width + 1, className: "opened month-group" });
    }
    columns.push(col.strong("_total", "Total"));
    first.push({ label: "Grand Total", span: 1, rowSpan: tall });
    return { columns, spans: tall === 2 ? [first, second] : first };
  }, [grid, openMonths, openWeeks]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading what="Loading the collections history" />;

  const built = data.months.filter((m) => m.source === "build");
  const fromFile = data.months.filter((m) => m.source === "file");
  const sub = [
    fromFile.length > 0 && `${MONTH_FULL[fromFile[0].month]}`
      + (fromFile.length > 1 ? ` to ${MONTH_FULL[fromFile.at(-1).month]}` : "")
      + " from the uploaded history file, as totals.",
    ...built.map((m) => `${MONTH_FULL[m.month]} from build #${m.run_id} (${m.week}`
      + `${m.status === "approved" ? ", approved" : ", not yet approved"}).`),
    built.length > 0 && "+ opens a month into its weeks, and a week into its payment types.",
  ].filter(Boolean).join(" ");

  return (
    <TableCard
      title={`Collections history ${data.year}`}
      sub={sub || `Every finished month of ${data.year}, by provider group.`}
      empty={`No collections history for ${data.year} yet.`}
      columns={columns} spans={spans} rows={grid.rows} />
  );
}
