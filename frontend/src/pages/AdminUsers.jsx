// Admin: accounts, roles, access and approvals.
import { useState } from "react";
import { api, stamp, when } from "../api";
import { useAuth } from "../auth";
import { useLoad } from "../hooks";
import { Card, DataTable, ErrorBox, Loading, Modal } from "../components";
import { Button, ConfirmButton, ConfirmPair, DeleteButton } from "../buttons";
import { Stat, Stats } from "../ui";
import { CheckIcon, CrossIcon, KeyIcon, LeaveIcon, PauseIcon, PlayIcon, SlidersIcon,
         UnlockIcon, UploadRightsIcon } from "../icons";

const STATUS = {
  unverified: ["", "Email not confirmed"],
  pending: ["warn", "Waiting"],
  active: ["good", "Active"],
  locked: ["alert", "Locked"],
  disabled: ["", "Disabled"],
};

const ROLE_LABEL = { viewer: "Viewer", admin: "Admin", system_admin: "System admin" };

export default function AdminUsers() {
  const { user: me, signOut } = useAuth();
  const { data: users, error, setError, reload } = useLoad(api.users, []);
  const reports = useLoad(api.reports, []).data ?? [];
  const [sent, setSent] = useState(null);       // whose password was just reset

  const act = (fn) => async () => {
    setError(null);
    try { await fn(); await reload(); } catch (e) { setError(e); }
  };

  async function reset(u) {
    setError(null);
    try {
      const r = await api.resetPassword(u.id);
      setSent(r.notified);
      await reload();
    } catch (e) { setError(e); }
  }

  async function removeSelf(u) {
    try { await api.deleteUser(u.id); await signOut(); }
    catch (e) { setError(e); }
  }

  if (!users) return error ? <ErrorBox error={error} /> : <Loading what="Loading accounts" />;

  const count = (fn) => users.filter(fn).length;
  const waiting = count((u) => u.status === "pending");

  return (
    <>
      <div className="head">
        <h1>Users</h1>
        <div className="sub">
          Viewers read the scorecards they are given. Admins upload, build and
          approve; a system admin can narrow which files each admin may upload.
          Only a system admin can make or change an admin.
        </div>
      </div>

      <ErrorBox error={error} />

      {sent && (
        <Card title={`Password reset for ${sent}`}
              sub="Their old password no longer works, and every session has been signed out."
              right={<Button tone="quiet" size="sm" onClick={() => setSent(null)}>Done</Button>}>
          <div className="small muted">
            We have emailed them to choose a new one with "Forgot password?" on
            the sign-in screen, which sends a 6-digit code to their email.
          </div>
        </Card>
      )}

      <Stats>
        <Stat label="Accounts" value={users.length}
              foot={`${count((u) => u.status === "active")} active`} />
        <Stat label="Admins" value={count((u) => u.is_admin)}
              foot={`${count((u) => u.is_system_admin)} system admin`
                    + `${count((u) => u.is_system_admin) === 1 ? "" : "s"}`} />
        <Stat label="Viewers" value={count((u) => u.role === "viewer")}
              foot={`${count((u) => u.role === "viewer" && !u.reports.length)} with no scorecard yet`} />
        <Stat label="Waiting" value={waiting} tone={waiting ? "amber" : undefined}
              foot={waiting ? "need approving" : "none waiting"} />
      </Stats>

      <Card flush>
        <DataTable
          rows={users}
          rowClass={(u) => (u.status === "pending" ? "highlight" : "")}
          columns={[
            { key: "name", label: "Person", strong: true,
              render: (u) => (
                <span className="who-cell">
                  <span title={`${u.name} · ${u.apd_id}`}>
                    {u.name}
                    <span className="muted small"> · {u.apd_id}</span>
                    {u.id === me.id && <span className="muted"> · you</span>}
                  </span>
                  <span className="small muted" title={u.email}>{u.email}</span>
                </span>
              ) },
            { key: "role", label: "Role",
              render: (u) => <RoleCell u={u} act={act} /> },
            { key: "reports", label: "Scorecards",
              render: (u) => <AccessCell u={u} reports={reports} act={act} /> },
            { key: "uploads", label: "Uploads",
              render: (u) => <UploadsCell u={u} reports={reports} onSaved={reload} /> },
            { key: "status", label: "Status",
              render: (u) => {
                const [tone, word] = STATUS[u.status] ?? ["", u.status];
                return (
                  <span className="who-cell">
                    <span><span className={`pill ${tone}`}
                                title={u.status === "locked"
                                  ? `Until ${stamp(u.locked_until)}` : undefined}>{word}</span></span>
                    <span className="small muted" style={{ marginTop: 4 }}>
                      {u.last_login_at ? `signed in ${when(u.last_login_at)}` : "never signed in"}
                    </span>
                  </span>
                );
              } },
            { key: "manage", label: "Manage", className: "actions",
              render: (u) => <Actions u={u} me={me} act={act} reset={reset}
                                      removeSelf={removeSelf} /> },
          ]}
        />
      </Card>
    </>
  );
}

// The role: a choice for a system admin looking at someone they manage, a label for everyone else.
function RoleCell({ u, act }) {
  const [pending, setPending] = useState(null);
  const label = <span className={`pill role-${u.role}`}>{ROLE_LABEL[u.role] ?? u.role}</span>;
  if (!u.can.roles.length) return label;

  if (pending) {
    return (
      <ConfirmPair confirm="Confirm system admin" busyLabel="Saving…"
                   onConfirm={act(() => api.setRole(u.id, pending))}
                   onCancel={() => setPending(null)} />
    );
  }
  return (
    <select className="picker role" value={u.role}
            onChange={(e) => e.target.value === "system_admin"
              ? setPending("system_admin")
              : act(() => api.setRole(u.id, e.target.value))()}>
      {u.can.roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
    </select>
  );
}

// Which scorecards a viewer may read: one chip per report, pressed or not.
function AccessCell({ u, reports, act }) {
  if (u.is_admin) return <span className="muted small">All scorecards</span>;
  return (
    <span className="chips">
      {reports.map((r) => {
        const on = u.reports.includes(r.key);
        const next = on ? u.reports.filter((k) => k !== r.key) : [...u.reports, r.key];
        return (
          <button key={r.key} type="button" className={`chip${on ? " on" : ""}`}
                  disabled={!u.can.access} aria-pressed={on}
                  title={u.can.access ? `${on ? "Take away" : "Give"} ${r.label}` : r.label}
                  onClick={act(() => api.setAccess(u.id, next))}>
            {on && (
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
                <path d="M2 5.2 4.1 7.3 8 3" fill="none" stroke="currentColor"
                      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
            {r.short}
          </button>
        );
      })}
      {!u.reports.length && !u.can.access && <span className="muted small">None</span>}
    </span>
  );
}

// The input names, short enough for a tag.
const INPUT_SHORT = {
  delta_wc: "Delta WC", delta_mlcr: "Delta MLCR",
  delta_wc_comments: "Delta WC comments", delta_mlcr_comments: "Delta MLCR comments",
  payment_detail: "Payment Detail", hearing_calendar: "Hearing Calendar",
  document_log: "Document log", kpi_numbers: "KPI numbers",
  owner_case_ar: "Owner Case AR", custom_case_ar: "Custom Case AR",
};
const short = (s) => INPUT_SHORT[s.key] ?? s.label;

// How the upload rights window groups the files; any file not named here goes under "Other files".
const FILE_GROUPS = [
  ["Delta workbooks", ["delta_wc", "delta_mlcr", "delta_wc_comments", "delta_mlcr_comments"]],
  ["Case ARs", ["owner_case_ar", "custom_case_ar"]],
];

// Every input once, with the scorecards that read it.
function inputsOf(reports) {
  const seen = new Map();
  for (const r of reports) {
    for (const s of r.sources) {
      const x = seen.get(s.key) ?? { ...s, reports: [] };
      x.reports.push(r);
      seen.set(s.key, x);
    }
  }
  return [...seen.values()];
}

function groupsOf(inputs) {
  const byKey = new Map(inputs.map((s) => [s.key, s]));
  const named = new Set(FILE_GROUPS.flatMap(([, keys]) => keys));
  return [
    ...FILE_GROUPS.map(([title, keys]) => [title, keys.map((k) => byKey.get(k)).filter(Boolean)]),
    ["Other files", inputs.filter((s) => !named.has(s.key))],
  ].filter(([, list]) => list.length);
}

// Which files an admin may upload, shown in the table: All files, No files, or the files by name.
function UploadsSummary({ u, inputs }) {
  if (u.uploads_all) return <span className="pill good">All files</span>;
  if (!u.uploads.length) return <span className="pill">No files</span>;
  return (
    <span className="file-tags">
      {inputs.filter((s) => u.uploads.includes(s.key)).map((s) => (
        <span key={s.key} className="file-tag" title={s.label}>{short(s)}</span>
      ))}
    </span>
  );
}

function UploadsCell({ u, reports, onSaved }) {
  const [open, setOpen] = useState(false);
  if (!u.is_admin) return <span className="muted small">None</span>;
  const inputs = inputsOf(reports);
  if (!u.can.uploads) return <UploadsSummary u={u} inputs={inputs} />;
  return (
    <span className="uploads-cell">
      <UploadsSummary u={u} inputs={inputs} />
      <Button size="sm" tone="quiet" icon={<SlidersIcon />} onClick={() => setOpen(true)}
              title={`Choose which files ${u.name || u.email} may upload`}>
        Edit
      </Button>
      {open && <UploadRights u={u} inputs={inputs} onSaved={onSaved}
                             onClose={() => setOpen(false)} />}
    </span>
  );
}

const MODES = [
  { value: "all", title: "All files",
    text: "Every file the scorecards read, and any added later." },
  { value: "some", title: "Chosen files", text: "Only the files you tick below." },
  { value: "none", title: "No files",
    text: "Uploads nothing. Building and approving stay as they are." },
];

// The upload rights window: all files, none, or the ones ticked. Nothing changes until Save.
function UploadRights({ u, inputs, onClose, onSaved }) {
  const [mode, setMode] = useState(u.uploads_all ? "all" : u.uploads.length ? "some" : "none");
  const [picked, setPicked] = useState(() => new Set(u.uploads_all ? [] : u.uploads));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const who = u.name || u.email;

  // What Save sends: null for every file, [] for none, otherwise the ticked keys.
  const ticked = inputs.filter((s) => picked.has(s.key)).map((s) => s.key);
  const sends = mode === "all" ? null : mode === "none" ? []
    : ticked.length === inputs.length ? null : ticked;
  const before = u.uploads_all ? null
    : inputs.filter((s) => u.uploads.includes(s.key)).map((s) => s.key);
  const changed = JSON.stringify(sends) !== JSON.stringify(before);

  const tick = (keys, on) => setPicked((was) => {
    const next = new Set(was);
    for (const k of keys) { if (on) next.add(k); else next.delete(k); }
    return next;
  });

  async function save() {
    setBusy(true); setError(null);
    try { await api.setUploadAccess(u.id, sends); await onSaved(); onClose(); }
    catch (e) { setError(e); setBusy(false); }
  }

  const note = mode === "all" ? `${who} can upload every file.`
    : mode === "none" ? `${who} will not be able to upload any file.`
    : !ticked.length ? "Nothing is ticked, so this saves as No files."
    : ticked.length === inputs.length ? "Every file is ticked, so this saves as All files."
    : `${who} can upload only the ${ticked.length === 1 ? "file" : "files"} ticked.`;

  return (
    <Modal title="Upload rights" icon={<UploadRightsIcon />} width={600}
           sub={<>{u.name && <strong>{u.name}</strong>}{u.name && " · "}{u.email}</>}
           onClose={onClose} locked={busy}
           footer={<>
             <span className="modal-note">{note}</span>
             <Button tone="quiet" onClick={onClose} disabled={busy}>Cancel</Button>
             <Button tone="primary" onClick={save} disabled={!changed} busy={busy}
                     busyLabel="Saving…">Save</Button>
           </>}>
      {error && <div className="modal-error">{String(error.message ?? error)}</div>}

      <div className="choice-grid" role="radiogroup" aria-label="Which files">
        {MODES.map((m) => (
          <button key={m.value} type="button" role="radio" aria-checked={mode === m.value}
                  className={`choice${mode === m.value ? " on" : ""}`}
                  onClick={() => setMode(m.value)}>
            <span className="choice-top">
              <span className="choice-dot" aria-hidden="true" />
              <span className="choice-title">{m.title}</span>
            </span>
            <span className="choice-text">{m.text}</span>
          </button>
        ))}
      </div>

      {mode === "some" && (
        <div className="pick-files">
          <div className="pick-bar">
            <span className="small muted">
              {ticked.length ? `${ticked.length} ticked` : "Tick the files this admin uploads"}
            </span>
            <span className="row tight">
              <Button tone="link" size="sm" onClick={() => tick(inputs.map((s) => s.key), true)}>
                Tick all
              </Button>
              <span className="muted">·</span>
              <Button tone="link" size="sm" onClick={() => setPicked(new Set())}>Clear</Button>
            </span>
          </div>
          {groupsOf(inputs).map(([title, list]) => {
            const all = list.every((s) => picked.has(s.key));
            return (
              <div key={title} className="pick-group">
                <div className="pick-group-head">
                  <h3>{title}</h3>
                  <Button tone="link" size="sm"
                          onClick={() => tick(list.map((s) => s.key), !all)}>
                    {all ? "Untick these" : "Tick these"}
                  </Button>
                </div>
                {list.map((s) => {
                  const on = picked.has(s.key);
                  return (
                    <label key={s.key} className={`check-row${on ? " on" : ""}`}>
                      <input type="checkbox" checked={on}
                             onChange={(e) => tick([s.key], e.target.checked)} />
                      <span className="check-box" aria-hidden="true">
                        <svg width="10" height="10" viewBox="0 0 10 10">
                          <path d="M2 5.2 4.1 7.3 8 3" fill="none" stroke="currentColor"
                                strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </span>
                      <span className="check-text">
                        <span className="check-name">{short(s)}</span>
                        <span className="check-sub">{s.label}</span>
                      </span>
                      <span className="check-tags">
                        {s.reports.map((r) => (
                          <span key={r.key} className={`tagline ${r.key}`}>{r.short}</span>
                        ))}
                      </span>
                    </label>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </Modal>
  );
}

// The tones say what each action does before the word is read.
function Actions({ u, me, act, reset, removeSelf }) {
  const c = u.can;
  const self = u.id === me.id;

  if (u.status === "unverified") {
    return (
      <span className="row tight">
        <span className="muted small">Waiting for them to confirm their email</span>
        {c.delete && (
          <ConfirmButton icon={<CrossIcon />} label="Turn down" confirm="Confirm turn down"
                         onConfirm={act(() => api.deleteUser(u.id))} />
        )}
      </span>
    );
  }

  if (u.status === "pending") {
    return (
      <span className="row tight">
        {c.approve && (
          <Button tone="go" solid size="sm" icon={<CheckIcon />}
                  onClick={act(() => api.approveUser(u.id))}
                  title={u.reports.length ? undefined
                    : "Tick the scorecards they should see first, or add them later"}>
            Approve
          </Button>
        )}
        {c.delete && (
          <ConfirmButton icon={<CrossIcon />} label="Turn down" confirm="Confirm turn down"
                         onConfirm={act(() => api.deleteUser(u.id))} />
        )}
      </span>
    );
  }

  return (
    <span className="row tight">
      {c.unlock && (
        <Button tone="go" solid size="sm" icon={<UnlockIcon />}
                onClick={act(() => api.unlockUser(u.id))}>Unlock</Button>
      )}
      {c.enable && (
        <Button tone="go" size="sm" icon={<PlayIcon />}
                onClick={act(() => api.setActive(u.id, true))}>Enable</Button>
      )}
      {c.reset_password && (
        <ConfirmButton tone="soft" icon={<KeyIcon />} label="Force password reset"
                       confirm="Confirm reset" onConfirm={() => reset(u)} />
      )}
      {c.sign_out && u.sessions > 0 && (
        <Button tone="soft" size="sm" icon={<LeaveIcon />}
                onClick={act(() => api.signOutUser(u.id))}>Sign out</Button>
      )}
      {c.disable && (
        <ConfirmButton tone="warn" icon={<PauseIcon />} label="Disable"
                       confirm="Confirm disable"
                       onConfirm={act(() => api.setActive(u.id, false))} />
      )}
      {c.delete && (
        self
          ? <DeleteButton label="Remove my account" busyLabel="Removing…"
                          onConfirm={() => removeSelf(u)} />
          : <DeleteButton onConfirm={act(() => api.deleteUser(u.id))} />
      )}
      {!Object.values(c).some((v) => (Array.isArray(v) ? v.length : v)) && (
        <span className="muted small">
          {self ? "Your own account: see your profile"
                : u.is_system_admin ? "Only another system admin can change this account"
                : "Only a system admin can change an admin"}
        </span>
      )}
    </span>
  );
}
