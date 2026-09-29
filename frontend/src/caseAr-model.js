/* The Case AR table's shape, with no React in it.

   GFS's Case AR is Validity x Closing Order. Printed flat, "Invalid" and
   "Valid" repeat down the first column and the two halves run together. So
   the Validity column becomes section headings instead: the Invalid rows
   under an Invalid heading with their own subtotal, a break, then the same
   for Valid, then the Grand Total - the way Excel lays out a pivot with an
   outer row field.

   A Case AR with no Validity column (All Providers, by File Status) is left
   as it is. */

export const GRAND_TOTAL = "Grand Total";
const SECTION_COLUMNS = ["Case_Validity", "Validity"];

export function sectionCaseAr({ columns, kinds, rows }) {
  const by = columns.find((c) => SECTION_COLUMNS.includes(c));
  if (!by || columns[0] !== by || columns.length < 2) {
    return { columns, sectioned: false, rows };
  }

  const shown = columns.filter((c) => c !== by);
  const lead = shown[0];
  const figures = shown.filter((c) => kinds[c] !== "text");
  const body = rows.filter((r) => r[by] !== GRAND_TOTAL);
  const grand = rows.find((r) => r[by] === GRAND_TOTAL);

  // Sections in the order the rows arrive: the server already sorts them.
  const order = [...new Set(body.map((r) => r[by]))];
  const out = [];
  for (const name of order) {
    const mine = body.filter((r) => r[by] === name);
    const sub = { [lead]: `${name} total`, _kind: "subtotal", _section: name };
    for (const c of figures) sub[c] = mine.reduce((s, r) => s + (r[c] ?? 0), 0);
    out.push({ _kind: "section", _section: name, _totals: sub });
    for (const r of mine) out.push({ ...r, _section: name });
    out.push(sub);
  }
  if (grand) out.push({ ...grand, [lead]: GRAND_TOTAL, _kind: "grand" });
  return { columns: shown, sectioned: true, rows: out };
}

/* "Invalid" -> "invalid", for a class name. */
export const sectionClass = (name) =>
  `sec-${String(name).toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
