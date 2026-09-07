import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, bytes, when } from "../api";
import { Card, DataTable, ErrorBox, Loading } from "../components";

/* The upload screen.

   The shape of it follows the actual working week: seven files are shared and
   go up once, and each report brings its own Case ARs on the day it is mailed -
   GFS on Tuesday, All Providers on Thursday. So the page asks WHICH REPORT the
   Case ARs belong to rather than guessing, because a wrong guess attaches
   Thursday's case activity to Tuesday's report and nothing in the file would
   ever show it. */

function isoWeek(d = new Date()) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
  const start = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  const n = Math.ceil(((t - start) / 86400000 + 1) / 7);
  return `${t.getUTCFullYear()}-W${String(n).padStart(2, "0")}`;
}

export default function Weeks() {
  const nav = useNavigate();
  const [week, setWeek] = useState(isoWeek());
  const [weeks, setWeeks] = useState([]);
  const [status, setStatus] = useState(null);
  const [forReport, setForReport] = useState("");
  const [progress, setProgress] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [over, setOver] = useState(false);
  const fileInput = useRef();

  const load = async (w) => {
    setError(null);
    try {
      setWeeks(await api.weeks());
      setStatus(await api.week(w));
    } catch (e) { setError(e); }
  };

  useEffect(() => { load(week); }, [week]);

  async function send(files) {
    if (!files?.length) return;
    setError(null); setResult(null); setProgress(0);
    try {
      const r = await api.upload(week, files, {
        forReport: forReport || undefined,
        uploadedBy: "web",
        onProgress: setProgress,
      });
      setResult(r);
      setStatus(r.status);
      setWeeks(await api.weeks());
    } catch (e) { setError(e); }
    finally { setProgress(null); }
  }

  async function build(reportKey) {
    setError(null);
    try {
      const { run_id } = await api.startRun(reportKey, week);
      nav(`/runs/${run_id}`);
    } catch (e) { setError(e); }
  }

  return (
    <>
      <div className="head">
        <h1>Upload a week</h1>
        <div className="sub">
          Seven files are shared. The two Case ARs belong to one report each.
        </div>
      </div>

      <ErrorBox error={error} />

      <Card>
        <div className="row">
          <label>Week</label>
          <input type="text" value={week} size={10}
                 onChange={(e) => setWeek(e.target.value.trim())} />
          {weeks.length > 0 && (
            <select value="" onChange={(e) => e.target.value && setWeek(e.target.value)}>
              <option value="">earlier weeks…</option>
              {weeks.map((w) => <option key={w.week} value={w.week}>{w.week}</option>)}
            </select>
          )}
          <span style={{ flex: 1 }} />
          <label>These Case ARs are for</label>
          <select value={forReport} onChange={(e) => setForReport(e.target.value)}>
            <option value="">— shared files only —</option>
            <option value="gfs">GFS (Tuesday)</option>
            <option value="all_providers">All Providers (Thursday)</option>
          </select>
        </div>

        <div
          className={`drop ${over ? "over" : ""}`}
          style={{ marginTop: 14 }}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); send([...e.dataTransfer.files]); }}
          onClick={() => fileInput.current.click()}
        >
          <input ref={fileInput} type="file" multiple hidden
                 onChange={(e) => send([...e.target.files])} />
          {progress == null ? (
            <>
              <div style={{ fontWeight: 560 }}>Drop this week's files here</div>
              <div className="mono" style={{ marginTop: 6 }}>
                Do not rename them. Anything that is not one of the nine inputs
                is ignored, not read.
              </div>
            </>
          ) : (
            <div>
              <div style={{ fontWeight: 560 }}>Uploading… {Math.round(progress * 100)}%</div>
              <div style={{ height: 4, background: "var(--grid)", borderRadius: 2,
                            marginTop: 10, overflow: "hidden" }}>
                <div style={{ width: `${progress * 100}%`, height: "100%",
                              background: "var(--series-1)" }} />
              </div>
            </div>
          )}
        </div>

        {!forReport && (
          <div className="mono" style={{ marginTop: 10 }}>
            Case AR files will be refused until you say which report they are for.
          </div>
        )}
      </Card>

      {result && (
        <Card title="What was received">
          <DataTable
            columns={[
              { key: "label", label: "Input" },
              { key: "filename", label: "File" },
              { key: "scope", label: "Used by" },
              { key: "size_bytes", label: "Size", num: true,
                render: (r) => bytes(r.size_bytes) },
              { key: "already_held", label: "",
                render: (r) => (r.already_held ? "already held" : "") },
            ]}
            rows={result.accepted}
          />
          {result.rejected.length > 0 && (
            <>
              <h3 style={{ marginTop: 16 }}>Ignored</h3>
              <DataTable
                columns={[{ key: "filename", label: "File" },
                          { key: "reason", label: "Why" }]}
                rows={result.rejected}
              />
            </>
          )}
        </Card>
      )}

      {status ? (
        <div className="grid cols-2">
          {Object.entries(status.reports).map(([key, r]) => (
            <Card key={key} title={r.label} sub={`mailed ${r.send_day}`}
                  right={
                    <button className="primary" disabled={!r.ready}
                            onClick={() => build(key)}>
                      {r.ready ? "Build" : "Not ready"}
                    </button>
                  }>
              {r.missing.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <h3>Still needed</h3>
                  {r.missing.map((m) => <div key={m}>· {m}</div>)}
                </div>
              )}
              <DataTable
                columns={[
                  { key: "filename", label: "Held", render: (h) => h.filename },
                  { key: "uploaded_at", label: "Received",
                    render: (h) => when(h.uploaded_at) },
                  { key: "size_bytes", label: "Size", num: true,
                    render: (h) => bytes(h.size_bytes) },
                ]}
                rows={r.have}
                empty="Nothing uploaded for this week yet."
              />
            </Card>
          ))}
        </div>
      ) : <Loading what="Checking the week" />}
    </>
  );
}
