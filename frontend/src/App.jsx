import { NavLink, Route, Routes, Navigate } from "react-router-dom";
import { useAuth } from "./auth";
import SignIn from "./pages/SignIn";
import Weeks from "./pages/Weeks";
import Runs from "./pages/Runs";
import Review from "./pages/Review";
import Dashboard from "./pages/Dashboard";
import { Loading } from "./components";

/* Nothing is reachable without an account. The gate is here, once, rather than
   on each page - and the API refuses anyway, so a missed page cannot leak. */
export default function App() {
  const { user, checking, signOut } = useAuth();

  if (checking) return <Loading what="Signing you in" />;
  if (!user) return <SignIn />;

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">Scorecard</div>
        <div className="sub">GFS &amp; All Providers</div>
        <nav>
          <NavLink to="/upload" className={({ isActive }) => isActive ? "on" : ""}>
            Upload a week
          </NavLink>
          <NavLink to="/runs" className={({ isActive }) => isActive ? "on" : ""}>
            Run history
          </NavLink>
        </nav>
        <div className="who">
          <div className="email">{user.email}</div>
          <div className="apd">{user.apd_id}</div>
          <button onClick={signOut}>Sign out</button>
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
