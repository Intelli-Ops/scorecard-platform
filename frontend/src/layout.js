// The client's row order for each block, from a build's "layout" figure, without React.

// Names match whatever their case or spacing: "BayCo" is "Bayco".
const key = (name) => String(name ?? "").split(/\s+/).filter(Boolean).join(" ").toLowerCase();

// The rows of one block, in the workbook's order; empty for a build that recorded none.
export function rowsOf(layout, section) {
  return (layout ?? []).filter((r) => r.section === section)
    .sort((a, b) => a.order - b.order).map((r) => r.row);
}

// `body` rearranged into the workbook's `order`. Each name listed takes its row from `body`, or
// `blank(name)` if it had no figures this week, as the workbook keeps a row of zeros. Rows the
// list does not name follow at the end, as the workbook adds them above the Total. With no
// order, `body` is returned as it is.
export function inSheetOrder(body, order, blank, name = (r) => r.group) {
  if (!order?.length) return body;
  const left = new Map(body.map((r) => [key(name(r)), r]));
  const seen = new Set();
  const out = [];
  for (const label of order) {
    const k = key(label);
    if (seen.has(k)) continue;
    seen.add(k);
    if (left.has(k)) {
      out.push(left.get(k));
      left.delete(k);
    } else {
      out.push(blank(label));
    }
  }
  return [...out, ...left.values()];
}
