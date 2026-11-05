// Tests for collectionsHistory-model.js.
import assert from "node:assert/strict";
import { test } from "node:test";

import { pivotHistory, TOTAL } from "./collectionsHistory-model.js";

const HISTORY = {
  year: 2026,
  order: ["Russman", "Medvantage", "Pro Ivy"],
  months: [{ month: 1, source: "file" }, { month: 2, source: "file" },
           { month: 10, source: "build", run_id: 7, week: "2026-W44", status: "approved" }],
  totals: [
    { group: "Medvantage", month: 1, amount: 300 },
    { group: "Russman", month: 1, amount: 1010.5 },
    { group: "Russman", month: 2, amount: 2000 },
    { group: "Artheon", month: 2, amount: 5 },
    { group: "Russman", month: 10, amount: 120 },
    { group: "Medvantage", month: 10, amount: 7 },
  ],
  weeks: [
    { group: "Russman", month: 10, week: 2, pt: "SETTLEMENT", payment: 20 },
    { group: "Russman", month: 10, week: 1, pt: "BILLING", payment: 100 },
    { group: "Medvantage", month: 10, week: 2, pt: "APPEAL", payment: 7 },
  ],
};

test("groups follow the sheet, and one with no figures keeps its row", () => {
  const g = pivotHistory(HISTORY);
  assert.deepEqual(g.rows.map((r) => r.group), ["Russman", "Medvantage", "Pro Ivy", "Artheon", TOTAL]);
  assert.deepEqual(g.months, [1, 2, 10]);
});

test("a month from a build opens into its weeks, and each week into its payment types", () => {
  const g = pivotHistory(HISTORY);
  assert.deepEqual(g.weeksOf, { 10: [1, 2] });
  assert.deepEqual(g.typesOf["10-2"], ["APPEAL", "SETTLEMENT"]);       // the sheet's order
  const russman = g.rows[0];
  assert.equal(russman.m10, 120);
  assert.equal(russman.m10w1, 100);
  assert.equal(russman.m10w2_SETTLEMENT, 20);
  assert.equal(russman._total, 1010.5 + 2000 + 120);
  assert.equal(g.weeksOf[1], undefined);                       // the file's months are totals
});

test("the Total row adds up every column, weeks and types included", () => {
  const total = pivotHistory(HISTORY).rows.at(-1);
  assert.equal(total.m1, 1310.5);
  assert.equal(total.m10w2, 27);
  assert.equal(total.m10w2_APPEAL, 7);
  assert.equal(total._total, 1310.5 + 2005 + 127);
});

test("nothing held is an empty table", () => {
  assert.deepEqual(pivotHistory({ months: [], totals: [], weeks: [] }).rows, []);
  assert.deepEqual(pivotHistory(null).rows, []);
});
