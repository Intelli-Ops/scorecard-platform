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

Both scorecards are built from nine weekly source files. **Seven are shared** -
uploaded once, used by both. **The two Case AR files are not.** Case ARs are
regenerated daily, and the reports go out on different days: GFS on Tuesday
uses Tuesday's Case ARs, All Providers on Thursday uses Thursday's. The
filenames are identical, so a week stores both copies tagged by report.

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
    config.py     every path in the project
    db/           models + session (SQLite locally, Postgres in production)
    storage/      content-addressed object store
    service/      ingest uploads, execute runs, read results back
  tests/
    golden/       golden-master: new output must equal the .bat pipeline's
frontend/         (not started - step 8b)
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
| 3 | Extract `settlement_grids()` / `cp_settled()` out of `run_week.py` | done |
| 4 | Reader layer: uploaded files → dataframes | |
| 5 | **Golden-master test** — reproduce Week 35 exactly | |
| 6 | Replace week folders with object storage + database | done |
| 7 | Run results become structured data, not console text | done |
| 8a | API, background builds, upload | done |
| 8b | Browser screens | next |

Steps 0–5 carry the whole risk. Once the golden master passes, the rest is
ordinary web work.

## Local development note

This folder currently sits under OneDrive. Before installing dependencies,
either exclude `.venv/` and `node_modules/` from sync or move the project
outside OneDrive — syncing tens of thousands of small files makes everything
slow and occasionally locks files mid-write.


## Golden master

`backend/tests/golden/` proves this project reproduces the .bat pipeline.
Run it with the legacy project present:

```
cd backend && python -m pytest tests/golden -v
```

Week 35 passes on all four tables. Two tolerances are applied on purpose and
are documented in the test: row order is not compared (polars does not promise
a stable order, and the .bat pipeline's own order varies run to run), and money
is compared to the cent (summing 278,930 values in a different order moves the
15th significant digit - the largest gap seen is 0.0000008 on 299,693,534.89).

The proof currently rests on ONE week: inputs/2026-W34/ holds no usable data.
Week 36 will give a second, independent confirmation for free - keep its
marts/<week>/*.parquet after the .bat run.


## A week is rows, not folders

`inputs/2026-W35/` becomes an `upload` row per file, with the bytes themselves
in the object store under the SHA-256 of their own content. That hash is the
upload check (chunked uploads are verified against it), the de-duplicator (the
seven shared files and an unchanged Thursday Case AR are stored once) and the
audit anchor (a run in December still points at the exact bytes it read).

A run records what it read, how long each file took, what it produced, and
every STEP 4 warning - so the questions the folders could not answer (who ran
it, when, what did it warn about, which upload did it actually use) now have
answers.

Verified end to end on the real Week 35 inputs: 9 of 12 files in the folder
classified, 3 delivered workbooks correctly ignored, and the four tables built
from the database still match the golden master.


## Warnings are data now

The .bat pipeline's STEP 4 messages are kept word for word, but each one now
carries a stable `code`, a `severity` and the numbers behind the sentence. That
is what lets the review screen answer questions the console never could:

  * is this warning NEW this week, or does it appear every week?
  * has the count moved - 900 dropped rows last week, 112,960 this week?
  * has one that used to appear stopped appearing?
  * plot one number across every week that reported it

`severity` is assigned by what it costs the reader. Dropped rows are routine;
the count is the signal. A KPI block with no source is `action` - a figure the
client will look at is missing and someone has to decide whether to send it.

A run finishes in `review`, not `done`. Approving it is a separate, recorded
act by a person.


## Running it

```
cd backend
../.venv/Scripts/python -m uvicorn app.main:app --reload
```

http://127.0.0.1:8000/docs is the API, generated from the routes.

| | |
|---|---|
| `GET /api/reports` | the two scorecards and the files each needs |
| `GET /api/weeks`, `GET /api/weeks/{week}` | what has been uploaded, what is missing |
| `POST /api/weeks/{week}/uploads` | receive files (`for_report` for the Case ARs) |
| `POST /api/runs?report=&week=` | queue a build, returns immediately |
| `GET /api/runs/{id}` | the review payload |
| `POST /api/runs/{id}/approve?by=` | sign off |
| `GET /api/runs/{id}/figures/{name}` | settlement, cp_settled, kpi - the dashboard |
| `GET /api/runs/{id}/tables/{name}` | a page of raw_data, delta_comparison, ... |

Builds run on one background thread, one at a time on purpose: two concurrent
runs would each hold a quarter-gigabyte spreadsheet in memory for no gain,
since the reports go out on different days.

Verified over HTTP against the real Week 35 files: 385 MB uploaded, three
delivered workbooks refused, build queued in 23 ms and finished in 67 s, all
four tables reproduced, and 236 dashboard records served.
