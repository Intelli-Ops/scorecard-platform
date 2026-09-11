/* The Delta pivot and its filters.
 *
 *   node --test src/delta-model.test.mjs
 *
 * This pivot is the one place in the app where the numbers on screen depend on
 * a control the reader is holding, so the filters get as much attention as the
 * arithmetic: a filter that quietly drops rows is worse than no filter.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { ALL, applyFilters, filterOptions, pivotDelta, TOTAL }
  from "./delta-model.js";

const row = (over = {}) => ({
  Group: "Artheon", Aging: "1-30", Location: "In House", Case_Validity: "Valid",
  "Lien Filed": "NO", "Closing Order": "CIC Pending", Type: "GFS",
  Settlement_Amount: 100, Billed: 500, Outstanding: 400, ...over,
});

const rows = [
  row(),
  row({ Aging: "90+", Settlement_Amount: 50 }),
  row({ Group: "Med-Legal", Aging: "31-60", Settlement_Amount: 25,
        Location: "Board", "Lien Filed": "YES" }),
  row({ Group: "Med-Legal", Aging: "1-30", Settlement_Amount: 25,
        Case_Validity: "Invalid" }),
];


/* ------------------------------------------------------------- the pivot */

test("aging columns are in scale order, not alphabetical", () => {
  // Sorting these as text puts "90+" between "31-60" and "61-90".
  const g = pivotDelta(rows);
  assert.deepEqual(g.buckets, ["1-30", "31-60", "90+"]);
});

test("only the buckets actually present get a column", () => {
  // Filtering to 90+ should leave one column, not four with three empty.
  const g = pivotDelta(rows.filter((r) => r.Aging === "90+"));
  assert.deepEqual(g.buckets, ["90+"]);
});

test("a bucket the data invents still gets a column rather than vanishing", () => {
  const g = pivotDelta([row({ Aging: "120+" })]);
  assert.ok(g.buckets.includes("120+"));
});

test("each cell is the sum of its group and bucket", () => {
  const g = pivotDelta(rows);
  const artheon = g.rows.find((r) => r.group === "Artheon");
  assert.equal(artheon["1-30"], 100);
  assert.equal(artheon["90+"], 50);
  assert.equal(artheon._total, 150);
  assert.equal(artheon._cases, 2);
});

test("the Grand Total row totals every group and every bucket", () => {
  const t = pivotDelta(rows).rows.find((r) => r.group === TOTAL);
  assert.equal(t["1-30"], 125);
  assert.equal(t._total, 200);
  assert.equal(t._cases, 4);
});

test("groups are ordered by settlement amount", () => {
  assert.deepEqual(pivotDelta(rows).rows.map((r) => r.group),
    ["Artheon", "Med-Legal", TOTAL]);
});

test("a row with no group is (blank), as the sheet writes it", () => {
  const g = pivotDelta([row({ Group: null })]);
  assert.equal(g.rows[0].group, "(blank)");
});

test("no rows means no table, not a lone Grand Total", () => {
  assert.deepEqual(pivotDelta([]).rows, []);
  assert.deepEqual(pivotDelta(undefined).rows, []);
});

/* ---------------------------------------------------------------- filters */

test("a column with one value is not offered as a filter", () => {
  // Type is GFS for every row here: a filter that cannot change anything.
  const keys = filterOptions(rows).map((f) => f.key);
  assert.ok(!keys.includes("Type"));
  assert.ok(keys.includes("Aging"));
});

test("every filter offers (All) first", () => {
  for (const f of filterOptions(rows)) assert.equal(f.values[0], ALL);
});

test("aging values are offered in scale order", () => {
  const aging = filterOptions(rows).find((f) => f.key === "Aging");
  assert.deepEqual(aging.values, [ALL, "1-30", "31-60", "90+"]);
});

test("(All) does not constrain", () => {
  assert.equal(applyFilters(rows, { Aging: ALL }).length, rows.length);
  assert.equal(applyFilters(rows, {}).length, rows.length);
  assert.equal(applyFilters(rows, undefined).length, rows.length);
});

test("filters combine - every one has to match", () => {
  const got = applyFilters(rows, { Aging: "1-30", Case_Validity: "Valid" });
  assert.equal(got.length, 1);
  assert.equal(got[0].Group, "Artheon");
});

test("filtering then pivoting gives the pivot of exactly those rows", () => {
  const got = pivotDelta(applyFilters(rows, { Location: "Board" }));
  assert.deepEqual(got.rows.map((r) => r.group), ["Med-Legal", TOTAL]);
  assert.equal(got.rows.find((r) => r.group === TOTAL)._total, 25);
});

test("a filter matching nothing gives an empty pivot, not everything", () => {
  // The failure that matters: a filter silently falling back to all rows.
  const got = pivotDelta(applyFilters(rows, { Location: "Nowhere" }));
  assert.deepEqual(got.rows, []);
});
