import { useState } from "react";
import { useAuth } from "../auth";

/* Sign in and sign up, on one screen.

   Three fields, and the rules are stated under each one BEFORE they are broken
   rather than as an error afterwards - the Appedology domain and the shape of
   an APD id are things you cannot guess, so the form says them up front.

   The server checks both again. A form is a courtesy; the rule lives in the
   API, where it cannot be bypassed by opening the developer console. */

const DOMAIN = "@appedology.com";

export default function SignIn() {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState("in");
  const [email, setEmail] = useState("");
  const [apd, setApd] = useState("");
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState(null);
  const [busy, setBusy] = useState(false);

  const joining = mode === "up";

  async function submit(e) {
    e.preventDefault();
    setProblem(null);
    setBusy(true);
    try {
      joining ? await signUp(email, apd, password) : await signIn(email, password);
    } catch (err) {
      setProblem(err.message);
    } finally {
      setBusy(false);
    }
  }

  function swap() {
    setMode(joining ? "in" : "up");
    setProblem(null);
  }

  return (
    <div className="gate">
      <div className="panel">
        <div className="mark">S</div>
        <h1>{joining ? "Create your account" : "Sign in"}</h1>
        <p className="lede">
          {joining
            ? "Appedology accounts only. You will be signed in straight away."
            : "The weekly GFS and All Providers scorecards."}
        </p>

        {problem && <div className="problem">{problem}</div>}

        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="email">Work email</label>
            <input id="email" type="email" autoComplete="username" required
                   placeholder={`you${DOMAIN}`} value={email}
                   onChange={(e) => setEmail(e.target.value)} />
            {joining && <div className="hint">Must end {DOMAIN}</div>}
          </div>

          {joining && (
            <div className="field">
              <label htmlFor="apd">APD ID</label>
              <input id="apd" type="text" required placeholder="APD-1234"
                     value={apd} onChange={(e) => setApd(e.target.value)} />
              <div className="hint">Your internal ID — APD followed by four digits</div>
            </div>
          )}

          <div className="field">
            <label htmlFor="password">Password</label>
            <input id="password" type="password" required
                   autoComplete={joining ? "new-password" : "current-password"}
                   value={password} onChange={(e) => setPassword(e.target.value)} />
            {joining && <div className="hint">At least 8 characters</div>}
          </div>

          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Please wait…" : joining ? "Create account" : "Sign in"}
          </button>
        </form>

        <div className="swap">
          {joining ? "Already have an account? " : "First time here? "}
          <button type="button" className="link" onClick={swap}>
            {joining ? "Sign in" : "Create one"}
          </button>
        </div>
      </div>
    </div>
  );
}
