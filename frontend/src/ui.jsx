/* The shared UI pieces every tab builds its screen out of.

   Before this, each tab wrote its own column definitions and its own tiles -
   its own money formatter, its own alignment, its own idea of what a total row
   looks like. Four tabs meant four chances to draw the same kind of figure
   four different ways, and a fix applied in one place and forgotten in three.

   So the pieces live here once and the tabs pick from them. A tab still
   decides WHAT its columns are and which figures lead the page; it no longer
   decides how a dollar figure is drawn, where it sits in its cell, or what a
   Total row looks like.

   The column builders themselves are in columns.js - pure functions, no React,
   so they can be read and tested on their own. Import them from there: a tab
   takes its columns from columns.js and its components from here. */

import { Children, cloneElement, isValidElement } from "react";

import { Card, DataTable, Tile } from "./components";
import { TOTAL, toneAt } from "./columns";

/* --------------------------------------------------------------- tiles */

/* The headline figures. `tone` tints the accent bar; `onClick` makes the tile
   a button, which is the only thing that should ever look pressable. */
export function Stat({ label, value, foot, tone, onClick, active, title }) {
  const cls = ["tile", tone ? `tone-${tone}` : "", onClick ? "clickable" : "",
               active ? "active" : ""].filter(Boolean).join(" ");
  const Node = onClick ? "button" : "div";
  return (
    <Node className={cls} onClick={onClick} title={title}
          type={onClick ? "button" : undefined}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {foot && <div className="foot">{foot}</div>}
    </Node>
  );
}

/* A row of them. `cols` is a hint, not a rule - the grid is auto-fit, so the
   row re-flows into whatever width the sidebar leaves it.

   Each child gets the next tone unless it names its own, so a tile that means
   something specific - an alert, say - can still say so. */
export function Stats({ children, cols = 4 }) {
  /* Children.map's own index, not a counter of our own: it already numbers
     children in flattened order, which is what a row of tiles is - the callers
     pass arrays, and an array counts as its elements rather than as one child. */
  const toned = Children.map(children, (child, i) =>
    (isValidElement(child)
      ? cloneElement(child, { tone: child.props.tone ?? toneAt(i) })
      : child));
  return <div className={`grid cols-${cols} stats`}>{toned}</div>;
}

/* ------------------------------------------------------------- a table */

/* One table in one card, which is how every table in the app is presented.
   Tabs pass columns and rows; everything else - the total row, the empty
   state, the scroll behaviour - is the same everywhere by construction. */
export function TableCard({ title, sub, right, columns, rows, spans,
                            empty, isTotal, rowClass, groupBy }) {
  return (
    <Card flush title={title} sub={sub} right={right}>
      <DataTable
        columns={columns} rows={rows} spans={spans}
        empty={empty ?? "Nothing to show"}
        isTotal={isTotal ?? ((r) => r.group === TOTAL || r.month === TOTAL)}
        rowClass={rowClass} groupBy={groupBy}
      />
    </Card>
  );
}

export { Tile };
