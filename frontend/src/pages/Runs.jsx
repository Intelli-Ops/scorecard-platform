import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, when } from "../api";
import { Card, ConfirmButton, DataTable, ErrorBox, Loading, Segmented,
         Status } from "../components";

/* Run history - what dated folders on one laptop could never provide.
   Every build of every report, who approved it, and what it warned about.

   Twelve weeks, no more. A history that grows without limit stops being read;
   a quarter is far enough back to see a trend and short enough to scan. */
export default function Runs() {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);
  const [report, setReport] = useState("");

  async function load() {
    setError(null);
    try { setRuns(await api.runs(report || undefined)); }
    catch (e) { setError(e); }
  }

  useEffect(() => {
    let alive = true;
    setRuns(null);
    api.runs(report || undefined)
      .then((r) => alive && setRuns(r))
      .catch((e) => alive && setError(e));
    return () => { alive = false; };
  }, [report]);

  async function remove(run) {
    await api.deleteRun(run.id);
    await load();
  }

  async function unapprove(run) {
    try { await api.unapprove(run.id); await load(); }
    catch (e) { setError(e); }
  }

  return (
    <>
      <div className="head spread">
        <div>
          <h1>Run history</h1>
          <div className="sub">
            The last 12 weeks. Every build, and what it warned about.
          </div>
        </div>
        <Segmented
          label="Report"
          value={report}
          onChange={setReport}
          options={[
            { value: "", label: "Both" },
            { value: "gfs", label: "GFS" },
            { value: "all_providers", label: "All Providers" },
          ]}
        />
      </div>

      <ErrorBox error={error} />

      {!runs ? <Loading what="Loading runs" /> : (
        <Card flush>
          <DataTable
            /* A week is normally two rows - GFS and All Providers - and more
               when one is rebuilt. The gap between weeks is what stops a
               week's pair reading as four unrelated builds. */
            groupBy={(r) => r.week}
            columns={[
              { key: "week", label: "Week", strong: true, nowrap: true,
                render: (r) => <Link to={`/runs/${r.id}`}>{r.week}</Link> },
              { key: "report", label: "Scorecard", nowrap: true,
                render: (r) => (
                  <span className={`tagline ${r.report_key}`}
                        title={r.report_full}>{r.report}</span>
                ) },
              { key: "status", label: "Status",
                render: (r) => <Status value={r.status} /> },
              { key: "actions", label: "Action", num: true,
                render: (r) => r.actions || "—" },
              { key: "warnings", label: "Warnings", num: true,
                render: (r) => r.warnings || "—" },
              { key: "started_at", label: "Started", nowrap: true,
                render: (r) => when(r.started_at) },
              { key: "approved_by", label: "Approved by", nowrap: true,
                render: (r) => r.approved_by
                  ? <span title={r.approved_by}>
                      {r.approved_by.split("@")[0]}
                    </span>
                  : "—" },
              /* The column that opens the scorecard now says so in its head.
                 A blank header leaves the reader to work out from one row
                 what a whole column is for. */
              { key: "open", label: "Open", width: 96,
                render: (r) => (
                  ["review", "approved"].includes(r.status)
                    ? <Link to={`/dashboard/${r.id}`}>Scorecard</Link>
                    : <span className="muted">—</span>
                ) },
              { key: "manage", label: "Manage", width: 190,
                render: (r) => (
                  <span className="row tight">
                    {r.status === "approved" && (
                      <button className="small quiet" onClick={() => unapprove(r)}>
                        Unapprove
                      </button>
                    )}
                    <ConfirmButton
                      onConfirm={() => remove(r)}
                      disabled={["pending", "running"].includes(r.status)}
                      title={["pending", "running"].includes(r.status)
                        ? "Still building - wait for it to finish."
                        : `Delete ${r.report} ${r.week}`}
                    />
                  </span>
                ) },
            ]}
            rows={runs}
            empty="No builds yet. Upload a week to get started."
          />
        </Card>
      )}

      <div className="small muted" style={{ marginTop: 4 }}>
        Deleting removes the build and its figures. The files you uploaded stay
        where they are — the other report needs them too.
      </div>
    </>
  );
}
