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

  /* An admin reset the password while this tab was open: the API starts
     refusing with "choose a new password", and the app switches to that
     screen rather than showing errors on every page. */
  useEffect(() => {
    const flag = () => setUser((u) => (u ? { ...u, must_change_password: true } : u));
    window.addEventListener("scorecard:password-change", flag);
    return () => window.removeEventListener("scorecard:password-change", flag);
  }, []);

  const finish = ({ token, user }) => { setToken(token); setUser(user); return user; };

  const value = {
    user,
    checking,
    signIn: async (email, password) => finish(await api.login(email, password)),
    /* A new account waits for an admin, so signing up does NOT sign you in -
       it returns what to tell the person instead. */
    signUp: (email, apdId, password) => api.signup(email, apdId, password),
    signOut: async () => {
      try { await api.logout(); } finally { setToken(null); setUser(null); }
    },
    /* After a profile change, so the corner of the screen and the password
       gate reflect it without a reload. */
    setUser,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
