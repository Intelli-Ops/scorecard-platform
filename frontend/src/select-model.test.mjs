// Tests for select-model.js.
import assert from "node:assert/strict";
import { test } from "node:test";

import { choices, flatten, narrow, typeahead } from "./select-model.js";

const OPTIONS = [
  "All",
  { group: "Uploads", options: [{ value: "upload", label: "File uploaded" },
                                { value: "delete", label: "File deleted" }] },
  { group: "Sign in", options: [{ value: "login", label: "Signed in" }] },
];

test("strings, pairs and groups become one numbered list", () => {
  const items = flatten(OPTIONS, "Everything");
  assert.deepEqual(items.map((i) => i.kind === "group" ? `# ${i.label}` : `${i.n} ${i.label}`),
                   ["0 Everything", "1 All", "# Uploads", "2 File uploaded", "3 File deleted",
                    "# Sign in", "4 Signed in"]);
  assert.equal(items[0].value, "");
  assert.equal(choices(items).length, 5);
});

test("a search keeps matching choices and their headings, numbered afresh", () => {
  const items = narrow(flatten(OPTIONS), "file");
  assert.deepEqual(items.map((i) => i.label), ["Uploads", "File uploaded", "File deleted"]);
  assert.deepEqual(choices(items).map((i) => i.n), [0, 1]);
  assert.equal(narrow(flatten(OPTIONS), "  ").length, 6);
  assert.deepEqual(narrow(flatten(OPTIONS), "zzz"), []);
});

test("typing a letter jumps to the next choice starting with it, wrapping round", () => {
  const items = flatten(["Artheon", "Bayco", "A Miles", "Russman"]);
  assert.equal(typeahead(items, "a", 0), 2);
  assert.equal(typeahead(items, "a", 2), 0);
  assert.equal(typeahead(items, "ru", 0), 3);
  assert.equal(typeahead(items, "x", 0), -1);
});

test("ticking keeps the list's order; the pill names the first and counts the rest", async () => {
  const { summary, toggle } = await import("./select-model.js");
  const items = flatten(["Artheon", "Bayco", "Russman"]);
  let v = toggle([], "Russman", items);
  v = toggle(v, "Artheon", items);
  assert.deepEqual(v, ["Artheon", "Russman"]);
  assert.deepEqual(toggle(v, "Artheon", items), ["Russman"]);
  assert.equal(summary([], items, "(All)"), "(All)");
  assert.equal(summary(["Bayco"], items), "Bayco");
  assert.equal(summary(v, items), "Artheon +1");
});
