// The dropdown's list arithmetic, without React.

// Options as Picker takes them (plain strings, { value, label }, or { group, options })
// laid out as one list: group headings and choices, each choice numbered in `n`.
// `placeholder`, when given, is a first choice whose value is "".
export function flatten(options, placeholder) {
  const items = [];
  let n = 0;
  const add = (o) => {
    const opt = typeof o === "string" ? { value: o, label: o } : o;
    items.push({ kind: "option", value: opt.value, label: String(opt.label), n: n++ });
  };
  if (placeholder) add({ value: "", label: placeholder });
  for (const o of options ?? []) {
    if (o && typeof o === "object" && o.group) {
      items.push({ kind: "group", label: o.group });
      for (const i of o.options ?? []) add(i);
    } else add(o);
  }
  return items;
}

// The items whose label contains `query` (any case), each group heading kept only while
// one of its choices is. Choices are numbered afresh so the arrow keys skip what's hidden.
export function narrow(items, query) {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  const out = [];
  let heading = null;
  let n = 0;
  for (const it of items) {
    if (it.kind === "group") { heading = it; continue; }
    if (!it.label.toLowerCase().includes(q)) continue;
    if (heading) { out.push(heading); heading = null; }
    out.push({ ...it, n: n++ });
  }
  return out;
}

export const choices = (items) => items.filter((it) => it.kind === "option");

// The choice to land on when a letter is typed: the next one after `from` whose label
// starts with `typed`, wrapping round; -1 when none does.
export function typeahead(items, typed, from) {
  const list = choices(items);
  const t = typed.toLowerCase();
  for (let k = 1; k <= list.length; k++) {
    const it = list[(from + k) % list.length];
    if (it.label.toLowerCase().startsWith(t)) return it.n;
  }
  return -1;
}

// A tick-box list's values with `v` ticked or unticked, kept in the list's own order.
export function toggle(values, v, items) {
  const set = new Set(values ?? []);
  if (set.has(v)) set.delete(v); else set.add(v);
  return choices(items).map((o) => o.value).filter((x) => set.has(x));
}

// What a tick-box pill says: nothing yet, the one choice, or the first and how many more.
export function summary(values, items, prompt = "") {
  const labels = choices(items).filter((o) => (values ?? []).includes(o.value))
    .map((o) => o.label);
  if (!labels.length) return prompt;
  return labels.length === 1 ? labels[0] : `${labels[0]} +${labels.length - 1}`;
}
