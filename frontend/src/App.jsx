// The app shell: sign-in gate, sidebar and page routes.
import { useEffect, useState } from "react";
import { NavLink, Route, Routes, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import SignIn from "./pages/SignIn";
import Weeks from "./pages/Weeks";
import Runs from "./pages/Runs";
import Review from "./pages/Review";
import Dashboard from "./pages/Dashboard";
import Current from "./pages/Current";
import Profile from "./pages/Profile";
import ChangePassword from "./pages/ChangePassword";
import AdminUsers from "./pages/AdminUsers";
import AdminActivity from "./pages/AdminActivity";
import AdminHolidays from "./pages/AdminHolidays";
import AdminProviders from "./pages/AdminProviders";
import { Loading } from "./components";
import { MenuIcon, NavCalendarIcon, NavChartIcon, NavHistoryIcon, NavListIcon, NavPeopleIcon, NavPersonIcon,
         NavShieldIcon, NavSignOutIcon, NavUploadIcon } from "./icons";

const OPEN_KEY = "scorecard.sidebar";

// One menu entry.
function Item({ to, icon, label, open }) {
  return (
    <NavLink to={to} className={({ isActive }) => (isActive ? "on" : "")}
             title={label}>
      <span className="glyph">{icon}</span>
      {open && <span className="text">{label}</span>}
    </NavLink>
  );
}

// A heading over a group of entries; collapsed, a hairline rule instead.
const Section = ({ open, children }) =>
  open ? <div className="nav-section">{children}</div> : <div className="nav-rule" />;

// Nothing is reachable without an account.
export default function App() {
  const { user, checking, signOut } = useAuth();
  const location = useLocation();

  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(OPEN_KEY) !== "closed"; } catch { return true; }
  });
  useEffect(() => {
    try { localStorage.setItem(OPEN_KEY, open ? "open" : "closed"); }
    catch { /* storage blocked */ }
  }, [open]);

  if (checking) return <Loading what="Signing you in" />;
  if (!user) return <SignIn />;
  if (user.must_change_password) return <ChangePassword />;

  const initials = (user.display_name ?? user.email)
    .split(/[\s.@]+/).filter(Boolean).slice(0, 2)
    .map((w) => w[0]).join("").toUpperCase();

  return (
    <div className={`app${open ? "" : " collapsed"}`}>
      <aside className="side">
        <div className="side-top">
          <button className="hamburger" onClick={() => setOpen(!open)}
                  aria-expanded={open} aria-label={open ? "Hide menu" : "Show menu"}
                  title={open ? "Hide menu" : "Show menu"}>
            <MenuIcon />
          </button>
          {open && (
            <div className="side-name">
              <div className="brand">Scorecard</div>
              <div className="sub">GFS &amp; All Providers</div>
            </div>
          )}
        </div>

        <nav>
          <Item to="/scorecard" icon={<NavChartIcon />} label="This week" open={open} />
          <Item to="/profile" icon={<NavPersonIcon />} label="Your profile" open={open} />

          {user.is_admin && (
            <>
              <Section open={open}>Workspace</Section>
              <Item to="/upload" icon={<NavUploadIcon />} label="Upload a week" open={open} />
              <Item to="/runs" icon={<NavHistoryIcon />} label="Run history" open={open} />
              <Section open={open}>Admin</Section>
              <Item to="/admin/activity" icon={<NavShieldIcon />} label="Activity" open={open} />
              <Item to="/admin/users" icon={<NavPeopleIcon />} label="Users" open={open} />
              <Item to="/admin/holidays" icon={<NavCalendarIcon />} label="Holidays" open={open} />
              <Item to="/admin/providers" icon={<NavListIcon />} label="Providers" open={open} />
            </>
          )}
        </nav>

        <div className="who">
          <NavLink to="/profile" className={({ isActive }) =>
                     `who-card${isActive ? " on" : ""}`}
                   title={`${user.email} · ${user.apd_id}. Your profile`}>
            <span className="avatar">{initials}</span>
            {open && (
              <span className="who-text">
                <span className="email">{user.display_name ?? user.email.split("@")[0]}</span>
                <span className="apd">{user.apd_id} · {user.role_label}</span>
              </span>
            )}
          </NavLink>
          <button className="signout" onClick={signOut} title="Sign out">
            <NavSignOutIcon />
            {open && <span>Sign out</span>}
          </button>
        </div>
      </aside>

      <main className="main">
        <div className="page" key={location.pathname}>
        <Routes>
          <Route path="/" element={<Navigate to="/scorecard" replace />} />
          <Route path="/scorecard" element={<Current />} />
          <Route path="/profile" element={<Profile />} />
          {user.is_admin && (
            <>
              <Route path="/upload" element={<Weeks />} />
              <Route path="/runs" element={<Runs />} />
              <Route path="/runs/:id" element={<Review />} />
              <Route path="/dashboard/:id" element={<Dashboard />} />
              <Route path="/admin/users" element={<AdminUsers />} />
              <Route path="/admin/activity" element={<AdminActivity />} />
              <Route path="/admin/holidays" element={<AdminHolidays />} />
              <Route path="/admin/providers" element={<AdminProviders />} />
            </>
          )}
          <Route path="*" element={<Navigate to="/scorecard" replace />} />
        </Routes>
        </div>
      </main>
    </div>
  );
}
