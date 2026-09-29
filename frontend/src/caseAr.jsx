import { useMemo, useState } from "react";
import { api, count } from "./api";
import { col } from "./columns";
import { ErrorBox, Loading, Picker } from "./components";
import { TableCard } from "./ui";
import { Button } from "./buttons";
import { useLoad } from "./hooks";
import { GRAND_TOTAL, sectionCaseAr, sectionClass } from "./caseAr-model";

/* The Case AR sheet, with the page filters its Excel pivot carries: Group,
   File status and Validity. Each change asks the server for the pivot again,
   because it is built from Raw Data - hundreds of thousands of rows that stay
   on the server. The Grand Total row is always last, and always the total of
   what the filters leave. */

const ALL = "(All)";
const isCount = (c) => /cases/i.test(c);

export default function CaseAr({ runId }) {
  const [chosen, setChosen] = useState({});
  /* The last pivot stays on screen while the next filter's is fetched. */
  const { data, error } = useLoad(() => api.caseAr(runId, chosen), [runId, chosen],
                                  { keep: true });

  const table = useMemo(() => (data ? sectionCaseAr(data) : null), [data]);

  const columns = useMemo(() => (table?.columns ?? []).map((c, i) => {
    const kind = data.kinds[c];
    if (kind === "text") {
      return i === 0 ? col.label(c, c, { className: "sticky full" }) : col.text(c, c);
    }
    return kind === "int" || isCount(c) ? col.count(c, c) : col.money(c, c);
  }), [table, data]);

  /* A section's heading: its name, and how many cases and closing orders
     sit under it, read off its subtotal. */
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

  const active = Object.entries(chosen).filter(([, v]) => v);
  const set = (key, value) =>
    setChosen((c) => ({ ...c, [key]: value === ALL ? undefined : value }));

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;

  return (
    <>
      <div className={`filters${active.length ? " on" : ""}`}>
        {data.filters.map((f) => (
          <Picker key={f.key} label={f.label} value={chosen[f.key] ?? ALL}
                  options={[ALL, ...f.values]} active={Boolean(chosen[f.key])}
                  onChange={(v) => set(f.key, v)}
                  onClear={() => set(f.key, ALL)} />
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
          ? active.map(([k, v]) => `${data.filters.find((f) => f.key === k)?.label} is ${v}`).join(" · ")
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
