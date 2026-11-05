// Uploading a week's files and starting builds.
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, bytes, when } from "../api";
import { useAuth } from "../auth";
import WorkingDays from "../WorkingDays";
import { Card, DataTable, ErrorBox, Loading, Modal, Picker }
  from "../components";
import { Button, DeleteButton } from "../buttons";
import { LockIcon, TrashIcon, UploadIcon } from "../icons";
import { REPORT_OPTIONS, reportShort } from "../reports";
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
  const [sendingAs, setSendingAs] = useState(null);
  const [deleting, setDeleting] = useState(null);     // the file the delete window asks about
  const fileInput = useRef();
  const validWeek = WEEK_RE.test(week);
  const mine = new Set(user.uploads ?? []);       // the inputs this account may upload
  const sources = useLoad(api.reports, []).data ?? [];
  const labels = [...new Map(sources.flatMap((r) => r.sources)
    .map((x) => [x.key, x.label])).entries()];

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

  // One file per request: nginx caps each request (DEPLOY.md), and a week's files together can pass that cap even when each one is well under it.
  // With `as`, the files are taken as that one input whatever they are called, once their columns check out.
  async function send(files, as) {
    if (!files?.length || !validWeek) return;
    setError(null); setResult(null); setProgress(0);
    if (as) setSendingAs(as.key);
    const total = files.reduce((n, f) => n + f.size, 0) || 1;
    const out = { week, accepted: [], rejected: [] };
    let done = 0;
    try {
      for (const f of files) {
        try {
          const r = await api.upload(week, [f], {
            forReport: (as ? as.forReport : forReport) || undefined,
            asSource: as?.key,
            onProgress: (p) => setProgress((done + p * f.size) / total),
          });
          out.accepted.push(...r.accepted);
          out.rejected.push(...r.rejected);
          out.status = r.status;
        } catch (e) {
          out.rejected.push({ filename: f.name, reason: e.message });
        }
        done += f.size;
      }
      setResult(out);
      if (out.status) statusLoad.setData(out.status);
      await weeksLoad.reload();
    } catch (e) { setError(e); }
    finally { setProgress(null); setSendingAs(null); }
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

  // Throws, so the confirmation window can say what went wrong.
  async function removeFile(id) {
    setError(null);
    const r = await api.removeUpload(week, id);
    setResult(null);
    statusLoad.setData(r.status);
    await weeksLoad.reload();
  }

  // The scorecards a file is listed under - both, for a shared file.
  const listedIn = (id) => Object.entries(status?.reports ?? {})
    .filter(([, r]) => r.have.some((h) => h.id === id)).map(([k]) => reportShort(k));

  return (
    <>
      <div className="head">
        <h1>Upload a week</h1>
        <div className="sub">
          Six files are shared between the reports, KPI numbers among them. The
          two Case ARs belong to one report each, and the two Delta &ldquo;-
          comments&rdquo; copies are GFS&apos;s only. KPI numbers and the comments
          usually come in on Tuesday: build without them on Monday and the build
          is marked partial.
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
            {uploaded > 0 && user.is_admin && user.uploads_all && (
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

        {!user.uploads_all && (
          <div className="small muted" style={{ marginTop: 12 }}>
            Your account uploads only: {(user.uploads ?? []).length
              ? labels.filter(([k]) => mine.has(k)).map(([, l]) => l).join(", ")
              : "no files yet - ask a system admin"}. Any other file is refused.
          </div>
        )}

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
                      ? (
                        <span className="row tight">
                          {!r.complete && (
                            <span className="pill warn">Partial · {r.missing.length} missing</span>
                          )}
                          <Button tone="primary" onClick={() => build(key)}
                                  disabled={building != null && building !== key}
                                  busy={building === key} busyLabel="Starting…">
                            {r.complete ? "Build" : "Build partial"}
                          </Button>
                        </span>
                      )
                      : <span className="pill">Nothing uploaded yet</span>
                  }>
              <DataTable
                columns={[
                  { key: "filename", label: "File" },
                  { key: "uploaded_at", label: "Received",
                    render: (h) => when(h.uploaded_at) },
                  { key: "size_bytes", label: "Size", num: true,
                    render: (h) => bytes(h.size_bytes) },
                  { key: "id", label: "", width: 52,
                    render: (h) => (mine.has(h.source_key) && (
                      <button type="button" className="icon-btn danger"
                              aria-label={`Delete ${h.filename}`}
                              title={`Delete ${h.filename} from ${week}`}
                              onClick={() => setDeleting(h)}>
                        <TrashIcon />
                      </button>
                    )) },
                ]}
                rows={r.have}
                empty="Nothing uploaded for this week yet."
              />
              {r.missing.length > 0 && (
                <div className="missing">
                  <div className="missing-head">
                    <h3>Not in yet <span className="missing-count">{r.missing.length}</span></h3>
                    <div className="small muted">
                      You can build without these: the parts that need them show no data.
                      {user.is_admin && r.missing_files
                        && " Upload one under any name, or drop it on its row: its sheets and columns are checked first."}
                    </div>
                  </div>
                  <ul className="missing-list">
                    {r.missing_files && user.is_admin
                      ? r.missing_files.map((m) => (
                        <MissingFile key={m.key} file={m} reportShort={reportShort(key)}
                                     disabled={progress != null}
                                     allowed={mine.has(m.key)}
                                     busy={sendingAs === m.key}
                                     progress={sendingAs === m.key ? progress : null}
                                     onPick={(f) => send([f], {
                                       key: m.key,
                                       forReport: m.per_report ? key : undefined,
                                     })} />
                      ))
                      : r.missing.map((m) => (
                        <li key={m} className="missing-row">
                          <FileBadge exts={[]} />
                          <span className="missing-text">
                            <span className="missing-name">{m}</span>
                          </span>
                        </li>
                      ))}
                  </ul>
                </div>
              )}
            </Card>
          ))}
        </div>
      ) : validWeek ? <Loading what="Checking the week" /> : (
        <div className="empty">Type a week as 2026-W38.</div>
      )}

      {deleting && (
        <DeleteFile file={deleting} week={week} listedIn={listedIn(deleting.id)}
                    onDelete={() => removeFile(deleting.id)}
                    onClose={() => setDeleting(null)} />
      )}
    </>
  );
}

// Asks before a file is deleted, and says plainly what will and will not change.
function DeleteFile({ file, week, listedIn, onDelete, onClose }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const where = listedIn.length > 1 ? `${listedIn.join(" and ")} scorecards`
    : `${listedIn[0] ?? "its"} scorecard`;
  const n = file.builds ?? 0;

  async function go() {
    setBusy(true); setError(null);
    try { await onDelete(); onClose(); }
    catch (e) { setError(e); setBusy(false); }
  }

  return (
    <Modal title="Delete this file?" icon={<TrashIcon />} tone="danger" width={520}
           sub={file.filename} onClose={onClose} locked={busy}
           footer={<>
             <span className="modal-note" />
             <Button tone="quiet" onClick={onClose} disabled={busy}>Cancel</Button>
             <Button tone="danger" solid icon={<TrashIcon />} onClick={go}
                     busy={busy} busyLabel="Deleting…">Delete file</Button>
           </>}>
      {error && <div className="modal-error">{String(error.message ?? error)}</div>}
      <ul className="facts">
        <li className="fact gone">
          <span className="fact-mark" aria-hidden="true">−</span>
          <span>
            Removed from the <strong>{where}</strong> for {week}.
            {listedIn.length > 1 && " Both use this one file."}
          </span>
        </li>
        <li className="fact">
          <span className="fact-mark" aria-hidden="true">↑</span>
          <span>It moves to <strong>Not in yet</strong>, so the right one can be uploaded in
            its place. The next build will not use it.</span>
        </li>
        <li className="fact kept">
          <span className="fact-mark" aria-hidden="true">✓</span>
          <span>
            {n
              ? <><strong>{n === 1 ? "The scorecard" : `The ${n} scorecards`} already built
                  from it</strong> {n === 1 ? "stays" : "stay"} exactly as {n === 1 ? "it is" : "they are"},
                  approved ones included. Build again to use a new file.</>
              : "No scorecard has been built from it yet."}
          </span>
        </li>
      </ul>
    </Modal>
  );
}

// The file's kind as a small coloured badge: XLS for a workbook, CSV for a table.
function FileBadge({ exts }) {
  const csv = exts.length > 0 && exts.every((x) => x === ".csv");
  const kind = !exts.length ? "file" : csv ? "csv" : "xls";
  return (
    <span className={`file-badge ${kind}`} aria-hidden="true">
      <span>{kind === "file" ? "" : kind.toUpperCase()}</span>
    </span>
  );
}

const extList = (exts) => exts.map((x) => x.slice(1).toUpperCase()).join(" or ");

// One input that is not in yet: its name, what kind of file it takes, and an Upload button -
// or drop the file on the row. Either way the file is taken as this input, whatever it is called.
function MissingFile({ file, reportShort, onPick, busy, progress, disabled, allowed }) {
  const input = useRef();
  const [over, setOver] = useState(false);
  const meta = [`${extList(file.exts)} file`,
                file.per_report ? `${reportShort}'s own copy` : null,
                "any file name"].filter(Boolean).join(" · ");

  if (!allowed) {
    return (
      <li className="missing-row locked">
        <FileBadge exts={file.exts} />
        <span className="missing-text">
          <span className="missing-name">{file.label}</span>
          <span className="missing-meta">{meta}</span>
        </span>
        <span className="missing-lock" title="A system admin has given this file to another admin">
          <LockIcon /> Another admin uploads this
        </span>
      </li>
    );
  }

  const drop = !disabled ? {
    onDragOver: (e) => { e.preventDefault(); setOver(true); },
    onDragLeave: () => setOver(false),
    onDrop: (e) => {
      e.preventDefault(); setOver(false);
      const f = e.dataTransfer.files?.[0];
      if (f) onPick(f);
    },
  } : {};

  return (
    <li className={`missing-row${over ? " over" : ""}${busy ? " busy" : ""}`} {...drop}>
      <FileBadge exts={file.exts} />
      <span className="missing-text">
        <span className="missing-name">{file.label}</span>
        <span className="missing-meta">
          {busy ? "Checking its sheets and columns…" : over ? "Drop to upload it as this file" : meta}
        </span>
      </span>
      <input ref={input} type="file" hidden accept={file.exts.join(",")}
             onChange={(e) => {
               const f = e.target.files?.[0];
               e.target.value = "";
               if (f) onPick(f);
             }} />
      <Button size="sm" tone="go" icon={busy ? <span className="spinner" /> : <UploadIcon />}
              disabled={disabled} busy={busy} busyLabel="Checking…"
              onClick={() => input.current.click()}
              title={`Choose the ${file.label} file, whatever it is called`}>
        Upload
      </Button>
      {busy && progress != null && (
        <span className="missing-progress" aria-hidden="true">
          <span style={{ width: `${Math.max(progress, 0.04) * 100}%` }} />
        </span>
      )}
    </li>
  );
}
