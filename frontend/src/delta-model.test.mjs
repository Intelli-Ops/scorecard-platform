// Tests for delta-model.js.
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

test("aging columns are in scale order, not alphabetical", () => {
  const g = pivotDelta(rows);
  assert.deepEqual(g.buckets, ["1-30", "31-60", "90+"]);
});

test("only the buckets actually present get a column", () => {
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

test("a column with one value is not offered as a filter", () => {
  const keys = filterOptions(rows).map((f) => f.key);
  assert.ok(!keys.includes("Type"));
  assert.ok(keys.includes("Group"));
});

test("aging and location are not filters; group is, first", () => {
  const keys = filterOptions(rows).map((f) => f.key);
  assert.ok(!keys.includes("Aging") && !keys.includes("Location"));
  assert.equal(keys[0], "Group");
});

test("a filter offers its values only; (All) is what the pill says when none is ticked", () => {
  for (const f of filterOptions(rows)) assert.ok(!f.values.includes(ALL));
});

test("(All) does not constrain", () => {
  assert.equal(applyFilters(rows, { Aging: ALL }).length, rows.length);
  assert.equal(applyFilters(rows, {}).length, rows.length);
  assert.equal(applyFilters(rows, undefined).length, rows.length);
  assert.equal(applyFilters(rows, { Aging: [] }).length, rows.length);
});

test("a filter with several values keeps rows matching any of them", () => {
  const one = applyFilters(rows, { Location: ["Board"] }).length;
  const both = applyFilters(rows, { Location: ["Board", "In House"] }).length;
  assert.ok(one > 0 && both > one);
  assert.equal(applyFilters(rows, { Location: ["Board", "In House"], Group: ["Artheon"] })
    .every((r) => r.Group === "Artheon"), true);
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
  const got = pivotDelta(applyFilters(rows, { Location: "Nowhere" }));
  assert.deepEqual(got.rows, []);
});

test("DOR pivot: 90+ settlements by Ongoing DOR Status, in the workbook's order", async () => {
  const { pivotDor, agingBrackets, DOR_AGING } = await import("./delta-model.js");
  const dor = [
    { Aging: "90+", "Ongoing DOR Status": "DOR Filed", Settlement_Amount: 100 },
    { Aging: "90+", "Ongoing DOR Status": "CIC Pending", Settlement_Amount: 50 },
    { Aging: "90+", "Ongoing DOR Status": "CIC Pending", Settlement_Amount: 25 },
    { Aging: "90+", "Ongoing DOR Status": "Zebra status", Settlement_Amount: 5 },
    { Aging: "90+", "Ongoing DOR Status": null, Settlement_Amount: 1 },
    { Aging: "90+", "Ongoing DOR Status": "Brand new", Settlement_Amount: 2 },
    { Aging: "1-30", "Ongoing DOR Status": "Future Hearing", Settlement_Amount: 900 },
  ];
  const order = ["Cannot file DOR", "CIC Pending", "DOR Filed", "Future Hearing"];
  const out = pivotDor(dor, DOR_AGING, order);
  assert.deepEqual(out.map((r) => r.status),
                   ["CIC Pending", "DOR Filed", "Brand new", "Zebra status", "(blank)", TOTAL]);
  assert.equal(out[0].amount, 75);
  assert.equal(out.at(-1).amount, 183);

  const all = pivotDor(dor, [], order);                     // no bracket chosen: every row
  assert.equal(all.at(-1).amount, 1083);
  assert.equal(all.find((r) => r.status === "Future Hearing").amount, 900);
  assert.deepEqual(pivotDor(dor, ["31-60"], order), []);
  assert.deepEqual(agingBrackets([...dor, { Aging: "61-90" }]), ["1-30", "61-90", "90+"]);
});

test("the DOR pivot follows the tab's filters as well as its own Aging", async () => {
  const { pivotDor, DOR_AGING } = await import("./delta-model.js");
  const dor = [
    { Group: "Artheon", Aging: "90+", "Ongoing DOR Status": "DOR Filed", Settlement_Amount: 100 },
    { Group: "Bayco", Aging: "90+", "Ongoing DOR Status": "DOR Filed", Settlement_Amount: 40 },
    { Group: "Artheon", Aging: "1-30", "Ongoing DOR Status": "DOR Filed", Settlement_Amount: 7 },
  ];
  const out = pivotDor(applyFilters(dor, { Group: ["Artheon"] }), DOR_AGING);
  assert.deepEqual(out.map((r) => [r.status, r.amount]), [["DOR Filed", 100], [TOTAL, 100]]);
});
