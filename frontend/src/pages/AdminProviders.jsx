// Admin: the provider list - which group each provider's cases count under.
import { useState } from "react";
import { api, personName, stamp } from "../api";
import { useLoad } from "../hooks";
import { Card, DataTable, ErrorBox, Loading } from "../components";
import { Button, DeleteButton } from "../buttons";

const EMPTY = { regid: "", provider_id: "", name: "", status: "Active", provider_group: "" };
const FIELDS = [
  ["regid", "BUSINESSREGID", { type: "number", min: 1, style: { width: 110 } }],
  ["provider_id", "Provider ID", {}],
  ["name", "Provider name", {}],
  ["status", "Status", { style: { width: 100 } }],
  ["provider_group", "Provider group", {}],
];

// Whose paper each provider's cases are, by BUSINESSREGID. Shown here only: the builds never read it.
const PAPER = {
  ...Object.fromEntries([335, 331, 302, 251, 248, 246, 245, 238, 237, 235, 234, 233]
    .map((id) => [id, "GFS"])),
  257: "Russman", 259: "Russman",
  344: "Dr. Naderi", 341: "Dr. Naderi", 332: "Dr. Naderi", 303: "Dr. Naderi",
  380: "Dorian", 379: "Dorian", 377: "Dorian",
  376: "Ronco",
};
const paper = (p) => PAPER[Number(p.regid)] ?? "Other Client";

const toBody = (row) => ({ ...row, regid: Number(row.regid) });
const ready = (row) => Number(row.regid) >= 1 && row.provider_id.trim()
  && row.provider_group.trim();

export default function AdminProviders() {
  const { data: providers, error, setError, reload } = useLoad(api.providers, []);
  const [editing, setEditing] = useState(null);     // { from: regid, row }
  const [filter, setFilter] = useState("");

  if (!providers) return error ? <ErrorBox error={error} /> : <Loading what="Loading providers" />;

  async function save() {
    setError(null);
    try {
      await api.editProvider(editing.from, toBody(editing.row));
      setEditing(null);
      await reload();
    } catch (e) { setError(e); }
  }

  async function remove(p) {
    setError(null);
    try { await api.deleteProvider(p.regid); await reload(); } catch (e) { setError(e); }
  }

  const q = filter.trim().toLowerCase();
  const rows = q
    ? providers.filter((p) => [p.regid, p.provider_id, p.name, p.provider_group, paper(p)]
        .some((v) => String(v ?? "").toLowerCase().includes(q)))
    : providers;
  const isEditing = (p) => editing?.from === p.regid;

  const cell = (key, opts) => (p) => (isEditing(p)
    ? <input {...opts} aria-label={key} value={editing.row[key] ?? ""}
             onChange={(e) => setEditing({ ...editing,
                                           row: { ...editing.row, [key]: e.target.value } })}
             onKeyDown={(e) => {
               if (e.key === "Enter" && ready(editing.row)) save();
               if (e.key === "Escape") setEditing(null);
             }} />
    : (p[key] ?? <span className="muted">—</span>));

  return (
    <>
      <div className="head">
        <h1>Providers</h1>
        <div className="sub">
          Which group each provider&apos;s cases count under - the Provider List the
          Supporting File used to carry. Builds made from now on use this list;
          rebuild a week to apply a change to it.
        </div>
      </div>

      {error && <ErrorBox error={error} />}

      <Card title="Add a provider">
        <AddProvider onAdded={reload} />
      </Card>

      <Card flush title={`${providers.length} providers`}
            right={<input type="search" placeholder="Search" aria-label="Search providers"
                          value={filter} onChange={(e) => setFilter(e.target.value)} />}>
        <DataTable
          rows={rows}
          empty={q ? "No provider matches." : "No providers yet."}
          columns={[
            ...FIELDS.map(([key, label, opts]) => (
              { key, label, strong: key === "regid", render: cell(key, opts) })),
            { key: "paper", label: "Paper",
              render: (p) => (paper(p) === "Other Client"
                ? <span className="muted">Other Client</span> : paper(p)) },
            { key: "set_by", label: "Changed",
              render: (p) => (p.set_by
                ? <span className="small muted">{personName(p.set_by)} · {stamp(p.set_at)}</span>
                : <span className="small muted">Starting list</span>) },
            { key: "actions", label: "",
              render: (p) => (isEditing(p)
                ? (
                  <span className="row tight">
                    <Button size="sm" tone="primary" disabled={!ready(editing.row)}
                            onClick={save}>Save</Button>
                    <Button size="sm" onClick={() => setEditing(null)}>Cancel</Button>
                  </span>
                ) : (
                  <span className="row tight">
                    <Button size="sm" onClick={() => setEditing({
                      from: p.regid,
                      row: Object.fromEntries(FIELDS.map(([k]) => [k, p[k] ?? ""])),
                    })}>Edit</Button>
                    <DeleteButton onConfirm={() => remove(p)} />
                  </span>
                )) },
          ]}
        />
      </Card>
    </>
  );
}

function AddProvider({ onAdded }) {
  const [row, setRow] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (!ready(row)) return;
    setBusy(true); setProblem(null);
    try {
      await api.addProvider(toBody(row));
      setRow(EMPTY);
      await onAdded();
    } catch (err) { setProblem(err.message); }
    finally { setBusy(false); }
  }

  return (
    <form className="form" onSubmit={submit}>
      {problem && <div className="problem">{problem}</div>}
      <div className="field">
        <div className="row tight" style={{ flexWrap: "wrap" }}>
          {FIELDS.map(([key, label, opts]) => (
            <input key={key} {...opts} placeholder={label} aria-label={label}
                   value={row[key]} onChange={(e) => setRow({ ...row, [key]: e.target.value })} />
          ))}
          <Button type="submit" tone={ready(row) ? "primary" : "plain"} disabled={!ready(row)}
                  busy={busy} busyLabel="Adding…">Add</Button>
        </div>
        <div className="hint">
          BUSINESSREGID, Provider ID and group are needed. A provider in an existing
          group joins that group&apos;s row in the scorecard.
        </div>
      </div>
    </form>
  );
}
