import { useEffect, useMemo, useState } from "react";
import { api, count } from "./api";
import { col } from "./columns";
import { ErrorBox, Loading, Picker } from "./components";
import { TableCard } from "./ui";
import { Button } from "./buttons";

/* The Case AR sheet, with the page filters its Excel pivot carries: Group,
   File status and Validity. Each change asks the server for the pivot again,
   because it is built from Raw Data - hundreds of thousands of rows that stay
   on the server. The Grand Total row is always last, and always the total of
   what the filters leave. */

const ALL = "(All)";
const GRAND_TOTAL = "Grand Total";
const isCount = (c) => /cases/i.test(c);

export default function CaseAr({ runId }) {
  const [chosen, setChosen] = useState({});
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    api.caseAr(runId, chosen)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e));
    return () => { alive = false; };
  }, [runId, chosen]);

  const columns = useMemo(() => (data?.columns ?? []).map((c, i) => {
    const kind = data.kinds[c];
    if (kind === "text") {
      return i === 0 ? col.label(c, c, { className: "sticky" }) : col.text(c, c);
    }
    return kind === "int" || isCount(c) ? col.count(c, c) : col.money(c, c);
  }), [data]);

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
        columns={columns} rows={data.rows}
        isTotal={(r) => r[data.columns[0]] === GRAND_TOTAL} />
    </>
  );
}
