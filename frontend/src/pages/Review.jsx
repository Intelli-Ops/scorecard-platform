import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, bytes, count, when } from "../api";
import { Card, DataTable, ErrorBox, Loading, Notes, Status, Tile } from "../components";

/* The review: what a build wants a person to know before the report goes out.

   It leads with what CHANGED rather than with what worked - warnings that are
   new or whose counts have moved, then row counts against last week, then
   exactly which files were read. */
export default function Review() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true, timer;
    const tick = async () => {
      try {
        const d = await api.run(id);
        if (!alive) return;
        setData(d);
        if (["pending", "running"].includes(d.run.status)) {
          timer = setTimeout(tick, 1500);
        }
      } catch (e) { alive && setError(e); }
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [id]);

  async function approve() {
    setBusy(true);
    try {
      await api.approve(id);
      setData(await api.run(id));
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  }

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading what="Loading the run" />;

  const run = data.run;

  if (["pending", "running"].includes(run.status)) {
    return (
      <>
        <div className="head">
          <h1>{run.week}</h1>
          <div className="sub">
            {run.status === "pending" ? "Queued." : "Reading the files and working out the numbers."}
            {" "}This takes about a minute. The page updates itself.
          </div>
        </div>
        <Card><Status value={run.status} /></Card>
      </>
    );
  }

  if (run.status === "failed") {
    return (
      <>
        <div className="head"><h1>{run.week} · failed</h1></div>
        <Card><div className="err">{run.error}</div></Card>
      </>
    );
  }

  const actions = data.note_counts.action;

  return (
    <>
      <div className="head spread">
        <div>
          <h1>{run.report}</h1>
          <div className="sub">
            {run.week} · run #{run.id} · built in {run.seconds?.toFixed(0)}s ·{" "}
            {data.compared_with
              ? `compared with ${data.compared_with.week}`
              : "no earlier week to compare with"}
          </div>
        </div>
        <div className="row">
          <Status value={run.status} />
          {run.status === "review" ? (
            <button className="primary" onClick={approve} disabled={busy}>
              {busy ? "Approving…" : "Approve"}
            </button>
          ) : (
            <span className="small muted">
              approved by {run.approved_by} · {when(run.approved_at)}
            </span>
          )}
          <Link className="btn" to={`/dashboard/${run.id}`}>Open scorecard</Link>
        </div>
      </div>

      <div className="grid cols-4" style={{ marginBottom: 26 }}>
        <Tile label="Needs attention" value={data.needs_attention ? "Yes" : "No"}
              foot={actions ? `${actions} figure${actions > 1 ? "s" : ""} missing a source`
                            : "nothing blocking"} />
        <Tile label="Warnings" value={count(data.note_counts.warning)}
              foot="dropped or corrected rows" />
        <Tile label="Rows produced"
              value={count(data.tables.reduce((s, t) => s + t.rows, 0))}
              foot={`${data.tables.length} tables`} />
        <Tile label="Files read" value={count(data.inputs.length)}
              foot="each pinned to its exact bytes" />
      </div>

      <Card flush title="What this run is telling you"
            sub="The wording is the pipeline's own. What is new is the comparison.">
        <div style={{ padding: "4px 22px 10px" }}>
          <Notes notes={data.notes} />
        </div>
      </Card>

      <div className="grid cols-2">
        <Card flush title="What it produced">
          <DataTable
            columns={[
              { key: "name", label: "Table", strong: true,
                render: (t) => t.name.replace(/_/g, " ") },
              { key: "rows", label: "Rows", num: true, render: (t) => count(t.rows) },
              { key: "rows_last_week", label: "Last week", num: true,
                render: (t) => t.rows_last_week == null ? "—" : count(t.rows_last_week) },
              { key: "change", label: "Change", num: true,
                render: (t) => t.change == null ? "—"
                  : (t.change > 0 ? "+" : "") + count(t.change) },
            ]}
            rows={data.tables}
          />
        </Card>

        <Card flush title="What it read"
              sub="Every file pinned to the exact bytes it contained.">
          <DataTable
            columns={[
              { key: "filename", label: "File",
                render: (i) => <span title={i.sha256}>{i.filename}</span> },
              { key: "scope", label: "Used by" },
              { key: "rows_read", label: "Rows", num: true,
                render: (i) => count(i.rows_read) },
              { key: "size_bytes", label: "Size", num: true,
                render: (i) => bytes(i.size_bytes) },
            ]}
            rows={data.inputs}
          />
        </Card>
      </div>
    </>
  );
}
