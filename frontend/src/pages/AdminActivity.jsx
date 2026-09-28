import { useEffect, useMemo, useState } from "react";
import { api, count, device, stamp, when } from "../api";
import { Card, DataTable, ErrorBox, Loading, Outcome, Picker, Segmented,
         TextFilter } from "../components";
import { Stat, Stats } from "../ui";
import { Button } from "../buttons";
import { DownloadIcon } from "../icons";

/* The activity log, for admins.

   Two halves. At the top, what the log says needs looking at - password
   guessing, sign-ins from new places, bulk exports - worked out from the log
   itself by the server. Below, the log: every event, newest first, filtered
   and exported as needed.

   An alert's "Show events" narrows the log to the rows behind it, so going
   from "something is wrong" to "here is exactly what happened" is one click. */

const PERIODS = [
  { value: 1, label: "24 hours" },
  { value: 7, label: "7 days" },
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
];

const WORD = { action: "Act on", warning: "Check", info: "Note" };

const EMPTY = { action: "", outcome: "", email: "", ip: "" };

export default function AdminActivity() {
  const [days, setDays] = useState(7);
  const [alerts, setAlerts] = useState(null);
  const [actions, setActions] = useState(null);
  const [filters, setFilters] = useState(EMPTY);
  const [typed, setTyped] = useState({ email: "", ip: "" });
  const [page, setPage] = useState(null);
  const [more, setMore] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.actions().then(setActions).catch(setError);
  }, []);

  useEffect(() => {
    let alive = true;
    setAlerts(null);
    api.alerts(days).then((a) => alive && setAlerts(a)).catch(setError);
    return () => { alive = false; };
  }, [days]);

  /* Typing in the email or address box waits for a pause before asking the
     server, rather than sending a query per keystroke. */
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) =>
      (f.email === typed.email && f.ip === typed.ip ? f : { ...f, ...typed })), 350);
    return () => clearTimeout(t);
  }, [typed]);

  const query = useMemo(() => ({ ...filters, days }), [filters, days]);

  useEffect(() => {
    let alive = true;
    setPage(null);
    api.activity({ ...query, limit: 100 })
      .then((p) => alive && setPage(p)).catch(setError);
    return () => { alive = false; };
  }, [query]);

  async function loadMore() {
    setMore(true);
    try {
      const p = await api.activity({ ...query, limit: 100, before_id: page.next });
      setPage({ items: [...page.items, ...p.items], next: p.next });
    } catch (e) { setError(e); }
    finally { setMore(false); }
  }

  function focus(alert) {
    const next = { ...EMPTY };
    if (alert.email) next.email = alert.email;
    if (alert.ip && !alert.email) next.ip = alert.ip;
    next.action = {
      password_guessing: "auth.login", spraying: "auth.login",
      locked: "auth.locked", new_address: "auth.login",
      out_of_hours: "auth.login", bulk_export: "table.export",
      denied: "admin.denied",
    }[alert.code] ?? "";
    if (["password_guessing", "spraying"].includes(alert.code)) next.outcome = "failure";
    setTyped({ email: next.email, ip: next.ip });
    setFilters(next);
    document.getElementById("activity-log")?.scrollIntoView({ behavior: "smooth" });
  }

  const actionOptions = useMemo(() => {
    if (!actions) return [];
    const groups = {};
    for (const [key, label] of Object.entries(actions.actions)) {
      const cat = actions.categories[key.split(".")[0]] ?? "Other";
      (groups[cat] ??= []).push({ value: key, label });
    }
    // Each group opens with "every event of this kind", then the events.
    return Object.entries(groups).map(([cat, items]) => ({
      group: cat,
      options: [{ value: `${items[0].value.split(".")[0]}.`, label: `All ${cat.toLowerCase()}` },
                ...items],
    }));
  }, [actions]);

  const filtered = Object.values(filters).some(Boolean);
  const s = alerts?.summary;

  return (
    <>
      <div className="head spread">
        <div>
          <h1>Activity</h1>
          <div className="sub">
            Everything people have done in the app, kept permanently. Nothing
            here can be edited or deleted.
          </div>
        </div>
        <Segmented label="Period" value={days} onChange={setDays} options={PERIODS} />
      </div>

      <ErrorBox error={error} />

      {!s ? <Loading what="Reading the log" /> : (
        <Stats cols={5}>
          <Stat label="Sign-ins" value={count(s.sign_ins)}
                foot={`${count(s.active_people)} people active`} />
          <Stat label="Failed sign-ins" value={count(s.failed_sign_ins)}
                tone={s.failed_sign_ins ? "rose" : undefined}
                foot="wrong passwords and unknown emails" />
          <Stat label="Exports" value={count(s.exports)} foot="whole tables as CSV" />
          <Stat label="Refused" value={count(s.denied)}
                tone={s.denied ? "amber" : undefined}
                foot="admin actions by non-admins" />
          <Stat label="Events" value={count(s.events)} foot="everything recorded" />
        </Stats>
      )}

      <Card flush title="Needs a look"
            sub={`Worked out from the log for the last ${
              PERIODS.find((p) => p.value === days)?.label}.`}>
        {!alerts ? <Loading /> : alerts.alerts.length === 0 ? (
          <div className="empty">Nothing unusual in this period.</div>
        ) : (
          <div style={{ padding: "4px 22px 10px" }}>
            {alerts.alerts.map((a, i) => (
              <div className={`note ${a.severity}`} key={i}>
                <div className="tag">{WORD[a.severity]}</div>
                <div style={{ flex: 1 }}>
                  <div className="strong">{a.title}</div>
                  <div className="small">{a.text}</div>
                  <div className="meta">
                    {a.count > 1
                      ? `${count(a.count)} events, ${when(a.first)} to ${when(a.last)}`
                      : when(a.last)}
                  </div>
                </div>
                <Button tone="soft" size="sm" onClick={() => focus(a)}>
                  Show events
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div id="activity-log" className={`filters${filtered ? " on" : ""}`}>
        <Picker label="Event" value={filters.action} active={!!filters.action}
                onChange={(v) => setFilters((f) => ({ ...f, action: v }))}
                onClear={() => setFilters((f) => ({ ...f, action: "" }))}
                placeholder="Everything" options={actionOptions} />
        <Picker label="Result" value={filters.outcome} active={!!filters.outcome}
                onChange={(v) => setFilters((f) => ({ ...f, outcome: v }))}
                onClear={() => setFilters((f) => ({ ...f, outcome: "" }))}
                placeholder="Any"
                options={[{ value: "success", label: "Success" },
                          { value: "failure", label: "Failed" },
                          { value: "denied", label: "Refused" }]} />
        <TextFilter label="Person" placeholder="email contains…" value={typed.email}
                    onChange={(v) => setTyped((t) => ({ ...t, email: v }))} />
        <TextFilter label="Address" placeholder="IP address" size={14} value={typed.ip}
                    onChange={(v) => setTyped((t) => ({ ...t, ip: v }))} />
        {/* Each filter has its own ×; this undoes several at once. */}
        {Object.values(filters).filter(Boolean).length > 1 && (
          <Button tone="quiet" size="sm" onClick={() => {
            setFilters(EMPTY); setTyped({ email: "", ip: "" });
          }}>Clear all</Button>
        )}
        <span className="spacer" />
        <Button size="sm" icon={<DownloadIcon />}
                onClick={() => api.downloadActivity(query).catch(setError)}>
          Export CSV
        </Button>
      </div>

      <Card flush>
        {!page ? <Loading what="Loading events" /> : (
          <>
            <DataTable
              rows={page.items}
              empty="No events match."
              rowClass={(r) => (r.outcome !== "success" ? `row-${r.outcome}` : "")}
              columns={[
                { key: "at", label: "When", nowrap: true, render: (r) => stamp(r.at) },
                { key: "email", label: "Person",
                  render: (r) => r.email ?? <span className="muted">-</span> },
                { key: "label", label: "Event", strong: true, nowrap: true },
                { key: "target", label: "On", render: (r) => r.target ?? "" },
                { key: "ip", label: "Address", nowrap: true, render: (r) => r.ip ?? "" },
                { key: "device", label: "Device", nowrap: true,
                  render: (r) => (r.user_agent ? device(r.user_agent) : "") },
                { key: "outcome", label: "Result",
                  render: (r) => <Outcome value={r.outcome} /> },
                { key: "detail", label: "Detail",
                  render: (r) => <Detail d={r.detail} /> },
              ]}
            />
            {page.next && (
              <div style={{ padding: 14, textAlign: "center" }}>
                <Button size="sm" onClick={loadMore} busy={more} busyLabel="Loading…">
                  Load older events
                </Button>
              </div>
            )}
          </>
        )}
      </Card>
    </>
  );
}

/* The event's particulars, on one line - the reason a sign-in failed, the
   files an upload brought in. The whole record is on the tooltip. */
function Detail({ d }) {
  if (!d || !Object.keys(d).length) return null;
  const parts = [];
  if (d.reason) parts.push(d.reason.replace(/_/g, " "));
  if (d.accepted) parts.push(`${d.accepted.length} file${d.accepted.length === 1 ? "" : "s"}`);
  if (d.rows != null) parts.push(`${count(d.rows)} rows`);
  if (d.role) parts.push(`now ${d.role}`);
  if (d.report && d.week) parts.push(`${d.report} ${d.week}`);
  const text = parts.join(" · ") || "details";
  return <span className="small muted" title={JSON.stringify(d, null, 1)}>{text}</span>;
}
