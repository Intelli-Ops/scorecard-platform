import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, bytes, count, when } from "../api";
import { Card, DataTable, ErrorBox, Loading, Notes, Status, Tile } from "../components";

/* The review screen - STEP 4, given somewhere to live.

   A build stops at `review`, not `done`. This is the page that decides whether
   the report goes out, so it leads with what changed rather than with what
   worked: the warnings that are new or whose counts have moved, then the row
   counts against last week, then the audit trail of exactly which bytes were
   read. */
export default function Review() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [approving, setApproving] = useState(false);

  useEffect(() => {
    let alive = true, timer;
    const tick = async () => {
      try {
        const d = await api.run(id);
        if (!alive) return;
        setData(d);
        // A build takes about a minute. Poll while it is still working.
        if (["pending", "running"].includes(d.run.status)) {
          timer = setTimeout(tick, 1500);
        }
      } catch (e) { alive && setError(e); }
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [id]);

  async function approve() {
    setApproving(true);
    try { setData(await api.run(id).then(async () => {
      await api.approve(id, "web"); return api.run(id);
    })); }
    catch (e) { setError(e); }
    finally { setApproving(false); }
  }

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading what="Loading the run" />;

  const run = data.run;

  if (["pending", "running"].includes(run.status)) {
    return (
      <>
        <div className="head">
          <h1>{run.week} · building</h1>
          <div className="sub">
            {run.status === "pending"
              ? `Queued${data.queued_ahead > 1 ? `, ${data.queued_ahead - 1} ahead` : ""}.`
              : "Reading the source files and working out the numbers."}
          </div>
        </div>
        <Card>
          <div className="row"><Status value={run.status} />
            <span className="mono">
              This takes about a minute. The page updates itself.
            </span>
          </div>
        </Card>
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
          <h1>{run.report} · {run.week}</h1>
          <div className="sub">
            Run #{run.id} · built in {run.seconds?.toFixed(0)}s ·{" "}
            {data.compared_with
              ? <>compared with {data.compared_with.week}</>
              : "no earlier week to compare with"}
          </div>
        </div>
        <div className="row">
          <Status value={run.status} />
          {run.status === "review" ? (
            <button className="primary" onClick={approve} disabled={approving}>
              {approving ? "Approving…" : "Approve"}
            </button>
          ) : (
            <span className="mono">
              approved by {run.approved_by} · {when(run.approved_at)}
            </span>
          )}
          <Link className="btn" to={`/dashboard/${run.id}`}>Open dashboard</Link>
        </div>
      </div>

      <div className="grid cols-3" style={{ marginBottom: 16 }}>
        <Tile label="Needs attention"
              value={data.needs_attention ? "Yes" : "No"}
              foot={actions ? `${actions} figure${actions > 1 ? "s" : ""} missing a source`
                            : "nothing blocking"} />
        <Tile label="Warnings" value={count(data.note_counts.warning)}
              foot="dropped or corrected rows" />
        <Tile label="Rows produced"
              value={count(data.tables.reduce((s, t) => s + t.rows, 0))}
              foot={`${data.tables.length} tables`} />
      </div>

      <Card title="What this run is telling you"
            sub="The wording is the pipeline's own. What is new is the comparison.">
        <Notes notes={data.notes} />
      </Card>

      <div className="grid cols-2">
        <Card title="What it produced">
          <DataTable
            columns={[
              { key: "name", label: "Table" },
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

        <Card title="What it read"
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
