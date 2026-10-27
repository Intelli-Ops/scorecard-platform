// Admin: the days off pacing leaves out.
import { useState } from "react";
import { api, stamp } from "../api";
import { useLoad } from "../hooks";
import { Card, DataTable, ErrorBox, Loading } from "../components";
import { Button, DeleteButton } from "../buttons";

const day = (iso) => new Date(`${iso}T00:00:00`);
const longDate = (iso) => day(iso).toLocaleDateString(undefined,
  { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const monthOf = (iso) => day(iso).toLocaleDateString(undefined,
  { month: "long", year: "numeric" });

export default function AdminHolidays() {
  const { data: holidays, error, setError, reload } = useLoad(api.holidays, []);

  if (!holidays) return error ? <ErrorBox error={error} /> : <Loading what="Loading holidays" />;

  async function remove(h) {
    setError(null);
    try { await api.deleteHoliday(h.day); await reload(); } catch (e) { setError(e); }
  }

  return (
    <>
      <div className="head">
        <h1>Holidays</h1>
        <div className="sub">
          A holiday is not a working day. Adding one takes a day off its week and
          its month in the pace; deleting one gives the day back. Builds made from
          now on use this list - rebuild a week to pace it again.
        </div>
      </div>

      {error && <ErrorBox error={error} />}

      <Card title="Add a holiday">
        <AddHoliday onAdded={reload} />
      </Card>

      <Card flush>
        <DataTable
          rows={holidays}
          empty="No holidays - every weekday is a working day."
          columns={[
            { key: "day", label: "Date", strong: true, render: (h) => longDate(h.day) },
            { key: "name", label: "Holiday" },
            { key: "month", label: "Takes a day off", render: (h) => monthOf(h.day) },
            { key: "set_by", label: "Added",
              render: (h) => (h.set_by
                ? <span className="small muted">{h.set_by.split("@")[0]} · {stamp(h.set_at)}</span>
                : <span className="small muted">Starting list</span>) },
            { key: "actions", label: "",
              render: (h) => <DeleteButton onConfirm={() => remove(h)} /> },
          ]}
        />
      </Card>
    </>
  );
}

function AddHoliday({ onAdded }) {
  const [date, setDate] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);
  const ready = date && name.trim();

  async function submit(e) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true); setProblem(null);
    try {
      await api.addHoliday(date, name.trim());
      setDate(""); setName("");
      await onAdded();
    } catch (err) { setProblem(err.message); }
    finally { setBusy(false); }
  }

  return (
    <form className="form" onSubmit={submit}>
      {problem && <div className="problem">{problem}</div>}
      <div className="field">
        <label htmlFor="holiday-name">Holiday</label>
        <div className="row tight">
          <input id="holiday-date" type="date" aria-label="Date" value={date}
                 style={{ flex: "0 0 auto", width: "auto" }}
                 onChange={(e) => setDate(e.target.value)} />
          <input id="holiday-name" type="text" maxLength={120} placeholder="Name, e.g. Eid ul-Fitr"
                 value={name} onChange={(e) => setName(e.target.value)} />
          <Button type="submit" tone={ready ? "primary" : "plain"} disabled={!ready}
                  busy={busy} busyLabel="Adding…">Add</Button>
        </div>
        <div className="hint">A weekday. Weekends are never working days.</div>
      </div>
    </form>
  );
}
