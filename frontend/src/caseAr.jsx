// The Case AR tab, with its Group, File status and Validity filters.
import { useMemo, useState } from "react";
import { api, count } from "./api";
import { col } from "./columns";
import { ErrorBox, Loading, Picker } from "./components";
import { TableCard } from "./ui";
import { Button } from "./buttons";
import { useLoad } from "./hooks";
import { GRAND_TOTAL, sectionCaseAr, sectionClass } from "./caseAr-model";

const ALL = "(All)";
const isCount = (c) => /cases/i.test(c);
const anyOf = (values) => (values.length > 1
  ? `${values.slice(0, -1).join(", ")} or ${values.at(-1)}` : values[0]);

export default function CaseAr({ runId }) {
  const [chosen, setChosen] = useState({});
  const { data, error } = useLoad(() => api.caseAr(runId, chosen), [runId, chosen],
                                  { keep: true });

  const table = useMemo(() => (data ? sectionCaseAr(data) : null), [data]);

  const columns = useMemo(() => (table?.columns ?? []).map((c, i) => {
    const kind = data.kinds[c];
    if (kind === "text") {
      return i === 0 ? col.label(c, c, { className: "sticky full", sortable: true }) : col.text(c, c);
    }
    return kind === "int" || isCount(c) ? col.count(c, c) : col.money(c, c);
  }), [table, data]);

  const cases = (table?.columns ?? []).find(isCount);
  const heading = (r) => r._kind === "section" && (
    <>
      <span className="section-name">{r._section}</span>
      <span className="section-meta">
        {cases && `${count(r._totals[cases])} cases · `}
        {count(table.rows.filter((x) => x._section === r._section && !x._kind).length)} closing orders
      </span>
    </>
  );

  // Each filter holds a list: rows matching any of its values are kept, and every filter
  // that is set has to match.
  const active = Object.entries(chosen).filter(([, v]) => v?.length);
  const set = (key, values) =>
    setChosen((c) => ({ ...c, [key]: values.length ? values : undefined }));

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;

  return (
    <>
      <div className={`filters${active.length ? " on" : ""}`}>
        {data.filters.map((f) => (
          <Picker key={f.key} label={f.label} multiple prompt={ALL}
                  value={chosen[f.key] ?? []} options={f.values}
                  active={Boolean(chosen[f.key]?.length)}
                  onChange={(v) => set(f.key, v)}
                  onClear={() => set(f.key, [])} />
        ))}
        <span className="spacer" />
        <span className="count">
          {active.length
            ? <><strong>{count(data.matched)}</strong> of {count(data.of)} rows</>
            : <>all <strong>{count(data.of)}</strong> rows</>}
        </span>
        {active.length > 1 && (
          <Button tone="quiet" size="sm" onClick={() => setChosen({})}>
            Clear all {active.length}
          </Button>
        )}
      </div>

      <TableCard
        title="Case AR"
        sub={active.length
          ? active.map(([k, v]) => `${data.filters.find((f) => f.key === k)?.label} is ${anyOf(v)}`)
              .join(" · ")
          : "Every case in Raw Data. Set a filter above to narrow it."}
        empty="No cases match these filters."
        columns={columns} rows={table.rows}
        section={heading}
        rowClass={(r) => [r._section ? sectionClass(r._section) : "",
                          r._kind === "subtotal" ? "subtotal" : ""].filter(Boolean).join(" ")}
        isTotal={(r) => r._kind === "grand" || r[table.columns[0]] === GRAND_TOTAL} />
    </>
  );
}
