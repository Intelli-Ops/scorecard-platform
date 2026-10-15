// The 6-box one-time code input and its countdown.
import { useEffect, useRef, useState } from "react";

const LENGTH = 6;

export function CodeInput({ value, onChange, onComplete, disabled, invalid }) {
  const boxes = useRef([]);
  const digits = value.padEnd(LENGTH, " ").slice(0, LENGTH).split("");

  const focus = (i) => boxes.current[Math.max(0, Math.min(LENGTH - 1, i))]?.focus();

  function put(at, typed) {
    const incoming = typed.replace(/\D/g, "");
    if (!incoming) return;
    const next = digits.slice();
    incoming.slice(0, LENGTH - at).split("").forEach((d, k) => { next[at + k] = d; });
    const code = next.join("").replace(/\s/g, "");
    onChange(code);
    focus(at + incoming.length);
    if (code.length === LENGTH) onComplete?.(code);
  }

  function key(i, e) {
    if (e.key === "Backspace") {
      e.preventDefault();
      const next = digits.slice();
      if (next[i].trim()) next[i] = " ";
      else if (i > 0) { next[i - 1] = " "; focus(i - 1); }
      onChange(next.join("").trimEnd().replace(/\s/g, ""));
    } else if (e.key === "ArrowLeft") { e.preventDefault(); focus(i - 1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); focus(i + 1); }
  }

  useEffect(() => { focus(0); }, []);

  return (
    <div className={`code-boxes${invalid ? " bad" : ""}`} role="group"
         aria-label="6-digit code">
      {digits.map((d, i) => (
        <input key={i} ref={(el) => { boxes.current[i] = el; }}
               type="text" inputMode="numeric" pattern="[0-9]*"
               autoComplete={i === 0 ? "one-time-code" : "off"}
               aria-label={`Digit ${i + 1}`} maxLength={LENGTH}
               value={d.trim()} disabled={disabled}
               onChange={(e) => put(i, e.target.value.replace(d.trim(), "") || e.target.value)}
               onKeyDown={(e) => key(i, e)}
               onPaste={(e) => { e.preventDefault(); put(i, e.clipboardData.getData("text")); }}
               onFocus={(e) => e.target.select()} />
      ))}
    </div>
  );
}

// Seconds left until `until` (a Date.now() value), ticking each second.
export function useCountdown(until) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!until) return undefined;
    const update = () => setNow(Date.now());
    const first = setTimeout(update, 0);
    const t = setInterval(update, 1000);
    return () => { clearTimeout(first); clearInterval(t); };
  }, [until]);
  return until ? Math.max(0, Math.ceil((until - now) / 1000)) : 0;
}

export const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
