import { NavLink, Route, Routes, Navigate } from "react-router-dom";
import Weeks from "./pages/Weeks";
import Runs from "./pages/Runs";
import Review from "./pages/Review";
import Dashboard from "./pages/Dashboard";

export default function App() {
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
