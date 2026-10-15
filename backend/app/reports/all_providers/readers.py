"""All Providers: reads the uploaded source files into tables."""
from __future__ import annotations
from dataclasses import dataclass, field

import fastexcel
import polars as pl

from ..cache import Cache
from ..locate import SourceSet
from ..notes import Note, info
from ..reading import FileRead, timed_reader


@dataclass
class ApSources:
    owner_ar: pl.DataFrame
    custom_ar: pl.DataFrame
    providers: pl.DataFrame           # provider -> group map
    delta_sheets: dict[str, pl.DataFrame]
    payments: pl.DataFrame
    hearing_noi: pl.DataFrame
    sql_doc: pl.DataFrame
    scorecard: pl.DataFrame | None
    template: object                  # the sheet the KPI layout is read from
    reads: list[FileRead] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)


def read_all_providers(sources: SourceSet, rules: dict,
                       cache: Cache | None = None) -> ApSources:
    if not sources.ok:
        raise FileNotFoundError("; ".join(sources.problems()))

    reads: list[FileRead] = []
    notes: list[Note] = []
    timed = timed_reader(cache, reads)

    owner_path = sources.path("owner_case_ar")
    owner_ar = timed("owner_case_ar", "Combined Owner Case AR", owner_path,
                     lambda: fastexcel.read_excel(str(owner_path))
                     .load_sheet("Sheet1", header_row=0).to_polars())

    custom_path = sources.path("custom_case_ar")
    custom_ar = timed("custom_case_ar", "Combined Custom Case AR", custom_path,
                      lambda: fastexcel.read_excel(str(custom_path)).load_sheet(
                          "Sheet1", header_row=0,
                          use_columns=["CASEID", "Closing Order", "Case_Validity",
                                       "FileStatus"]).to_polars())

    sup_path = sources.path("supporting")
    providers = timed("supporting", "Supporting File", sup_path,
                      lambda: fastexcel.read_excel(str(sup_path)).load_sheet(
                          "Provider List", header_row=0).to_polars())
    notes.append(info(
        "supporting_file_contents",
        f"{providers.height} providers, "
        f"{providers['Provider Group'].n_unique()} groups",
        providers=providers.height,
        groups=int(providers["Provider Group"].n_unique())))

    books = {"wc": sources.path("delta_wc"), "mlcr": sources.path("delta_mlcr")}
    delta_sheets: dict[str, pl.DataFrame] = {}
    for spec in rules["delta"]["sources"]:
        book, sheet = books[spec["workbook"]], spec["sheet"]
        cols = list(spec["columns"].values())
        delta_sheets[sheet] = timed(
            f"delta_{sheet}", sheet, book,
            lambda b=book, s=sheet, c=cols: fastexcel.read_excel(str(b)).load_sheet(
                s, header_row=0, use_columns=c).to_polars(),
            source_key=f"delta_{spec['workbook']}")

    pay_path = sources.path("payment_detail")
    payments = timed("payment_detail", "Payment Detail Report", pay_path,
                     lambda: fastexcel.read_excel(str(pay_path)).load_sheet(
                         rules["collections"]["sheet"], header_row=0).to_polars())

    hc_path = sources.path("hearing_calendar")
    hearing_noi = timed("hearing_calendar", "Hearing Calendar", hc_path,
                        lambda: fastexcel.read_excel(str(hc_path)).load_sheet(
                            "NOI, CP Settlements", header_row=0).to_polars())

    sql_path = sources.path("document_log")
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

    from .workbook import read_sheets
    tpl_path = sources.path("template")
    kpi_sheet_name = rules["template"]["kpi_sheet"]
    template = read_sheets(tpl_path, {kpi_sheet_name})[kpi_sheet_name]
    reads.append(FileRead("template", "template", "Last week's workbook",
                          tpl_path.name, rows=len(template.cells), seconds=0.0))

    return ApSources(owner_ar=owner_ar, custom_ar=custom_ar, providers=providers,
                     delta_sheets=delta_sheets, payments=payments,
                     hearing_noi=hearing_noi, sql_doc=sql_doc,
                     scorecard=scorecard, template=template,
                     reads=reads, notes=notes)
