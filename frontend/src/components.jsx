import { useState } from "react";

export const SERIES = [
  "var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)",
  "var(--series-5)", "var(--series-6)", "var(--series-7)", "var(--series-8)",
];

/* Colour follows the entity, not its rank: a name always gets the same slot,
   so hiding a group in a filter never repaints the ones left on screen. */
export function colorFor(name, ordered) {
  const i = ordered.indexOf(name);
  return SERIES[(i < 0 ? 0 : i) % SERIES.length];
}

export function Card({ title, sub, right, children }) {
  return (
    <section className="card">
      {(title || right) && (
        <div className="spread" style={{ marginBottom: 12 }}>
          <div>
            {title && <h2 style={{ margin: 0 }}>{title}</h2>}
            {sub && <div className="mono">{sub}</div>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Tile({ label, value, foot }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {foot && <div className="foot">{foot}</div>}
    </div>
  );
}

/* Every chart ships a table view.

   Partly the documented relief - three light-mode series sit below 3:1 against
   the surface. Mostly because this is a scorecard: people came for the numbers,
   and a chart that cannot be read as figures is half a report. */
export function ChartFrame({ title, sub, legend, table, children }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className="card">
      <div className="chart-head">
        <div>
          <h2 style={{ margin: 0 }}>{title}</h2>
          {sub && <div className="mono">{sub}</div>}
        </div>
        {table && (
          <button className="small" onClick={() => setAsTable(!asTable)}>
            {asTable ? "Chart" : "Table"}
          </button>
        )}
      </div>
      {asTable ? <div className="scroll">{table}</div> : children}
      {!asTable && legend?.length > 1 && (
        <div className="legend">
          {legend.map((l) => (
            <span className="key" key={l.name}>
              <span className="swatch" style={{ background: l.color }} />
              {l.name}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

export function Tip({ active, payload, label, format = (v) => v }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey}>
          <span className="k" style={{ color: p.color }}>■</span>
          <span className="k"> {p.name}</span>
          <span className="v">{format(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

export function DataTable({ columns, rows, empty = "Nothing to show" }) {
  if (!rows?.length) return <div className="empty">{empty}</div>;
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr>{columns.map((c) => (
            <th key={c.key} className={c.num ? "num" : ""}>{c.label}</th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} className={c.num ? "num" : ""}>
                  {c.render ? c.render(r) : String(r[c.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const ICON = { action: "!", warning: "▲", info: "i" };
const WORD = { action: "Action", warning: "Warning", info: "Info" };

/* Severity never travels as colour alone - each note carries an icon and the
   word, so it survives colourblindness, greyscale printing and forced colours. */
export function Notes({ notes }) {
  if (!notes?.length) return <div className="empty">Nothing unusual.</div>;
  return (
    <div>
      {notes.map((n, i) => (
        <div className={`note ${n.severity}`} key={i}>
          <div className="icon" title={WORD[n.severity]}>{ICON[n.severity]}</div>
          <div className="body">
            <div>{n.text}</div>
            <div className="meta">
              {WORD[n.severity]}
              {n.change && n.change !== "same as last week" && ` · ${n.change}`}
              {n.moved && Object.entries(n.moved).map(([k, v]) => (
                <span key={k}> · {k} {v.was.toLocaleString()} → {v.now.toLocaleString()}</span>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Status({ value }) {
  const tone = { approved: "good", review: "warning", failed: "critical",
                 running: "", pending: "" }[value] ?? "";
  return <span className={`pill ${tone}`}>{value}</span>;
}

export function Loading({ what = "Loading" }) {
  return <div className="empty">{what}…</div>;
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="card err">{String(error.message ?? error)}</div>;
}
