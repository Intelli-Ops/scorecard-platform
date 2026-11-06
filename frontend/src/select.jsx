// The app's dropdown: a pill like the other filters, opening a list drawn in the app's own
// style rather than the browser's plain one. Long lists get a search box.
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CheckIcon } from "./icons";
import { choices, flatten, narrow, summary, toggle, typeahead } from "./select-model";

const SEARCH_FROM = 9;       // a list with more choices than this gets a search box
const GAP = 6;

// `placeholder` is a first choice worth "" (such as "Everything"); `prompt` is only the
// text shown while nothing is chosen (such as "earlier weeks…").
//
// With `multiple`, `value` is a list and each choice has a tick box. The ticks are handed
// to `onChange` once, when the list closes, so a filter re-runs once rather than per tick.
export function Select({ value, onChange, options, placeholder, prompt, label,
                         className = "", disabled, multiple = false }) {
  const id = useId();
  const trigger = useRef(null);
  const menu = useRef(null);
  const list = useRef(null);
  const search = useRef(null);
  const typed = useRef({ text: "", at: 0 });
  const latest = useRef({});
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [place, setPlace] = useState(null);
  const [draft, setDraft] = useState([]);

  const all = useMemo(() => flatten(options, placeholder), [options, placeholder]);
  const items = useMemo(() => narrow(all, query), [all, query]);
  const shown = choices(items);
  const picked = multiple ? (value ?? []) : [];
  const ticked = open ? draft : picked;
  const chosen = multiple ? null : choices(all).find((o) => o.value === value);
  const text = multiple ? summary(picked, all, prompt ?? "") : chosen?.label ?? prompt ?? "";
  const searchable = choices(all).length > SEARCH_FROM;
  const isOn = (v) => (multiple ? ticked.includes(v) : v === value);

  // What closing needs, kept current for the listeners set up when the list opened.
  useEffect(() => {
    latest.current = { draft, picked, multiple, onChange };
  });

  const show = () => {
    if (disabled) return;
    setQuery("");
    setDraft(picked);
    const first = choices(all).find((o) => (multiple ? picked.includes(o.value)
                                                     : o.value === value));
    setActive(first?.n ?? 0);
    setOpen(true);
  };
  const close = (refocus = true) => {
    const { draft: d, picked: p, multiple: m, onChange: change } = latest.current;
    setOpen(false);
    setPlace(null);
    if (refocus) trigger.current?.focus();
    if (m && (d.length !== p.length || d.some((v, i) => v !== p[i]))) change(d);
  };
  const pick = (it) => {
    if (multiple) {
      setDraft((d) => toggle(d, it.value, all));
      return;
    }
    close();
    if (it.value !== value) onChange(it.value);
  };

  // Below the pill, or above it when there's more room there; kept in place on scroll.
  useLayoutEffect(() => {
    if (!open) return undefined;
    const measure = () => {
      const r = trigger.current?.getBoundingClientRect();
      if (!r) return;
      const below = window.innerHeight - r.bottom;
      const up = below < 240 && r.top > below;
      const room = (up ? r.top : below) - GAP - 12;
      const right = r.left > window.innerWidth / 2;
      setPlace({
        minWidth: Math.max(r.width, multiple ? 220 : 0),
        maxHeight: Math.max(160, Math.min(multiple ? 400 : 340, room)),
        ...(up ? { bottom: window.innerHeight - r.top + GAP } : { top: r.bottom + GAP }),
        ...(right ? { right: window.innerWidth - r.right } : { left: r.left }),
        up,
        // Inside an open pop-up window the list must sit in that window, or it would be
        // drawn beneath it.
        host: trigger.current.closest("dialog[open]") ?? document.body,
      });
    };
    measure();
    const onScroll = (e) => { if (!menu.current?.contains(e.target)) measure(); };
    const onDown = (e) => {
      if (!menu.current?.contains(e.target) && !trigger.current?.contains(e.target)) {
        close(false);
      }
    };
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", measure);
    document.addEventListener("mousedown", onDown, true);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", measure);
      document.removeEventListener("mousedown", onDown, true);
    };
    // close() reads what it needs from `latest`, so the list opening is all that matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const ready = open && place != null;
  useEffect(() => {
    if (ready) (search.current ?? list.current)?.focus({ preventScroll: true });
  }, [ready]);
  useEffect(() => {
    if (!ready) return;
    list.current?.querySelector(`[data-n="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [ready, active]);

  const onTriggerKey = (e) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
      e.preventDefault();
      show();
    }
  };

  const onMenuKey = (e) => {
    if (e.target.tagName === "BUTTON" && (e.key === "Enter" || e.key === " ")) return;
    const last = shown.length - 1;
    const step = { ArrowDown: 1, ArrowUp: -1, PageDown: 8, PageUp: -8 }[e.key];
    if (step) {
      e.preventDefault();
      setActive((a) => Math.min(last, Math.max(0, a + step)));
    } else if (!searchable && (e.key === "Home" || e.key === "End")) {
      e.preventDefault();
      setActive(e.key === "Home" ? 0 : last);
    } else if (e.key === "Enter" || (multiple && !searchable && e.key === " ")) {
      e.preventDefault();
      const it = shown.find((o) => o.n === active);
      if (it) pick(it);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === "Tab") {
      e.preventDefault();
      close();
    } else if (!searchable && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const now = e.timeStamp;
      const t = typed.current;
      t.text = now - t.at < 600 ? t.text + e.key : e.key;
      t.at = now;
      const hit = typeahead(items, t.text, t.text.length > 1 ? active - 1 : active);
      if (hit >= 0) setActive(hit);
    }
  };

  const listId = `${id}-list`;
  const activeId = shown.some((o) => o.n === active) ? `${id}-${active}` : undefined;
  const { up, host, ...box } = place ?? {};
  const unticked = shown.filter((o) => !draft.includes(o.value));
  const reserved = (searchable ? 44 : 0) + (multiple ? 48 : 0);
  const fullList = multiple && picked.length > 1
    ? choices(all).filter((o) => picked.includes(o.value)).map((o) => o.label).join(", ")
    : undefined;

  return (
    <>
      <button ref={trigger} type="button" disabled={disabled} title={fullList}
              className={`picker${open ? " open" : ""} ${className}`.trim()}
              aria-haspopup="listbox" aria-expanded={open} aria-controls={open ? listId : undefined}
              aria-label={label ? `${label}: ${fullList ?? text}` : undefined}
              onClick={() => (open ? close() : show())} onKeyDown={onTriggerKey}>
        <span className={`picker-text${(multiple ? picked.length : chosen) ? "" : " prompt"}`}>
          {text}
        </span>
        <svg className="picker-caret" width="10" height="7" viewBox="0 0 10 7" aria-hidden="true">
          <path d="M1 1.5 5 5.5 9 1.5" fill="none" stroke="currentColor" strokeWidth="1.7"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {ready && createPortal(
        <div ref={menu} className={`menu${up ? " up" : ""}${multiple ? " multi" : ""}`}
             style={box} onKeyDown={onMenuKey}>
          {searchable && (
            <div className="menu-search">
              <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true">
                <circle cx="6" cy="6" r="4.2" fill="none" stroke="currentColor" strokeWidth="1.5" />
                <path d="m9.2 9.2 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              <input ref={search} type="text" value={query} placeholder="Search…"
                     aria-label={`Search ${label ? label.toLowerCase() : "the list"}`}
                     aria-controls={listId} aria-activedescendant={activeId}
                     onChange={(e) => { setQuery(e.target.value); setActive(0); }} />
            </div>
          )}
          <div ref={list} id={listId} className="menu-list" role="listbox" tabIndex={-1}
               aria-label={label} aria-multiselectable={multiple || undefined}
               aria-activedescendant={searchable ? undefined : activeId}
               style={{ maxHeight: box.maxHeight - reserved }}>
            {items.map((it, i) => it.kind === "group"
              ? <div key={`g${i}`} className="menu-group" role="presentation">{it.label}</div>
              : (
                <div key={`o${i}`} id={`${id}-${it.n}`} data-n={it.n} role="option"
                     aria-selected={isOn(it.value)}
                     className={`menu-item${it.n === active ? " active" : ""}`
                                + `${isOn(it.value) ? " chosen" : ""}`}
                     onMouseMove={() => it.n !== active && setActive(it.n)}
                     onMouseDown={(e) => e.preventDefault()}
                     onClick={() => pick(it)}>
                  {multiple && (
                    <span className="menu-tick" aria-hidden="true">
                      {isOn(it.value) && <CheckIcon />}
                    </span>
                  )}
                  <span className="menu-label">{it.label}</span>
                  {!multiple && isOn(it.value) && <CheckIcon />}
                </div>
              ))}
            {!items.length && (
              <div className="menu-empty">Nothing matches &ldquo;{query.trim()}&rdquo;.</div>
            )}
          </div>
          {multiple && (
            <div className="menu-foot">
              {query.trim() && unticked.length > 0 ? (
                <button type="button" className="menu-link"
                        onClick={() => setDraft((d) => unticked.reduce(
                          (acc, o) => toggle(acc, o.value, all), d))}>
                  Tick {unticked.length} shown
                </button>
              ) : (
                <button type="button" className="menu-link" disabled={!draft.length}
                        onClick={() => setDraft([])}>
                  Clear{draft.length ? ` ${draft.length}` : ""}
                </button>
              )}
              <button type="button" className="menu-done" onClick={() => close()}>
                {draft.length ? `Show ${draft.length}` : "Show all"}
              </button>
            </div>
          )}
        </div>,
        host)}
    </>
  );
}
