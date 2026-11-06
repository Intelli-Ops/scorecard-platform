// Shared components: password fields, cards, tiles, filters, tables, status labels and the pop-up window.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { CapsIcon, CrossIcon, EyeIcon, EyeOffIcon } from "./icons";
import { Select } from "./select";
import { sortAtoZ } from "./sort-model";

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
// With `multiple`, `value` is a list and several choices can be ticked at once.
export function Picker({ label, value, onChange, options, placeholder, prompt, active,
                         onClear, multiple }) {
  const clearable = active && onClear;
  return (
    <div className={`filter${active ? " on" : ""}`}>
      {label && <span className="filter-label">{label}</span>}
      <span className="clearable">
        <Select className={`${active ? "on" : ""}${clearable ? " has-x" : ""}`}
                label={label} value={value} onChange={onChange} options={options}
                placeholder={placeholder} prompt={prompt} multiple={multiple} />
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
  // Heading rows above the column names: one row of spans, or several (a closed month
  // opened into its weeks puts the month on one row and its weeks on the next). Each
  // sticky row sits under the ones above it, however tall they grow.
  const spanRows = !spans?.length ? [] : Array.isArray(spans[0]) ? spans : [spans];
  const rowRefs = useRef([]);
  const [tops, setTops] = useState([]);
  useLayoutEffect(() => {
    const rows = rowRefs.current.slice(0, spanRows.length).filter(Boolean);
    if (!rows.length) return undefined;
    const measure = () => {
      const out = [0];
      for (const r of rows) out.push(out[out.length - 1] + r.offsetHeight);
      setTops((was) => (was.join() === out.join() ? was : out));
    };
    measure();
    const ro = new ResizeObserver(measure);
    rows.forEach((r) => ro.observe(r));
    return () => ro.disconnect();
  }, [spans, rows?.length, spanRows.length]);
  const top = (i) => (tops[i] != null ? { top: tops[i] } : undefined);

  // A sortable column (`sortable: true`) has an A-Z button in its heading: on, its rows
  // go A to Z, the Total and any section rows staying put; off, back to the order given.
  const [sortKey, setSortKey] = useState(null);
  const shown = sortKey && rows?.length
    ? sortAtoZ(rows, sortKey, (r) => Boolean(isTotal?.(r) || section?.(r) || r._kind))
    : rows;
  const heading = (c) => {
    if (!c.sortable) return c.label;
    const on = sortKey === c.key;
    const say = on ? "Back to the usual order" : "Sort A to Z";
    return (
      <span className="sort-head">
        <span>{c.label}</span>
        <button type="button" className={`sort-az${on ? " on" : ""}`} aria-pressed={on}
                aria-label={say} title={say}
                onClick={() => setSortKey(on ? null : c.key)}>A-Z</button>
      </span>
    );
  };

  if (!rows?.length) return <div className="empty">{empty}</div>;
  return (
    <div className="scroll">
      <table className="grid-table">
        <thead>
          {spanRows.map((row, r) => (
            <tr key={r} className={`spans${r ? " sub" : ""}`}
                ref={(el) => { rowRefs.current[r] = el; }}>
              {row.map((g, i) => (
                <th key={i} colSpan={g.span ?? 1} rowSpan={g.rowSpan ?? 1}
                    className={`span ${g.className ?? ""}`} style={top(r)}>{g.label}</th>
              ))}
            </tr>
          ))}
          <tr>{columns.map((c) => (
            <th key={c.key} className={cellClass(c)}
                style={{ ...(c.width ? { width: c.width } : {}),
                         ...(spanRows.length ? top(spanRows.length) : {}) }}>{heading(c)}</th>
          ))}</tr>
        </thead>
        <tbody>
          {shown.map((r, i) => {
            const title = section?.(r);
            if (title) {
              return (
                <tr key={`section-${i}`}
                    className={["section", rowClass?.(r, i) ?? ""].filter(Boolean).join(" ")}>
                  <td colSpan={columns.length}><div className="section-inner">{title}</div></td>
                </tr>
              );
            }
            const newGroup = groupBy && i > 0 && groupBy(r) !== groupBy(shown[i - 1]);
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

// A build made before every file was in: says so, and which files it lacks.
export function PartialNotice({ missing }) {
  if (!missing?.length) return null;
  return (
    <div className="waiting rise">
      <span className="pulse" aria-hidden="true" />
      <span>
        <strong>Partial scorecard.</strong> Built without {missing.join(", ")} -
        the parts that need {missing.length === 1 ? "it" : "them"} show no data.
        Upload the rest and build again for the full scorecard.
      </span>
    </div>
  );
}

// A window over the page: a heading, its body, and its buttons along the foot. Escape, the ×,
// or a click on the dimmed page closes it - unless `locked`, while something is being saved.
export function Modal({ title, sub, icon, tone, onClose, locked, footer, width, children }) {
  const ref = useRef(null);
  const latest = useRef({ onClose, locked });
  useEffect(() => { latest.current = { onClose, locked }; });

  useEffect(() => {
    const d = ref.current;
    d.showModal();
    d.querySelector(".modal-box").focus();      // the window, not its × - Tab moves on from here
    const cancel = (e) => {
      e.preventDefault();
      if (!latest.current.locked) latest.current.onClose();
    };
    d.addEventListener("cancel", cancel);
    return () => { d.removeEventListener("cancel", cancel); if (d.open) d.close(); };
  }, []);

  return (
    <dialog ref={ref} className="modal" aria-labelledby="modal-title"
            style={width ? { "--modal-w": `${width}px` } : undefined}
            onMouseDown={(e) => {
              if (e.target === ref.current && !locked) onClose();
            }}>
      <div className="modal-box" tabIndex={-1}>
        <div className="modal-head">
          {icon && <span className={`modal-icon${tone ? ` ${tone}` : ""}`}>{icon}</span>}
          <div className="modal-heading">
            <div className="modal-title" id="modal-title">{title}</div>
            {sub && <div className="modal-sub">{sub}</div>}
          </div>
          <button type="button" className="modal-x" onClick={onClose} disabled={locked}
                  aria-label="Close" title="Close">
            <CrossIcon />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </dialog>
  );
}
