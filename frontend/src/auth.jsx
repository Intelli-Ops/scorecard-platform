import { createContext, useContext, useEffect, useState } from "react";
import { api, setToken, getToken } from "./api";

/* Who is signed in.

   The token is kept in localStorage so a refresh does not sign you out. That
   is the right trade for a tool on one company network in development; once
   this is deployed on a single domain it should become an httpOnly cookie,
   which JavaScript cannot read at all. */

const Ctx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    (async () => {
      if (!getToken()) { setChecking(false); return; }
      try {
        setUser(await api.me());          // the token may have expired or been revoked
      } catch {
        setToken(null);
      } finally {
        setChecking(false);
      }
    })();
  }, []);

  const finish = ({ token, user }) => { setToken(token); setUser(user); return user; };

  const value = {
    user,
    checking,
    signIn: async (email, password) => finish(await api.login(email, password)),
    signUp: async (email, apdId, password) => finish(await api.signup(email, apdId, password)),
    signOut: async () => {
      try { await api.logout(); } finally { setToken(null); setUser(null); }
    },
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
