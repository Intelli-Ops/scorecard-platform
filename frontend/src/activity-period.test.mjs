import { test } from "node:test";
import assert from "node:assert/strict";
import { parseDay, periodOf, today } from "./activity-period.js";

const local = (iso) => new Date(iso);

test("a day runs midnight to midnight, local time", () => {
  const p = periodOf("day", "2026-09-29");
  assert.equal(local(p.since).getTime(), new Date(2026, 8, 29).getTime());
  assert.equal(local(p.until).getTime(), new Date(2026, 8, 30).getTime());
  assert.equal(p.label, "29 Sep 2026");
});

test("a week is Monday to Sunday, whichever day is chosen", () => {
  for (const day of ["2026-09-28", "2026-10-01", "2026-10-04"]) {   // Mon, Thu, Sun
    const p = periodOf("week", day);
    assert.equal(local(p.since).getTime(), new Date(2026, 8, 28).getTime());
    assert.equal(local(p.until).getTime(), new Date(2026, 9, 5).getTime());
    assert.equal(p.label, "Week of 28 Sep 2026 to 4 Oct 2026");
  }
});

test("a month is the whole calendar month, across a year end too", () => {
  const p = periodOf("month", "2026-12-15");
  assert.equal(local(p.since).getTime(), new Date(2026, 11, 1).getTime());
  assert.equal(local(p.until).getTime(), new Date(2027, 0, 1).getTime());
  assert.equal(p.label, "Dec 2026");
});

test("nonsense is not a period", () => {
  assert.equal(parseDay("2026-02-31"), null);
  assert.equal(periodOf("day", ""), null);
  assert.equal(periodOf("year", "2026-09-29"), null);
});

test("today is written the way the date box reads it", () => {
  assert.equal(today(new Date(2026, 0, 5)), "2026-01-05");
});
