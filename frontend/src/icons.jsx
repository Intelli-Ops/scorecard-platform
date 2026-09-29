/* Small line icons for buttons, drawn on one 14px grid with one stroke, so a
   row of them reads as a set. Drawn rather than typed: crisp at any zoom, and
   no font has to have the character. */

const S = { fill: "none", stroke: "currentColor", strokeWidth: 1.5,
            strokeLinecap: "round", strokeLinejoin: "round" };

const Icon = ({ children }) => (
  <svg className="icon" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
    {children}
  </svg>
);

export const CheckIcon = () => (
  <Icon><path d="M3 7.3 5.8 10 11 4.2" {...S} /></Icon>
);

export const CrossIcon = () => (
  <Icon><path d="M4 4l6 6M10 4l-6 6" {...S} /></Icon>
);

/* A key - a new password. */
export const KeyIcon = () => (
  <Icon>
    <circle cx="4.8" cy="9.2" r="2.4" {...S} />
    <path d="M6.5 7.5 11.5 2.5M9.6 4.4l1.4 1.4M10.9 3.1l1.2 1.2" {...S} />
  </Icon>
);

/* An arrow leaving a door - signed out. */
export const LeaveIcon = () => (
  <Icon>
    <path d="M5.5 2.5H3.5a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h2" {...S} />
    <path d="M8.5 4.5 11 7 8.5 9.5M11 7H5.5" {...S} />
  </Icon>
);

/* A circle with a bar - switched off, not gone. */
export const PauseIcon = () => (
  <Icon>
    <circle cx="7" cy="7" r="4.7" {...S} />
    <path d="M3.7 10.3l6.6-6.6" {...S} />
  </Icon>
);

/* A circle with a play mark - on again. */
export const PlayIcon = () => (
  <Icon>
    <circle cx="7" cy="7" r="4.7" {...S} />
    <path d="M6 5.1 9 7 6 8.9Z" {...S} />
  </Icon>
);

export const TrashIcon = () => (
  <Icon>
    <path d="M2.8 4h8.4M5.6 4V2.8h2.8V4M4 4l.6 7.2h4.8L10 4" {...S} />
  </Icon>
);

/* An open padlock. */
export const UnlockIcon = () => (
  <Icon>
    <rect x="3" y="6.3" width="8" height="5.2" rx="1.2" {...S} />
    <path d="M5 6.3V4.6a2 2 0 0 1 3.9-.6" {...S} />
  </Icon>
);

/* An open eye - show the password. */
export const EyeIcon = () => (
  <Icon>
    <path d="M1.5 7S3.6 3 7 3s5.5 4 5.5 4-2.1 4-5.5 4S1.5 7 1.5 7Z" {...S} />
    <circle cx="7" cy="7" r="1.8" {...S} />
  </Icon>
);

/* The eye struck through - hide it again. */
export const EyeOffIcon = () => (
  <Icon>
    <path d="M1.5 7S3.6 3 7 3s5.5 4 5.5 4-2.1 4-5.5 4S1.5 7 1.5 7Z" {...S} />
    <circle cx="7" cy="7" r="1.8" {...S} />
    <path d="M2.5 11.5l9-9" {...S} />
  </Icon>
);

/* An arrow up over a bar - Caps Lock. */
export const CapsIcon = () => (
  <Icon>
    <path d="M7 2.5 11 7H8.8v2.2H5.2V7H3Z" {...S} />
    <path d="M5.2 11.5h3.6" {...S} />
  </Icon>
);

/* An arrow into a tray - saving a file. */
export const DownloadIcon = () => (
  <Icon>
    <path d="M7 2.5v6.2M4.6 6.5 7 8.9l2.4-2.4" {...S} />
    <path d="M2.8 9.8v1a.9.9 0 0 0 .9.9h6.6a.9.9 0 0 0 .9-.9v-1" {...S} />
  </Icon>
);
