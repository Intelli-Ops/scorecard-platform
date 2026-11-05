// The Delta Comparison tab.
import { useMemo, useState } from "react";
import { count } from "./api";
import { col, total } from "./columns";
import { Picker } from "./components";
import { TableCard } from "./ui";
import { ALL, applyFilters, filterOptions, pivotDelta, TOTAL } from "./delta-model";
import { Button } from "./buttons";

// Delta Comparison, the way it was actually made.

export default function Delta({ rows }) {
  const [chosen, setChosen] = useState({});

  const filters = useMemo(() => filterOptions(rows), [rows]);
  const filtered = useMemo(() => applyFilters(rows, chosen), [rows, chosen]);
  const grid = useMemo(() => pivotDelta(filtered), [filtered]);

  const isSet = (v) => Boolean(v) && v !== ALL;
  const active = Object.entries(chosen).filter(([, v]) => isSet(v));
  const set = (key, value) => setChosen((c) => ({ ...c, [key]: value }));
  const all = rows?.length ?? 0;

  const columns = useMemo(() => [
    col.label("group", "Group", { width: 190, className: "sticky", sortable: true }),
    ...grid.buckets.map((b) => col.money(b, b)),
    col.strong("_total", "Grand Total"),
    total(col.count("_cases", "Cases")),
  ], [grid.buckets]);

  return (
    <>
      <div className={`filters${active.length ? " on" : ""}`}>
        {filters.map((f) => (
          <Picker key={f.key} label={f.label} value={chosen[f.key] ?? ALL}
                  onChange={(v) => set(f.key, v)} options={f.values}
                  active={isSet(chosen[f.key])}
                  onClear={() => set(f.key, ALL)} />
        ))}
        <span className="spacer" />
        <span className="count">
          {active.length
            ? <><strong>{count(filtered.length)}</strong> of {count(all)} rows</>
            : <>all <strong>{count(all)}</strong> rows</>}
        </span>
        {active.length > 1 && (
          <Button tone="quiet" size="sm" onClick={() => setChosen({})}>
            Clear all {active.length}
          </Button>
        )}
      </div>

      <TableCard
        title="Sum of Settlement Amount"
        sub={active.length
          ? `${active.map(([k, v]) => `${k} is ${v}`).join(" · ")} · ${count(filtered.length)} of ${count(all)} rows`
          : `All ${count(all)} delta rows. Set a filter above to narrow the pivot.`}
        empty={active.length
          ? "No rows match these filters."
          : "This run produced no delta rows."}
        columns={columns} rows={grid.rows}
        isTotal={(r) => r.group === TOTAL} />
    </>
  );
}
