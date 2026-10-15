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

export const bytes = (n) =>
  n < 1e6 ? `${(n / 1e3).toFixed(0)} KB` : `${(n / 1e6).toFixed(1)} MB`;

export const when = (iso) =>
  iso ? new Date(iso).toLocaleString(undefined,
    { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";

const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Weeks are written out: "Week-2", not "Wk 2".
export const weekLabel = (n) => `Week-${n}`;

export const bucketLabel = (b) =>
  b?.startsWith("M") ? MONTHS[+b.slice(1)] ?? b : weekLabel(b?.slice(1));

export const monthName = (m) => MONTHS[m] ?? String(m);

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
export const stamp = (iso) =>
  iso ? new Date(iso).toLocaleString(undefined,
    { day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit" }) : "";

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
  const day = (d) => d.getUTCDate();
  const mon = (d) => MONTHS[d.getUTCMonth() + 1];
  const start = monday.getUTCMonth() === sunday.getUTCMonth()
    ? `${day(monday)}`
    : monday.getUTCFullYear() === sunday.getUTCFullYear()
      ? `${day(monday)} ${mon(monday)}`
      : `${day(monday)} ${mon(monday)} ${monday.getUTCFullYear()}`;
  return `${start} to ${day(sunday)} ${mon(sunday)} ${sunday.getUTCFullYear()}`;
}
