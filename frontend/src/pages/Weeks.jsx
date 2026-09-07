import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, bytes, when } from "../api";
import { Card, DataTable, ErrorBox, Loading } from "../components";

/* Uploading a week.

   Shaped like the actual working week: seven files are shared and go up once,
   and each report brings its own Case ARs on the day it is mailed - GFS on
   Tuesday, All Providers on Thursday. The page asks which report a Case AR is
   for rather than guessing, because guessing wrong attaches Thursday's case
   activity to Tuesday's report and nothing in the file would ever show it. */

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

  useEffect(() => {
    let alive = true;
    setStatus(null);
    (async () => {
      try {
        const [w, s] = await Promise.all([api.weeks(), api.week(week)]);
        if (!alive) return;
        setWeeks(w); setStatus(s);
      } catch (e) { alive && setError(e); }
    })();
    return () => { alive = false; };
  }, [week]);

  async function send(files) {
    if (!files?.length) return;
    setError(null); setResult(null); setProgress(0);
    try {
      const r = await api.upload(week, files, {
        forReport: forReport || undefined, uploadedBy: "web",
        onProgress: setProgress,
      });
      setResult(r); setStatus(r.status);
      setWeeks(await api.weeks());
    } catch (e) { setError(e); }
    finally { setProgress(null); }
  }

  async function build(reportKey) {
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
          Seven files are shared between the reports. The two Case ARs belong to
          one report each.
        </div>
      </div>

      <ErrorBox error={error} />

      <Card>
        <div className="spread" style={{ marginBottom: 16 }}>
          <div className="row">
            <label>Week</label>
            <input type="text" value={week} size={9}
                   onChange={(e) => setWeek(e.target.value.trim())} />
            {weeks.length > 0 && (
              <select value="" onChange={(e) => e.target.value && setWeek(e.target.value)}>
                <option value="">earlier weeks…</option>
                {weeks.map((w) => <option key={w.week} value={w.week}>{w.week}</option>)}
              </select>
            )}
          </div>
          <div className="row">
            <label>These Case ARs are for</label>
            <select value={forReport} onChange={(e) => setForReport(e.target.value)}>
              <option value="">Shared files only</option>
              <option value="gfs">GFS · Tuesday</option>
              <option value="all_providers">All Providers · Thursday</option>
            </select>
          </div>
        </div>

        <div
          className={`drop ${over ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); send([...e.dataTransfer.files]); }}
          onClick={() => fileInput.current.click()}
        >
          <input ref={fileInput} type="file" multiple hidden
                 onChange={(e) => send([...e.target.files])} />
          {progress == null ? (
            <>
              <div className="big">Drop this week's files here</div>
              <div className="small" style={{ marginTop: 6 }}>
                Keep their names as they are. Anything that is not one of the
                inputs is ignored, not read.
              </div>
            </>
          ) : (
            <>
              <div className="big">Uploading {Math.round(progress * 100)}%</div>
              <div className="bar" style={{ marginTop: 14, maxWidth: 420,
                                            marginInline: "auto" }}>
                <span style={{ width: `${progress * 100}%` }} />
              </div>
            </>
          )}
        </div>

        {!forReport && (
          <div className="small muted" style={{ marginTop: 12 }}>
            Case AR files are refused until you say which report they belong to.
          </div>
        )}
      </Card>

      {result && (
        <Card flush title="What was received"
              sub={`${result.accepted.length} accepted, ${result.rejected.length} ignored`}>
          <DataTable
            columns={[
              { key: "label", label: "Input", strong: true },
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
            <DataTable
              columns={[{ key: "filename", label: "Ignored" },
                        { key: "reason", label: "Why" }]}
              rows={result.rejected}
            />
          )}
        </Card>
      )}

      {status ? (
        <div className="grid cols-2">
          {Object.entries(status.reports).map(([key, r]) => (
            <Card key={key} flush title={r.label} sub={`Mailed ${r.send_day}`}
                  right={
                    r.ready
                      ? <button className="primary" onClick={() => build(key)}>Build</button>
                      /* Not a button when there is nothing to press: a greyed-out
                         primary still reads as the thing to click. */
                      : <span className="pill">{r.missing.length} still needed</span>
                  }>
              <DataTable
                columns={[
                  { key: "filename", label: "File" },
                  { key: "uploaded_at", label: "Received",
                    render: (h) => when(h.uploaded_at) },
                  { key: "size_bytes", label: "Size", num: true,
                    render: (h) => bytes(h.size_bytes) },
                ]}
                rows={r.have}
                empty="Nothing uploaded for this week yet."
              />
              {r.missing.length > 0 && (
                <div style={{ padding: "14px 22px", borderTop: "1px solid var(--line)" }}>
                  <h3>Still needed</h3>
                  {r.missing.map((m) => (
                    <div key={m} className="small muted">{m}</div>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      ) : <Loading what="Checking the week" />}
    </>
  );
}
