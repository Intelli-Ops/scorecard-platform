// Column definitions shared by every table.
import { count, money, pct } from "./format.js";

export { TOTAL } from "./layout.js";

export const TONES = ["green", "teal", "blue", "violet", "amber", "rose"];

export const toneAt = (i) => TONES[i % TONES.length];

// Column builders.

const base = (key, label, extra = {}) => ({ key, label, align: "center", ...extra });

// A dash for nothing, never a bare 0 or an empty cell.
const dash = (v, format) => (v == null ? "-" : format(v));

export const col = {
  label: (key, label, extra = {}) =>
    base(key, label, { align: "left", strong: true, ...extra }),

  text: (key, label, extra = {}) => base(key, label, { align: "left", ...extra }),

  money: (key, label, extra = {}) =>
    base(key, label, { render: (r) => dash(r[key] || null, money), ...extra }),

  pct: (key, label, extra = {}) =>
    base(key, label, { render: (r) => dash(r[key], pct), ...extra }),

  count: (key, label, extra = {}) =>
    base(key, label, { render: (r) => dash(r[key], count), ...extra }),

  strong: (key, label, extra = {}) => total(col.money(key, label, extra)),
};

// The provider-group column most grids lead with.
export const GROUP = col.label("group", "Group", { width: 186, className: "sticky", sortable: true });

// Mark any column as a total column, whatever it holds.
export function total(column) {
  return { ...column, strong: true,
           className: ["total-col", column.className].filter(Boolean).join(" ") };
}

// A month and its Settlement % as one unit, with the heading that spans them.
export function amountPctPair(bucket, label, { current = false } = {}) {
  const className = current ? "current" : undefined;
  return {
    span: { label, span: 2, className },
    columns: [
      col.money(bucket, "Amount", { className }),
      col.pct(`${bucket}_pct`, "Settlement %", { className }),
    ],
  };
}

// A month's amount alone, shaped like amountPctPair, for a report with no Settlement %.
export function amountOnly(bucket, label, { current = false } = {}) {
  const className = current ? "current" : undefined;
  return {
    span: { label, span: 1, className },
    columns: [col.money(bucket, "Amount", { className })],
  };
}

// Assemble a list of pairs (and any plain columns) into the two rows a grouped-header table needs.
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
