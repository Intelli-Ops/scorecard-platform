import { useLayoutEffect, useRef, useState } from "react";
import { CapsIcon, EyeIcon, EyeOffIcon } from "./icons";

/* Every password box in the app: an eye to show or hide what was typed, and
   a note when Caps Lock is on - the two reasons a right password is refused.
   Takes the same props as an <input>. */
export function PasswordInput({ onKeyDown, onKeyUp, onBlur, ...props }) {
  const [shown, setShown] = useState(false);
  const [caps, setCaps] = useState(false);
  const check = (e) => setCaps(Boolean(e.getModifierState?.("CapsLock")));
  return (
    <>
      <span className="password">
        <input {...props} type={shown ? "text" : "password"}
               onKeyDown={(e) => { check(e); onKeyDown?.(e); }}
               onKeyUp={(e) => { check(e); onKeyUp?.(e); }}
               onMouseDown={check}
               onBlur={(e) => { setCaps(false); onBlur?.(e); }} />
        <button type="button" className="eye" onClick={() => setShown((s) => !s)}
                aria-label={shown ? "Hide password" : "Show password"}
                aria-pressed={shown} title={shown ? "Hide password" : "Show password"}>
          {shown ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      </span>
      {caps && (
        <div className="caps" role="status"><CapsIcon /> Caps Lock is on</div>
      )}
    </>
  );
}

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

/* A headline figure. `tone` tints the accent bar; `onClick` makes the tile
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

/* The same tile under its older name. */
export const Tile = Stat;

/* The one filter control, used everywhere a filter is needed.

   One thing on screen at a time: the report has six sheets, and showing all
   six at once is what makes the workbook hard to read in the first place.

   Choices are separated by a hairline rule rather than by boxes - the "|" is
   drawn, not typed, so it never lands in a copy-paste and never wraps onto a
   line of its own. */
export function Segmented({ options, value, onChange, label, onClear }) {
  /* The highlight is one element that slides to the chosen option, rather
     than each button switching its own background on and off - the eye
     follows it across, so the change of view is felt as well as seen. */
  const box = useRef(null);
  const [mark, setMark] = useState(null);
  const index = options.findIndex((o) => o.value === value);

  useLayoutEffect(() => {
    const measure = () => {
      const btn = box.current?.children[index + 1];     // [0] is the mark
      setMark(btn ? { left: btn.offsetLeft, width: btn.offsetWidth } : null);
    };
    measure();
    // Labels change width when fonts load or the window resizes.
    const ro = new ResizeObserver(measure);
    if (box.current) ro.observe(box.current);
    return () => ro.disconnect();
  }, [index, options.length]);

  return (
    <div className={`filter${onClear ? " on" : ""}`}>
      {label && <span className="filter-label">{label}</span>}
      <div className="seg" ref={box}>
        <span className="seg-mark" aria-hidden="true"
              style={mark ? { transform: `translateX(${mark.left}px)`,
                               width: mark.width, opacity: 1 } : { opacity: 0 }} />
        {options.map((o) => (
          <button key={o.value} className={o.value === value ? "on" : ""}
                  aria-pressed={o.value === value}
                  onClick={() => onChange(o.value)}>
            {o.label}
          </button>
        ))}
      </div>
      {/* Passed only while the choice is narrowing something - "GFS" rather
          than "Both" - so the × appears exactly when there is a filter. */}
      {onClear && <ClearX what={label} onClick={onClear} />}
    </div>
  );
}

/* A dropdown, dressed the same way as the segmented control so the two read
   as one family. Used where the choices are too many to sit in a row.

   `active` marks it as narrowing something. A row of filters all looking
   identical whether or not they are set is how you end up reading a filtered
   table as if it were the whole thing - so a set filter colours itself, and
   its label goes dark. */
export function Picker({ label, value, onChange, options, placeholder, active,
                         onClear }) {
  /* `onClear` gives a set filter its own ×, so one of several can be undone
     without starting again from nothing. */
  const clearable = active && onClear;
  return (
    <div className={`filter${active ? " on" : ""}`}>
      {label && <span className="filter-label">{label}</span>}
      <span className="clearable">
        <select className={`picker${active ? " on" : ""}${clearable ? " has-x" : ""}`}
                value={value} onChange={(e) => onChange(e.target.value)}>
          {placeholder && <option value="">{placeholder}</option>}
          {options.map((o) =>
            typeof o === "string"
              ? <option key={o} value={o}>{o}</option>
              /* { group, options }: a heading over related choices. */
              : o.group
                ? <optgroup key={o.group} label={o.group}>
                    {o.options.map((i) =>
                      <option key={i.value} value={i.value}>{i.label}</option>)}
                  </optgroup>
                : <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        {clearable && <ClearX what={label} onClick={onClear} />}
      </span>
    </div>
  );
}

/* A free-text filter - an email, an address - in the same dress as a Picker,
   with the same × once something is typed. */
export function TextFilter({ label, value, onChange, placeholder, size }) {
  const set = Boolean(value);
  return (
    <div className={`filter${set ? " on" : ""}`}>
      {label && <span className="filter-label">{label}</span>}
      <span className="clearable">
        <input type="text" className={set ? "has-x" : ""} placeholder={placeholder}
               size={size} value={value} onChange={(e) => onChange(e.target.value)}
               onKeyDown={(e) => e.key === "Escape" && onChange("")} />
        {set && <ClearX what={label} onClick={() => onChange("")} />}
      </span>
    </div>
  );
}

/* The × itself: small, round, and only there while there is something to
   remove. It pops in, so the eye notices the filter is now removable. */
export function ClearX({ what, onClick, title }) {
  const text = title
    ?? `Remove ${what ? `the ${what.toLowerCase()} filter` : "this filter"}`;
  return (
    <button type="button" className="clear-x" onClick={onClick}
            aria-label={text} title={text}>
      <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
        <path d="M1 1l6 6M7 1 1 7" stroke="currentColor" strokeWidth="1.6"
              strokeLinecap="round" />
      </svg>
    </button>
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
/* `section(row)`, when it returns something, draws that row as one heading
   across the whole table rather than as cells - a band that starts a section
   (Case AR's Invalid and Valid). */
export function DataTable({ columns, rows, empty = "Nothing to show",
                            isTotal, rowClass, groupBy, spans, section }) {
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
            const heading = section?.(r);
            if (heading) {
              return (
                <tr key={`section-${i}`}
                    className={["section", rowClass?.(r, i) ?? ""].filter(Boolean).join(" ")}>
                  <td colSpan={columns.length}><div className="section-inner">{heading}</div></td>
                </tr>
              );
            }
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

const WORD = { action: "Action", warning: "Warning", info: "Note" };

export function Notes({ notes, empty = "Nothing unusual." }) {
  if (!notes?.length) return <div className="empty">{empty}</div>;
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

/* How an event in the activity log went. A word, with the colour beside it. */
export function Outcome({ value }) {
  const [tone, word] = {
    success: ["", "Success"],
    failure: ["warn", "Failed"],
    denied: ["alert", "Refused"],
  }[value] ?? ["", value];
  return <span className={`pill ${tone}`}>{word}</span>;
}

/* Waiting: a spinner and what it is waiting for, over shimmering bars shaped
   like the rows about to arrive, so the page does not jump when they do. */
export const Loading = ({ what = "Loading" }) => (
  <div className="loading" role="status" aria-live="polite">
    <div className="loading-line"><span className="spinner" />{what}…</div>
    <div className="skeleton" style={{ width: "72%" }} />
    <div className="skeleton" style={{ width: "88%" }} />
    <div className="skeleton" style={{ width: "54%" }} />
  </div>
);

export const ErrorBox = ({ error }) =>
  error ? <div className="card err">{String(error.message ?? error)}</div> : null;
