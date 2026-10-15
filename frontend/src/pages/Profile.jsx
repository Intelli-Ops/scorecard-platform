// Your profile: name, password, sessions and recent activity.
import { useState } from "react";
import { api, device, stamp, when } from "../api";
import { useAuth } from "../auth";
import { useLoad } from "../hooks";
import { reportShort } from "../reports";
import { Card, DataTable, ErrorBox, Loading, NewPasswordFields, Outcome,
         PasswordInput } from "../components";
import { Button } from "../buttons";
import { LeaveIcon } from "../icons";

// Your own account: who you are, your password, where you are signed in, and what you have done recently.

export function PasswordForm({ onDone, temporary = false }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [problem, setProblem] = useState(null);
  const [done, setDone] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setProblem(null); setDone(null);
    if (next !== again) { setProblem("The two new passwords differ."); return; }
    setBusy(true);
    try {
      const r = await api.changePassword(current, next);
      setCurrent(""); setNext(""); setAgain("");
      setDone(r.other_sessions_ended
        ? `Password changed. ${r.other_sessions_ended} other session`
          + `${r.other_sessions_ended === 1 ? " was" : "s were"} signed out.`
        : "Password changed.");
      onDone?.(r.user);
    } catch (err) { setProblem(err.message); }
    finally { setBusy(false); }
  }

  return (
    <form className="form" onSubmit={submit}>
      {problem && <div className="problem">{problem}</div>}
      {done && <div className="done">{done}</div>}
      <div className="field">
        <label htmlFor="pw-current">
          {temporary ? "Temporary password" : "Current password"}
        </label>
        <PasswordInput id="pw-current" required
               autoComplete="current-password" value={current}
               onChange={(e) => setCurrent(e.target.value)} />
      </div>
      <NewPasswordFields value={next} onChange={setNext}
                         again={again} onAgain={setAgain} />
      <Button tone="primary" type="submit" busy={busy} busyLabel="Saving…">
        Change password
      </Button>
    </form>
  );
}

function NameForm({ user, onSaved }) {
  const [name, setName] = useState(user.display_name ?? "");
  const [problem, setProblem] = useState(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const changed = (name.trim() || null) !== (user.display_name ?? null);

  async function submit(e) {
    e.preventDefault();
    setProblem(null); setSaved(false); setBusy(true);
    try { onSaved(await api.updateProfile(name)); setSaved(true); }
    catch (err) { setProblem(err.message); }
    finally { setBusy(false); }
  }

  return (
    <form className="form inline" onSubmit={submit}>
      {problem && <div className="problem">{problem}</div>}
      <div className="field">
        <label htmlFor="display-name">Name</label>
        <div className="row tight">
          <input id="display-name" type="text" maxLength={120}
                 placeholder={user.email.split("@")[0]} value={name}
                 onChange={(e) => { setName(e.target.value); setSaved(false); }} />
          <Button type="submit" tone={changed ? "primary" : "plain"}
                  disabled={!changed} busy={busy} busyLabel="Saving…">
            {saved ? "Saved" : "Save"}
          </Button>
        </div>
        <div className="hint">How the app addresses you. Optional.</div>
      </div>
    </form>
  );
}

export default function Profile() {
  const { user, setUser } = useAuth();
  const { data, error, setError, reload } =
    useLoad(() => Promise.all([api.mySessions(), api.myActivity()]), []);
  const [sessions, activity] = data ?? [null, null];

  const act = (fn) => async (...args) => {
    try { await fn(...args); await reload(); } catch (e) { setError(e); }
  };
  const end = act(api.endSession);
  const endOthers = act(api.endOtherSessions);

  const others = sessions?.filter((s) => !s.current).length ?? 0;

  return (
    <>
      <div className="head">
        <h1>Your profile</h1>
        <div className="sub">Your account, your password, and where you are signed in.</div>
      </div>

      <ErrorBox error={error} />

      <div className="grid cols-2">
        <Card title="Account">
          <dl className="kv">
            <dt>Email</dt><dd>{user.email}</dd>
            <dt>APD ID</dt><dd>{user.apd_id}</dd>
            <dt>Role</dt>
            <dd><span className={`pill role-${user.role}`}>{user.role_label}</span></dd>
            <dt>Scorecards</dt>
            <dd>{user.is_admin ? "All scorecards"
                 : user.reports.length
                   ? user.reports.map(reportShort).join(", ")
                   : "None yet. Ask an admin."}</dd>
            <dt>Member since</dt><dd>{stamp(user.created_at)}</dd>
            <dt>Password set</dt><dd>{stamp(user.password_changed_at) || "-"}</dd>
          </dl>
          <NameForm user={user} onSaved={setUser} />
        </Card>

        <Card title="Change password"
              sub="Your other sessions are signed out when you change it.">
          <PasswordForm onDone={(u) => { setUser(u); reload(); }} />
        </Card>
      </div>

      <Card flush title="Where you are signed in"
            sub="If you do not recognise one, sign it out and change your password."
            right={others > 0 && (
              <Button tone="soft" size="sm" icon={<LeaveIcon />} onClick={endOthers}>
                Sign out everywhere else
              </Button>
            )}>
        {!sessions ? <Loading /> : (
          <DataTable
            columns={[
              { key: "device", label: "Device", strong: true,
                render: (s) => device(s.user_agent) },
              { key: "ip", label: "Address", render: (s) => s.ip ?? "-" },
              { key: "created_at", label: "Signed in", nowrap: true,
                render: (s) => when(s.created_at) },
              { key: "last_seen_at", label: "Last active", nowrap: true,
                render: (s) => when(s.last_seen_at) },
              { key: "end", label: "", width: 130,
                render: (s) => s.current
                  ? <span className="pill good">This device</span>
                  : <Button tone="soft" size="sm" icon={<LeaveIcon />}
                            onClick={() => end(s.id)}>
                      Sign out
                    </Button> },
            ]}
            rows={sessions}
          />
        )}
      </Card>

      <Card flush title="Your recent activity" sub="The last 25 things recorded against your account.">
        {!activity ? <Loading /> : (
          <DataTable
            columns={[
              { key: "at", label: "When", nowrap: true, render: (r) => when(r.at) },
              { key: "label", label: "What", strong: true },
              { key: "target", label: "On", render: (r) => r.target ?? "" },
              { key: "ip", label: "Address", render: (r) => r.ip ?? "" },
              { key: "outcome", label: "Result",
                render: (r) => <Outcome value={r.outcome} /> },
            ]}
            rows={activity}
            empty="Nothing recorded yet."
          />
        )}
      </Card>
    </>
  );
}
