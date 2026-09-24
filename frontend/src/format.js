/* How a value is written down.

   Pure functions, no network and no `import.meta`, so they can be imported by
   anything - including a plain `node --test` run, which is why they are not in
   api.js with the HTTP client any more.

   One place decides what a dollar figure, a per cent and a count look like, so
   the same number reads the same way on every screen. */

export const money = (n) =>
  n == null ? "" : n.toLocaleString(undefined,
    { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const money2 = (n) =>
  n == null ? "" : n.toLocaleString(undefined,
    { style: "currency", currency: "USD", minimumFractionDigits: 2 });

export const pct = (n) =>
  n == null ? "" : `${(n * 100).toFixed(1)}%`;

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

/* Ordering for the x axis: months first in calendar order, then the current
   month's weeks. Sorting the raw labels as text would put W2 before M12. */
export const bucketSort = (a, b) => {
  const rank = (s) => (s.startsWith("M") ? [0, +s.slice(1)] : [1, +s.slice(1)]);
  const [ka, va] = rank(a), [kb, vb] = rank(b);
  return ka - kb || va - vb;
};
