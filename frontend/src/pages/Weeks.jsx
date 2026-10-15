// Uploading a week's files and starting builds.
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, bytes, when } from "../api";
import { useAuth } from "../auth";
import WorkingDays from "../WorkingDays";
import { Card, DataTable, ErrorBox, Loading, Picker }
  from "../components";
import { Button, DeleteButton } from "../buttons";
import { REPORT_OPTIONS } from "../reports";
import { useLoad } from "../hooks";

// Uploading a week.

function isoWeek(d = new Date()) {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
  const start = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  const n = Math.ceil(((t - start) / 86400000 + 1) / 7);
  return `${t.getUTCFullYear()}-W${String(n).padStart(2, "0")}`;
}

const WEEK_RE = /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/;

export default function Weeks() {
  const nav = useNavigate();
  const { user } = useAuth();
  const [week, setWeek] = useState(isoWeek());
  const [forReport, setForReport] = useState("");
  const [progress, setProgress] = useState(null);
  const [over, setOver] = useState(false);
  const [building, setBuilding] = useState(null);
  const fileInput = useRef();
  const validWeek = WEEK_RE.test(week);

  const weeksLoad = useLoad(api.weeks, []);
  const statusLoad = useLoad(
    () => (validWeek ? api.week(week) : Promise.resolve(null)), [week]);
  const weeks = weeksLoad.data ?? [];
  const status = statusLoad.data;

  const [result, setResult] = useState(null);
  const [failure, setFailure] = useState(null);
  const setError = (e) => setFailure(e ? { week, error: e } : null);
  const error = (failure?.week === week ? failure.error : null)
    ?? statusLoad.error ?? weeksLoad.error;

  async function send(files) {
    if (!files?.length || !validWeek) return;
    setError(null); setResult(null); setProgress(0);
    try {
      const r = await api.upload(week, files, {
        forReport: forReport || undefined,
        onProgress: setProgress,
      });
      setResult(r);
      statusLoad.setData(r.status);
      await weeksLoad.reload();
    } catch (e) { setError(e); }
    finally { setProgress(null); }
  }

  async function build(reportKey) {
    setBuilding(reportKey);
    try {
      const { run_id } = await api.startRun(reportKey, week);
      nav(`/runs/${run_id}`);
    } catch (e) {
      if (e.detail?.run_id) nav(`/runs/${e.detail.run_id}`);
      else setError(e);
    } finally { setBuilding(null); }
  }

  const uploaded = status?.files ?? 0;

  async function removeWeek() {
    try {
      setError(null);
      await api.deleteWeek(week);
      setResult(null);
      await Promise.all([weeksLoad.reload(), statusLoad.reload()]);
    } catch (e) { setError(e); }
  }

  async function removeFile(id) {
    try {
      setError(null);
      const r = await api.removeUpload(week, id);
      setResult(null);
      statusLoad.setData(r.status);
      await weeksLoad.reload();
    } catch (e) { setError(e); }
  }

  return (
    <>
      <div className="head">
        <h1>Upload a week</h1>
        <div className="sub">
          Seven files are shared between the reports. The two Case ARs belong to
          one report each. On Tuesday, add the two Delta &ldquo;- comments&rdquo;
          copies too: they fill Ongoing DOR Status and Details in GFS&apos;s Delta
          raw data.
        </div>
      </div>

      <ErrorBox error={error} />

      <Card>
        <div className="spread" style={{ marginBottom: 16 }}>
          <div className="filter">
            <span className="filter-label">Week</span>
            <input type="text" value={week} size={9}
                   onChange={(e) => setWeek(e.target.value.trim())} />
            {weeks.length > 0 && (
              <select className="picker" value=""
                      onChange={(e) => e.target.value && setWeek(e.target.value)}>
                <option value="">earlier weeks…</option>
                {weeks.map((w) => <option key={w.week} value={w.week}>{w.week}</option>)}
              </select>
            )}
          </div>
          <span className="row tight">
            <Picker label="These Case ARs are for" value={forReport}
                    onChange={setForReport} active={!!forReport}
                    onClear={() => setForReport("")}
                    options={[
                      { value: "", label: "Shared files only" },
                      ...REPORT_OPTIONS.map((r) => (
                        { value: r.key, label: `${r.short} · ${r.sendDay}` })),
                    ]} />
            {uploaded > 0 && user.is_admin && (
              <DeleteButton
                label={`Delete ${week}`}
                onConfirm={removeWeek}
                title={`Remove every file uploaded for ${week}, and its builds. `
                       + `This cannot be undone.`} />
            )}
          </span>
        </div>

        <div
          className={`drop ${over ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); send([...e.dataTransfer.files]); }}
          onClick={() => validWeek && fileInput.current.click()}
        >
          <input ref={fileInput} type="file" multiple hidden
                 onChange={(e) => {
                   send([...e.target.files]);
                   e.target.value = "";
                 }} />
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

        {validWeek && <WorkingDays key={week} week={week} />}
      </Card>

      {result?.week === week && (
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
                      ? <Button tone="primary" onClick={() => build(key)}
                                disabled={building != null && building !== key}
                                busy={building === key} busyLabel="Starting…">
                          Build
                        </Button>
                      : <span className="pill">{r.missing.length} still needed</span>
                  }>
              <DataTable
                columns={[
                  { key: "filename", label: "File" },
                  { key: "uploaded_at", label: "Received",
                    render: (h) => when(h.uploaded_at) },
                  { key: "size_bytes", label: "Size", num: true,
                    render: (h) => bytes(h.size_bytes) },
                  { key: "id", label: "",
                    render: (h) => (h.read_by_a_build
                      ? <span className="small muted"
                              title="A build read this file. Delete that build to remove it.">
                          used by a build
                        </span>
                      : <DeleteButton size="sm" label="Remove"
                                      confirm="Confirm remove"
                                      onConfirm={() => removeFile(h.id)}
                                      title={`Remove ${h.filename} from ${week}`} />) },
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
      ) : validWeek ? <Loading what="Checking the week" /> : (
        <div className="empty">Type a week as 2026-W38.</div>
      )}
    </>
  );
}
