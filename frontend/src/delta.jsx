// The Delta Comparison tab.
import { useMemo, useState } from "react";
import { count } from "./api";
import { col, total } from "./columns";
import { Picker } from "./components";
import { TableCard } from "./ui";
import { agingBrackets, ALL, applyFilters, DOR_AGING, filterOptions, pivotDelta, pivotDor,
         TOTAL } from "./delta-model";
import { Button } from "./buttons";

// Delta Comparison, the way it was actually made.

const anyOf = (values) => (values.length > 1
  ? `${values.slice(0, -1).join(", ")} or ${values.at(-1)}` : values[0]);

export default function Delta({ rows, dorOrder }) {
  const [chosen, setChosen] = useState({});

  const filters = useMemo(() => filterOptions(rows), [rows]);
  const filtered = useMemo(() => applyFilters(rows, chosen), [rows, chosen]);
  const grid = useMemo(() => pivotDelta(filtered), [filtered]);

  // Each filter holds a list: rows matching any of its values are kept, and every filter
  // that is set has to match.
  const active = Object.entries(chosen).filter(([, v]) => v?.length);
  const set = (key, values) => setChosen((c) => ({ ...c, [key]: values }));
  const all = rows?.length ?? 0;
  const label = (key) => filters.find((f) => f.key === key)?.label ?? key;
  const brackets = useMemo(() => agingBrackets(rows), [rows]);

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
          <Picker key={f.key} label={f.label} multiple prompt={ALL}
                  value={chosen[f.key] ?? []} options={f.values}
                  onChange={(v) => set(f.key, v)}
                  active={Boolean(chosen[f.key]?.length)}
                  onClear={() => set(f.key, [])} />
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
          ? `${active.map(([k, v]) => `${label(k)} is ${anyOf(v)}`).join(" · ")} · ${count(filtered.length)} of ${count(all)} rows`
          : `All ${count(all)} delta rows. Set a filter above to narrow the pivot.`}
        empty={active.length
          ? "No rows match these filters."
          : "This run produced no delta rows."}
        columns={columns} rows={grid.rows}
        isTotal={(r) => r.group === TOTAL} />

      <DorPivot rows={filtered} brackets={brackets} order={dorOrder}
                narrowedBy={active.map(([k, v]) => `${label(k)} is ${anyOf(v)}`)} />
    </>
  );
}

const DOR_COLUMNS = [
  col.label("status", "Ongoing DOR Status", { width: 320, className: "sticky", sortable: true }),
  col.money("amount", "Settlement Amount"),
];

// The sheet's second pivot: where the old settlements stand with the litigation team.
// It has its own Aging filter, on 90+ until someone changes it, and follows the tab's
// filters above too (`rows` arrive already narrowed by them; `narrowedBy` says how).
function DorPivot({ rows, brackets, order, narrowedBy }) {
  const [aging, setAging] = useState(DOR_AGING);
  const grid = useMemo(() => pivotDor(rows, aging, order), [rows, aging, order]);
  const set = aging.length > 0;

  return (
    <>
      <div className={`filters${set ? " on" : ""}`}>
        <Picker label="Aging" multiple prompt={ALL} value={aging} options={brackets}
                onChange={setAging} active={set} onClear={() => setAging([])} />
        <span className="spacer" />
        {(aging.length !== 1 || aging[0] !== DOR_AGING[0]) && (
          <Button tone="quiet" size="sm" onClick={() => setAging(DOR_AGING)}>
            Back to {DOR_AGING[0]}
          </Button>
        )}
      </div>
      <TableCard
        title="Sum of Settlement Amount by Ongoing DOR Status"
        sub={[set ? `Aging ${anyOf(aging)}` : "Every aging bracket", ...narrowedBy,
              "the litigation team's status, from the Delta comments files."].join(" · ")}
        empty={narrowedBy.length
          ? "No settlements match these filters and aging brackets."
          : "No settlements in these aging brackets."}
        columns={DOR_COLUMNS} rows={grid}
        isTotal={(r) => r.status === TOTAL} />
    </>
  );
}
