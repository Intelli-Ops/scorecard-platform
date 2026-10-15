// The two reports' names, as the screens show them.
export const REPORT_OPTIONS = [
  { key: "gfs", short: "GFS", sendDay: "Tuesday" },
  { key: "all_providers", short: "All Providers", sendDay: "Thursday" },
];

export const reportShort = (key) =>
  REPORT_OPTIONS.find((r) => r.key === key)?.short ?? key;
