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
  // Checked by the numbers rather than the words, which vary by locale.
  assert.equal(weekRange("2026-W38"), "14 to 20 Sep 2026");
  assert.equal(weekRange("2026-W01"), "29 Dec 2025 to 4 Jan 2026");
  assert.equal(weekRange("2026-W53"), "28 Dec 2026 to 3 Jan 2027");
  assert.equal(weekRange("not a week"), "not a week");
});
