// Shared components: password fields, cards, tiles, filters, tables and status labels.
import { useLayoutEffect, useRef, useState } from "react";
import { CapsIcon, EyeIcon, EyeOffIcon } from "./icons";

// Every password box in the app.
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

// A new password, typed twice.
export function NewPasswordFields({ value, onChange, again, onAgain }) {
  return (
    <>
      <div className="field">
        <label htmlFor="pw-new">New password</label>
        <PasswordInput id="pw-new" required minLength={8}
               autoComplete="new-password" value={value}
               onChange={(e) => onChange(e.target.value)} />
        <div className="hint">At least 8 characters</div>
      </div>
      <div className="field">
        <label htmlFor="pw-again">New password again</label>
        <PasswordInput id="pw-again" required autoComplete="new-password"
               value={again} onChange={(e) => onAgain(e.target.value)} />
      </div>
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

// A headline figure.
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

// The one filter control, used everywhere a filter is needed.
export function Segmented({ options, value, onChange, label, onClear }) {
  const box = useRef(null);
  const [mark, setMark] = useState(null);
  const index = options.findIndex((o) => o.value === value);

  useLayoutEffect(() => {
    const measure = () => {
      const btn = box.current?.children[index + 1];     // [0] is the mark
      setMark(btn ? { left: btn.offsetLeft, width: btn.offsetWidth } : null);
    };
    measure();
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
      {onClear && <ClearX what={label} onClick={onClear} />}
    </div>
  );
}

// A dropdown, dressed the same way as the segmented control so the two read as one family.
export function Picker({ label, value, onChange, options, placeholder, active,
                         onClear }) {
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

// A free-text filter - an email, an address - in the same dress as a Picker, with the same × once something is typed.
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

// The × itself: small, round, and only there while there is something to remove.
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

// How a column is drawn.
function cellClass(c) {
  const align = c.align ?? (c.num ? "right" : "left");
  return [align === "right" ? "num" : `al-${align}`,
          c.strong ? "strong" : "", c.nowrap ? "nowrap" : "",
          c.className ?? ""].filter(Boolean).join(" ");
}

// `section(row)`, when it returns something, draws that row as one heading across the whole table rather than as cells.
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

// How an event in the activity log went.
export function Outcome({ value }) {
  const [tone, word] = {
    success: ["", "Success"],
    failure: ["warn", "Failed"],
    denied: ["alert", "Refused"],
  }[value] ?? ["", value];
  return <span className={`pill ${tone}`}>{word}</span>;
}

// Waiting: a spinner and what it is waiting for, over shimmering bars shaped like the rows about to arrive, so the page does not jump when they do.
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
