// Tests for settlement-model.js, against the delivered workbook.
import assert from "node:assert/strict";
import { test } from "node:test";

import { TOTAL, monthToDate, paceTotals, pivot, pivotPace, sortBlocks, splitBuckets }
  from "./settlement-model.js";

const WEEKLY = { W32: 17200, W33: 9900, W34: 35543.07, W35: 39800 };
const PACED = { W32: 72240, W33: 56910, W34: 87700.298, W35: 107565.2235 };

const rows = (over = {}) => [
  { block: "In House", group: "A Miles", bucket: "M1", amount: 94277.2,
    settlement_pct: 0.340538653 },
  { block: "In House", group: "A Miles", bucket: "M2", amount: 87496.39,
    settlement_pct: 0.262636832 },
  ...Object.entries(WEEKLY).map(([bucket, amount]) => ({
    block: "In House", group: "A Miles", bucket, amount,
  })),
  { block: "Board", group: "A Miles", bucket: "M1", amount: 5500 },
  ...Object.entries(over).map(([bucket, amount]) => ({
    block: "In House", group: "Artheon", bucket, amount,
  })),
];

test("months sort before weeks, each in calendar order", () => {
  const { months, weeks } = splitBuckets(rows());
  assert.deepEqual(months, ["M1", "M2"]);
  assert.deepEqual(weeks, ["W32", "W33", "W34", "W35"]);
});

test("the month total is the current month's weeks, not the year", () => {
  const p = pivot(rows(), [], "In House");
  const total = p.rows.find((r) => r.group === TOTAL);
  assert.equal(Math.round(total._month * 100) / 100, 102443.07);
});

test("the year total is every bucket, months and weeks together", () => {
  const p = pivot(rows(), [], "In House");
  const total = p.rows.find((r) => r.group === TOTAL);
  assert.equal(Math.round(total._total * 100) / 100, 284216.66);
});

test("a block only ever sees its own rows", () => {
  const p = pivot(rows(), [], "Board");
  const total = p.rows.find((r) => r.group === TOTAL);
  assert.equal(total._total, 5500);
  assert.equal(total._month, 0);          // Board has no weeks in this fixture
});

test("the Total row's per cent is read from settlement_totals, never summed", () => {
  const totals = [{ block: "In House", bucket: "M1", settlement_pct: 0.461539954 }];
  const p = pivot(rows(), totals, "In House");
  const total = p.rows.find((r) => r.group === TOTAL);
  assert.equal(total.M1_pct, 0.461539954);
});

test("groups are ordered by what they settled over the year", () => {
  const p = pivot(rows({ M1: 387970.41 }), [], "In House");
  assert.deepEqual(p.rows.map((r) => r.group), ["Artheon", "A Miles", TOTAL]);
});

test("a missing per cent stays missing rather than becoming zero", () => {
  const p = pivot(rows(), [], "In House");
  const aMiles = p.rows.find((r) => r.group === "A Miles");
  assert.equal(aMiles.M1_pct, 0.340538653);
  assert.equal(aMiles.W32_pct, undefined);   // the fixture gives weeks no per cent
});

test("In House comes before Board", () => {
  assert.deepEqual(sortBlocks(["Board", "In House"]), ["In House", "Board"]);
  assert.deepEqual(sortBlocks(["Other", "board", "IN HOUSE"]), ["IN HOUSE", "board", "Other"]);
});

// ---------------------------------------------------------------- pace

const paceRows = Object.entries(PACED).map(([bucket, pace]) => ({
  block: "In House", group: "A Miles", bucket, pace,
}));

test("the pace block keeps the workbook's numbers and week order", () => {
  const p = pivotPace(paceRows, "In House");
  assert.deepEqual(p.weeks, ["W32", "W33", "W34", "W35"]);
  const row = p.rows.find((r) => r.group === "A Miles");
  for (const [w, want] of Object.entries(PACED)) assert.equal(row[w], want);
});

test("pace totals come from the LAST week alone, not from summing the weeks", () => {
  assert.equal(paceTotals(paceRows)["In House"], 107565.2235);
});

test("a run built before pacing existed yields nothing, not a crash", () => {
  assert.deepEqual(pivotPace([], "In House"), { weeks: [], rows: [] });
  assert.deepEqual(pivotPace(undefined, "In House"), { weeks: [], rows: [] });
  assert.deepEqual(paceTotals(undefined), {});
});

test("month to date counts weeks only, per block", () => {
  const mtd = monthToDate(rows());
  assert.equal(Math.round(mtd["In House"] * 100) / 100, 102443.07);
  assert.equal(mtd["Board"], undefined);   // no weekly rows for Board here
});

import { withMonthWeeks } from "./settlement-model.js";

test("a closed month's weeks join its rows without touching the totals", () => {
  const monthRows = [
    { block: "In House", group: "A", bucket: "M10", amount: 30 },
    { block: "In House", group: "B", bucket: "M10", amount: 5 },
  ];
  const weeks = [
    { block: "In House", month: 10, bucket: "W1", group: "A", amount: 10, settlement_pct: 0.5 },
    { block: "In House", month: 10, bucket: "W2", group: "A", amount: 20, settlement_pct: 0.25 },
    { block: "In House", month: 10, bucket: "W1", group: "B", amount: 5, settlement_pct: 1 },
    { block: "In House", month: 10, bucket: "W1", group: null, amount: 15, settlement_pct: 0.6 },
    { block: "Board", month: 10, bucket: "W1", group: "A", amount: 99 },
  ];
  const p = withMonthWeeks(pivot(monthRows, [], "In House"), weeks, "In House");
  assert.deepEqual(p.weeksOf, { M10: ["W1", "W2"] });
  const a = p.rows.find((r) => r.group === "A");
  assert.equal(a.M10W1, 10);
  assert.equal(a.M10W2_pct, 0.25);
  const total = p.rows.find((r) => r.group === "Total");
  assert.equal(total.M10W1, 15);
  assert.equal(total.M10W1_pct, 0.6);       // the Total row's own %, not a sum
  assert.equal(total._total, 35);           // year to date is unchanged
});

test("a run without closed-month weeks has nothing to open", () => {
  const p = withMonthWeeks(pivot([], [], "In House"), undefined, "In House");
  assert.deepEqual(p.weeksOf, {});
});
