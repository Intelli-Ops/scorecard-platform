import { useMemo, useState } from "react";
import { count } from "./api";
import { col } from "./columns";
import { Picker } from "./components";
import { TableCard } from "./ui";
import { ALL, applyFilters, filterOptions, pivotDelta, TOTAL } from "./delta-model";

/* Delta Comparison, the way it was actually made.

   By hand it was: paste the delta rows into a sheet, drop a pivot beside them,
   set the filters at the top, read the grid. So that is what this is - the
   filters, then the pivot they drive. The rows themselves are the next tab
   along, because they are the evidence rather than the answer, and 666 of them
   under the grid would bury it.

   The pivot is built in the browser from the rows, not asked of the server, so
   changing a filter is instant and the numbers can never disagree with the tab
   beside them - they are the same rows.

   No tiles on this tab. The figure that matters here changes with every filter,
   and a headline that restates one cell of the grid under it is not a headline.
   What the filters are doing is said in the bar itself - how many rows of how
   many - which is the only number the grid does not already show. */

export default function Delta({ rows }) {
  const [chosen, setChosen] = useState({});

  const filters = useMemo(() => filterOptions(rows), [rows]);
  const filtered = useMemo(() => applyFilters(rows, chosen), [rows, chosen]);
  const grid = useMemo(() => pivotDelta(filtered), [filtered]);

  /* "Set" means narrowing something - (All) and unset are the same thing, and
     neither should light the control up. */
  const isSet = (v) => Boolean(v) && v !== ALL;
  const active = Object.entries(chosen).filter(([, v]) => isSet(v));
  const set = (key, value) => setChosen((c) => ({ ...c, [key]: value }));
  const all = rows?.length ?? 0;

  const columns = useMemo(() => [
    col.label("group", "Group", { width: 190, className: "sticky" }),
    ...grid.buckets.map((b) => col.money(b, b)),
    col.strong("_total", "Grand Total"),
    col.count("_cases", "Cases"),
  ], [grid.buckets]);

  return (
    <>
      <div className={`filters${active.length ? " on" : ""}`}>
        {filters.map((f) => (
          <Picker key={f.key} label={f.label} value={chosen[f.key] ?? ALL}
                  onChange={(v) => set(f.key, v)} options={f.values}
                  active={isSet(chosen[f.key])} />
        ))}
        <span className="spacer" />
        <span className="count">
          {active.length
            ? <><strong>{count(filtered.length)}</strong> of {count(all)} rows</>
            : <>all <strong>{count(all)}</strong> rows</>}
        </span>
        {active.length > 0 && (
          <button className="small" onClick={() => setChosen({})}>
            Clear {active.length === 1 ? "filter" : `${active.length} filters`}
          </button>
        )}
      </div>

      <TableCard
        title="Sum of Settlement Amount"
        sub={active.length
          ? `${active.map(([k, v]) => `${k} is ${v}`).join(" · ")} — ${count(filtered.length)} of ${count(all)} rows`
          : `All ${count(all)} delta rows. Set a filter above to narrow the pivot.`}
        empty={active.length
          ? "No rows match these filters."
          : "This run produced no delta rows."}
        columns={columns} rows={grid.rows}
        isTotal={(r) => r.group === TOTAL} />
    </>
  );
}
