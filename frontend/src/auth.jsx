import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api";

/* Who is signed in.

   The sign-in is an httpOnly cookie, which JavaScript cannot read at all -
   so there is nothing here to look at to know whether someone is signed in.
   The server is asked instead: it answers with the account, or with a 401. */

const Ctx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setUser(await api.me());
      } catch {
        // Not signed in, or the session has ended: the sign-in screen.
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

  const finish = ({ user }) => { setUser(user); return user; };

  const value = {
    user,
    checking,
    signIn: async (email, password) => finish(await api.login(email, password)),
    /* A new account waits for an admin, so signing up does NOT sign you in -
       it returns what to tell the person instead. */
    signUp: (email, apdId, password) => api.signup(email, apdId, password),
    signOut: async () => {
      try { await api.logout(); } finally { setUser(null); }
    },
    /* After a profile change, so the corner of the screen and the password
       gate reflect it without a reload. */
    setUser,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
