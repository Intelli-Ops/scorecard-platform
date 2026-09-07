import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, count, when } from "../api";
import { Card, DataTable, ErrorBox, Loading, Segmented, Status } from "../components";

/* Run history - what dated folders on one laptop could never provide.
   Every build of every report, who approved it, and what it warned about. */
export default function Runs() {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);
  const [report, setReport] = useState("");

  useEffect(() => {
    let alive = true;
    setRuns(null);
    api.runs(report || undefined)
      .then((r) => alive && setRuns(r))
      .catch((e) => alive && setError(e));
    return () => { alive = false; };
  }, [report]);

  if (error) return <ErrorBox error={error} />;

  return (
    <>
      <div className="head spread">
        <div>
          <h1>Run history</h1>
          <div className="sub">Every build, and what it warned about.</div>
        </div>
        <Segmented
          value={report}
          onChange={setReport}
          options={[
            { value: "", label: "Both" },
            { value: "gfs", label: "GFS" },
            { value: "all_providers", label: "All Providers" },
          ]}
        />
      </div>

      {!runs ? <Loading what="Loading runs" /> : (
        <Card flush>
          <DataTable
            columns={[
              { key: "week", label: "Week", strong: true,
                render: (r) => <Link to={`/runs/${r.id}`}>{r.week}</Link> },
              { key: "status", label: "Status",
                render: (r) => <Status value={r.status} /> },
              { key: "actions", label: "Action", num: true,
                render: (r) => r.actions || "—" },
              { key: "warnings", label: "Warnings", num: true,
                render: (r) => r.warnings || "—" },
              { key: "rows", label: "Raw data rows", num: true,
                render: (r) => count(r.rows?.raw_data) },
              { key: "seconds", label: "Built in", num: true,
                render: (r) => (r.seconds ? `${r.seconds.toFixed(0)}s` : "—") },
              { key: "started_at", label: "Started",
                render: (r) => when(r.started_at) },
              { key: "approved_by", label: "Approved by",
                render: (r) => r.approved_by ?? "—" },
              { key: "open", label: "",
                render: (r) => <Link to={`/dashboard/${r.id}`}>Scorecard</Link> },
            ]}
            rows={runs}
            empty="No builds yet. Upload a week to get started."
          />
        </Card>
      )}
    </>
  );
}
