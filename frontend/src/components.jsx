import { useEffect, useState } from "react";

export function Card({ title, sub, right, flush, children }) {
  if (!title && !right) return <section className="card">{children}</section>;
  return (
    <section className={`card${flush ? " flush" : ""}`}>
      <div className={flush ? "card-head" : "spread"}
           style={flush ? undefined : { marginBottom: 16 }}>
        <div>
          <h2>{title}</h2>
          {sub && <div className="small muted" style={{ marginTop: 3 }}>{sub}</div>}
        </div>
        {right}
      </div>
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

/* The one filter control, used everywhere a filter is needed.

   One thing on screen at a time: the report has six sheets, and showing all
   six at once is what makes the workbook hard to read in the first place.

   Choices are separated by a hairline rule rather than by boxes - the "|" is
   drawn, not typed, so it never lands in a copy-paste and never wraps onto a
   line of its own. */
export function Segmented({ options, value, onChange, label }) {
  return (
    <div className="filter">
      {label && <span className="filter-label">{label}</span>}
      <div className="seg">
        {options.map((o) => (
          <button key={o.value} className={o.value === value ? "on" : ""}
                  onClick={() => onChange(o.value)}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/* A dropdown, dressed the same way as the segmented control so the two read
   as one family. Used where the choices are too many to sit in a row.

   `active` marks it as narrowing something. A row of filters all looking
   identical whether or not they are set is how you end up reading a filtered
   table as if it were the whole thing - so a set filter colours itself, and
   its label goes dark. */
export function Picker({ label, value, onChange, options, placeholder, active }) {
  return (
    <div className={`filter${active ? " on" : ""}`}>
      {label && <span className="filter-label">{label}</span>}
      <select className={`picker${active ? " on" : ""}`} value={value}
              onChange={(e) => onChange(e.target.value)}>
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((o) =>
          typeof o === "string"
            ? <option key={o} value={o}>{o}</option>
            : <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

/* Every table in the app is this one.

   One component means one set of rules - the same ruled grid, the same header,
   the same right-aligned numbers - so a table on the review screen and a table
   on the dashboard cannot drift into looking like two different products.

   groupBy draws a heavier rule wherever its value changes. The run history
   holds two runs per week, and without that break a week's pair is not
   visually distinguishable from the week above it. */
/* How a column is drawn - shared by the heading and its cells, so the two can
   never disagree about where a column sits.

   `align` is the current way to say it ("left" | "center" | "right"); `num` is
   the older flag and still means right, so tables written before this keep
   working unchanged. */
function cellClass(c) {
  const align = c.align ?? (c.num ? "right" : "left");
  return [align === "right" ? "num" : `al-${align}`,
          c.strong ? "strong" : "", c.nowrap ? "nowrap" : "",
          c.className ?? ""].filter(Boolean).join(" ");
}

/* `spans` is an optional row of grouped headings above the column names -
   [{ label: "August 2026", span: 2 }, ...] - so a month can sit over its own
   Settlement Amount and Settlement % the way the workbook prints it. Without
   it the two columns read as unrelated, and a sheet with a pair per month
   becomes a wall of alternating headings. */
export function DataTable({ columns, rows, empty = "Nothing to show",
                            isTotal, rowClass, groupBy, spans }) {
  if (!rows?.length) return <div className="empty">{empty}</div>;
  return (
    <div className="scroll">
      <table className="grid-table">
        <thead>
          {spans && (
            <tr className="spans">
              {spans.map((g, i) => (
                <th key={i} colSpan={g.span ?? 1}
                    className={`span ${g.className ?? ""}`}>{g.label}</th>
              ))}
            </tr>
          )}
          <tr>{columns.map((c) => (
            <th key={c.key} className={cellClass(c)}
                style={c.width ? { width: c.width } : undefined}>{c.label}</th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const newGroup = groupBy && i > 0 && groupBy(r) !== groupBy(rows[i - 1]);
            const cls = [isTotal?.(r) ? "total" : "",
                         newGroup ? "group-start" : "",
                         rowClass?.(r, i) ?? ""].filter(Boolean).join(" ");
            return (
              <tr key={r.id ?? i} className={cls}>
                {columns.map((c) => {
                  const v = c.render ? c.render(r) : (r[c.key] ?? "");
                  return (
                    <td key={c.key}
                        className={cellClass(c)}
                        /* Cells are one line and clip. The whole value is on
                           the tooltip, so nothing is actually lost. */
                        title={typeof v === "string" ? v : undefined}>
                      {v}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* Deleting asks twice, in place.

   A browser confirm() box is easy to click through without reading. Making the
   second click a differently-worded button in the row itself means you have to
   look at the row you are about to destroy. */
export function ConfirmButton({ label = "Delete", confirm = "Really delete?",
                                busyLabel = "Deleting…", onConfirm,
                                disabled, title }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!armed) return;
    // Disarms itself, so a half-pressed delete never sits waiting on the page.
    const t = setTimeout(() => setArmed(false), 5000);
    return () => clearTimeout(t);
  }, [armed]);

  if (busy) return <button className="small" disabled>{busyLabel}</button>;
  if (!armed)
    return (
      <button className="small quiet" disabled={disabled} title={title}
              onClick={() => setArmed(true)}>{label}</button>
    );
  return (
    <span className="row tight">
      <button className="small danger" onClick={async () => {
        setBusy(true);
        try { await onConfirm(); } finally { setBusy(false); setArmed(false); }
      }}>{confirm}</button>
      <button className="small quiet" onClick={() => setArmed(false)}>Keep</button>
    </span>
  );
}

const WORD = { action: "Action", warning: "Warning", info: "Note" };

export function Notes({ notes }) {
  if (!notes?.length) return <div className="empty">Nothing unusual.</div>;
  return (
    <div>
      {notes.map((n, i) => (
        <div className={`note ${n.severity}`} key={i}>
          <div className="tag">{WORD[n.severity]}</div>
          <div>
            <div>{n.text}</div>
            {(n.change && n.change !== "same as last week") || n.moved ? (
              <div className="meta">
                {n.change}
                {n.moved && Object.entries(n.moved).map(([k, v]) => (
                  <span key={k}>
                    {" · "}{k} {v.was.toLocaleString()} → {v.now.toLocaleString()}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Status({ value }) {
  const tone = { approved: "good", review: "warn", failed: "alert" }[value] ?? "";
  return <span className={`pill ${tone}`}>{value}</span>;
}

export const Loading = ({ what = "Loading" }) => <div className="empty">{what}…</div>;

export const ErrorBox = ({ error }) =>
  error ? <div className="card err">{String(error.message ?? error)}</div> : null;
