"""GFS: reads the uploaded source files into tables."""
from __future__ import annotations
from dataclasses import dataclass, field

import fastexcel
import polars as pl

from ..cache import Cache
from ..locate import SourceSet
from ..notes import Note, info, warning
from ..reading import FileRead, provider_list, timed_reader
from .core.case_ar import gfs_case_ids


@dataclass
class GfsSources:
    """Each table is None when its file was not uploaded - a partial build."""
    owner_ar: pl.DataFrame | None     # Raw Data + Case AR
    custom_ar: pl.DataFrame | None    # Closing Order / Validity / Status lookups
    gfs_cases: pl.DataFrame | None    # which cases count as GFS (from Owner AR)
    providers: pl.DataFrame           # provider -> group map
    delta_sheets: dict[str, pl.DataFrame]   # only the sheets uploaded
    payments: pl.DataFrame | None     # Collection High-Level
    hearing_noi: pl.DataFrame | None  # CP Settled Cases
    sql_doc: pl.DataFrame | None      # KPI: SBR and DDE
    scorecard: pl.DataFrame | None    # KPI numbers - may legitimately be absent
    delta_comments: dict[str, pl.DataFrame] = field(default_factory=dict)
    reads: list[FileRead] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return sum(r.seconds for r in self.reads)


def read_gfs(sources: SourceSet, rules: dict, cache: Cache | None = None) -> GfsSources:
    reads: list[FileRead] = []
    notes: list[Note] = []
    timed = timed_reader(cache, reads)

    owner_path = sources.optional("owner_case_ar")
    owner_ar = timed("owner_case_ar", "Combined Owner Case AR", owner_path,
                     lambda: fastexcel.read_excel(str(owner_path))
                     .load_sheet("Sheet1", header_row=0).to_polars())

    custom_path = sources.optional("custom_case_ar")
    custom_ar = timed("custom_case_ar", "Combined Custom Case AR", custom_path,
                      lambda: fastexcel.read_excel(str(custom_path)).load_sheet(
                          "Sheet1", header_row=0,
                          use_columns=["CASEID", "Closing Order", "Case_Validity",
                                       "FileStatus", "Lien Filed"]).to_polars())

    providers = provider_list(rules)
    gfs_cases = None if owner_ar is None else gfs_case_ids(owner_ar, rules)
    if gfs_cases is not None:
        notes.append(info("supporting_file_contents",
                          f"{gfs_cases.height:,} GFS cases (from the Owner Case AR), "
                          f"{providers.height} providers",
                          gfs_cases=gfs_cases.height, providers=providers.height))

    books = {"wc": sources.optional("delta_wc"), "mlcr": sources.optional("delta_mlcr")}
    delta_sheets: dict[str, pl.DataFrame] = {}
    for spec in rules["delta"]["sources"]:
        book = books[spec["workbook"]]
        sheet = spec["sheet"]
        cols = list(spec["columns"].values())
        df = timed(
            f"delta_{sheet}", sheet, book,
            lambda b=book, s=sheet, c=cols: fastexcel.read_excel(str(b)).load_sheet(
                s, header_row=0, use_columns=c).to_polars(),
            source_key=f"delta_{spec['workbook']}")
        if df is not None:
            delta_sheets[sheet] = df

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

    pay_path = sources.optional("payment_detail")
    payments = timed("payment_detail", "Payment Detail Report", pay_path,
                     lambda: fastexcel.read_excel(str(pay_path)).load_sheet(
                         rules["collections"]["sheet"], header_row=0).to_polars())

    hc_path = sources.optional("hearing_calendar")
    hearing_noi = timed("hearing_calendar", "Hearing Calendar", hc_path,
                        lambda: fastexcel.read_excel(str(hc_path)).load_sheet(
                            "NOI, CP Settlements", header_row=0,
                            use_columns=["Hearing Date", "Outstanding",
                                         "Settlement Amount"]).to_polars())

    sql_path = sources.optional("document_log")
    sql_doc = timed("document_log", "SQL document log", sql_path,
                    lambda: pl.read_csv(sql_path))

    sc_cfg = rules["kpi"].get("scorecard") or {}
    sc_path = sources.optional("kpi_numbers")
    if sc_path is None:
        scorecard = None
        notes.append(warning(
            "kpi_numbers_not_supplied",
            "KPI numbers file not supplied - the blocks it feeds (DOR, PMR, NTP, "
            "Enforcement Of Agreement, Medical Index, Med Legal) will show no data "
            "this week"))
    else:
        scorecard = timed("kpi_numbers", "KPI numbers", sc_path,
                          lambda: fastexcel.read_excel(str(sc_path)).load_sheet(
                              sc_cfg.get("sheet", 0), header_row=None).to_polars())

    return GfsSources(owner_ar=owner_ar, custom_ar=custom_ar, gfs_cases=gfs_cases,
                      providers=providers, delta_sheets=delta_sheets,
                      payments=payments, hearing_noi=hearing_noi, sql_doc=sql_doc,
                      scorecard=scorecard, delta_comments=delta_comments,
                      reads=reads, notes=notes)
