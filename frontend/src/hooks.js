// Shared hooks: loading data, and closing popovers on outside click.
import { useCallback, useEffect, useRef, useState } from "react";

// Fetching what a screen shows, once, in one place.
export function useLoad(load, deps, { keep = false } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const latest = useRef(load);
  latest.current = load;
  const generation = useRef(0);

  const fetchNow = useCallback(async (clear) => {
    const mine = ++generation.current;
    setError(null);
    if (clear) setData(null);
    try {
      const d = await latest.current();
      if (mine === generation.current) setData(d);
    } catch (e) {
      if (mine === generation.current) setError(e);
    }
  }, []);

  // oxlint-disable-next-line react-hooks/exhaustive-deps -- deps are the caller's
  useEffect(() => { fetchNow(!keep); }, deps);

  const reload = useCallback(() => fetchNow(false), [fetchNow]);
  return { data, error, setData, setError, reload };
}

// A set of keys each click adds or takes away: which months or weeks are open.
export function useToggleSet(initial = []) {
  const [set, setSet] = useState(() => new Set(initial));
  const toggle = useCallback((key) => setSet((was) => {
    const next = new Set(was);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  }), []);
  return [set, toggle];
}

// Closing something - a confirmation, a pending choice - when the person clicks anywhere else or presses Escape.
export function useDismiss(active, onDismiss) {
  const ref = useRef(null);
  const latest = useRef(onDismiss);
  useEffect(() => { latest.current = onDismiss; });
  useEffect(() => {
    if (!active) return;
    const away = (e) => {
      if (ref.current && !ref.current.contains(e.target)) latest.current();
    };
    const esc = (e) => e.key === "Escape" && latest.current();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [active]);
  return ref;
}
