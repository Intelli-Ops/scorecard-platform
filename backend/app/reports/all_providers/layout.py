"""Read the template workbook and work out where everything sits.

The GFS automation hardcodes its sheet layout in config - row 9 is A Miles, column
17 is the first week, and so on. That works there because the GFS template is a
fixed shape that is reused week after week.

The All Providers workbook is not that shape. Its Settlement grids and its
Collections grid live on the SAME sheet at DIFFERENT column offsets, its provider
list runs to 33 rows and changes when a provider is taken on, and it gains a week
column every week of the month. Any row/column map typed into a config file here
would be wrong within a fortnight, and wrong quietly.

So the layout is read out of the template instead, every run:

    * blocks are found by their label in column B ("Settlements (In House)")
    * group rows are read off column B between the block header and its Total row
    * month columns are found by their header text ("January 2026")
    * week columns are what sits between the last month and the month Total
    * the Collections week blocks are found by their "BILLING" markers

Nothing here opens Excel. An .xlsx is a zip of XML and the header rows are small,
so this is a few milliseconds even against a 38 MB workbook.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import re
import zipfile

MONTHS = ["january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december"]
CELL_RE = re.compile(r'<c ([^>]*?)(?:/>|>(.*?)</c>)', re.S)
ROW_RE = re.compile(r'<row [^>]*?r="(\d+)"[^>]*?(?:/>|>(.*?)</row>)', re.S)


def col_letters(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_num(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _norm(s: object) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def month_of(label: object) -> int | None:
    """'January 2026' -> 1. Also matches 'August Total' and 'Aug-26'."""
    t = _norm(label)
    if not t:
        return None
    for i, m in enumerate(MONTHS, start=1):
        if t.startswith(m) or t.startswith(m[:3] + " ") or t.startswith(m[:3] + "-"):
            return i
    return None


class Sheet:
    """The cells of one worksheet, as text, addressed by (row, col)."""

    def __init__(self, cells: dict[tuple[int, int], str], name: str):
        self.cells = cells
        self.name = name

    def get(self, r: int, c: int) -> str:
        return self.cells.get((r, c), "")

    def row(self, r: int) -> dict[int, str]:
        return {c: v for (rr, c), v in self.cells.items() if rr == r}

    def find_in_column(self, col: int, label: str) -> int | None:
        want = _norm(label)
        for (r, c), v in sorted(self.cells.items()):
            if c == col and _norm(v) == want:
                return r
        return None


def read_sheets(path: Path, wanted: set[str], max_row: int = 400,
                max_col: int = 80) -> dict[str, Sheet]:
    """Pull the named worksheets out of an .xlsx as {sheet name: Sheet}.

    Only the top-left corner of each sheet is read (400 x 80 by default), which is
    all the layout lives in and keeps the 250 MB Raw Data sheet from being parsed.
    """
    z = zipfile.ZipFile(path)
    sst: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        x = z.read("xl/sharedStrings.xml").decode("utf8")
        for m in re.finditer(r"<si>(.*?)</si>", x, re.S):
            sst.append("".join(re.findall(r"<t[^>]*>(.*?)</t>", m.group(1), re.S)))
    wbx = z.read("xl/workbook.xml").decode("utf8")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf8")
    target = {m.group(1): m.group(2) for m in
              re.finditer(r'<Relationship Id="([^"]+)"[^>]*Target="([^"]+)"', rels)}

    out: dict[str, Sheet] = {}
    for m in re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="([^"]+)"', wbx):
        name = _unescape(m.group(1))
        if name not in wanted:
            continue
        part = "xl/" + target[m.group(2)].lstrip("/")
        out[name] = Sheet(_cells(z.read(part).decode("utf8"), sst, max_row, max_col),
                          name)
    missing = wanted - set(out)
    if missing:
        raise KeyError(f"{path.name} has no sheet named: {sorted(missing)}")
    return out


def _unescape(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&lt;", "<")
             .replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))


def _cells(xml: str, sst: list[str], max_row: int, max_col: int
           ) -> dict[tuple[int, int], str]:
    if "<sheetData" not in xml:
        return {}
    body = xml[xml.index("<sheetData"):xml.index("</sheetData>")]
    out: dict[tuple[int, int], str] = {}
    for rm in ROW_RE.finditer(body):
        r = int(rm.group(1))
        if r > max_row:
            break
        for cm in CELL_RE.finditer(rm.group(2) or ""):
            attrs, guts = cm.group(1), cm.group(2) or ""
            ref = re.search(r'r="([A-Z]+)(\d+)"', attrs)
            if not ref:
                continue
            c = col_num(ref.group(1))
            if c > max_col:
                continue
            t = re.search(r't="([^"]+)"', attrs)
            t = t.group(1) if t else "n"
            v = re.search(r"<v>(.*?)</v>", guts, re.S)
            if t == "s" and v:
                out[(r, c)] = _unescape(sst[int(v.group(1))])
            elif t == "inlineStr":
                out[(r, c)] = _unescape(
                    "".join(re.findall(r"<t[^>]*>(.*?)</t>", guts, re.S)))
            elif v:
                out[(r, c)] = v.group(1)
    return out


# ---------------------------------------------------------------------------


def key(s: object) -> str:
    """Match a Provider Group to a sheet row label ignoring case and punctuation.

    The sheets are typed by hand and do not spell the Provider List back exactly:
    the Settlement grids say "BayCo" where the Provider List says "Bayco", and the
    Collections grid says "Bayco". Matching on the letters and digits alone makes
    all three the same row and keeps a cosmetic edit from silently dropping a
    provider out of the client's totals.
    """
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


class RowIndex:
    """group label -> sheet row, matched on `key()`."""

    def _index(self) -> dict[str, int]:
        return {key(label): row for label, row in self.rows.items()}

    def row_for(self, group: str) -> int | None:
        return self._index().get(key(group))

    def missing(self, groups) -> list[str]:
        idx = self._index()
        return sorted({g for g in groups if key(g) not in idx})


@dataclass
class GridBlock(RowIndex):
    """One rectangular block on the grid sheet: rows are groups, columns are time."""
    name: str
    header_row: int
    rows: dict[str, int] = field(default_factory=dict)   # group label -> sheet row
    total_row: int | None = None
    month_cols: dict[int, int] = field(default_factory=dict)   # month no -> column
    week_cols: list[int] = field(default_factory=list)
    month_total_col: int | None = None
    grand_total_col: int | None = None
    current_month: int | None = None       # the month the week columns belong to

    @property
    def first_row(self) -> int:
        return min(self.rows.values())

    @property
    def last_row(self) -> int:
        return max([self.total_row or 0] + list(self.rows.values()))


@dataclass
class CollectionsBlock(GridBlock):
    """Collections: each week is five columns (four payment types plus a total)."""
    week_first_cols: list[int] = field(default_factory=list)
    week_width: int = 5


@dataclass
class CpBlock(RowIndex):
    """CP Settled Cases: three columns per month (count, outstanding, settlement)."""
    header_row: int
    rows: dict[str, int] = field(default_factory=dict)
    month_cols: dict[int, int] = field(default_factory=dict)
    grand_total_col: int | None = None


@dataclass
class Layout:
    in_house: GridBlock
    in_house_pace: GridBlock
    board: GridBlock
    board_pace: GridBlock
    cp: CpBlock
    collections: CollectionsBlock
    collections_pace: CollectionsBlock
    notes: list[str] = field(default_factory=list)

    @property
    def groups(self) -> list[str]:
        """Every group label the sheet has a row for, anywhere."""
        seen: dict[str, None] = {}
        for b in (self.in_house, self.board, self.collections):
            for g in b.rows:
                seen.setdefault(g, None)
        return list(seen)


TOTAL_LABELS = {"total", "grand total"}


def _group_rows(sh: Sheet, start: int, stop: int, col: int = 2
                ) -> tuple[dict[str, int], int | None]:
    """Read group labels down column B until the block's Total row."""
    rows: dict[str, int] = {}
    total = None
    for r in range(start, stop):
        label = sh.get(r, col).strip()
        if not label:
            if rows:
                break
            continue
        if _norm(label) in TOTAL_LABELS:
            total = r
            break
        rows[label] = r
    return rows, total


def _time_columns(header: dict[int, str]) -> tuple[dict[int, int], list[int],
                                                   int | None, int | None, int | None]:
    """Split a settlement header row into months, weeks, month total, grand total.

    The header reads: January 2026 .. July 2026, August 2026, (blanks), Total,
    Grand Total. The month labelled last is the one split into weeks, so every
    column from it up to (but not including) Total is a week column.
    """
    months: dict[int, int] = {}
    total_col = grand_col = None
    for c, v in sorted(header.items()):
        t = _norm(v)
        if t == "grand total":
            grand_col = c
        elif t == "total":
            total_col = c
        else:
            m = month_of(v)
            if m:
                months[m] = c
    if not months:
        return {}, [], total_col, grand_col, None
    current = max(months)
    first_week = months.pop(current)
    end = total_col if total_col else (grand_col if grand_col else first_week + 1)
    weeks = list(range(first_week, end))
    return months, weeks, total_col, grand_col, current


def _read_grid_block(sh: Sheet, label: str, next_row: int) -> GridBlock:
    start = sh.find_in_column(2, label)
    if start is None:
        raise KeyError(f"'{sh.name}' has no block labelled {label!r} in column B")
    # The header sits on the block's own row when the label shares it (In House),
    # otherwise on the row below (Board). Whichever carries a month name wins.
    header_row = start if any(month_of(v) for v in sh.row(start).values()) else start + 1
    rows, total = _group_rows(sh, header_row + 1, next_row)
    months, weeks, tot_c, grand_c, cur = _time_columns(sh.row(header_row))
    return GridBlock(label, header_row, rows, total, months, weeks, tot_c, grand_c, cur)


def _read_pace_block(sh: Sheet, label: str, next_row: int, grid: GridBlock) -> GridBlock:
    """A pace block has no month columns of its own - only the week columns."""
    start = sh.find_in_column(2, label)
    if start is None:
        raise KeyError(f"'{sh.name}' has no block labelled {label!r} in column B")
    header_row = start + 1                       # holds just the month name
    rows, total = _group_rows(sh, header_row + 1, next_row)
    return GridBlock(label, header_row, rows, total, {}, list(grid.week_cols),
                     None, None, grid.current_month)


def _read_collections(sh: Sheet, label: str, next_row: int) -> CollectionsBlock:
    start = sh.find_in_column(2, label)
    if start is None:
        raise KeyError(f"'{sh.name}' has no block labelled {label!r} in column B")
    header_row = start + 1
    header = sh.row(header_row)
    firsts = sorted(c for c, v in header.items() if _norm(v) == "billing")
    width = (firsts[1] - firsts[0]) if len(firsts) > 1 else 5
    months: dict[int, int] = {}
    grand = total = None
    for c, v in sorted(header.items()):
        if firsts and c >= firsts[0]:
            if _norm(v) == "grand total":
                grand = c
            elif month_of(v) and _norm(v).endswith("total"):
                total = c
            continue
        m = month_of(v)
        if m:
            months[m] = c
    cur = month_of(sh.get(header_row, total)) if total else None
    weeks = [c for f in firsts for c in range(f, f + width)]
    rows, tot_row = _group_rows(sh, header_row + 1, next_row)
    return CollectionsBlock(label, header_row, rows, tot_row, months, weeks,
                            total, grand, cur, week_first_cols=firsts, week_width=width)


def _read_collections_pace(sh: Sheet, label: str, next_row: int,
                           grid: CollectionsBlock) -> CollectionsBlock:
    start = sh.find_in_column(2, label)
    if start is None:
        raise KeyError(f"'{sh.name}' has no block labelled {label!r} in column B")
    rows, total = _group_rows(sh, start + 2, next_row)
    return CollectionsBlock(label, start + 1, rows, total, {},
                            list(grid.week_cols), None, None, grid.current_month,
                            week_first_cols=list(grid.week_first_cols),
                            week_width=grid.week_width)


def _read_cp(sh: Sheet, label: str, next_row: int) -> CpBlock:
    start = sh.find_in_column(2, label)
    if start is None:
        raise KeyError(f"'{sh.name}' has no block labelled {label!r} in column B")
    months, grand = {}, None
    for c, v in sorted(sh.row(start).items()):
        if _norm(v) == "grand total":
            grand = c
        else:
            m = month_of(v)
            if m:
                months[m] = c
    rows, _ = _group_rows(sh, start + 2, next_row)
    return CpBlock(start, rows, months, grand)


def read_layout(template: Path, rules: dict) -> Layout:
    """Work out the grid sheet's shape from the template itself."""
    t = rules["template"]
    sheets = read_sheets(template, {t["grid_sheet"]})
    sh = sheets[t["grid_sheet"]]
    b = t["blocks"]

    # Where each block stops is where the next one starts.
    starts = {}
    for key, label in b.items():
        r = sh.find_in_column(2, label)
        if r is None:
            raise KeyError(f"'{sh.name}' has no block labelled {label!r} in column B")
        starts[key] = r
    order = sorted(starts, key=lambda k: starts[k])
    stop = {}
    for i, key in enumerate(order):
        stop[key] = starts[order[i + 1]] if i + 1 < len(order) else 10_000

    in_house = _read_grid_block(sh, b["in_house"], stop["in_house"])
    board = _read_grid_block(sh, b["board"], stop["board"])
    coll = _read_collections(sh, b["collections"], stop["collections"])
    lay = Layout(
        in_house=in_house,
        in_house_pace=_read_pace_block(sh, b["in_house_pace"],
                                       stop["in_house_pace"], in_house),
        board=board,
        board_pace=_read_pace_block(sh, b["board_pace"], stop["board_pace"], board),
        cp=_read_cp(sh, b["cp"], stop["cp"]),
        collections=coll,
        collections_pace=_read_collections_pace(sh, b["collections_pace"],
                                                stop["collections_pace"], coll),
    )
    return lay


@dataclass
class DeltaLayout(RowIndex):
    """Delta Comparison-2026: three columns per month, groups down the side.

    Unlike the grid sheet this one never grows - it is laid out for all twelve
    months of the year from the start, with Total Settlements / Pay Received YES /
    Pay Received NO columns at the far right.
    """
    header_row: int
    month_row: int
    rows: dict[str, int] = field(default_factory=dict)
    total_row: int | None = None
    month_cols: dict[int, int] = field(default_factory=dict)   # month -> first of 3
    total_cols: list[int] = field(default_factory=list)        # the three at the end


def read_delta_layout(template: Path, rules: dict) -> DeltaLayout:
    name = rules["template"]["delta_sheet"]
    sh = read_sheets(template, {name})[name]
    month_row = sh.find_in_column(2, "Month")
    header_row = sh.find_in_column(2, "PAPER")
    if month_row is None or header_row is None:
        raise KeyError(f"'{name}' is missing its 'Month' or 'PAPER' row in column B")
    months: dict[int, int] = {}
    totals: list[int] = []
    for c, v in sorted(sh.row(month_row).items()):
        if c < 3:
            continue
        try:                       # the month row holds Excel serial dates
            serial = int(float(v))
        except (TypeError, ValueError):
            if _norm(v).startswith("total"):
                totals.append(c)
            continue
        import datetime as _dt
        months[(_dt.date(1899, 12, 30) + _dt.timedelta(days=serial)).month] = c
    rows, total = _group_rows(sh, header_row + 1, 10_000)
    return DeltaLayout(header_row, month_row, rows, total, months, totals)


def describe(lay: Layout) -> str:
    def one(b) -> str:
        wk = f"{col_letters(b.week_cols[0])}..{col_letters(b.week_cols[-1])}" \
             if b.week_cols else "-"
        return (f"   {b.name:<32} rows {b.first_row}-{b.last_row} "
                f"({len(b.rows)} groups)  months {len(b.month_cols)}  weeks {wk}")
    lines = [one(lay.in_house), one(lay.board), one(lay.collections)]
    lines.append(f"   {'CP Settled Cases':<32} rows "
                 f"{min(lay.cp.rows.values(), default=0)}-"
                 f"{max(lay.cp.rows.values(), default=0)}  "
                 f"months {len(lay.cp.month_cols)}")
    return "\n".join(lines)
