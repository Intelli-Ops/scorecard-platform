const BASE = import.meta.env.VITE_API ?? "http://127.0.0.1:8000";
const TOKEN_KEY = "scorecard.token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);

function authHeaders(extra = {}) {
  const t = getToken();
  return t ? { ...extra, Authorization: `Bearer ${t}` } : extra;
}

async function json(path, opts = {}) {
  const r = await fetch(BASE + path, { ...opts, headers: authHeaders(opts.headers) });
  if (r.status === 401) {
    // The token has expired or been revoked. Drop it and send them to sign in.
    setToken(null);
    if (!path.startsWith("/api/auth/")) window.location.reload();
  }
  if (!r.ok) {
    let detail;
    try { detail = (await r.json()).detail; } catch { detail = await r.text(); }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.json();
}

const post = (path, body) =>
  json(path, { method: "POST", headers: { "Content-Type": "application/json" },
               body: JSON.stringify(body) });

export const api = {
  // --- accounts ---
  signup: (email, apd_id, password) =>
    post("/api/auth/signup", { email, apd_id, password }),
  login: (email, password) => post("/api/auth/login", { email, password }),
  logout: () => json("/api/auth/logout", { method: "POST" }),
  me: () => json("/api/auth/me"),

  reports: () => json("/api/reports"),
  weeks: () => json("/api/weeks"),
  week: (w) => json(`/api/weeks/${w}`),

  // The browser sends the files; the server hashes what it receives and
  // refuses anything that is not one of the nine inputs.
  upload(week, files, { forReport, uploadedBy, onProgress } = {}) {
    const body = new FormData();
    for (const f of files) body.append("files", f, f.name);
    if (forReport) body.append("for_report", forReport);
    if (uploadedBy) body.append("uploaded_by", uploadedBy);

    // XHR rather than fetch: it reports upload progress, and a 385 MB week
    // with no progress bar looks indistinguishable from a hung page.
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open("POST", `${BASE}/api/weeks/${week}/uploads`);
      const token = getToken();
      if (token) x.setRequestHeader("Authorization", `Bearer ${token}`);
      x.upload.onprogress = (e) =>
        e.lengthComputable && onProgress?.(e.loaded / e.total);
      x.onload = () => {
        try {
          const body = JSON.parse(x.responseText);
          x.status >= 200 && x.status < 300
            ? resolve(body)
            : reject(new Error(body.detail ?? x.statusText));
        } catch { reject(new Error(`upload failed (${x.status})`)); }
      };
      x.onerror = () => reject(new Error("upload failed - is the server running?"));
      x.send(body);
    });
  },

  startRun: (report, week, asOf) =>
    json(`/api/runs?report=${report}&week=${week}` +
         (asOf ? `&as_of=${asOf}` : ""), { method: "POST" }),
  // Twelve weeks, not twenty rows: a week holds two runs and more when one is
  // rebuilt, so a row limit cuts the list in the middle of a week.
  runs: (report, weeks = 12) =>
    json(`/api/runs?weeks=${weeks}` + (report ? `&report=${report}` : "")),
  run: (id) => json(`/api/runs/${id}`),
  // Who approved comes from the signed-in account, not from the caller.
  approve: (id) => json(`/api/runs/${id}/approve`, { method: "POST" }),
  unapprove: (id) => json(`/api/runs/${id}/unapprove`, { method: "POST" }),
  deleteRun: (id) => json(`/api/runs/${id}`, { method: "DELETE" }),

  // Uploads outlive runs, so deleting builds one by one never clears a
  // week. This is what removes the files themselves.
  deleteWeek: (w) => json(`/api/weeks/${w}`, { method: "DELETE" }),
  figures: (id, name) => json(`/api/runs/${id}/figures/${name}`),
  table: (id, name, { limit = 100, offset = 0 } = {}) =>
    json(`/api/runs/${id}/tables/${name}?limit=${limit}&offset=${offset}`),

  /* Download a whole table as CSV.

     Fetched rather than linked, because the request needs the sign-in header
     and a plain <a href> cannot carry one. The file is handed to the browser
     from memory once it has arrived. */
  async downloadCsv(id, name) {
    const r = await fetch(`${BASE}/api/runs/${id}/tables/${name}/csv`,
                          { headers: authHeaders() });
    if (!r.ok) throw new Error(`Could not export ${name} (${r.status})`);
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = (r.headers.get("Content-Disposition") ?? "")
      .match(/filename="?([^"]+)"?/)?.[1] ?? `${name}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};

/* Formatting lives in format.js - pure, and importable without a bundler.
   Re-exported here because every screen has always reached for it through
   api.js, and moving a file is not a reason to touch twenty imports. */
export * from "./format.js";
