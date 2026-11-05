// Small line icons.
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

// A key - a new password.
export const KeyIcon = () => (
  <Icon>
    <circle cx="4.8" cy="9.2" r="2.4" {...S} />
    <path d="M6.5 7.5 11.5 2.5M9.6 4.4l1.4 1.4M10.9 3.1l1.2 1.2" {...S} />
  </Icon>
);

// An arrow leaving a door - signed out.
export const LeaveIcon = () => (
  <Icon>
    <path d="M5.5 2.5H3.5a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h2" {...S} />
    <path d="M8.5 4.5 11 7 8.5 9.5M11 7H5.5" {...S} />
  </Icon>
);

// A circle with a bar - switched off, not gone.
export const PauseIcon = () => (
  <Icon>
    <circle cx="7" cy="7" r="4.7" {...S} />
    <path d="M3.7 10.3l6.6-6.6" {...S} />
  </Icon>
);

// A circle with a play mark - on again.
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

// An open padlock.
export const UnlockIcon = () => (
  <Icon>
    <rect x="3" y="6.3" width="8" height="5.2" rx="1.2" {...S} />
    <path d="M5 6.3V4.6a2 2 0 0 1 3.9-.6" {...S} />
  </Icon>
);

// An open eye - show the password.
export const EyeIcon = () => (
  <Icon>
    <path d="M1.5 7S3.6 3 7 3s5.5 4 5.5 4-2.1 4-5.5 4S1.5 7 1.5 7Z" {...S} />
    <circle cx="7" cy="7" r="1.8" {...S} />
  </Icon>
);

// The eye struck through - hide it again.
export const EyeOffIcon = () => (
  <Icon>
    <path d="M1.5 7S3.6 3 7 3s5.5 4 5.5 4-2.1 4-5.5 4S1.5 7 1.5 7Z" {...S} />
    <circle cx="7" cy="7" r="1.8" {...S} />
    <path d="M2.5 11.5l9-9" {...S} />
  </Icon>
);

// An arrow up over a bar - Caps Lock.
export const CapsIcon = () => (
  <Icon>
    <path d="M7 2.5 11 7H8.8v2.2H5.2V7H3Z" {...S} />
    <path d="M5.2 11.5h3.6" {...S} />
  </Icon>
);

// An arrow into a tray - saving a file.
export const DownloadIcon = () => (
  <Icon>
    <path d="M7 2.5v6.2M4.6 6.5 7 8.9l2.4-2.4" {...S} />
    <path d="M2.8 9.8v1a.9.9 0 0 0 .9.9h6.6a.9.9 0 0 0 .9-.9v-1" {...S} />
  </Icon>
);

// An arrow out of a tray - sending a file.
export const UploadIcon = () => (
  <Icon>
    <path d="M7 9V2.8M4.6 5.1 7 2.7l2.4 2.4" {...S} />
    <path d="M2.8 9.8v1a.9.9 0 0 0 .9.9h6.6a.9.9 0 0 0 .9-.9v-1" {...S} />
  </Icon>
);

// A shut padlock - someone else's to do.
export const LockIcon = () => (
  <Icon>
    <rect x="3" y="6.3" width="8" height="5.2" rx="1.2" {...S} />
    <path d="M4.9 6.3V4.7a2.1 2.1 0 0 1 4.2 0v1.6" {...S} />
  </Icon>
);

// Two sliders - choosing what is allowed.
export const SlidersIcon = () => (
  <Icon>
    <path d="M2.5 4.5h3M8.5 4.5h3M2.5 9.5h6M11 9.5h.5" {...S} />
    <circle cx="7" cy="4.5" r="1.4" {...S} />
    <circle cx="9.7" cy="9.5" r="1.4" {...S} />
  </Icon>
);

// A tray with an arrow out, larger - the heading of the upload rights window.
export const UploadRightsIcon = () => (
  <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M8 10.5V2.5M4.8 5.7 8 2.5l3.2 3.2" fill="none" stroke="currentColor"
          strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M2.5 10.5v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2" fill="none"
          stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"
          strokeLinejoin="round" />
  </svg>
);

const NAV = { fill: "none", stroke: "currentColor", strokeWidth: 1.6,
              strokeLinecap: "round", strokeLinejoin: "round" };

export function MenuIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      {[4.5, 9, 13.5].map((y) => (
        <line key={y} x1="2" y1={y} x2="16" y2={y} {...NAV} />
      ))}
    </svg>
  );
}

// An arrow going up out of a tray - uploading.
export const NavUploadIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M8 10.5V2.5M4.8 5.7 8 2.5l3.2 3.2" {...NAV} />
    <path d="M2.5 10.5v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2" {...NAV} />
  </svg>
);

// Stacked rows with a clock hand - a list of past builds.
export const NavHistoryIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M2.5 4h11M2.5 8h6M2.5 12h6" {...NAV} />
    <circle cx="12" cy="11" r="3.2" {...NAV} />
    <path d="M12 9.4V11l1.1.9" {...NAV} />
  </svg>
);

// Two people - everyone's accounts.
export const NavPeopleIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <circle cx="6" cy="5.8" r="2.4" {...NAV} />
    <path d="M1.8 13.5c.5-2.3 2.2-3.7 4.2-3.7s3.7 1.4 4.2 3.7" {...NAV} />
    <path d="M10.6 3.6a2.4 2.4 0 0 1 0 4.5M12 9.9c1.2.5 2 1.8 2.3 3.6" {...NAV} />
  </svg>
);

// A head and shoulders - your own account.
export const NavPersonIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <circle cx="8" cy="5.5" r="2.8" {...NAV} />
    <path d="M2.8 13.8c.6-2.7 2.7-4.3 5.2-4.3s4.6 1.6 5.2 4.3" {...NAV} />
  </svg>
);

// A shield with a pulse line - the security record.
export const NavShieldIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M8 1.8 13.2 3.8v3.9c0 3.1-2.2 5.6-5.2 6.6-3-1-5.2-3.5-5.2-6.6V3.8Z" {...NAV} />
    <path d="M4.8 8.2h1.6l1-1.8 1.4 3.3 1-1.5h1.4" {...NAV} />
  </svg>
);

// A calendar page with one day marked - the holidays.
export const NavCalendarIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <rect x="2.5" y="3.5" width="11" height="10" rx="1" {...NAV} />
    <path d="M2.5 6.5h11M5.5 2v3M10.5 2v3" {...NAV} />
    <path d="M9.5 9h2v2h-2Z" {...NAV} />
  </svg>
);

// A list with a bullet on each line - the provider list.
export const NavListIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M6 4h7.5M6 8h7.5M6 12h7.5" {...NAV} />
    <path d="M2.8 4h.4M2.8 8h.4M2.8 12h.4" {...NAV} strokeWidth="2" />
  </svg>
);

// Three bars on a baseline - the scorecard itself.
export const NavChartIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M2.5 13.5h11" {...NAV} />
    <path d="M4.5 11V8M8 11V4.5M11.5 11V6.5" {...NAV} strokeWidth="2" />
  </svg>
);

// A door with an arrow leaving it - signing out.
export const NavSignOutIcon = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M6.5 2.5h-3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3" {...NAV} />
    <path d="M10 5l3 3-3 3M13 8H6.5" {...NAV} />
  </svg>
);
