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
import { Loading } from "./components";
import { MenuIcon, NavChartIcon, NavHistoryIcon, NavPeopleIcon, NavPersonIcon,
         NavShieldIcon, NavSignOutIcon, NavUploadIcon } from "./icons";

const OPEN_KEY = "scorecard.sidebar";

/* One menu entry. Collapsed, only the icon shows and the tooltip names it. */
function Item({ to, icon, label, open }) {
  return (
    <NavLink to={to} className={({ isActive }) => (isActive ? "on" : "")}
             title={label}>
      <span className="glyph">{icon}</span>
      {open && <span className="text">{label}</span>}
    </NavLink>
  );
}

/* A heading over a group of entries; collapsed, a hairline rule instead. */
const Section = ({ open, children }) =>
  open ? <div className="nav-section">{children}</div> : <div className="nav-rule" />;

/* Nothing is reachable without an account. The gate is here, once, rather than
   on each page - and the API refuses anyway, so a missed page cannot leak. */
export default function App() {
  const { user, checking, signOut } = useAuth();
  const location = useLocation();

  /* The sidebar remembers whether it was open. Someone who collapses it wants
     the room on every page, not just until the next click. */
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(OPEN_KEY) !== "closed"; } catch { return true; }
  });
  useEffect(() => {
    try { localStorage.setItem(OPEN_KEY, open ? "open" : "closed"); }
    catch { /* storage blocked - remembered for this visit only */ }
  }, [open]);

  if (checking) return <Loading what="Signing you in" />;
  if (!user) return <SignIn />;
  // A temporary password from an admin opens nothing but the form to replace it.
  if (user.must_change_password) return <ChangePassword />;

  const initials = (user.display_name ?? user.email)
    .split(/[\s.@]+/).filter(Boolean).slice(0, 2)
    .map((w) => w[0]).join("").toUpperCase();

  return (
    <div className={`app${open ? "" : " collapsed"}`}>
      {/* Pinned to the window: it stays put while a long scorecard scrolls
          under it, so the menu and Sign out are always one click away. */}
      <aside className="side">
        <div className="side-top">
          {/* Collapsed, the button is all that is left - so it stays in the
              same place on screen either way and never moves under the
              cursor. */}
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
          {/* Everyone's own account - a viewer included, who has to be able
              to change their password without hunting for it. */}
          <Item to="/profile" icon={<NavPersonIcon />} label="Your profile" open={open} />

          {/* A viewer reads scorecards; everything else here is an admin's.
              The API refuses it regardless - this only keeps the menu honest. */}
          {user.is_admin && (
            <>
              <Section open={open}>Workspace</Section>
              <Item to="/upload" icon={<NavUploadIcon />} label="Upload a week" open={open} />
              <Item to="/runs" icon={<NavHistoryIcon />} label="Run history" open={open} />
              <Section open={open}>Admin</Section>
              <Item to="/admin/activity" icon={<NavShieldIcon />} label="Activity" open={open} />
              <Item to="/admin/users" icon={<NavPeopleIcon />} label="Users" open={open} />
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
        {/* Keyed by the page, so each page arrives with the same short rise
            rather than snapping in. */}
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
            </>
          )}
          <Route path="*" element={<Navigate to="/scorecard" replace />} />
        </Routes>
        </div>
      </main>
    </div>
  );
}
