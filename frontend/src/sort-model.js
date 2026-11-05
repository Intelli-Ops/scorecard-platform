// A to Z for a table's name column, without React.
const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

// `rows` with each run of ordinary rows put A to Z by `key`. Rows that `fixed` picks out
// (the Total, a section's heading or subtotal) stay where they are, and the rows between
// them are sorted among themselves, so a section's rows never leave it.
export function sortAtoZ(rows, key, fixed = () => false) {
  const out = [];
  let run = [];
  const flush = () => {
    run.sort((a, b) => collator.compare(String(a[key] ?? ""), String(b[key] ?? "")));
    out.push(...run);
    run = [];
  };
  for (const r of rows ?? []) {
    if (fixed(r)) { flush(); out.push(r); } else run.push(r);
  }
  flush();
  return out;
}
