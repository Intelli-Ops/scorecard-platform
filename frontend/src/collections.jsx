import { useMemo } from "react";
import { money } from "./api";
import { assemble, col } from "./columns";
import { Stat, Stats, TableCard } from "./ui";
import {
  collectionsPaceTotal, collectionsToDate, paymentTypeTotals,
  pivotCollections, pivotCollectionsPace, TOTAL, weekLabel,
} from "./collections-model";

/* The Collection High-Level sheet.

   Same manner as Settlement, one dimension different: where Settlement opens
   the current month into weeks and puts a Settlement % beside each, Collections
   opens each WEEK into its four payment types and totals them.

     Week-32                        Week-33 ...
     BILLING REBILLING APPEAL SETTLEMENT Total

   The Pace block under it paces a group's whole week, not each payment type -
   that is what the sheet does, and pacing a single payment type would be
   projecting noise.

   The sheet's payment-type footer is not a table here. It is five figures, and
   they are already the tiles at the top of the page - printing them twice on
   one screen is not a layout, it is a duplicate.

   What is NOT here: the closed months, January to July, which the workbook
   carries as one column each. The pipeline does not produce them - the
   collections table it builds covers the current month only - so showing them
   would mean inventing them. See the note in the card. */

const GROUP = col.label("group", "Group", { width: 186, className: "sticky" });

export default function Collections({ rows, pace, monthLabel }) {
  const grid = useMemo(() => pivotCollections(rows), [rows]);
  const paced = useMemo(() => pivotCollectionsPace(pace), [pace]);

  /* One span per week over its payment types plus that week's total, then the
     month total. Built through `assemble` so a heading can never claim more
     columns than were added. */
  const { columns, spans } = useMemo(() => {
    const parts = grid.weeks.map((w) => ({
      span: { label: weekLabel(w), span: grid.types.length + 1, className: "current" },
      columns: [
        ...grid.types.map((t) =>
          col.money(`w${w}_${t}`, t, { className: "current" })),
        col.strong(`w${w}`, "Week total", { className: "current" }),
      ],
    }));
    parts.push({
      spanLabel: monthLabel ?? "This month",
      column: col.strong("_total", "Month total"),
    });
    return assemble(GROUP, parts);
  }, [grid, monthLabel]);

  const paceColumns = useMemo(() => [
    GROUP,
    ...paced.weeks.map((w) =>
      col.money(w, weekLabel(w.slice(1)), { className: "current" })),
  ], [paced.weeks]);

  return (
    <>
      <TableCard
        title="Collections"
        sub={`Each week of ${monthLabel ?? "the current month"} opened into its payment types. The closed months January to July are not shown: the pipeline builds this grid for the current month only.`}
        empty="No collections for this run."
        columns={columns} spans={spans} rows={grid.rows} />

      {paced.weeks.length > 0 && (
        <TableCard
          title="Collections: Pace"
          sub={`Where ${monthLabel ?? "this month"} lands if the rest of it goes at the rate seen so far. A group's whole week is paced, not each payment type. The sheet does the same, and pacing one payment type would be projecting noise.`}
          columns={paceColumns} rows={paced.rows} />
      )}

    </>
  );
}

/* The tiles ARE the payment-type footer the sheet prints under the grid - the
   total, then the four types that make it up. It was a table here too until
   that turned out to be the same five figures twice on one screen; the tiles
   are the better half, because they carry each type's share as well.

   No tile names a tone: Stats walks the palette, so the five never repeat. */
export function CollectionsTiles({ rows, pace, monthLabel }) {
  const total = useMemo(() => collectionsToDate(rows), [rows]);
  const paceTo = useMemo(() => collectionsPaceTotal(pace), [pace]);
  const byType = useMemo(() => paymentTypeTotals(rows), [rows]);
  const label = monthLabel ?? "this month";

  const types = byType.filter((r) => r.pt !== TOTAL);
  const share = (n) => (total ? `${((n / total) * 100).toFixed(2)}% of the month`
                              : "no collections yet");

  return (
    <Stats cols={5}>
      <Stat label={`Collections · ${label}`} value={money(total)}
            foot={paceTo ? `pacing to ${money(paceTo)}` : "settled this month"} />
      {types.map((r) => (
        <Stat key={r.pt} label={r.pt} value={money(r.payment)}
              foot={share(r.payment)} />
      ))}
    </Stats>
  );
}
