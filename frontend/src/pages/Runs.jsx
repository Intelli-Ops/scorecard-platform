import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, count, when } from "../api";
import { Card, DataTable, ErrorBox, Loading, Status } from "../components";

/* Run history - the thing dated folders on one laptop could never provide.

   Every build of every report, who approved it, and how many warnings it
   raised. A count that jumps week on week is visible from this list alone. */
export default function Runs() {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);
  const [report, setReport] = useState("");

  useEffect(() => {
    let alive = true;
    api.runs(report || undefined)
      .then((r) => alive && setRuns(r))
      .catch((e) => alive && setError(e));
    return () => { alive = false; };
  }, [report]);

  if (error) return <ErrorBox error={error} />;
  if (!runs) return <Loading what="Loading runs" />;

  return (
    <>
      <div className="head">
        <h1>Run history</h1>
        <div className="sub">Every build, and what it warned about.</div>
      </div>

      <Card right={
        <select value={report} onChange={(e) => setReport(e.target.value)}>
          <option value="">Both reports</option>
          <option value="gfs">GFS</option>
          <option value="all_providers">All Providers</option>
        </select>
      }>
        <DataTable
          columns={[
            { key: "week", label: "Week",
              render: (r) => <Link to={`/runs/${r.id}`}>{r.week}</Link> },
            { key: "status", label: "Status", render: (r) => <Status value={r.status} /> },
            { key: "actions", label: "Action", num: true,
              render: (r) => (r.actions ? `! ${r.actions}` : "—") },
            { key: "warnings", label: "Warnings", num: true,
              render: (r) => r.warnings || "—" },
            { key: "raw", label: "Raw Data rows", num: true,
              render: (r) => count(r.rows?.raw_data) },
            { key: "seconds", label: "Built in", num: true,
              render: (r) => (r.seconds ? `${r.seconds.toFixed(0)}s` : "—") },
            { key: "started_at", label: "Started", render: (r) => when(r.started_at) },
            { key: "approved_by", label: "Approved by",
              render: (r) => r.approved_by ?? "—" },
            { key: "open", label: "",
              render: (r) => <Link to={`/dashboard/${r.id}`}>Dashboard</Link> },
          ]}
          rows={runs}
          empty="No builds yet. Upload a week to get started."
        />
      </Card>
    </>
  );
}
