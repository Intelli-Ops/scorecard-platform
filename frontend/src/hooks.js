import { useCallback, useEffect, useRef, useState } from "react";

/* Fetching what a screen shows, once, in one place.

   Every screen needed the same few lines: start the request, drop its answer
   if the screen has moved on before it arrived (a late answer for the last
   filter must not overwrite the one for this filter), keep the error, and
   fetch again after an action. They were written out in ten components.

     const { data, error, setError, setData, reload } =
       useLoad(() => api.runs(report), [report]);

   `load` is called whenever a value in `deps` changes. Until the first answer
   `data` is null. `keep` holds on to the previous answer while the next one
   is fetched, for a table that should not blank out while a filter changes.
   `reload()` fetches again without clearing what is on screen, and never
   throws - a failure lands in `error`. */
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
