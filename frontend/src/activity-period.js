// Day, week and month ranges for deleting activity.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmt = (d) => `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;

// "2026-09-29" -> a local Date at midnight, or null.
export function parseDay(text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text ?? "");
  if (!m) return null;
  const d = new Date(+m[1], +m[2] - 1, +m[3]);
  return d.getMonth() === +m[2] - 1 ? d : null;       // 2026-02-31 is not a day
}

// { since, until, label } for kind "day" | "week" | "month", or null.
export function periodOf(kind, text) {
  const d = parseDay(text);
  if (!d) return null;
  let since, until, label;
  if (kind === "day") {
    since = d;
    until = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1);
    label = fmt(since);
  } else if (kind === "week") {
    const back = (d.getDay() + 6) % 7;                // days since Monday
    since = new Date(d.getFullYear(), d.getMonth(), d.getDate() - back);
    until = new Date(since.getFullYear(), since.getMonth(), since.getDate() + 7);
    const last = new Date(until.getFullYear(), until.getMonth(), until.getDate() - 1);
    label = `Week of ${fmt(since)} to ${fmt(last)}`;
  } else if (kind === "month") {
    since = new Date(d.getFullYear(), d.getMonth(), 1);
    until = new Date(d.getFullYear(), d.getMonth() + 1, 1);
    label = `${MONTHS[since.getMonth()]} ${since.getFullYear()}`;
  } else {
    return null;
  }
  return { since: since.toISOString(), until: until.toISOString(), label };
}

// Today as "2026-09-29", for the date box to start on.
export function today(now = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}
