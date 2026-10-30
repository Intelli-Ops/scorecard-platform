// Admin: accounts, roles, access and approvals.
import { useState } from "react";
import { api, stamp, when } from "../api";
import { useAuth } from "../auth";
import { useLoad } from "../hooks";
import { Card, DataTable, ErrorBox, Loading } from "../components";
import { Button, ConfirmButton, ConfirmPair, DeleteButton } from "../buttons";
import { Stat, Stats } from "../ui";
import { CheckIcon, CrossIcon, KeyIcon, LeaveIcon, PauseIcon, PlayIcon,
         UnlockIcon } from "../icons";

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
                  <span>{u.name}{u.id === me.id && <span className="muted"> · you</span>}</span>
                  <span className="small muted">{u.email} · {u.apd_id}</span>
                </span>
              ) },
            { key: "role", label: "Role",
              render: (u) => <RoleCell u={u} act={act} /> },
            { key: "reports", label: "Scorecards",
              render: (u) => <AccessCell u={u} reports={reports} act={act} /> },
            { key: "uploads", label: "Uploads",
              render: (u) => <UploadsCell u={u} reports={reports} act={act} /> },
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

// The input names, short enough for a chip.
const INPUT_SHORT = {
  delta_wc: "Delta WC", delta_mlcr: "Delta MLCR",
  delta_wc_comments: "Delta WC comments", delta_mlcr_comments: "Delta MLCR comments",
  payment_detail: "Payment Detail", hearing_calendar: "Hearing Calendar",
  document_log: "Document log", kpi_numbers: "KPI numbers",
  owner_case_ar: "Owner Case AR", custom_case_ar: "Custom Case AR",
};

// Which files an admin may upload: every one, or those a system admin picked.
function UploadsCell({ u, reports, act }) {
  const [open, setOpen] = useState(false);
  if (!u.is_admin) return <span className="muted small">None</span>;
  const inputs = [...new Map(reports.flatMap((r) => r.sources)
    .map((s) => [s.key, s])).values()];
  const summary = u.uploads_all ? "All files"
    : u.uploads.length ? `${u.uploads.length} of ${inputs.length} files` : "No files";
  if (!u.can.uploads) {
    return <span className="muted small" title={u.uploads_all ? undefined
      : u.uploads.map((k) => INPUT_SHORT[k] ?? k).join(", ")}>{summary}</span>;
  }

  const set = (next) => act(() => api.setUploadAccess(
    u.id, next.length === inputs.length ? null : next));
  return (
    <span className="who-cell">
      <span className="row tight">
        <span className="small">{summary}</span>
        <Button size="sm" tone="quiet" onClick={() => setOpen(!open)}
                aria-expanded={open}>{open ? "Done" : "Choose"}</Button>
      </span>
      {open && (
        <span className="chips wrap" style={{ marginTop: 6 }}>
          <button type="button" className={`chip${u.uploads_all ? " on" : ""}`}
                  aria-pressed={u.uploads_all} onClick={act(() => api.setUploadAccess(u.id, null))}
                  title="Every file, now and any added later">All files</button>
          {inputs.map((s) => {
            const on = !u.uploads_all && u.uploads.includes(s.key);
            const base = u.uploads_all ? [] : u.uploads;
            const next = on ? base.filter((k) => k !== s.key) : [...base, s.key];
            return (
              <button key={s.key} type="button" className={`chip${on ? " on" : ""}`}
                      aria-pressed={on} title={s.label} onClick={set(next)}>
                {INPUT_SHORT[s.key] ?? s.label}
              </button>
            );
          })}
        </span>
      )}
    </span>
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
