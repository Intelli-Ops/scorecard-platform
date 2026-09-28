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

const OPEN_KEY = "scorecard.sidebar";

/* Icons, drawn rather than typed: they stay crisp at any size, do not depend
   on a font having the character, and the menu button cannot be mistaken for
   a menu ITEM the way two identical "three lines" glyphs were. */
const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.6,
                 strokeLinecap: "round", strokeLinejoin: "round" };

function MenuIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      {[4.5, 9, 13.5].map((y) => (
        <line key={y} x1="2" y1={y} x2="16" y2={y} {...stroke} />
      ))}
    </svg>
  );
}

/* An arrow going up out of a tray - uploading. */
const UploadIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M8 10.5V2.5M4.8 5.7 8 2.5l3.2 3.2" {...stroke} />
    <path d="M2.5 10.5v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2" {...stroke} />
  </svg>
);

/* Stacked rows with a clock hand - a list of past builds. */
const HistoryIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M2.5 4h11M2.5 8h6M2.5 12h6" {...stroke} />
    <circle cx="12" cy="11" r="3.2" {...stroke} />
    <path d="M12 9.4V11l1.1.9" {...stroke} />
  </svg>
);

/* Two people - everyone's accounts. */
const PeopleIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <circle cx="6" cy="5.8" r="2.4" {...stroke} />
    <path d="M1.8 13.5c.5-2.3 2.2-3.7 4.2-3.7s3.7 1.4 4.2 3.7" {...stroke} />
    <path d="M10.6 3.6a2.4 2.4 0 0 1 0 4.5M12 9.9c1.2.5 2 1.8 2.3 3.6" {...stroke} />
  </svg>
);

/* A shield with a pulse line - the security record. */
/* A head and shoulders - your own account. */
const PersonIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <circle cx="8" cy="5.5" r="2.8" {...stroke} />
    <path d="M2.8 13.8c.6-2.7 2.7-4.3 5.2-4.3s4.6 1.6 5.2 4.3" {...stroke} />
  </svg>
);

const ShieldIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M8 1.8 13.2 3.8v3.9c0 3.1-2.2 5.6-5.2 6.6-3-1-5.2-3.5-5.2-6.6V3.8Z" {...stroke} />
    <path d="M4.8 8.2h1.6l1-1.8 1.4 3.3 1-1.5h1.4" {...stroke} />
  </svg>
);

/* Three bars on a baseline - the scorecard itself. */
const ChartIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M2.5 13.5h11" {...stroke} />
    <path d="M4.5 11V8M8 11V4.5M11.5 11V6.5" {...stroke} strokeWidth="2" />
  </svg>
);

/* A door with an arrow leaving it - signing out. */
const LeaveIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M6.5 2.5h-3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3" {...stroke} />
    <path d="M10 5l3 3-3 3M13 8H6.5" {...stroke} />
  </svg>
);

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
  const [open, setOpen] = useState(
    () => localStorage.getItem(OPEN_KEY) !== "closed");
  useEffect(() => {
    localStorage.setItem(OPEN_KEY, open ? "open" : "closed");
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
          <Item to="/scorecard" icon={<ChartIcon />} label="This week" open={open} />
          {/* Everyone's own account - a viewer included, who has to be able
              to change their password without hunting for it. */}
          <Item to="/profile" icon={<PersonIcon />} label="Your profile" open={open} />

          {/* A viewer reads scorecards; everything else here is an admin's.
              The API refuses it regardless - this only keeps the menu honest. */}
          {user.is_admin && (
            <>
              <Section open={open}>Workspace</Section>
              <Item to="/upload" icon={<UploadIcon />} label="Upload a week" open={open} />
              <Item to="/runs" icon={<HistoryIcon />} label="Run history" open={open} />
              <Section open={open}>Admin</Section>
              <Item to="/admin/activity" icon={<ShieldIcon />} label="Activity" open={open} />
              <Item to="/admin/users" icon={<PeopleIcon />} label="Users" open={open} />
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
            <LeaveIcon />
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
