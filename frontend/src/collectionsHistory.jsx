// Collections history: the year month by month, under the Collections tab.
import { useMemo } from "react";
import { api, monthFull, weekLabel } from "./api";
import { GROUP, col } from "./columns";
import { ErrorBox, Loading } from "./components";
import { OpenableHead, TableCard } from "./ui";
import { useLoad, useToggleSet } from "./hooks";
import { pivotHistory } from "./collectionsHistory-model";

export default function CollectionsHistory({ runId }) {
  const { data, error } = useLoad(() => api.collectionsHistory(runId), [runId]);
  const grid = useMemo(() => pivotHistory(data), [data]);
  const [openMonths, toggleMonth] = useToggleSet();
  const [openWeeks, toggleWeek] = useToggleSet();

  const { columns, spans } = useMemo(() => {
    const hasWeeks = (m) => (grid.weeksOf[m] ?? []).length > 0;
    const monthOpen = (m) => openMonths.has(m) && hasWeeks(m);
    const tall = grid.months.some(monthOpen) ? 2 : 1;

    const monthHead = (m) => (hasWeeks(m)
      ? <OpenableHead label={monthFull(m)} open={openMonths.has(m)}
                      say={openMonths.has(m) ? `Close ${monthFull(m)} back to its total`
                                             : `Open ${monthFull(m)} into its weeks`}
                      onClick={() => toggleMonth(m)} />
      : monthFull(m));

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
        const label = (
          <OpenableHead label={weekLabel(w)} open={open}
                        say={open ? `Close ${weekLabel(w)} back to its total`
                                  : `Open ${weekLabel(w)} into its payment types`}
                        onClick={() => toggleWeek(key)} />);
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
      second.push({ label: `${monthFull(m)} total`, span: 1,
                    className: "opened opened-total" });
      first.push({ label: monthHead(m), span: width + 1, className: "opened month-group" });
    }
    columns.push(col.strong("_total", "Total"));
    first.push({ label: "Grand Total", span: 1, rowSpan: tall });
    return { columns, spans: tall === 2 ? [first, second] : first };
  }, [grid, openMonths, openWeeks, toggleMonth, toggleWeek]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading what="Loading the collections history" />;

  const built = data.months.filter((m) => m.source === "build");
  const fromFile = data.months.filter((m) => m.source === "file");
  const sub = [
    fromFile.length > 0 && monthFull(fromFile[0].month)
      + (fromFile.length > 1 ? ` to ${monthFull(fromFile.at(-1).month)}` : "")
      + " from the uploaded history file, as totals.",
    ...built.map((m) => `${monthFull(m.month)} from build #${m.run_id} (${m.week}`
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
