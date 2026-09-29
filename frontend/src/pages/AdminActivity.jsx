import { useEffect, useMemo, useState } from "react";
import { api, count, device, stamp, when } from "../api";
import { Card, DataTable, ErrorBox, Loading, Outcome, Picker, Segmented,
         TextFilter } from "../components";
import { Stat, Stats } from "../ui";
import { useAuth } from "../auth";
import { Button, DeleteButton } from "../buttons";
import { DownloadIcon } from "../icons";
import { useLoad } from "../hooks";
import { periodOf, today } from "../activity-period";

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
  const { user } = useAuth();
  const canDelete = user.is_system_admin;
  const [days, setDays] = useState(7);
  const [filters, setFilters] = useState(EMPTY);
  const [typed, setTyped] = useState({ email: "", ip: "" });
  const [more, setMore] = useState(false);
  const [actionError, setError] = useState(null);

  const actionsLoad = useLoad(api.actions, []);
  const alertsLoad = useLoad(() => api.alerts(days), [days]);
  const actions = actionsLoad.data;
  const alerts = alertsLoad.data;

  /* Typing in the email or address box waits for a pause before asking the
     server, rather than sending a query per keystroke. */
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) =>
      (f.email === typed.email && f.ip === typed.ip ? f : { ...f, ...typed })), 350);
    return () => clearTimeout(t);
  }, [typed]);

  const query = useMemo(() => ({ ...filters, days }), [filters, days]);
  const pageLoad = useLoad(() => api.activity({ ...query, limit: 100 }), [query]);
  const page = pageLoad.data;
  const error = actionError ?? actionsLoad.error ?? alertsLoad.error ?? pageLoad.error;

  /* Ticked rows. Kept with the list they were ticked on, so changing a
     filter never leaves ticks on rows that are no longer on screen. */
  const [ticked, setTicked] = useState({ page: null, ids: new Set() });
  const chosen = ticked.page === page ? ticked.ids : new Set();
  const tick = (ids, on) => {
    const next = new Set(chosen);
    for (const id of ids) {
      if (on) next.add(id); else next.delete(id);
    }
    setTicked({ page, ids: next });
  };
  const allTicked = page?.items.length > 0 && page.items.every((r) => chosen.has(r.id));

  /* Delete, then show the log as it now is - with the deletion's own row. */
  async function remove(body) {
    setError(null);
    try {
      await api.deleteActivity(body);
      setTicked({ page: null, ids: new Set() });
      await Promise.all([pageLoad.reload(), alertsLoad.reload()]);
    } catch (e) { setError(e); }
  }

  async function loadMore() {
    const before = page.next;
    setMore(true);
    try {
      const p = await api.activity({ ...query, limit: 100, before_id: before });
      /* Only onto the page it continues: if the filters changed while this
         was on its way, its rows belong to a list no longer on screen. */
      pageLoad.setData((cur) => (cur?.next === before
        ? { items: [...cur.items, ...p.items], next: p.next } : cur));
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
            Everything people have done in the app. Nothing here can be edited;
            only a system admin can delete events, and each deletion is itself
            recorded.
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

      {canDelete && chosen.size > 0 && (
        <div className="row" style={{ marginBottom: 12 }}>
          <DeleteButton size="md" label={`Delete ${chosen.size} selected`}
                        confirm={`Confirm delete ${chosen.size}`}
                        onConfirm={() => remove({ ids: [...chosen],
                                                  label: `${chosen.size} selected` })} />
          <Button tone="quiet" size="sm"
                  onClick={() => setTicked({ page: null, ids: new Set() })}>
            Clear selection
          </Button>
        </div>
      )}

      <Card flush>
        {!page ? <Loading what="Loading events" /> : (
          <>
            <DataTable
              rows={page.items}
              empty="No events match."
              rowClass={(r) => (r.outcome !== "success" ? `row-${r.outcome}` : "")}
              columns={[
                ...(canDelete ? [{
                  key: "tick", width: 34,
                  label: <input type="checkbox" aria-label="Select every event shown"
                                checked={allTicked}
                                onChange={(e) => tick(page.items.map((r) => r.id),
                                                      e.target.checked)} />,
                  render: (r) => <input type="checkbox" aria-label="Select this event"
                                        checked={chosen.has(r.id)}
                                        onChange={(e) => tick([r.id], e.target.checked)} />,
                }] : []),
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
                ...(canDelete ? [{
                  key: "delete", label: "", width: 44,
                  render: (r) => <DeleteButton label={null} title="Delete this event"
                                               confirm="Delete"
                                               onConfirm={() => remove({ ids: [r.id],
                                                 label: `event ${r.id}` })} />,
                }] : []),
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

      {canDelete && <DeletePeriod onDelete={remove} />}
    </>
  );
}

const SPANS = [
  { value: "day", label: "A day" },
  { value: "week", label: "A week" },
  { value: "month", label: "A month" },
  { value: "all", label: "Everything" },
];

/* Deleting a stretch of the log: the day, week or month holding a date, or
   all of it. It says how many events that is before anything goes, and asks
   once more. The deletion leaves its own row behind, even after
   "Everything". */
function DeletePeriod({ onDelete }) {
  const [span, setSpan] = useState("day");
  const [date, setDate] = useState(today());
  const period = span === "all" ? null : periodOf(span, date);
  const body = span === "all" ? { everything: true, label: "Everything" }
    : period && { since: period.since, until: period.until, label: period.label };
  const key = JSON.stringify(body);

  /* How many it would delete - counted by the server, not guessed from the
     page, which holds only the newest hundred. */
  const preview = useLoad(() => (body ? api.deleteActivity({ ...body, dry_run: true })
                                      : Promise.resolve(null)), [key]);
  const n = preview.data?.count;

  return (
    <Card title="Delete activity"
          sub="System admins only. Deleted events cannot be brought back; the deletion itself is recorded.">
      <div className="row" style={{ flexWrap: "wrap", gap: 12 }}>
        <Segmented value={span} onChange={setSpan} options={SPANS} />
        {span !== "all" && (
          <input type="date" value={date} max={today()}
                 onChange={(e) => setDate(e.target.value)}
                 aria-label={`A date in the ${span} to delete`} />
        )}
        <span className="small muted">
          {span === "all" ? "Every event in the log"
            : period ? period.label : "Choose a date"}
          {n != null && ` · ${count(n)} event${n === 1 ? "" : "s"}`}
        </span>
        <span className="spacer" />
        <DeleteButton size="md"
                      label={n ? `Delete ${count(n)} event${n === 1 ? "" : "s"}` : "Delete"}
                      disabled={!body || !n}
                      onConfirm={async () => { await onDelete(body); await preview.reload(); }} />
      </div>
      {preview.error && (
        <div className="small err" style={{ marginTop: 8 }}>{preview.error.message}</div>
      )}
    </Card>
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
  if (d.deleted != null) parts.push(`${count(d.deleted)} deleted`);
  const text = parts.join(" · ") || "details";
  return <span className="small muted" title={JSON.stringify(d, null, 1)}>{text}</span>;
}
