# Scorecard Platform

A web application that produces the weekly scorecards — **GFS** and
**All Providers** — as a dashboard rather than an Excel workbook.

This is a **separate project**. The existing `.bat` pipelines in
`gfs-automation/` keep running untouched every week; nothing here changes
them. They remain the source of truth until this system is proved against
them.

## Why this exists

The current process produces a 21 MB Excel workbook. That works, but:

- it runs from a batch file on one person's laptop, in a OneDrive folder
- 278,930 rows of Raw Data are hidden inside the file to feed one pivot,
  which is why it is 21 MB and slow to open
- there is no run history, no audit trail visible to anyone else, and no
  way to compare one week against another without opening two workbooks
- the client sees one month per KPI column, never the trend

A dashboard fixes all of those, and — because the deliverable is no longer
a workbook — the pipeline no longer needs to drive a real installed copy
of Excel over COM. That removes the Windows/Office dependency entirely and
the whole thing runs in ordinary Linux containers.

## Two reports, one platform

Both scorecards are built from the **same nine weekly source files**, so a
week is uploaded once and both reports are produced from it.

Their calculation cores are *not* shared. A diff of the two shows 50–90% of
lines differing — they are genuinely different maths. Merging them into one
generic engine would be a large refactor that puts verified numbers at risk,
so each report keeps its own `core/` package and its own `rules.yml`.
Everything around the maths is shared.

## Layout

```
backend/
  app/
    api/          HTTP routes
    db/           models, migrations
    storage/      object storage (chunked upload lands here)
    jobs/         background worker - a run takes ~72s, too long for a request
    reports/
      __init__.py            report registry + the nine weekly source files
      gfs/
        core/                lifted verbatim from gfs/marts/ - DO NOT EDIT casually
        rules.yml            lifted verbatim from config/rules.yml
      all_providers/
        core/                lifted verbatim from ap/marts/
        rules.yml
  tests/
    golden/       golden-master: new output must equal the .bat pipeline's
frontend/         (not started)
docs/
```

## The calculation cores are lifted, not rewritten

`app/reports/*/core/` is a **byte-identical copy** of the mart modules from
the existing pipelines. Those modules import only polars and the standard
library — no file paths, no Excel, no config loading, not a single `print()`
— which is why they moved across without modification.

They encode business rules that were verified cell-by-cell against a
hand-built workbook (see `GFS-AUTOMATION.md`, parts 8 and 9). **Treat them as
audited code.** Changes belong in `rules.yml` wherever possible.

Library versions in `requirements.txt` are pinned exactly to the versions
that produced the verified Week 35 numbers. Do not bump them without
re-running the golden-master test.

## Build order

| Step | | Status |
|---|---|---|
| 0 | Freeze the existing project in git as a reference point | done |
| 1 | New repo and skeleton | done |
| 2 | Lift the calculation cores and rules across | done |
| 3 | Extract `settlement_grids()` / `cp_settled()` out of `run_week.py` | next |
| 4 | Reader layer: uploaded files → dataframes | |
| 5 | **Golden-master test** — reproduce Week 35 exactly | |
| 6 | Replace week folders with object storage + database | |
| 7 | Run results become structured data, not console text | |
| 8 | API, jobs, upload, UI | |

Steps 0–5 carry the whole risk. Once the golden master passes, the rest is
ordinary web work.

## Local development note

This folder currently sits under OneDrive. Before installing dependencies,
either exclude `.venv/` and `node_modules/` from sync or move the project
outside OneDrive — syncing tens of thousands of small files makes everything
slow and occasionally locks files mid-write.
