import { useState } from "react";
import { api, stamp } from "./api";
import { useLoad } from "./hooks";
import { ClearX } from "./components";
import { Button } from "./buttons";

/* How many working days the week's month has - the number every pace figure
   is projected on (month-to-date, over the days elapsed, times this).

   The calendar's count (weekdays less the holidays in the rules) is shown and
   used until someone enters a different one. An entry is for the whole month,
   so every week of it - and every build from then on - paces on it. Builds
   already made keep the number they used; build again to pick up a change. */
/* The parent keys this by week, so a new week starts from a clean form. */
export default function WorkingDays({ week }) {
  const { data: info, error, setData: setInfo } = useLoad(() => api.weekMonth(week), [week]);
  // What is typed; null means "the number in use", so nothing is copied in.
  const [typedValue, setValue] = useState(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);
  const [saved, setSaved] = useState(false);

  async function save(days) {
    setBusy(true); setProblem(null); setSaved(false);
    try {
      setInfo(await api.setWorkingDays(week, days));
      setValue(null);
      setSaved(true);
    } catch (e) { setProblem(e.message); }
    finally { setBusy(false); }
  }

  if (!info) {
    return error ? <div className="workdays err small">{error.message}</div> : null;
  }

  const value = typedValue ?? String(info.working_days);
  const typed = Number(value);
  const changed = value !== "" && typed !== info.working_days;

  return (
    <form className={`workdays${info.entered ? " entered" : ""}`}
          onSubmit={(e) => { e.preventDefault(); if (changed) save(typed); }}>
      <div className="workdays-text">
        <div className="workdays-title">Working days in {info.label}</div>
        <div className="small muted">
          {info.entered
            ? `Entered by ${info.set_by?.split("@")[0]} · ${stamp(info.set_at)}. `
              + `The calendar says ${info.calendar_days}.`
            : `From the calendar: weekdays less holidays. Change it if the office `
              + `worked a different number of days.`}
        </div>
      </div>
      <span className="clearable">
        <input type="number" min={1} max={31} value={value} aria-label="Working days"
               className={info.entered ? "has-x" : ""}
               onChange={(e) => { setValue(e.target.value); setSaved(false); }}
               onKeyDown={(e) => {
                 // Escape drops an unsaved number and puts back the one in use.
                 if (e.key === "Escape") { setValue(null); setProblem(null); }
               }} />
        {info.entered && (
          <ClearX title={`Go back to the calendar's ${info.calendar_days}`}
                  onClick={() => save(null)} />
        )}
      </span>
      <Button type="submit" size="sm" tone={changed ? "primary" : "plain"}
              disabled={!changed} busy={busy} busyLabel="Saving…">
        {saved && !changed ? "Saved" : "Save"}
      </Button>
      {problem && <div className="workdays-problem small err">{problem}</div>}
      <DaysPassed week={week} info={info} />
    </form>
  );
}

/* The working days gone by the end of the week being built - what the pace
   divides the month-to-date by. Worked out, not entered: it follows from the
   calendar, the holidays and the month's working days above. */
function DaysPassed({ week, info }) {
  const through = new Date(`${info.passed_through}T00:00:00`)
    .toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  const month = info.label.split(" ")[0];
  return (
    <div className="workdays-passed">
      <div className="workdays-text">
        <div className="workdays-title">Days passed in {month} by the end of {week}</div>
        <div className="small muted">
          Working days from 1 {month.slice(0, 3)} to {through} (week {info.week_of_month} of
          the month). The pace is month-to-date over these, times {info.working_days}.
        </div>
      </div>
      <div className="workdays-figure" aria-label="Days passed" key={info.days_passed}>
        <strong>{info.days_passed}</strong>
        <span className="small muted">of {info.working_days}</span>
      </div>
    </div>
  );
}
