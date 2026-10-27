"""All Providers: reads the uploaded source files into tables."""
from __future__ import annotations
from dataclasses import dataclass, field

import fastexcel
import polars as pl

from ..cache import Cache
from ..locate import SourceSet
from ..notes import Note, info
from ..reading import FileRead, provider_list, timed_reader


@dataclass
class ApSources:
    """Each table is None when its file was not uploaded - a partial build."""
    owner_ar: pl.DataFrame | None
    custom_ar: pl.DataFrame | None
    providers: pl.DataFrame           # provider -> group map
    delta_sheets: dict[str, pl.DataFrame]   # only the sheets uploaded
    payments: pl.DataFrame | None
    hearing_noi: pl.DataFrame | None
    sql_doc: pl.DataFrame | None
    scorecard: pl.DataFrame | None
    reads: list[FileRead] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)


def read_all_providers(sources: SourceSet, rules: dict,
                       cache: Cache | None = None) -> ApSources:
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
                                       "FileStatus"]).to_polars())

    providers = provider_list(rules)
    notes.append(info(
        "supporting_file_contents",
        f"{providers.height} providers, "
        f"{providers['Provider Group'].n_unique()} groups",
        providers=providers.height,
        groups=int(providers["Provider Group"].n_unique())))

    books = {"wc": sources.optional("delta_wc"), "mlcr": sources.optional("delta_mlcr")}
    delta_sheets: dict[str, pl.DataFrame] = {}
    for spec in rules["delta"]["sources"]:
        book, sheet = books[spec["workbook"]], spec["sheet"]
        cols = list(spec["columns"].values())
        df = timed(
            f"delta_{sheet}", sheet, book,
            lambda b=book, s=sheet, c=cols: fastexcel.read_excel(str(b)).load_sheet(
                s, header_row=0, use_columns=c).to_polars(),
            source_key=f"delta_{spec['workbook']}")
        if df is not None:
            delta_sheets[sheet] = df

    pay_path = sources.optional("payment_detail")
    payments = timed("payment_detail", "Payment Detail Report", pay_path,
                     lambda: fastexcel.read_excel(str(pay_path)).load_sheet(
                         rules["collections"]["sheet"], header_row=0).to_polars())

    hc_path = sources.optional("hearing_calendar")
    hearing_noi = timed("hearing_calendar", "Hearing Calendar", hc_path,
                        lambda: fastexcel.read_excel(str(hc_path)).load_sheet(
                            "NOI, CP Settlements", header_row=0).to_polars())

    sql_path = sources.optional("document_log")
    sql_doc = timed("document_log", "SQL document log", sql_path,
                    lambda: pl.read_csv(sql_path))

    sc_cfg = rules["kpi"].get("scorecard") or {}
    sc_path = sources.optional("kpi_numbers")
    if sc_path is None:
        scorecard = None
        notes.append(info("kpi_numbers_not_supplied",
                          "KPI / litigation numbers file not supplied"))
    else:
        scorecard = timed("kpi_numbers", "KPI numbers", sc_path,
                          lambda: fastexcel.read_excel(str(sc_path)).load_sheet(
                              sc_cfg.get("sheet", 0), header_row=None).to_polars())

    return ApSources(owner_ar=owner_ar, custom_ar=custom_ar, providers=providers,
                     delta_sheets=delta_sheets, payments=payments,
                     hearing_noi=hearing_noi, sql_doc=sql_doc,
                     scorecard=scorecard,
                     reads=reads, notes=notes)
