// Formatting numbers, money, dates and sizes.
// Money to the cent, always.
export const money = (n) =>
  n == null ? "" : n.toLocaleString(undefined,
    { style: "currency", currency: "USD",
      minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const pct = (n) =>
  n == null ? "" : `${(n * 100).toFixed(2)}%`;

export const count = (n) =>
  n == null ? "" : n.toLocaleString();

// A person's name from their work email, the same way the server makes one:
// "ali.asghar@appedology.com" is "Ali Asghar".
export function personName(email) {
  const local = String(email ?? "").split("@")[0];
  const words = local.split(/[._\-+\s]+/).filter(Boolean);
  return words.map((w) => w[0].toUpperCase() + w.slice(1).toLowerCase()).join(" ") || local;
}

export const bytes = (n) =>
  n < 1e6 ? `${(n / 1e3).toFixed(0)} KB` : `${(n / 1e6).toFixed(1)} MB`;

const dateTime = (options) => (iso) =>
  iso ? new Date(iso).toLocaleString(undefined,
    { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", ...options }) : "";

export const when = dateTime();

const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_FULL = ["", "January", "February", "March", "April", "May", "June", "July",
                     "August", "September", "October", "November", "December"];
const utcDay = (d) => d.getUTCDate();
const utcMonth = (d) => MONTHS[d.getUTCMonth() + 1];

// Weeks are written out: "Week-2", not "Wk 2".
export const weekLabel = (n) => `Week-${n}`;

export const bucketLabel = (b) =>
  b?.startsWith("M") ? MONTHS[+b.slice(1)] ?? b : weekLabel(b?.slice(1));

export const monthName = (m) => MONTHS[m] ?? String(m);
export const monthFull = (m) => MONTHS_FULL[m] ?? String(m);

// Two ISO dates as the days between them: "1 to 9 Oct", "28 Sep to 2 Oct".
export function daySpan(first, last) {
  const [a, b] = [first, last].map((d) => new Date(`${d}T00:00:00Z`));
  if (first === last) return `${utcDay(a)} ${utcMonth(a)}`;
  return a.getUTCMonth() === b.getUTCMonth()
    ? `${utcDay(a)} to ${utcDay(b)} ${utcMonth(b)}`
    : `${utcDay(a)} ${utcMonth(a)} to ${utcDay(b)} ${utcMonth(b)}`;
}

// The days week `n` of `month` covers, from a run's week spans; "" if not known.
export function weekDays(spans, month, n) {
  const w = spans?.[String(month)]?.find((s) => s.week === Number(n));
  return w ? daySpan(w.first, w.last) : "";
}

// A browser's self-description, reduced to what a person recognises.
export function device(ua) {
  if (!ua) return "Unknown device";
  const browser =
    /Edg\//.test(ua) ? "Edge" :
    /OPR\//.test(ua) ? "Opera" :
    /Firefox\//.test(ua) ? "Firefox" :
    /Chrome\//.test(ua) ? "Chrome" :
    /Safari\//.test(ua) ? "Safari" :
    /python|curl|httpx|testclient/i.test(ua) ? "Script" : "Browser";
  const os =
    /Windows/.test(ua) ? "Windows" :
    /iPhone|iPad/.test(ua) ? "iOS" :
    /Mac OS X/.test(ua) ? "macOS" :
    /Android/.test(ua) ? "Android" :
    /Linux/.test(ua) ? "Linux" : null;
  return os ? `${browser} on ${os}` : browser;
}

// A date and time in full, for a record that may be read months later.
export const stamp = dateTime({ year: "numeric" });

// "2026-W38" as the days it covers.
export function weekRange(label) {
  const m = /^(\d{4})-W(\d{2})$/.exec(label ?? "");
  if (!m) return label ?? "";
  const [year, week] = [+m[1], +m[2]];
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const monday = new Date(jan4);
  monday.setUTCDate(jan4.getUTCDate() - ((jan4.getUTCDay() || 7) - 1) + (week - 1) * 7);
  const sunday = new Date(monday);
  sunday.setUTCDate(monday.getUTCDate() + 6);
  const start = monday.getUTCMonth() === sunday.getUTCMonth()
    ? `${utcDay(monday)}`
    : monday.getUTCFullYear() === sunday.getUTCFullYear()
      ? `${utcDay(monday)} ${utcMonth(monday)}`
      : `${utcDay(monday)} ${utcMonth(monday)} ${monday.getUTCFullYear()}`;
  return `${start} to ${utcDay(sunday)} ${utcMonth(sunday)} ${sunday.getUTCFullYear()}`;
}
