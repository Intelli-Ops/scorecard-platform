"""Turn the nine located GFS source files into tables.

Same reads as scripts/run_week.py in the .bat pipeline - same sheets, same
header rows, same column subsets - with two differences:

  * nothing is printed. The .bat pipeline announced each file as it went; here
    every read is recorded in a ReadReport the API can serve and the review
    screen can show.
  * no folder layout is assumed. Files arrive already located (see locate.py),
    so this works the same whether they came from an upload or from an
    inputs/<week>/ folder during the golden-master test.

The column subsets are not tidying. Combined Custom Case AR is 240 MB and only
five of its columns are ever used; asking for five instead of all of them is
most of why a run takes seconds rather than minutes.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import time

import fastexcel
import polars as pl

from ..cache import Cache
from ..locate import SourceSet
from ..notes import Note, info, warning
from ..reading import FileRead, timed_reader
from .core.case_ar import gfs_case_ids



@dataclass
class GfsSources:
    owner_ar: pl.DataFrame            # Raw Data + Case AR
    custom_ar: pl.DataFrame           # Closing Order / Validity / Status lookups
    gfs_cases: pl.DataFrame           # which cases count as GFS (from Owner AR)
    providers: pl.DataFrame           # provider -> group map
    delta_sheets: dict[str, pl.DataFrame]
    payments: pl.DataFrame            # Collection High-Level
    hearing_noi: pl.DataFrame         # CP Settled Cases
    sql_doc: pl.DataFrame             # KPI: SBR and DDE
    scorecard: pl.DataFrame | None    # KPI numbers - may legitimately be absent
    # Tuesday's "- comments" Delta copies: Delta source sheet -> the Case Id and
    # Ongoing DOR columns of its own sheet. Empty when they were not uploaded.
    delta_comments: dict[str, pl.DataFrame] = field(default_factory=dict)
    reads: list[FileRead] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return sum(r.rows for r in self.reads)

    @property
    def seconds(self) -> float:
        return sum(r.seconds for r in self.reads)


def read_gfs(sources: SourceSet, rules: dict, cache: Cache | None = None) -> GfsSources:
    if not sources.ok:
        raise FileNotFoundError("; ".join(sources.problems()))

    reads: list[FileRead] = []
    notes: list[Note] = []
    timed = timed_reader(cache, reads)

    # --- the two Case AR files ------------------------------------------
    owner_path = sources.path("owner_case_ar")
    owner_ar = timed("owner_case_ar", "Combined Owner Case AR", owner_path,
                     lambda: fastexcel.read_excel(str(owner_path))
                     .load_sheet("Sheet1", header_row=0).to_polars())

    custom_path = sources.path("custom_case_ar")
    custom_ar = timed("custom_case_ar", "Combined Custom Case AR", custom_path,
                      lambda: fastexcel.read_excel(str(custom_path)).load_sheet(
                          "Sheet1", header_row=0,
                          use_columns=["CASEID", "Closing Order", "Case_Validity",
                                       "FileStatus", "Lien Filed"]).to_polars())

    # --- Supporting File: only the Provider List ------------------------
    # Its 'GFS Cases' sheet is Phase 1 output, so it is rebuilt from the Owner
    # Case AR (same filter as Raw Data) rather than pasted in by hand - the
    # sheet can stay empty.
    sup_path = sources.path("supporting")
    t = time.perf_counter()
    providers = fastexcel.read_excel(str(sup_path)).load_sheet(
        "Provider List", header_row=0).to_polars()
    reads.append(FileRead("supporting", "supporting", "Supporting File",
                          sup_path.name, rows=providers.height,
                          seconds=time.perf_counter() - t))
    gfs_cases = gfs_case_ids(owner_ar, rules)
    notes.append(info("supporting_file_contents",
                      f"{gfs_cases.height:,} GFS cases (from the Owner Case AR), "
                      f"{providers.height} providers",
                      gfs_cases=gfs_cases.height, providers=providers.height))

    # --- the delta workbooks --------------------------------------------
    # Which sheets, and which columns of them, is declared in rules.yml rather
    # than here, so a renamed column is a config change and not a code change.
    books = {"wc": sources.path("delta_wc"), "mlcr": sources.path("delta_mlcr")}
    delta_sheets: dict[str, pl.DataFrame] = {}
    for spec in rules["delta"]["sources"]:
        book = books[spec["workbook"]]
        sheet = spec["sheet"]
        cols = list(spec["columns"].values())
        delta_sheets[sheet] = timed(
            f"delta_{sheet}", sheet, book,
            lambda b=book, s=sheet, c=cols: fastexcel.read_excel(str(b)).load_sheet(
                s, header_row=0, use_columns=c).to_polars(),
            source_key=f"delta_{spec['workbook']}")

    # --- Tuesday: the "- comments" copies, for Ongoing DOR ---------------
    # Optional. Only the key and the two comment columns are read, from each
    # Delta sheet's OWN sheet of its comments workbook (rules.yml
    # delta.comments). Missing is not a failure: the columns stay blank and
    # the review says so.
    ccfg = rules["delta"].get("comments") or {}
    delta_comments: dict[str, pl.DataFrame] = {}
    for src_sheet, (book, in_sheet) in (ccfg.get("sheets") or {}).items():
        path = sources.optional(f"delta_{book}_comments")
        if path is None:
            continue
        delta_comments[src_sheet] = timed(
            f"delta_{book}_comments", f"{in_sheet} (comments)", path,
            lambda p=path, s=in_sheet: fastexcel.read_excel(str(p)).load_sheet(
                s, header_row=0,
                use_columns=[ccfg["key"], *ccfg["columns"]]).to_polars())

    # --- payments, hearing calendar, SQL doc -----------------------------
    pay_path = sources.path("payment_detail")
    payments = timed("payment_detail", "Payment Detail Report", pay_path,
                     lambda: fastexcel.read_excel(str(pay_path)).load_sheet(
                         rules["collections"]["sheet"], header_row=0).to_polars())

    hc_path = sources.path("hearing_calendar")
    hearing_noi = timed("hearing_calendar", "Hearing Calendar", hc_path,
                        lambda: fastexcel.read_excel(str(hc_path)).load_sheet(
                            "NOI, CP Settlements", header_row=0,
                            use_columns=["Hearing Date", "Outstanding",
                                         "Settlement Amount"]).to_polars())

    sql_path = sources.path("document_log")
    sql_doc = timed("document_log", "SQL document log", sql_path,
                    lambda: pl.read_csv(sql_path))

    # --- KPI numbers - optional ------------------------------------------
    # Read with NO header row: the sheet stacks three blocks (GFS, Russman,
    # Others) and the one we want does not start at row 1 - its header is found
    # by its marker instead. Some weeks the email does not arrive in time; that
    # is a fact to report, not a failure, and the blocks it feeds keep last
    # week's figures rather than being zeroed.
    sc_cfg = rules["kpi"].get("scorecard") or {}
    sc_path = sources.optional("kpi_numbers")
    if sc_path is None:
        scorecard = None
        notes.append(warning(
            "kpi_numbers_not_supplied",
            "KPI numbers file not supplied - the blocks it feeds will "
            "keep last week's figures"))
    else:
        scorecard = timed("kpi_numbers", "KPI numbers", sc_path,
                          lambda: fastexcel.read_excel(str(sc_path)).load_sheet(
                              sc_cfg.get("sheet", 0), header_row=None).to_polars())

    return GfsSources(owner_ar=owner_ar, custom_ar=custom_ar, gfs_cases=gfs_cases,
                      providers=providers, delta_sheets=delta_sheets,
                      payments=payments, hearing_noi=hearing_noi, sql_doc=sql_doc,
                      scorecard=scorecard, delta_comments=delta_comments,
                      reads=reads, notes=notes)
