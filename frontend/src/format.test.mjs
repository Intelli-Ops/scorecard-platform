// Tests for format.js.
import { test } from "node:test";
import assert from "node:assert/strict";
import { device } from "./format.js";

test("a browser is named by what it is, not what it imitates", () => {
  const edge = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    + "(KHTML, like Gecko) Chrome/129.0 Safari/537.36 Edg/129.0";
  const chrome = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    + "(KHTML, like Gecko) Chrome/129.0 Safari/537.36";
  const safari = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    + "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
  assert.equal(device(edge), "Edge on Windows");
  assert.equal(device(chrome), "Chrome on macOS");
  assert.equal(device(safari), "Safari on iOS");
  assert.equal(device("python-httpx/0.28"), "Script");
  assert.equal(device(null), "Unknown device");
});

import { weekRange } from "./format.js";

test("a week number is written as the Monday to Sunday it covers", () => {
  assert.equal(weekRange("2026-W38"), "14 to 20 Sep 2026");
  assert.equal(weekRange("2026-W01"), "29 Dec 2025 to 4 Jan 2026");
  assert.equal(weekRange("2026-W53"), "28 Dec 2026 to 3 Jan 2027");
  assert.equal(weekRange("not a week"), "not a week");
});

import { daySpan, weekDays } from "./format.js";

test("a week of the month is written as the days it covers", () => {
  assert.equal(daySpan("2026-10-01", "2026-10-09"), "1 to 9 Oct");
  assert.equal(daySpan("2026-09-28", "2026-10-02"), "28 Sep to 2 Oct");
  const spans = { 10: [{ week: 1, first: "2026-10-01", last: "2026-10-09" }] };
  assert.equal(weekDays(spans, 10, "1"), "1 to 9 Oct");
  assert.equal(weekDays(spans, 10, 2), "");
  assert.equal(weekDays(undefined, 10, 1), "");      // a run built before week spans
});

import { personName } from "./format.js";

test("a name is made from a work email when none is chosen", () => {
  assert.equal(personName("ali.asghar@appedology.com"), "Ali Asghar");
  assert.equal(personName("ASVA.KAMAL@appedology.com"), "Asva Kamal");
  assert.equal(personName("sara_khan-2@appedology.com"), "Sara Khan 2");
  assert.equal(personName("omar@appedology.com"), "Omar");
  assert.equal(personName(null), "");
});
