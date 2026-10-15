// Tests for collections-model.js, against the delivered workbook.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  collectionsPaceTotal, collectionsToDate, paymentTypeTotals,
  pivotCollections, pivotCollectionsPace, PAYMENT_TYPES, TOTAL,
} from "./collections-model.js";

const rows = [
  { Group: "Med-Legal", Week: 32, PT: "APPEAL", Payment: 2076.73 },
  { Group: "Med-Legal", Week: 32, PT: "SETTLEMENT", Payment: 17718.64 },
  { Group: "Artheon", Week: 32, PT: "BILLING", Payment: 37294.24 },
  { Group: "Artheon", Week: 32, PT: "REBILLING", Payment: 29.29 },
  { Group: "Artheon", Week: 32, PT: "APPEAL", Payment: 3934.88 },
  { Group: "Artheon", Week: 32, PT: "SETTLEMENT", Payment: 84999.89 },
  { Group: "Artheon", Week: 33, PT: "BILLING", Payment: 10628.48 },
];

const round2 = (n) => Math.round(n * 100) / 100;

test("a week's total is its payment types added up", () => {
  const g = pivotCollections(rows);
  const medLegal = g.rows.find((r) => r.group === "Med-Legal");
  assert.equal(round2(medLegal.w32), 19795.37);          // the sheet's figure
  assert.equal(medLegal.w32_APPEAL, 2076.73);
  assert.equal(medLegal.w32_BILLING, undefined);         // nothing, not zero
});

test("the Artheon week 32 total matches the sheet", () => {
  const g = pivotCollections(rows);
  const artheon = g.rows.find((r) => r.group === "Artheon");
  assert.equal(round2(artheon.w32), 126258.30);
});

test("weeks come out in order and payment types in the sheet's order", () => {
  const g = pivotCollections(rows);
  assert.deepEqual(g.weeks, [32, 33]);
  assert.deepEqual(g.types, PAYMENT_TYPES);
});

test("a payment type nobody used does not become a column", () => {
  const g = pivotCollections([
    { Group: "A", Week: 32, PT: "BILLING", Payment: 10 },
  ]);
  assert.deepEqual(g.types, ["BILLING"]);
});

test("the Total row sums every group, per type and per week", () => {
  const g = pivotCollections(rows);
  const total = g.rows.find((r) => r.group === TOTAL);
  assert.equal(round2(total.w32), round2(19795.37 + 126258.30));
  assert.equal(round2(total.w32_SETTLEMENT), round2(17718.64 + 84999.89));
  assert.equal(round2(total._total), round2(19795.37 + 126258.30 + 10628.48));
});

test("groups are ordered by what they collected", () => {
  const g = pivotCollections(rows);
  assert.deepEqual(g.rows.map((r) => r.group), ["Artheon", "Med-Legal", TOTAL]);
});

test("an empty run yields an empty grid rather than a crash", () => {
  assert.deepEqual(pivotCollections([]), { weeks: [], types: [], rows: [] });
  assert.deepEqual(pivotCollections(undefined).weeks, []);
});

const PACE = { W32: 748851.978, W33: 663188.358, W34: 800879.758,
               W35: 1002578.0835 };
const paceRows = Object.entries(PACE).map(([bucket, pace]) => ({
  group: "Total-ish", bucket, pace,
}));

test("the pace block keeps the workbook's numbers and week order", () => {
  const p = pivotCollectionsPace(paceRows);
  assert.deepEqual(p.weeks, ["W32", "W33", "W34", "W35"]);
  const row = p.rows.find((r) => r.group === "Total-ish");
  for (const [w, want] of Object.entries(PACE)) assert.equal(row[w], want);
});

test("the pace total is the LAST week alone, not the weeks summed", () => {
  assert.equal(collectionsPaceTotal(paceRows), 1002578.0835);
});

test("a run built before collections pacing existed yields nothing", () => {
  assert.deepEqual(pivotCollectionsPace([]), { weeks: [], rows: [] });
  assert.equal(collectionsPaceTotal([]), null);
  assert.equal(collectionsPaceTotal(undefined), null);
});

test("the payment-type footer keeps the sheet's order and totals", () => {
  const f = paymentTypeTotals(rows);
  assert.deepEqual(f.map((r) => r.pt),
    ["BILLING", "REBILLING", "APPEAL", "SETTLEMENT", TOTAL]);
  assert.equal(round2(f.find((r) => r.pt === "SETTLEMENT").payment),
    round2(17718.64 + 84999.89));
  assert.equal(round2(f.at(-1).payment), round2(collectionsToDate(rows)));
});

test("month to date is every row, whatever the week or type", () => {
  assert.equal(round2(collectionsToDate(rows)),
    round2(19795.37 + 126258.30 + 10628.48));
  assert.equal(collectionsToDate([]), 0);
  assert.equal(collectionsToDate(undefined), 0);
});
