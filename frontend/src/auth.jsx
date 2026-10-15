// Who is signed in, shared with every screen.
import { createContext, useContext, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "./api";

const Ctx = createContext(null);

export function AuthProvider({ children }) {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setUser(await api.me());
      } catch {
        // not signed in
      } finally {
        setChecking(false);
      }
    })();
  }, []);

  useEffect(() => {
    const flag = () => setUser((u) => (u ? { ...u, must_change_password: true } : u));
    window.addEventListener("scorecard:password-change", flag);
    return () => window.removeEventListener("scorecard:password-change", flag);
  }, []);

  const finish = ({ user }) => { setUser(user); return user; };

  const value = {
    user,
    checking,
    signIn: async (email, password) => finish(await api.login(email, password)),
    signUp: (email, apdId, password) => api.signup(email, apdId, password),
    signOut: async () => {
      try { await api.logout(); }
      finally { setUser(null); navigate("/", { replace: true }); }
    },
    setUser,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
