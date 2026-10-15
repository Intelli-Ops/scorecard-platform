// Buttons used throughout the app.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useDismiss } from "./hooks";
import { TrashIcon } from "./icons";

// Every button in the app is one of these.

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

// A link dressed as a button.
export function LinkButton({ to, tone, size, solid, icon, children, className }) {
  return (
    <Link to={to} className={classes({ tone, size, solid, className })}>
      {icon}{children}
    </Link>
  );
}

// The question itself: a red "Confirm …" and a Cancel beside it.
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

// An action that asks once more before it happens.
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

// Delete, everywhere: the bin, the word, and "Confirm delete".
export function DeleteButton({ label = "Delete", confirm = "Confirm delete",
                               busyLabel = "Deleting…", ...rest }) {
  return <ConfirmButton icon={<TrashIcon />} label={label} confirm={confirm}
                        busyLabel={busyLabel} {...rest} />;
}
