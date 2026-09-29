/* The two scorecards, as the screens name them. The server holds the full
   list (GET /api/reports) but only admins may read it, and a viewer's own
   profile has to name the reports too - so the few words each screen needs
   live here once rather than typed into three pages. */

export const REPORT_OPTIONS = [
  { key: "gfs", short: "GFS", sendDay: "Tuesday" },
  { key: "all_providers", short: "All Providers", sendDay: "Thursday" },
];

export const reportShort = (key) =>
  REPORT_OPTIONS.find((r) => r.key === key)?.short ?? key;
