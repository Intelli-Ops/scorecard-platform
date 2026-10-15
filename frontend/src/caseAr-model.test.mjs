// Tests for caseAr-model.js.
import assert from "node:assert/strict";
import { test } from "node:test";

import { GRAND_TOTAL, sectionCaseAr, sectionClass } from "./caseAr-model.js";

const kinds = { Case_Validity: "text", "Closing Order": "text",
                "# Of Cases": "int", BILLED: "float" };
const gfs = {
  columns: ["Case_Validity", "Closing Order", "# Of Cases", "BILLED"], kinds,
  rows: [
    { Case_Validity: "Invalid", "Closing Order": "CIC Pending", "# Of Cases": 2, BILLED: 10.25 },
    { Case_Validity: "Invalid", "Closing Order": "Dismissal", "# Of Cases": 1, BILLED: 5.5 },
    { Case_Validity: "Valid", "Closing Order": "CIC Pending", "# Of Cases": 4, BILLED: 100.01 },
    { Case_Validity: GRAND_TOTAL, "Closing Order": "", "# Of Cases": 7, BILLED: 115.76 },
  ],
};

test("Invalid then Valid, each a heading, its rows and a subtotal, then the Grand Total", () => {
  const t = sectionCaseAr(gfs);
  assert.deepEqual(t.columns, ["Closing Order", "# Of Cases", "BILLED"]);
  assert.deepEqual(t.rows.map((r) => r._kind ?? "row"),
    ["section", "row", "row", "subtotal", "section", "row", "subtotal", "grand"]);
  const invalid = t.rows[3];
  assert.equal(invalid["Closing Order"], "Invalid total");
  assert.equal(invalid["# Of Cases"], 3);
  assert.equal(invalid.BILLED, 15.75);
  assert.equal(t.rows.at(-1)["Closing Order"], GRAND_TOTAL);
});

test("a Case AR without a Validity column is left flat", () => {
  const ap = { columns: ["File Status", "Count of Cases"],
               kinds: { "File Status": "text", "Count of Cases": "int" },
               rows: [{ "File Status": "ACTIVE", "Count of Cases": 3 }] };
  const t = sectionCaseAr(ap);
  assert.equal(t.sectioned, false);
  assert.equal(t.rows, ap.rows);
});

test("section class names", () => {
  assert.equal(sectionClass("Invalid"), "sec-invalid");
  assert.equal(sectionClass("Valid"), "sec-valid");
});
