/* How a column is drawn - the shared vocabulary every table builds from.

   Before this, each tab wrote its own column definitions - its own money
   formatter, its own alignment, its own idea of what a total row looks like.
   Four tabs meant four chances to format a figure differently from the sheet
   next to it, and a fix applied in one place and forgotten in three.

   So the pieces live here once and the tabs pick from them. A tab still
   decides WHAT its columns are; it no longer decides how a dollar figure is
   drawn, where it sits in its cell, or what a Total row looks like. */

import { count, money, money2, pct } from "./format.js";

export const TOTAL = "Total";

/* The tile accent hues, in the order a row walks them.

   Assigned by POSITION rather than picked per tile, because picking meant
   remembering what the tile beside it already used - and forgetting produced
   rows with two greens, two teals and one odd one out. Six is more than any
   row currently holds; past that it wraps, which still beats a row of tiles
   that all look alike.

   Each name has a `.tile.tone-<name>` rule in theme.css. */
export const TONES = ["green", "teal", "blue", "violet", "amber", "rose"];

export const toneAt = (i) => TONES[i % TONES.length];

/* ------------------------------------------------------------- columns */

/* Column builders. Every one takes (key, label, extra) and returns a column
   the DataTable understands, so a tab reads as a list of what its columns MEAN
   rather than a list of render functions.

   Values are CENTRED. Money is normally set flush right so the decimal points
   stack, but these tables are read across - a provider's row against the month
   columns beside it - and a centred column under a centred heading keeps the
   pairs legible when a month is two columns wide. `tabular-nums` is on
   everywhere, so the digits still line up under each other. */

const base = (key, label, extra = {}) => ({ key, label, align: "center", ...extra });

/* An em dash for nothing, never a bare 0 or an empty cell: a group that
   settled nothing and a group with no row at all read differently on a
   scorecard, and the reader is entitled to tell them apart. */
const dash = (v, format) => (v == null ? "—" : format(v));

export const col = {
  /* The row's subject - a provider, a month, a file status. Left aligned:
     it is a label, and a ragged-right column of names is what the eye scans
     down. */
  label: (key, label, extra = {}) =>
    base(key, label, { align: "left", strong: true, ...extra }),

  text: (key, label, extra = {}) => base(key, label, { align: "left", ...extra }),

  money: (key, label, extra = {}) =>
    base(key, label, { render: (r) => dash(r[key] || null, money), ...extra }),

  /* Cents, for the tables where a figure is checked against a workbook rather
     than read at a glance. */
  money2: (key, label, extra = {}) =>
    base(key, label, { render: (r) => dash(r[key] || null, money2), ...extra }),

  pct: (key, label, extra = {}) =>
    base(key, label, { render: (r) => dash(r[key], pct), ...extra }),

  count: (key, label, extra = {}) =>
    base(key, label, { render: (r) => dash(r[key], count), ...extra }),

  /* A figure that carries the eye - a total, a year to date. */
  strong: (key, label, extra = {}) =>
    base(key, label, { strong: true, render: (r) => dash(r[key] || null, money), ...extra }),
};

/* A month and its Settlement % as one unit, with the heading that spans them.
   Returned together so a span can never drift out of step with the columns it
   covers - the bug this shape exists to make impossible. */
export function amountPctPair(bucket, label, { current = false } = {}) {
  const className = current ? "current" : undefined;
  return {
    span: { label, span: 2, className: current ? "current" : undefined },
    columns: [
      col.money(bucket, "Amount", { className }),
      col.pct(`${bucket}_pct`, "Settlement %", { className }),
    ],
  };
}

/* Assemble a list of pairs (and any plain columns) into the two rows a
   grouped-header table needs. */
export function assemble(lead, parts) {
  const columns = [lead];
  const spans = [{ label: "", span: 1, className: "lead" }];
  for (const p of parts) {
    if (p.span) { spans.push(p.span); columns.push(...p.columns); }
    else { spans.push({ label: p.spanLabel ?? "", span: 1, className: p.spanClass });
           columns.push(p.column ?? p); }
  }
  return { columns, spans };
}
