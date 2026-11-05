// Tests for layout.js and the models that follow the All Providers workbook's row order.
import assert from "node:assert/strict";
import { test } from "node:test";

import { inSheetOrder, rowsOf } from "./layout.js";
import { pivotDeltaComparison, TOTAL } from "./deltaComparison-model.js";
import { kpiBlocks } from "./kpi-model.js";
import { cpAcross, pivot } from "./settlement-model.js";
import { pivotCollections } from "./collections-model.js";

const LAYOUT = [
  { section: "In House", row: "Med-Legal", order: 0 },
  { section: "In House", row: "BayCo", order: 1 },
  { section: "In House", row: "Pro Ivy", order: 2 },
  { section: "kpi", row: "SBR", order: 0 },
  { section: "kpi", row: "DOR", order: 1 },
  { section: "kpi", row: "NTP", order: 2 },
  { section: "kpi/SBR", row: "Russman", order: 1 },
  { section: "kpi/SBR", row: "Accumen Healthcare", order: 0 },
];

test("a block's rows come back in the workbook's order", () => {
  assert.deepEqual(rowsOf(LAYOUT, "In House"), ["Med-Legal", "BayCo", "Pro Ivy"]);
  assert.deepEqual(rowsOf(LAYOUT, "kpi/SBR"), ["Accumen Healthcare", "Russman"]);
  assert.deepEqual(rowsOf(undefined, "In House"), []);
});

test("listed rows keep their place, quiet ones are kept, unlisted ones go last", () => {
  const body = [{ group: "Artheon" }, { group: "Bayco" }, { group: "Med-Legal" }];
  const out = inSheetOrder(body, ["Med-Legal", "BayCo", "Pro Ivy"], (group) => ({ group, blank: true }));
  assert.deepEqual(out.map((r) => r.group), ["Med-Legal", "Bayco", "Pro Ivy", "Artheon"]);
  assert.equal(out[2].blank, true);
  assert.equal(inSheetOrder(body, [], () => null), body);
});

test("settlement rows follow the sheet, and a build with no layout still goes biggest first", () => {
  const rows = [
    { block: "In House", group: "Artheon", bucket: "W1", amount: 900 },
    { block: "In House", group: "Med-Legal", bucket: "W1", amount: 10 },
  ];
  const ordered = pivot(rows, [], "In House", rowsOf(LAYOUT, "In House"));
  assert.deepEqual(ordered.rows.map((r) => r.group),
                   ["Med-Legal", "BayCo", "Pro Ivy", "Artheon", "Total"]);
  assert.equal(ordered.rows.at(-1).W1, 910);
  assert.deepEqual(pivot(rows, [], "In House").rows.map((r) => r.group),
                   ["Artheon", "Med-Legal", "Total"]);
});

test("collections rows follow the sheet too", () => {
  const rows = [{ Group: "Artheon", Week: 1, PT: "BILLING", Payment: 5 },
                { Group: "Russman", Week: 1, PT: "BILLING", Payment: 1 }];
  assert.deepEqual(pivotCollections(rows, ["Russman", "Medvantage"]).rows.map((r) => r.group),
                   ["Russman", "Medvantage", "Artheon", "Total"]);
});

test("Delta Comparison: groups down, each month's three measures across, the year at the end", () => {
  const rows = [
    { Group: "Russman", Month: 1, "Total Settlement": 100, "Pay Received - YES": 80,
      "Pay Received - NO": 20 },
    { Group: "Russman", Month: 3, "Total Settlement": 50, "Pay Received - YES": 50,
      "Pay Received - NO": 0 },
    { Group: "A Miles", Month: 3, "Total Settlement": 10, "Pay Received - YES": 0,
      "Pay Received - NO": 10 },
  ];
  const g = pivotDeltaComparison(rows, { order: ["365 Medical", "A Miles", "Russman"], upTo: 4 });
  assert.deepEqual(g.months, [1, 2, 3, 4]);
  assert.deepEqual(g.rows.map((r) => r.group), ["365 Medical", "A Miles", "Russman", TOTAL]);
  const russman = g.rows[2];
  assert.equal(russman.m1_yes, 80);
  assert.equal(russman._total, 150);
  assert.equal(russman._no, 20);
  const total = g.rows.at(-1);
  assert.equal(total.m3_total, 60);
  assert.equal(total._no, 30);
  assert.deepEqual(pivotDeltaComparison([], { upTo: 4 }).rows, []);
});

test("KPI blocks and their rows follow the workbook", () => {
  const kpi = [
    { block: "NTP", group: "A Miles", value: 3 },
    { block: "SBR", group: "Russman", value: 5698 },
    { block: "SBR", group: "Accumen Healthcare", value: 302 },
    { block: "DOR", group: "Russman", value: 67 },
  ];
  const blocks = kpiBlocks(kpi, "Oct", LAYOUT);
  assert.deepEqual(blocks.map((b) => b.name), ["SBR", "DOR", "NTP"]);
  assert.deepEqual(blocks[0].rows.map((r) => r.group), ["Accumen Healthcare", "Russman", "Total"]);
  assert.equal(blocks[0].total, 6000);
});

test("CP Settled Cases goes across the months on one row", () => {
  const g = cpAcross([{ month: 2, cases: 6, outstanding: 1223.2, settled: 2780.96 },
                      { month: 1, cases: 7, outstanding: 1775.48, settled: 3800 }], "Med-Legal");
  assert.deepEqual(g.months, [1, 2]);
  assert.equal(g.rows[0].group, "Med-Legal");
  assert.equal(g.rows[0].m1_cases, 7);
  assert.equal(g.rows[0]._cases, 13);
  assert.deepEqual(cpAcross([], "Med-Legal").rows, []);
});

test("A to Z sorts the names but leaves the Total and section rows where they are", async () => {
  const { sortAtoZ } = await import("./sort-model.js");
  const fixed = (r) => r.group === TOTAL || Boolean(r._kind);
  const rows = [{ group: "Russman" }, { group: "a Miles" }, { group: "Artheon" },
                { group: "365 Medical" }, { group: TOTAL }];
  assert.deepEqual(sortAtoZ(rows, "group", fixed).map((r) => r.group),
                   ["365 Medical", "a Miles", "Artheon", "Russman", TOTAL]);
  assert.deepEqual(rows.map((r) => r.group)[0], "Russman");          // the input is left alone

  const sections = [{ _kind: "section", group: "Invalid" }, { group: "Open" }, { group: "Closed" },
                    { _kind: "subtotal", group: "Invalid total" },
                    { _kind: "section", group: "Valid" }, { group: "Verified" }, { group: "CIC" },
                    { _kind: "subtotal", group: "Valid total" }, { group: "Grand Total", _kind: "grand" }];
  assert.deepEqual(sortAtoZ(sections, "group", fixed).map((r) => r.group),
                   ["Invalid", "Closed", "Open", "Invalid total",
                    "Valid", "CIC", "Verified", "Valid total", "Grand Total"]);
});
