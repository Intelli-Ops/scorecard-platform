import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { TrashIcon } from "./icons";

/* Every button in the app is one of these.

   One component, so every button looks and behaves the same way - the same
   shape, the same hover, the same press - and a change to how buttons look is
   made once. A page says what a button MEANS (its tone) and the look follows:

     primary  filled green    the thing you came to the page to do
     plain    white face      an ordinary action
     quiet    grey tint       available, but secondary - Done, Clear all
     soft     grey tint, turns teal under the pointer - routine row actions
     go       green tint      lets something happen - approve, unlock, enable
     warn     amber tint      stops something for now - disable
     danger   red tint        cannot be undone - delete
     link     text only       inline, inside a sentence

   `solid` fills a tinted tone at rest as well as on hover, for the one
   action in a row that is most likely wanted (Approve beside Turn down). */

function classes({ tone = "plain", size, solid, className }) {
  return ["btn", `tone-${tone}`, size === "sm" ? "sm" : "",
          solid ? "solid" : "", className ?? ""].filter(Boolean).join(" ");
}

export function Button({ tone, size, solid, icon, busy, busyLabel, children,
                         className, type = "button", disabled, ...rest }) {
  return (
    <button type={type} className={classes({ tone, size, solid, className })}
            disabled={disabled || busy} {...rest}>
      {icon}
      {busy && busyLabel ? busyLabel : children}
    </button>
  );
}

/* A link dressed as a button - for going somewhere rather than doing
   something, so the browser still treats it as a link (open in a new tab,
   copy address). */
export function LinkButton({ to, tone, size, solid, icon, children, className }) {
  return (
    <Link to={to} className={classes({ tone, size, solid, className })}>
      {icon}{children}
    </Link>
  );
}

/* Closing something - a confirmation, a pending choice - when the person
   clicks anywhere else or presses Escape. The way a macOS popover goes away:
   no timer that takes it back while they are still reading it. */
export function useDismiss(active, onDismiss) {
  const ref = useRef(null);
  const latest = useRef(onDismiss);
  useEffect(() => { latest.current = onDismiss; });
  useEffect(() => {
    if (!active) return;
    const away = (e) => {
      if (ref.current && !ref.current.contains(e.target)) latest.current();
    };
    const esc = (e) => e.key === "Escape" && latest.current();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [active]);
  return ref;
}

/* The question itself: a red "Confirm …" and a Cancel beside it. Everything
   else in its row steps aside while it is showing (see .is-armed in
   theme.css), so these two are the only choices left. It stays until one of
   them is pressed, or the person clicks elsewhere or presses Escape - it
   does not quietly change back while they are deciding. */
export function ConfirmPair({ confirm = "Confirm", busyLabel = "Working…",
                              onConfirm, onCancel, size = "sm", icon }) {
  const [busy, setBusy] = useState(false);
  const ref = useDismiss(!busy, onCancel);
  return (
    <span ref={ref} className="confirm-pair is-armed" role="group">
      <Button tone="danger" solid size={size} icon={icon} autoFocus
              busy={busy} busyLabel={busyLabel}
              onClick={async () => {
                setBusy(true);
                try { await onConfirm(); }
                finally { setBusy(false); onCancel(); }
              }}>
        {confirm}
      </Button>
      <Button tone="quiet" size={size} disabled={busy} onClick={onCancel}>
        Cancel
      </Button>
    </span>
  );
}

/* An action that asks once more before it happens: the first click swaps
   the button for a ConfirmPair in its place. */
export function ConfirmButton({ label, confirm, busyLabel, onConfirm,
                                tone = "danger", size = "sm", solid,
                                icon, disabled, title }) {
  const [armed, setArmed] = useState(false);
  if (armed) {
    return <ConfirmPair confirm={confirm} busyLabel={busyLabel} size={size}
                        icon={icon} onConfirm={onConfirm}
                        onCancel={() => setArmed(false)} />;
  }
  return (
    <Button tone={tone} size={size} solid={solid} icon={icon} disabled={disabled}
            title={title} onClick={() => setArmed(true)}>{label}</Button>
  );
}

/* Delete, everywhere: the bin, the word, and "Confirm delete". */
export function DeleteButton({ label = "Delete", confirm = "Confirm delete",
                               busyLabel = "Deleting…", ...rest }) {
  return <ConfirmButton icon={<TrashIcon />} label={label} confirm={confirm}
                        busyLabel={busyLabel} {...rest} />;
}
