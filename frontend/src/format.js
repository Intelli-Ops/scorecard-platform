/* How a value is written down.

   Pure functions, no network and no `import.meta`, so they can be imported by
   anything - including a plain `node --test` run, which is why they are not in
   api.js with the HTTP client any more.

   One place decides what a dollar figure, a per cent and a count look like, so
   the same number reads the same way on every screen. */

/* Money to the cent, always: a scorecard figure is checked against the
   workbook, and a whole-dollar figure never quite matches it. */
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

/* Bucket labels come from the .bat pipeline: W2 is week 2 of the month, M5 is month 5.
   Both appear because the report shows weekly detail for the current month and
   monthly totals for the months before it. */
const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/* Weeks are written out: "Week-2", not "Wk 2". These are weeks of the month
   (a week belongs to the month of its Wednesday) and the people reading the
   sheet say them in full, so the screen does too. One
   definition, here, because it was written twice and the two could drift. */
export const weekLabel = (n) => `Week-${n}`;

export const bucketLabel = (b) =>
  b?.startsWith("M") ? MONTHS[+b.slice(1)] ?? b : weekLabel(b?.slice(1));

export const monthName = (m) => MONTHS[m] ?? String(m);

/* A browser's self-description, reduced to what a person recognises -
   "Chrome on Windows" rather than a 130-character user-agent string. Order
   matters: Edge and Opera also call themselves Chrome, and Chrome also calls
   itself Safari, so the more specific names are tried first. */
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

/* A date and time in full, for a record that may be read months later -
   "28 Sept 2026, 09:14" - where `when` leaves the year off. */
export const stamp = (iso) =>
  iso ? new Date(iso).toLocaleString(undefined,
    { day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit" }) : "";

/* "2026-W38" as the days it covers - "14 to 20 Sept 2026", Monday to Sunday -
   because nobody outside the build knows which dates a week number means. */
export function weekRange(label) {
  const m = /^(\d{4})-W(\d{2})$/.exec(label ?? "");
  if (!m) return label ?? "";
  const [year, week] = [+m[1], +m[2]];
  // ISO week 1 is the week holding 4 January.
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
