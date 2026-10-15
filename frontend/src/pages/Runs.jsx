// Build history.
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, when } from "../api";
import { useAuth } from "../auth";
import { useLoad } from "../hooks";
import { REPORT_OPTIONS } from "../reports";
import { Card, DataTable, ErrorBox, Loading, Segmented,
         Status } from "../components";
import { Button, DeleteButton } from "../buttons";

// Run history - what dated folders on one laptop could never provide.
export default function Runs() {
  const { user } = useAuth();
  const [report, setReport] = useState("");
  const { data: runs, error, setError, reload } =
    useLoad(() => api.runs(report || undefined), [report]);

  const act = (fn) => async (run) => {
    try { await fn(run.id); await reload(); } catch (e) { setError(e); }
  };
  const remove = act(api.deleteRun);
  const unapprove = act(api.unapprove);

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
          onClear={report ? () => setReport("") : undefined}
          options={[{ value: "", label: "Both" },
                    ...REPORT_OPTIONS.map((r) => ({ value: r.key, label: r.short }))]}
        />
      </div>

      <ErrorBox error={error} />

      {!runs ? <Loading what="Loading runs" /> : (
        <Card flush>
          <DataTable
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
                render: (r) => r.actions || "-" },
              { key: "warnings", label: "Warnings", num: true,
                render: (r) => r.warnings || "-" },
              { key: "started_at", label: "Started", nowrap: true,
                render: (r) => when(r.started_at) },
              { key: "approved_by", label: "Approved by", nowrap: true,
                render: (r) => r.approved_by
                  ? <span title={r.approved_by}>
                      {r.approved_by.split("@")[0]}
                    </span>
                  : "-" },
              { key: "open", label: "Open", width: 96,
                render: (r) => (
                  ["review", "approved"].includes(r.status)
                    ? <Link to={`/dashboard/${r.id}`}>Scorecard</Link>
                    : <span className="muted">-</span>
                ) },
              { key: "manage", label: "Manage", width: 190,
                render: (r) => (
                  <span className="row tight">
                    {r.status === "approved" && (
                      <Button tone="soft" size="sm" onClick={() => unapprove(r)}>
                        Unapprove
                      </Button>
                    )}
                    {user.is_admin && <DeleteButton
                      onConfirm={() => remove(r)}
                      disabled={["pending", "running"].includes(r.status)}
                      title={["pending", "running"].includes(r.status)
                        ? "Still building - wait for it to finish."
                        : `Delete ${r.report} ${r.week}, and the files it `
                          + `read once no other run needs them`}
                    />}
                  </span>
                ) },
            ]}
            rows={runs}
            empty="No builds yet. Upload a week to get started."
          />
        </Card>
      )}

      <div className="small muted" style={{ marginTop: 4 }}>
        {user.is_admin
          ? "Deleting removes the build and its figures. The files you uploaded "
            + "stay where they are, because the other report needs them too."
          : "Only an admin can delete a build."}
      </div>
    </>
  );
}
