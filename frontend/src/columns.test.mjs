// Tests for columns.js.
import assert from "node:assert/strict";
import { test } from "node:test";

import { amountPctPair, assemble, col, toneAt, TONES, TOTAL }
  from "./columns.js";

test("figures are centred, labels are left", () => {
  assert.equal(col.money("m", "Amount").align, "center");
  assert.equal(col.pct("p", "Settlement %").align, "center");
  assert.equal(col.count("c", "Cases").align, "center");
  assert.equal(col.label("g", "Group").align, "left");
  assert.equal(col.text("t", "Status").align, "left");
});

test("the row's subject carries the weight", () => {
  assert.equal(col.label("g", "Group").strong, true);
  assert.equal(col.strong("_total", "Year to date").strong, true);
});

test("nothing renders as an em dash, never a bare zero", () => {
  assert.equal(col.money("m", "A").render({}), "-");
  assert.equal(col.money("m", "A").render({ m: 0 }), "-");
  assert.equal(col.count("c", "A").render({}), "-");
  assert.equal(col.pct("p", "A").render({}), "-");
});

test("a real zero per cent is a number, not a dash", () => {
  assert.equal(col.pct("p", "A").render({ p: 0 }), "0.00%");
});

test("money is exact to the cent, never rounded to the dollar", () => {
  assert.match(col.money("m", "A").render({ m: 1234.56 }), /^\$1,234\.56$/);
  assert.match(col.money("m", "A").render({ m: 1234.5 }), /^\$1,234\.50$/);
  assert.match(col.money("m", "A").render({ m: 1234.56 }), /^\$1,234\.56$/);
  assert.match(col.pct("p", "A").render({ p: 0.340538653 }), /^34\.05%$/);
});

test("total columns are bold and carry the total tint", () => {
  const c = col.strong("_total", "Grand Total", { className: "current" });
  assert.equal(c.strong, true);
  assert.equal(c.className, "total-col current");
});

test("extras override the defaults rather than being ignored", () => {
  const c = col.money("m", "A", { align: "right", className: "current" });
  assert.equal(c.align, "right");
  assert.equal(c.className, "current");
});

test("a month pair is two columns under one heading", () => {
  const p = amountPctPair("M8", "Aug");
  assert.equal(p.span.label, "Aug");
  assert.equal(p.span.span, 2);
  assert.equal(p.columns.length, 2);
  assert.deepEqual(p.columns.map((c) => c.key), ["M8", "M8_pct"]);
});

test("the current month's pair is marked on both of its columns", () => {
  const p = amountPctPair("W35", "Wk 35", { current: true });
  assert.equal(p.span.className, "current");
  for (const c of p.columns) assert.equal(c.className, "current");
});

test("spans always cover exactly as many columns as there are", () => {
  const { columns, spans } = assemble(col.label("group", "Group"), [
    amountPctPair("M1", "Jan"),
    amountPctPair("M2", "Feb"),
    { spanLabel: "Grand total", column: col.strong("_total", "Year") },
  ]);
  const covered = spans.reduce((s, g) => s + (g.span ?? 1), 0);
  assert.equal(covered, columns.length);
  assert.equal(columns.length, 6);          // group + 2 + 2 + total
  assert.equal(columns[0].key, "group");
});

test("TOTAL is one spelling, shared", () => {
  assert.equal(TOTAL, "Total");
});

test("no two tiles in a row share an accent", () => {
  const row = Array.from({ length: 5 }, (_, i) => toneAt(i));
  assert.equal(new Set(row).size, 5);
});

test("the palette itself has no duplicates", () => {
  assert.equal(new Set(TONES).size, TONES.length);
});

test("a row longer than the palette wraps rather than running out", () => {
  assert.equal(toneAt(TONES.length), TONES[0]);
  assert.equal(toneAt(TONES.length + 2), TONES[2]);
});
