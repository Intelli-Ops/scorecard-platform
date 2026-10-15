"""Reads cells from an .xlsx file without Excel."""
from __future__ import annotations
from html import unescape
from pathlib import Path
import re
import zipfile

CELL_RE = re.compile(r'<c ([^>]*?)(?:/>|>(.*?)</c>)', re.S)
ROW_RE = re.compile(r'<row [^>]*?r="(\d+)"[^>]*?(?:/>|>(.*?)</row>)', re.S)


def col_num(letters: str) -> int:
    """"B" -> 2, "AA" -> 27."""
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


class Sheet:
    """The cells of one worksheet, as text, addressed by (row, col)."""

    def __init__(self, cells: dict[tuple[int, int], str], name: str):
        self.cells = cells
        self.name = name


def read_sheets(path: Path, wanted: set[str], max_row: int = 400,
                max_col: int = 80) -> dict[str, Sheet]:
    """The named worksheets of an .xlsx, as {sheet name: rows}."""
    out: dict[str, Sheet] = {}
    with zipfile.ZipFile(path) as z:            # closed, or Windows keeps the file locked
        sst: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            x = z.read("xl/sharedStrings.xml").decode("utf8")
            for m in re.finditer(r"<si>(.*?)</si>", x, re.S):
                sst.append("".join(re.findall(r"<t[^>]*>(.*?)</t>", m.group(1), re.S)))
        wbx = z.read("xl/workbook.xml").decode("utf8")
        rels = z.read("xl/_rels/workbook.xml.rels").decode("utf8")
        target = {m.group(1): m.group(2) for m in
                  re.finditer(r'<Relationship Id="([^"]+)"[^>]*Target="([^"]+)"', rels)}

        for m in re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="([^"]+)"', wbx):
            name = unescape(m.group(1))
            if name not in wanted:
                continue
            part = "xl/" + target[m.group(2)].lstrip("/")
            out[name] = Sheet(_cells(z.read(part).decode("utf8"), sst, max_row, max_col),
                              name)
    missing = wanted - set(out)
    if missing:
        raise KeyError(f"{path.name} has no sheet named: {sorted(missing)}")
    return out


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
                out[(r, c)] = unescape(sst[int(v.group(1))])
            elif t == "inlineStr":
                out[(r, c)] = unescape(
                    "".join(re.findall(r"<t[^>]*>(.*?)</t>", guts, re.S)))
            elif v:
                out[(r, c)] = v.group(1)
    return out
