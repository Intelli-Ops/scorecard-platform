// Sign in, sign up, email confirmation and Forgot password.
import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Button } from "../buttons";
import { CodeInput, clock, useCountdown } from "../codes";
import { NewPasswordFields, PasswordInput } from "../components";

const DOMAIN = "@appedology.com";
const RESEND_AFTER = 60;        // seconds - the server refuses sooner anyway

const TITLES = {
  in: ["Sign in", "The weekly GFS and All Providers scorecards."],
  up: ["Create your account",
       "Appedology accounts only. You confirm your email with a code, then an admin approves the account."],
  verify: ["Confirm your email", null],
  forgot: ["Forgot your password?",
           "Enter your work email and we will send you a 6-digit code to reset it."],
  code: ["Enter your code", null],
  newpass: ["Choose a new password",
            "Every place you are signed in will be signed out."],
};

export default function SignIn() {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState("in");
  const [email, setEmail] = useState("");
  const [apd, setApd] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [code, setCode] = useState("");
  const [ticket, setTicket] = useState(null);
  const [problem, setProblem] = useState(null);
  const [done, setDone] = useState(null);
  const [busy, setBusy] = useState(false);
  const [expiresAt, setExpiresAt] = useState(null);
  const [resendAt, setResendAt] = useState(null);
  const left = useCountdown(expiresAt);
  const wait = useCountdown(resendAt);

  function go(next, message = null) {
    setMode(next);
    setProblem(null);
    setDone(message);
    setCode("");
  }

  function codeSent(minutes = 5) {
    setExpiresAt(Date.now() + minutes * 60_000);
    setResendAt(Date.now() + RESEND_AFTER * 1000);
  }

  async function step(fn) {
    setProblem(null);
    setDone(null);
    setBusy(true);
    try { await fn(); }
    catch (err) {
      setProblem(err.message);
      setCode("");                    // a wrong code is retyped, not edited
      return err;
    } finally { setBusy(false); }
    return null;
  }

  const submit = (fn) => (e) => { e.preventDefault(); fn(); };

  const signInNow = () => step(async () => {
    try { await signIn(email, password); }
    catch (err) {
      if (err.detail?.code !== "email_unverified") throw err;
      setExpiresAt(null);
      setResendAt(null);
      go("verify", "Your email is not confirmed yet. Enter the code we sent, "
                   + "or send a new one.");
    }
  });

  const signUpNow = () => step(async () => {
    const r = await signUp(email, apd, password);
    codeSent(r.minutes);
    go("verify", r.message);
  });

  const verifyNow = (typed = code) => step(async () => {
    const r = await api.verifyEmail(email, typed);
    setPassword("");
    go("in", r.message);
  });

  const resendVerification = () => step(async () => {
    const r = await api.resendVerification(email, password);
    codeSent();
    setDone(r.message);
  });

  const sendResetCode = () => step(async () => {
    const r = await api.forgotPassword(email);
    codeSent(r.minutes);
    go("code", `${r.message} It works for ${r.minutes} minutes.`);
  });

  const checkCode = (typed = code) => step(async () => {
    const r = await api.checkResetCode(email, typed);
    setTicket(r.ticket);
    setPassword("");
    setAgain("");
    go("newpass");
  });

  const saveNewPassword = () => {
    if (password !== again) { setProblem("The two passwords differ."); return; }
    step(async () => {
      const r = await api.setNewPassword(ticket, password);
      setTicket(null);
      setPassword("");
      setAgain("");
      go("in", r.message);
    });
  };

  const [title, lede] = TITLES[mode];

  return (
    <div className="gate">
      <div className="panel">
        <div className="mark">S</div>
        <h1>{title}</h1>
        {lede && <p className="lede">{lede}</p>}
        {(mode === "verify" || mode === "code") && (
          <p className="lede">
            We sent a 6-digit code to <span className="sent-to">{email}</span>.
          </p>
        )}

        {problem && <div className="problem" role="alert">{problem}</div>}
        {done && <div className="done" role="status">{done}</div>}

        {(mode === "in" || mode === "up") && (
          <form onSubmit={submit(mode === "in" ? signInNow : signUpNow)}>
            <EmailField email={email} setEmail={setEmail} hint={mode === "up"} />

            {mode === "up" && (
              <div className="field">
                <label htmlFor="apd">APD ID</label>
                <input id="apd" type="text" required placeholder="APD-1234"
                       value={apd} onChange={(e) => setApd(e.target.value)} />
                <div className="hint">Your internal ID: APD followed by four digits</div>
              </div>
            )}

            <div className="field">
              <div className="label-row">
                <label htmlFor="password">Password</label>
                {mode === "in" && (
                  <Button tone="link" onClick={() => go("forgot")}>Forgot password?</Button>
                )}
              </div>
              <PasswordInput id="password" required
                     autoComplete={mode === "up" ? "new-password" : "current-password"}
                     value={password} onChange={(e) => setPassword(e.target.value)} />
              {mode === "up" && <div className="hint">At least 8 characters</div>}
            </div>

            <Button tone="primary" type="submit" className="wide" busy={busy}
                    busyLabel="Please wait…">
              {mode === "in" ? "Sign in" : "Create account"}
            </Button>
          </form>
        )}

        {(mode === "verify" || mode === "code") && (
          <form onSubmit={submit(() => (mode === "verify" ? verifyNow() : checkCode()))}>
            <CodeInput value={code} onChange={setCode} disabled={busy}
                       invalid={Boolean(problem)}
                       onComplete={(c) => (mode === "verify" ? verifyNow(c) : checkCode(c))} />
            <div className="code-meta">
              {expiresAt == null ? "Use the newest code we sent."
                : left > 0 ? <>Expires in <b>{clock(left)}</b></>
                : <span className="expired">This code has expired. Send a new one.</span>}
            </div>
            <Button tone="primary" type="submit" className="wide" busy={busy}
                    busyLabel="Checking…" disabled={code.length < 6}>
              {mode === "verify" ? "Confirm email" : "Continue"}
            </Button>
            <div className="swap">
              Did not get it?{" "}
              {wait > 0
                ? <span className="muted">Send a new code in {wait}s</span>
                : <Button tone="link" disabled={busy}
                          onClick={mode === "verify" ? resendVerification : sendResetCode}>
                    Send a new code
                  </Button>}
            </div>
          </form>
        )}

        {mode === "forgot" && (
          <form onSubmit={submit(sendResetCode)}>
            <EmailField email={email} setEmail={setEmail} />
            <Button tone="primary" type="submit" className="wide" busy={busy}
                    busyLabel="Sending…">
              Send code
            </Button>
          </form>
        )}

        {mode === "newpass" && (
          <form onSubmit={submit(saveNewPassword)}>
            <NewPasswordFields value={password} onChange={setPassword}
                               again={again} onAgain={setAgain} />
            <Button tone="primary" type="submit" className="wide" busy={busy}
                    busyLabel="Saving…">
              Save new password
            </Button>
          </form>
        )}

        <div className="swap">
          {mode === "in" && <>First time here? <Button tone="link" onClick={() => go("up")}>Create an account</Button></>}
          {mode === "up" && <>Already have an account? <Button tone="link" onClick={() => go("in")}>Sign in</Button></>}
          {!["in", "up"].includes(mode) && (
            <Button tone="link" onClick={() => go("in")}>Back to sign in</Button>
          )}
        </div>
      </div>
    </div>
  );
}

function EmailField({ email, setEmail, hint }) {
  return (
    <div className="field">
      <label htmlFor="email">Work email</label>
      <input id="email" type="email" autoComplete="username" required
             placeholder={`you${DOMAIN}`} value={email}
             onChange={(e) => setEmail(e.target.value)} />
      {hint && <div className="hint">Must end {DOMAIN}</div>}
    </div>
  );
}
