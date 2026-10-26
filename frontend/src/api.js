// Calls to the backend API.
const BASE = import.meta.env.VITE_API ?? "http://127.0.0.1:8000";

try { localStorage.removeItem("scorecard.token"); } catch { /* storage blocked */ }

async function json(path, opts = {}) {
  const r = await fetch(BASE + path, opts);
  if (r.status === 401) {
    if (!path.startsWith("/api/auth/")) window.location.reload();
  }
  if (!r.ok) {
    let detail;
    try { detail = (await r.json()).detail; } catch { detail = r.statusText; }
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

// Save a response as a file.
async function download(path, fallbackName) {
  const r = await fetch(BASE + path);
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
  signup: (email, apd_id, password) =>
    post("/api/auth/signup", { email, apd_id, password }),
  login: (email, password) => post("/api/auth/login", { email, password }),
  verifyEmail: (email, code) => post("/api/auth/verify-email", { email, code }),
  resendVerification: (email, password) =>
    post("/api/auth/verify-email/resend", { email, password }),
  forgotPassword: (email) => post("/api/auth/password/forgot", { email }),
  checkResetCode: (email, code) =>
    post("/api/auth/password/verify-code", { email, code }),
  setNewPassword: (ticket, password) =>
    post("/api/auth/password/reset", { ticket, password }),
  logout: () => json("/api/auth/logout", { method: "POST" }),
  me: () => json("/api/auth/me"),

  updateProfile: (display_name) => patch("/api/me", { display_name }),
  changePassword: (current, next) =>
    post("/api/me/password", { current, new: next }),
  mySessions: () => json("/api/me/sessions"),
  endSession: (id) => json(`/api/me/sessions/${id}`, { method: "DELETE" }),
  endOtherSessions: () => post("/api/me/sessions/end-others"),
  myActivity: () => json("/api/me/activity"),

  users: () => json("/api/admin/users"),
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
  deleteActivity: (body) => post("/api/admin/activity/delete", body),
  downloadActivity: (filters = {}) =>
    download(`/api/admin/activity/csv${query(filters)}`, "activity.csv"),

  reports: () => json("/api/reports"),
  currentScorecards: () => json("/api/scorecards/current"),
  weeks: () => json("/api/weeks"),
  week: (w) => json(`/api/weeks/${w}`),
  weekMonth: (w) => json(`/api/weeks/${w}/month`),
  setWorkingDays: (w, days) =>
    json(`/api/weeks/${w}/month`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ working_days: days }) }),

  upload(week, files, { forReport, onProgress } = {}) {
    const body = new FormData();
    for (const f of files) body.append("files", f, f.name);
    if (forReport) body.append("for_report", forReport);

    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open("POST", `${BASE}/api/weeks/${week}/uploads`);
      x.upload.onprogress = (e) =>
        e.lengthComputable && onProgress?.(e.loaded / e.total);
      x.onload = () => {
        try {
          const body = JSON.parse(x.responseText);
          if (x.status >= 200 && x.status < 300) resolve(body);
          else reject(new Error(body.detail?.message ?? body.detail
                                ?? x.statusText));
        } catch {
          reject(new Error(x.status === 413
            ? "upload failed (413): larger than the web server accepts"
            : `upload failed (${x.status})`));
        }
      };
      x.onerror = () => reject(new Error("upload failed - is the server running?"));
      x.send(body);
    });
  },

  startRun: (report, week, asOf) =>
    json(`/api/runs?report=${report}&week=${week}` +
         (asOf ? `&as_of=${asOf}` : ""), { method: "POST" }),
  runs: (report, weeks = 12) =>
    json(`/api/runs?weeks=${weeks}` + (report ? `&report=${report}` : "")),
  run: (id) => json(`/api/runs/${id}`),
  approve: (id) => json(`/api/runs/${id}/approve`, { method: "POST" }),
  unapprove: (id) => json(`/api/runs/${id}/unapprove`, { method: "POST" }),
  deleteRun: (id) => json(`/api/runs/${id}`, { method: "DELETE" }),

  deleteWeek: (w) => json(`/api/weeks/${w}`, { method: "DELETE" }),
  removeUpload: (w, id) =>
    json(`/api/weeks/${w}/uploads/${id}`, { method: "DELETE" }),
  figures: (id, name) => json(`/api/runs/${id}/figures/${name}`),
  caseAr: (id, filters = {}) => json(`/api/runs/${id}/case-ar${query(filters)}`),
  table: (id, name, { limit = 100, offset = 0 } = {}) =>
    json(`/api/runs/${id}/tables/${name}?limit=${limit}&offset=${offset}`),

  downloadCsv: (id, name) =>
    download(`/api/runs/${id}/tables/${name}/csv`, `${name}.csv`),
};

export * from "./format.js";
