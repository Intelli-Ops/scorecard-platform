import { useEffect, useState } from "react";
import { NavLink, Route, Routes, Navigate } from "react-router-dom";
import { useAuth } from "./auth";
import SignIn from "./pages/SignIn";
import Weeks from "./pages/Weeks";
import Runs from "./pages/Runs";
import Review from "./pages/Review";
import Dashboard from "./pages/Dashboard";
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

/* Nothing is reachable without an account. The gate is here, once, rather than
   on each page - and the API refuses anyway, so a missed page cannot leak. */
export default function App() {
  const { user, checking, signOut } = useAuth();

  /* The sidebar remembers whether it was open. Someone who collapses it wants
     the room on every page, not just until the next click. */
  const [open, setOpen] = useState(
    () => localStorage.getItem(OPEN_KEY) !== "closed");
  useEffect(() => {
    localStorage.setItem(OPEN_KEY, open ? "open" : "closed");
  }, [open]);

  if (checking) return <Loading what="Signing you in" />;
  if (!user) return <SignIn />;

  const link = ({ isActive }) => (isActive ? "on" : "");

  return (
    <div className={`app${open ? "" : " collapsed"}`}>
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
          <NavLink to="/upload" className={link} title="Upload a week">
            <span className="glyph"><UploadIcon /></span>
            {open && <span className="text">Upload a week</span>}
          </NavLink>
          <NavLink to="/runs" className={link} title="Run history">
            <span className="glyph"><HistoryIcon /></span>
            {open && <span className="text">Run history</span>}
          </NavLink>
        </nav>

        <div className="who">
          {open ? (
            <>
              <div className="email">{user.email}</div>
              <div className="apd">{user.apd_id}</div>
              <button onClick={signOut}>Sign out</button>
            </>
          ) : (
            /* Collapsed: initials stand in for the address, and the tooltip
               still says who is signed in. */
            <button className="initials" onClick={signOut}
                    title={`${user.email} · ${user.apd_id} — sign out`}>
              {user.email.slice(0, 2).toUpperCase()}
            </button>
          )}
        </div>
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/upload" replace />} />
          <Route path="/upload" element={<Weeks />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<Review />} />
          <Route path="/dashboard/:id" element={<Dashboard />} />
        </Routes>
      </main>
    </div>
  );
}
