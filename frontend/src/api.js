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
    try { detail = (await r.json()).detail; } catch { detail = r.statusText; }
    /* An admin reset this account's password while it was open. The app shows
       the choose-a-new-password screen once it knows, so tell it. */
    if (detail?.code === "password_change_required") {
      window.dispatchEvent(new Event("scorecard:password-change"));
    }
    const err = new Error(typeof detail === "string" ? detail
                          : detail?.message ?? JSON.stringify(detail));
    err.status = r.status;
    err.detail = detail;
    throw err;
  }
  return r.json();
}

const send = (method) => (path, body) =>
  json(path, { method, headers: { "Content-Type": "application/json" },
               body: JSON.stringify(body ?? {}) });
const post = send("POST");
const patch = send("PATCH");

const query = (params) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") q.set(k, v);
  }
  const text = q.toString();
  return text ? `?${text}` : "";
};

/* Save a response as a file. Fetched rather than linked, because the request
   needs the sign-in header and a plain <a href> cannot carry one. */
async function download(path, fallbackName) {
  const r = await fetch(BASE + path, { headers: authHeaders() });
  if (!r.ok) throw new Error(`Could not download ${fallbackName} (${r.status})`);
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = (r.headers.get("Content-Disposition") ?? "")
    .match(/filename="?([^"]+)"?/)?.[1] ?? fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  // --- accounts ---
  signup: (email, apd_id, password) =>
    post("/api/auth/signup", { email, apd_id, password }),
  login: (email, password) => post("/api/auth/login", { email, password }),
  logout: () => json("/api/auth/logout", { method: "POST" }),
  me: () => json("/api/auth/me"),

  // --- your own profile ---
  updateProfile: (display_name) => patch("/api/me", { display_name }),
  changePassword: (current, next) =>
    post("/api/me/password", { current, new: next }),
  mySessions: () => json("/api/me/sessions"),
  endSession: (id) => json(`/api/me/sessions/${id}`, { method: "DELETE" }),
  endOtherSessions: () => post("/api/me/sessions/end-others"),
  myActivity: () => json("/api/me/activity"),

  // --- admin ---
  users: () => json("/api/admin/users"),
  // `reports` optional: grant a new viewer its scorecards as it is approved.
  approveUser: (id, reports) =>
    post(`/api/admin/users/${id}/approve`, reports ? { reports } : {}),
  setRole: (id, role) => post(`/api/admin/users/${id}/role`, { role }),
  setAccess: (id, reports) => post(`/api/admin/users/${id}/access`, { reports }),
  deleteUser: (id) => json(`/api/admin/users/${id}`, { method: "DELETE" }),
  setActive: (id, active) => post(`/api/admin/users/${id}/active`, { active }),
  unlockUser: (id) => post(`/api/admin/users/${id}/unlock`),
  resetPassword: (id) => post(`/api/admin/users/${id}/reset-password`),
  signOutUser: (id) => post(`/api/admin/users/${id}/sign-out`),
  actions: () => json("/api/admin/actions"),
  activity: (filters = {}) => json(`/api/admin/activity${query(filters)}`),
  alerts: (days = 7) => json(`/api/admin/alerts?days=${days}`),
  downloadActivity: (filters = {}) =>
    download(`/api/admin/activity/csv${query(filters)}`, "activity.csv"),

  reports: () => json("/api/reports"),
  // The latest APPROVED scorecard per report, and who approved it.
  currentScorecards: () => json("/api/scorecards/current"),
  weeks: () => json("/api/weeks"),
  week: (w) => json(`/api/weeks/${w}`),
  // The month a week belongs to, and the working days its pace uses.
  weekMonth: (w) => json(`/api/weeks/${w}/month`),
  // null goes back to the calendar's count.
  setWorkingDays: (w, days) =>
    json(`/api/weeks/${w}/month`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ working_days: days }) }),

  // The browser sends the files; the server hashes what it receives and
  // refuses anything that is not one of the nine inputs.
  // Who uploaded is taken from the signed-in account on the server.
  upload(week, files, { forReport, onProgress } = {}) {
    const body = new FormData();
    for (const f of files) body.append("files", f, f.name);
    if (forReport) body.append("for_report", forReport);

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
          if (x.status >= 200 && x.status < 300) resolve(body);
          else reject(new Error(body.detail?.message ?? body.detail
                                ?? x.statusText));
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
  // The Case AR pivot, rebuilt on the server for { group, file_status, validity }.
  caseAr: (id, filters = {}) => json(`/api/runs/${id}/case-ar${query(filters)}`),
  table: (id, name, { limit = 100, offset = 0 } = {}) =>
    json(`/api/runs/${id}/tables/${name}?limit=${limit}&offset=${offset}`),

  // A whole table as CSV - every row, not the page on screen.
  downloadCsv: (id, name) =>
    download(`/api/runs/${id}/tables/${name}/csv`, `${name}.csv`),
};

/* Formatting lives in format.js - pure, and importable without a bundler.
   Re-exported here because every screen has always reached for it through
   api.js, and moving a file is not a reason to touch twenty imports. */
export * from "./format.js";
