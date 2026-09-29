# Scorecard Platform: architecture and code guide

This is the technical companion to the other two documents:

| Document | For | Answers |
|---|---|---|
| [README.md](README.md) | Anyone running the app | How do I install it, start it, and build a week? |
| [HOW-IT-WORKS.md](HOW-IT-WORKS.md) | The people who use it | What do the screens mean, and what do I do each week? |
| **ARCHITECTURE.md** (this file) | Developers changing it | What is each part, why is it there, and how do the parts fit? |

Each section explains a component with a real example: the data it takes, what
it does, and why it was built that way rather than the obvious alternative.

---

## Contents

1. [The system at a glance](#1-the-system-at-a-glance)
2. [The stack, and why each piece](#2-the-stack-and-why-each-piece)
3. [The repository, folder by folder](#3-the-repository-folder-by-folder)
4. [The life of one week, end to end](#4-the-life-of-one-week-end-to-end)
5. [Backend: the HTTP layer (`app/api`)](#5-backend-the-http-layer-appapi)
6. [Backend: the application logic (`app/service`)](#6-backend-the-application-logic-appservice)
7. [Backend: the calculations (`app/reports`)](#7-backend-the-calculations-appreports)
8. [Backend: database, files and jobs](#8-backend-database-files-and-jobs)
9. [Security, layer by layer](#9-security-layer-by-layer)
10. [Frontend](#10-frontend)
11. [Which endpoint feeds which screen](#11-which-endpoint-feeds-which-screen)
12. [Configuration](#12-configuration)
13. [Tests](#13-tests)
14. [How to extend it](#14-how-to-extend-it)
15. [Conventions](#15-conventions)
16. [Glossary](#16-glossary)

---

## 1. The system at a glance

```
 Browser (React)                    Server (one Python process)                     Disk
 ───────────────                    ───────────────────────────                     ────
                     /api/...  ┌──────────────────────────────────────────┐
  pages/*.jsx  ───── fetch ──► │ api/        HTTP: who may call what        │
  api.js                       │   deps.py   signed_in / current_user /     │
  hooks.js (useLoad)           │             require_admin                  │
                               │ service/    what the app does              │
                               │   ingest    classify + store uploads   ────┼──► data/objects/  (uploaded files,
                               │   runner    build a run, delete, approve   │                   by SHA-256)
                               │   review    the review screen              │
                               │   auth      accounts, sessions             │
                               │   audit     the activity log               │
                               │ jobs/worker one background build thread ───┼──► data/results/  (parquet tables
                               │ reports/    THE CALCULATIONS               │                   a run produced)
                               │   gfs/  all_providers/  (pure polars)  ────┼──► data/cache/    (parsed Excel,
                               │ db/         SQLAlchemy models          ────┼──► scorecard.db     per week)
                               └──────────────────────────────────────────┘     (or MySQL)
```

Three ideas shape everything else:

1. **The calculations are separate from the web code.** `app/reports/` knows
   nothing about HTTP, users or the database. It takes DataFrames in and gives
   DataFrames and dictionaries back. That is what lets the golden-master tests
   compare its output with the old Excel pipeline cell by cell.
2. **A run is recorded, never recalculated.** A build stores its tables as
   parquet and its figures and warnings in the database. Opening a scorecard
   from March reads what March produced; it does not rerun March's maths
   against today's rules.
3. **Files are addressed by their content.** An upload is stored under the
   SHA-256 of its bytes. The same file uploaded twice is stored once, and a run
   can always say exactly which bytes it read.

---

## 2. The stack, and why each piece

### Backend

| Tool | What it does here | Why this one |
|---|---|---|
| **Python 3.11** | The language | The calculations were already Python (the gfs-automation `.bat` pipeline) and had been verified against the delivered workbooks. Porting them to anything else would have meant verifying them again. |
| **FastAPI** | HTTP routes, request validation, OpenAPI docs | Type-annotated routes validate input for free: `run_id: int` refuses `"abc"` with a 422 before our code runs. Dependencies (`Depends(require_admin)`) put access checks in one place. |
| **Uvicorn** | Runs FastAPI | The standard server for it. `--reload` restarts it on every save during development. |
| **Polars** | Every table calculation | A week's Raw Data is 278,930 rows. Polars handles that in well under a second and its expressions (`pl.col("Paid").sum()`) read like the steps they replace. |
| **fastexcel** (calamine) | Reads `.xlsx` / `.xlsb` | About 2 s for the 240 MB Custom Case AR, where openpyxl took about 35 s. It can also read only the named columns (`use_columns=[...]`), which is most of the saving. |
| **PyArrow / Parquet** | Stores produced tables and the parse cache | Columnar, compressed, typed. A page of Raw Data is read without loading the other 278,880 rows (`pl.scan_parquet(...).slice(...)`). |
| **SQLAlchemy 2** | Database access | One set of models for SQLite on a laptop and MySQL on the server. |
| **SQLite / MySQL 8** | Accounts, uploads, runs, figures, the activity log | SQLite needs nothing installed; MySQL is what the server runs. `SCORECARD_DB` switches between them. |
| **PyMySQL** | The MySQL driver | Pure Python: it installs the same way on Windows and Ubuntu, with nothing to compile. |
| **PyYAML** | Reads `rules.yml` | Business rules (holidays, which settlement types count, aging buckets) are data, not code, so they are changed without touching Python. |
| **pytest** | Tests | Plain functions and fixtures; `TestClient` drives the real API. |

What is deliberately **not** used:

- **No queue server** (Redis, Celery). Builds run on one background thread in
  the web process (`jobs/worker.py`). A build that dies can be started again;
  its inputs are still stored. See [section 8](#jobsworkerpy-one-build-at-a-time).
- **No ORM migrations tool** (Alembic) yet. `db/migrate.py` only ever adds
  missing columns, which has been all the schema has needed.
- **No password library.** PBKDF2 is in Python's standard library, so there is
  no dependency to keep patched.

### Frontend

| Tool | What it does here | Why this one |
|---|---|---|
| **React 19** | The screens | Components map onto the workbook's parts: one component per tab. |
| **React Router 7** | Pages and URLs | `/runs/12` is a link someone can paste in Teams. |
| **Vite 8** | Dev server and production build | Instant reloads, and its proxy sends `/api/...` to the backend, so the page and the API share one origin. |
| **oxlint** | Linting | Fast, and catches the React hook mistakes that matter (`rules-of-hooks`). |
| **node:test** | Tests for the table-shaping code | The `*-model.js` files are pure functions; they run under plain Node with no browser and no bundler. |

No UI kit and no chart library: the tables are drawn by one `DataTable`
component and styled in `theme.css`, so every table looks the same by
construction.

---

## 3. The repository, folder by folder

```
scorecard-platform/
├── README.md                 install, run, use
├── HOW-IT-WORKS.md           plain-English guide for users
├── ARCHITECTURE.md           this file
├── backend/
│   ├── requirements.txt      pinned calculation libraries + platform libraries
│   ├── pytest.ini
│   ├── app/
│   │   ├── main.py           creates the FastAPI app: routers, CORS, security headers, start-up
│   │   ├── config.py         every path and setting, from environment variables
│   │   ├── manage.py         server-side commands: create-admin, reset-password, copy-db…
│   │   ├── api/              HTTP layer - thin
│   │   ├── service/          what the app does - accounts, uploads, runs, the log
│   │   ├── reports/          the calculations - no HTTP, no database
│   │   ├── db/               tables, the session, schema upgrades
│   │   ├── storage/          the content-addressed file store
│   │   └── jobs/             the background build thread
│   └── tests/                pytest; golden/ compares with the old pipeline
├── frontend/
│   ├── index.html
│   ├── vite.config.js        dev server + /api proxy
│   ├── public/favicon.svg
│   └── src/
│       ├── main.jsx          mounts <App/> inside the router and the auth provider
│       ├── App.jsx           sidebar, sign-in gate, routes
│       ├── api.js            every call to the backend
│       ├── auth.jsx          who is signed in
│       ├── hooks.js          useLoad (fetching), useDismiss (popovers)
│       ├── pages/            one file per screen
│       ├── settlement.jsx … kpi.jsx, caseAr.jsx, delta.jsx    one file per dashboard tab
│       ├── *-model.js        pure table-shaping functions, tested in *.test.mjs
│       ├── components.jsx    DataTable, Card, Stat, filters, Loading, ErrorBox
│       ├── ui.jsx            TableCard, Stats - compositions of the above
│       ├── buttons.jsx       Button, ConfirmButton, DeleteButton
│       ├── icons.jsx         every icon, drawn as SVG
│       ├── columns.js        how a column of a given kind is drawn
│       ├── format.js         money, %, counts, dates, week labels
│       ├── reports.js        the two reports' short names
│       ├── activity-period.js   day / week / month ranges for deleting activity
│       └── theme.css
└── data/                     NOT in git: database, uploads, results, cache
```

**Why three backend layers?** Each has one reason to change:

| Layer | Changes when… | Example |
|---|---|---|
| `api/` | the URL, the input shape, or who may call it changes | making `/api/runs` admin-only |
| `service/` | how the app behaves changes | "a deleted run takes its unused uploads with it" |
| `reports/` | the business calculation changes | "Med-Legal counts F&F settlements only" |

A rule written in `api/` would be skipped by anything that is not an HTTP
request (the background worker, `manage.py`, a test). A rule written in
`reports/` would drag the database into code that has to stay testable against
Excel. So routes stay a few lines each and call `service/`.

---

## 4. The life of one week, end to end

Follow **2026-W38** (Mon 14 – Sun 20 Sep) through the whole system.

### 4.1 Upload

The admin drops `Master Settlement & Collection Delta WC 09.21.2026.xlsb` onto
the Upload page.

1. **Browser.** `api.upload()` in `api.js` sends a multipart POST to
   `/api/weeks/2026-W38/uploads` with XHR (not `fetch`) so it can show a
   progress bar.
2. **Access.** `week_routes.upload` depends on `require_admin`, which depends on
   `current_user`, which depends on `signed_in`. A viewer is refused with 403
   and the attempt is logged.
3. **Input check.** `valid_week("2026-W38")` confirms the label is a real ISO
   week. It becomes part of a folder path later, so `"../.."` must never get
   through.
4. **Stream to disk.** `_save_upload` copies the file to a temporary folder in
   1 MB chunks and stops at `SCORECARD_MAX_UPLOAD_MB` (413 if over).
5. **Classify.** `service/ingest.classify()` asks each `SourceFile` in the
   registry whether the name matches:

   ```python
   SourceFile("delta_wc", ("delta wc",), excludes=("comment",))
   # "master settlement & collection delta wc 09.21.2026.xlsb"
   #   contains "delta wc"   -> yes
   #   contains "comment"    -> no
   #   suffix .xlsb in exts  -> yes      => delta_wc
   ```

6. **Store.** `FileStore.put()` hashes the bytes while copying them, then
   renames the copy to `data/objects/3f/3f9a…c2.xlsb`. If that address already
   exists, the upload is marked `already_held` and nothing is written.
7. **Record.** An `Upload` row: week, `source_key="delta_wc"`,
   `report_key=None` (shared by both reports), the hash and the uploader's email.
8. **Log.** `audit.record("upload.files", …)` after the database session has
   committed.

The response carries the week's new status: which files each report has and
which it still needs. The Build button turns on when nothing required is missing.

### 4.2 Build

The admin presses **Build** for GFS.

1. `POST /api/runs?report=gfs&week=2026-W38` → `run_routes.start_run`.
2. Under a lock, it checks nothing is already building that report and week,
   and that `week_status` says it is ready.
3. `worker.submit()` inserts a `Run` row with status `pending` and puts
   `(run_id, "gfs", "2026-W38", None)` on an in-memory queue. The request
   returns at once with `{"run_id": 12, "status": "pending"}`.
4. The worker thread takes the job and calls `runner.execute()`:

```
runner.execute(run 12)
 ├─ source_set()          latest upload per source_key for GFS + W38 → file paths
 ├─ load_rules("gfs")     rules.yml, parsed once and copied
 ├─ _apply_working_days() the month's working days: entered, or the calendar's
 ├─ read_gfs()            reads each Excel sheet through the parse cache
 ├─ gfs.pipeline.run()    the calculations → RunResult
 ├─ RunInput rows         which upload each source came from, rows read, seconds
 ├─ RunTable rows         raw_data, case_ar, delta_comparison, collections → parquet
 ├─ RunFigure rows        settlement grids, KPI blocks, pace… flattened to records
 ├─ RunNote rows          what the review screen shows
 └─ status = "review"
```

If anything raises, the run is marked `failed` with the error, in a session
of its own so the rollback cannot undo the "failed".

### 4.3 Review and approve

The browser polls `GET /api/runs/12` every 1.5 s until the status is no longer
`pending` or `running`. `service/review.review()` then builds the review
screen: each note compared with the same report's previous week ("new this
week", "changed", "resolved"), table row counts against last week, and the
input files with their hashes.

**Approve** (`POST /api/runs/12/approve`) records who and when. Only an
approved run is visible to viewers.

### 4.4 Read

A viewer opens **This week**. `GET /api/scorecards/current` returns, per report
the viewer may read, the latest approved run. The dashboard then fetches that
run's figures and tables (see [section 11](#11-which-endpoint-feeds-which-screen)).
Nothing is recalculated. Raw Data is paged 50 rows at a time from its parquet
file.

---

## 5. Backend: the HTTP layer (`app/api`)

Every route is a few lines: check input, open a database session, call
`service/`, record the action in the activity log, return a dict. FastAPI turns
the dict into JSON.

### `deps.py`: who is asking

Three dependencies, each building on the last:

| Dependency | Passes when | Otherwise |
|---|---|---|
| `signed_in` | the `Authorization: Bearer <token>` header names a live session of an active, approved account | 401 → the browser goes to the sign-in page |
| `current_user` | `signed_in`, and the account is not holding a temporary password | 403 with `{"code": "password_change_required"}` → the browser shows the change-password screen |
| `require_admin` | `current_user`, and the role is admin or system admin | 403, and the attempt is logged as `admin.denied` |

They are applied to **whole routers**, not remembered route by route:

```python
router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
```

A route that needs the user object as well asks for it again
(`user=Depends(require_admin)`). FastAPI runs each dependency once per request,
so the check is not repeated.

`valid_week()` also lives here: a week label must match `2026-W38` and be a
week that exists in that year. 2026 has a week 53; 2027 does not.

### The four routers

| File | Prefix | Guard | Holds |
|---|---|---|---|
| `auth_routes.py` | `/api/auth` | none (how you get a token) | sign-up, sign-in, sign-out, the form rules |
| `auth_routes.py` | `/api/me` | `signed_in` | your profile, password, sessions, activity |
| `week_routes.py` | `/api` | `current_user` (+ admin per route) | reports, weeks, uploads, the month's working days |
| `run_routes.py` | `/api` | `current_user` (+ admin per route) | builds, the current scorecard, runs, approvals, figures, tables, CSV |
| `admin_routes.py` | `/api/admin` | `require_admin` | accounts, the activity log, alerts, deleting activity |

`/api/me` needs only `signed_in` on purpose: someone holding a temporary
password must still reach the form that replaces it.

### Patterns worth knowing

**Log after commit, not inside the session.** A failed sign-in raises; if the
log row were written in the same session, the rollback would delete it. So
the route lets the session commit, then calls `audit.record`, which opens a
session of its own:

```python
with session() as s:
    try:
        user, token = auth.sign_in(s, ...)
    except auth.LoginRefused as e:
        refused = e          # let the session commit the failed-login counter
if refused is not None:
    audit.record("auth.login", ..., outcome="failure")
    raise HTTPException(401, str(refused))
```

**One shape for every account action.** `admin_routes._change()` loads the
target, applies the change, and logs either the success or the refusal. No
account action can forget the log.

**404 rather than 403 for runs a viewer may not read** (`run_routes._readable`).
A viewer has no business learning which run ids exist.

**Plain `def`, not `async def`, for anything that blocks.** FastAPI runs a
plain `def` on a worker thread. The upload route copies and hashes hundreds of
megabytes; as `async def` it stalled every other request while it did.

---

## 6. Backend: the application logic (`app/service`)

| Module | Responsibility |
|---|---|
| `ingest.py` | Classify uploaded files, store them, record `Upload` rows; work out what a week has and is missing |
| `runner.py` | Execute a build; read produced tables back; approve, unapprove, delete a run or a week |
| `review.py` | The review screen, the previous-week comparison, run history |
| `figures.py` | Flatten sheet-shaped results (grids keyed by `(group, bucket)`) into records |
| `case_ar_view.py` | Rebuild the Case AR pivot from Raw Data for the filters chosen on screen |
| `auth.py` | Accounts, password hashing, lockout, sessions, the admin rules |
| `audit.py` | Write, search, export and delete activity-log rows |
| `detect.py` | Read the log for alerts: password guessing, new addresses, bulk exports… |
| `ratelimit.py` | Per-address and per-account budgets for failed attempts |
| `csvsafe.py` | Keep spreadsheet formulas out of CSV exports |

### `ingest.py`

**Which upload does a report use?** The newest one per `source_key`, with one
rule that matters more than any other: the two **Case AR** files are uploaded
per report, because GFS is mailed on Tuesday with Tuesday's copy and All
Providers on Thursday with Thursday's. The filenames are identical.

```python
# Upload rows for 2026-W38, newest first:
#   owner_case_ar  report_key="all_providers"  (Thursday)
#   owner_case_ar  report_key="gfs"            (Tuesday)
#   delta_wc       report_key=None             (shared)
latest_uploads(s, get("gfs"), "2026-W38")
# -> {"owner_case_ar": <Tuesday's>, "delta_wc": <shared>, ...}
```

A Case AR uploaded without saying which report it is for is refused rather
than guessed. Nothing inside the file would ever reveal a wrong guess.

`week_status()` reads the week's uploads **once** and lets each report pick
its files from that list. It used to query once per source per report (19
queries per week, repeated for every week in the list).

### `runner.py`

Besides `execute()` (above):

- **`table_page(run, name, offset, limit)`** reads one page of a produced table
  lazily. Only the page is decoded, and the row count comes from the `RunTable`
  row.
- **`column_kinds(schema)`** returns `"float" | "int" | "text"` per column. It
  is sent with every table so the browser formats a whole column one way. It
  once guessed per cell and put "$3,071" beside a bare "614".
- **`delete(run)` reference-counts everything.** A parquet result is removed
  only when no other `RunTable` points at its hash. An upload goes only when no
  other run read it, and its blob goes only when no other `Upload` row names
  it. Delete the GFS run and All Providers keeps the shared files it needs.
- **`delete_week(week)`** removes the week's runs, then every upload, then the
  week's parse cache (`data/cache/<week>/`), which is client data in another
  format.

### `review.py`

```python
_key(code, detail) == (code, detail.get("block"), detail.get("provider"))
```

Notes are matched to last week's by that key, so two "new provider" notes stay
distinct. The review then says, per note: `new this week`, `changed` (with the
numbers that moved), `same as last week`, or `resolved since last week`.
`needs_attention` is true when there is any **action** note, or any
non-info note that is new this week.

### `auth.py`

- **Hashing.** PBKDF2-HMAC-SHA256, 16-byte random salt, 600,000 iterations,
  stored as `pbkdf2_sha256$600000$<salt>$<hash>`. The iteration count is
  stored with each hash, so raising it later needs no migration: an older hash
  is replaced the next time its owner signs in (`needs_rehash`).
- **Same answer for a wrong email and a wrong password**, and the same time
  taken: an unknown email still runs a dummy hash (`_burn_time`).
- **Lockout.** Five wrong passwords in a row lock the account for 15 minutes.
- **Sessions** are random 32-byte tokens. The database stores only their
  SHA-256, so a copy of the database cannot be used to sign in. Sessions last
  14 days. "Last seen" is written at most every 5 minutes, not on every request.
- **Who manages whom** (`manages()`): any admin manages viewers; only a system
  admin manages admins; nobody else touches a system admin. Nobody changes
  their own account from the Users screen. `permissions()` sends the result
  with each row, so the screen offers exactly the buttons the server accepts.

### `audit.py`, `detect.py`

`record()` never raises. A broken log must not break the app, so a failed
write is reported on the server's error output and the request carries on.

`detect.alerts()` works alerts out of the log when they are asked for, rather
than storing them. The log stays the only record, and changing a threshold
changes every alert, past ones included:

| Alert | Raised when |
|---|---|
| `password_guessing` | 5+ wrong passwords for one email |
| `spraying` | one IP fails against 3+ different emails |
| `locked` | an account was locked |
| `new_address` | a good sign-in from an IP that account has not used in 90 days |
| `out_of_hours` | a sign-in outside `SCORECARD_WORK_HOURS` |
| `bulk_export` | 10+ table exports by one person within an hour |
| `denied` | a non-admin tried an admin action |
| `deletions` | runs, weeks or activity were deleted |

### `ratelimit.py`, `csvsafe.py`

```python
LOGIN_FAILURES    = (20, 15 * 60)   # wrong sign-ins from one IP
SIGNUPS           = (10, 60 * 60)   # new accounts from one IP
PASSWORD_FAILURES = (10, 15 * 60)   # wrong "current password" on one account
```

Kept in memory: the app is one process, and a restart forgetting the counts
only ever errs towards letting someone in.

`csvsafe.cell("=HYPERLINK(...)")` returns `"'=HYPERLINK(...)"`. Excel shows
the text and runs nothing. `"-12.5"` is left alone because it is a number.

---

## 7. Backend: the calculations (`app/reports`)

```
reports/
├── __init__.py        the registry: the two reports, their input files, load_rules()
├── locate.py          SourceSet (found / missing files); _matches(); locate_dirs() for tests
├── cache.py           ParquetCache: parse an Excel sheet once per week
├── reading.py         FileRead + timed_reader(): every sheet read is timed and counted
├── common.py          i64, excel_weeknum, norm, find_row - shared by both reports
├── period.py          the month and its weeks, from the week label
├── pacing.py          run-rate projection
├── notes.py           Note(code, severity, message, detail)
├── review_notes.py    the checks both reports end with
├── gfs/               readers.py, pipeline.py, rules.yml, core/{case_ar,delta,settlement,collections,kpi}.py
└── all_providers/     readers.py, pipeline.py, rules.yml, workbook.py, core/{case_ar,delta,collections,kpi}.py
```

### Why two separate pipelines

GFS and All Providers look alike, but diffing them shows 50–90% of lines
differing. For example, GFS filters to live GFS settlements and rewrites
Partial Paid amounts; All Providers keeps every provider and totals the year.
One parameterised engine would be a maze of `if report == "gfs"`. So each
report keeps its own `core/` and `rules.yml`, and only what is genuinely the
same is shared (`common.py`, `period.py`, `pacing.py`, `review_notes.py`).

### The registry (`__init__.py`)

```python
REPORTS["gfs"].sources
# SHARED_SOURCES   delta_wc, delta_mlcr, payment_detail, supporting,
#                  hearing_calendar, document_log, kpi_numbers (optional)
# CASE_AR_SOURCES  owner_case_ar, custom_case_ar          (per report)
# extra_sources    delta_wc_comments, delta_mlcr_comments (GFS, optional)
```

`load_rules(key)` parses `rules.yml` once (cached on the file's modified time)
and returns a **deep copy** each time. A build writes the month's working days
into its copy, and that must not leak into the next request.

### Reading (`readers.py`, `cache.py`, `reading.py`)

```python
timed = timed_reader(cache, reads)
owner_ar = timed("owner_case_ar", "Combined Owner Case AR", path,
                 lambda: fastexcel.read_excel(str(path)).load_sheet("Sheet1").to_polars())
```

Two things happen around every read:

- **The cache.** `ParquetCache` stores the parsed sheet as
  `data/cache/<week>/<report>/<key>-<sha prefix>-<size>-<mtime>.parquet`. A
  rebuild reads the 240 MB Case AR in 0.1 s instead of a minute. A corrected
  upload has a different hash, so it is always read fresh.
- **The record.** A `FileRead` notes the rows and seconds. The run stores them
  on `RunInput`, and the review screen shows them.

### The calendar (`period.py`)

A Mon–Fri week belongs to the month of its **Wednesday**:

```
2026-W36  Mon 31 Aug – Fri 4 Sep   → September, week 1 (shown 1–4 Sep; 31 Aug counts in August)
2026-W40  Mon 28 Sep – Fri 2 Oct   → September, week 5 (28–30 Sep); 1–2 Oct join October week 1
```

`reporting_period("2026-W38", holidays)` returns a `Period`: year 2026, month
9, the month's weeks, `weeks_so_far=3`, and the last day counted (Sun 20 Sep;
nothing dated later is counted even if the files already contain it).

### Pacing (`pacing.py`)

The sheet's own formula, `=SUM(J9,K9)/8*21`:

```
pace = month-to-date ÷ working days elapsed × working days in the month

$40,000 settled by the end of week 2, 8 working days gone, 21 in the month
  → 40,000 ÷ 8 × 21 = $105,000
```

Working days are weekdays not listed under `holidays` in `rules.yml`, unless an
admin entered a different count for the month on the Upload page
(`MonthSetting`). At month end elapsed equals the month's days, and the pace
equals the actual total.

### GFS, step by step (`gfs/pipeline.run`)

| Step | Function | What it does |
|---|---|---|
| Raw Data | `core/case_ar.build_raw_data` | Owner Case AR, filtered to GFS owners and case types, joined to the Custom Case AR for Closing Order and Validity |
| Case AR | `core/case_ar.build_case_ar` | Validity × Closing Order pivot of Raw Data |
| Delta | `core/delta.combine_delta` | WC Delta + Med-Legal Delta + IMR Delta onto 15 shared columns, matched **by name** (the three sheets spell the same field differently); Med-Legal keeps F&F only |
| | `core/delta.build_delta` | live GFS settlements only: drop inactive providers, non-GFS, closed; rewrite Partial Paid amounts; join Custom Case AR; age buckets |
| | `core/delta.attach_comments` | Tuesday: Ongoing DOR Status / Details by Case Id from the "- comments" copies (below) |
| Collections | `core/collections.build_collections` | Payment Detail by group, week and payment type |
| Settlement | `core/settlement.settlement_grids` | In House / Board amounts and % by group, past months and this month's weeks |
| Pace | `pacing.pace_grid` | the two Pace blocks, from the same grids |
| KPI | `core/kpi.build_kpi_sql`, `build_kpi_scorecard` | SQL document log counts + the KPI numbers file |
| Notes | `review_notes.review_notes`, `comment_notes` | new providers, missing data, duplicate case ids, DOR matches |

**Tuesday comments**, as an example of how a rule is carried through. Each
Delta row takes its comment from its **own** sheet of the comments copy:

```
Delta row: Case_ID 1234, _source_sheet "WC Delta"
  → look up Case Id 1234 in "Delta WC … - comments.xlsb", sheet "WC Delta"
Delta row: Case_ID 1234, _source_sheet "Med-Legal Delta"
  → look up in "Delta MLCR … - comments.xlsb", sheet "Med-Legal Delta"
Delta row from "IMR Delta"
  → left blank (that sheet has no comment columns)
```

Without the files, the two columns are still there but blank. They are never
carried over from last week.

### All Providers: what is different

- No "GFS" filters: every provider in the Provider List counts.
- **Its KPI rows are read out of last week's delivered workbook**
  (`TEMPLATE_SOURCE`, read by `workbook.read_sheets`). The provider list on
  that sheet grows when a provider is taken on, and a row map typed into config
  would be wrong within a fortnight.
- Its Delta Comparison is a finished grid (group × month × paid yes/no), not a
  row table.

### `rules.yml`

Every threshold and list lives there, never in Python:

```yaml
holidays:
  - 2026-01-01   # New Year
  - 2026-05-25   # Memorial Day (U.S.)
delta:
  keep_settlement_types:
    Med-Legal Delta: [F&F]
  aging_buckets: [[30, "1-30"], [60, "31-60"], [90, "61-90"]]
  comments:
    key: Case Id
    columns: [Ongoing DOR Status, Ongoing DOR Details]
```

Changing a rule changes future builds only. Built runs keep what they
produced.

### Notes

A `Note` is `code` (stable across weeks, so it can be compared), `severity`
(`action` > `warning` > `info`), `message` (the old pipeline's wording) and
`detail` (the numbers behind the sentence):

```python
warning("delta_comments_missing",
        "No '- comments' copy for Med-Legal Delta was uploaded - ...",
        block="Med-Legal Delta")
```

`service/review.SECTIONS` places each code in a review card (New providers /
No data / Duplicates / Other).

---

## 8. Backend: database, files and jobs

### `db/models.py`: the tables

| Table | One row is | Key columns |
|---|---|---|
| `user_account` | an account | email (unique), apd_id (unique), password_hash, role, report_access, pending, is_active, must_change_password, failed_logins, locked_until |
| `user_session` | a signed-in browser | token (SHA-256 of the real token), expires_at, revoked, ip, user_agent, last_seen_at |
| `upload` | one received file | week, report_key (NULL = shared), source_key, filename, sha256, size_bytes, uploaded_by |
| `run` | one build | report_key, week, status, as_of, error, approved_by/at, working_days(+source) |
| `run_input` | which upload a run read | run_id, upload_id, rows_read, seconds |
| `run_table` | a produced table | run_id, name, rows, columns, sha256 of its parquet |
| `run_figure` | sheet-shaped results as JSON records | run_id, name (`settlement`, `kpi`…), data |
| `run_note` | a review note | run_id, seq, code, severity, text, detail |
| `month_setting` | working days entered for a month | month (`2026-09`), working_days, set_by/at |
| `activity_log` | one recorded action | at, user_id, email, action, outcome, target, detail, ip, user_agent |

A run's status moves:

```
pending ──► running ──► review ──► approved
                 │                    │
                 └──► failed          └──► review   (unapprove)
```

**`UtcDateTime`**: neither SQLite nor MySQL stores a time zone. Times are
stored as naive UTC and returned as aware UTC, so a sign-in at 09:14 UTC is
never shown to the browser as 09:14 local.

**`activity_log` has no foreign key to the account**, on purpose. A failed
sign-in may name no account, and a deleted account's history must survive.
The email is copied in as it was at the time.

### `db/migrate.py`, `db/session.py`

- `add_missing_columns()` compares each table with its model and adds what is
  missing. It never drops or retypes anything, so it is safe on real data and
  harmless to run twice.
- `protect_activity_log()` installs a trigger that refuses any **UPDATE** on
  the activity log. Rows can be deleted (by a system admin, and the deletion is
  itself logged), but never edited.
- `session()` is a context manager: commit on success, rollback on any
  exception, always close. Every service function takes the session as an
  argument instead of opening its own, so a route's work commits or fails as
  one unit.

### `storage/files.py`: the content-addressed store

```
put("Delta WC 09.21.2026.xlsb")
  → hash while copying to data/objects/tmpXXXX.part
  → sha256 = 3f9a…c2
  → rename to data/objects/3f/3f9a…c2.xlsb   (or keep the existing one: deduplicated)
```

- The first two characters are a folder, because a flat folder of tens of
  thousands of files is slow to list on Windows.
- The extension is kept, because the Excel reader picks its parser by it.
- `remove()` is only ever called once no database row names the hash any more.

### `jobs/worker.py`: one build at a time

A build reads about 385 MB and holds a quarter-gigabyte sheet in memory.
Two at once would double that and write the same week's cache. So there is one
thread and one queue. `recover()` runs at start-up and marks builds a previous
process never finished as `failed`, with a reason, so they do not spin forever.

### `manage.py`

```powershell
python -m app.manage create-admin you@appedology.com APD-1234   # first system admin
python -m app.manage reset-password someone@appedology.com       # prints a temporary password
python -m app.manage protect-log --as "mysql://root:...@host/scorecard"
python -m app.manage copy-db "sqlite:///C:/dev/scorecard-platform/data/scorecard.db"
```

---

## 9. Security, layer by layer

| Threat | Defence | Where |
|---|---|---|
| Someone signs up with a colleague's email | Accounts wait for an admin's approval | `auth.sign_up`, Users screen |
| Password guessing at one account | 5 wrong → locked 15 min; logged; alert | `auth.sign_in`, `detect` |
| One address trying many accounts, or locking people out | 20 failures per IP per 15 min → 429 | `ratelimit`, `auth_routes.login` |
| Mass sign-ups (each costs CPU to hash) | 10 per IP per hour | `ratelimit` |
| An open session used to guess the password | 10 wrong "current password" per 15 min | `auth_routes.change_password` |
| Learning which emails have accounts by timing | Same message, dummy hash for unknown emails | `auth._burn_time` |
| A stolen database dump used to sign in | Only token hashes stored; PBKDF2 for passwords | `models.Session`, `auth` |
| A viewer reading drafts or other reports | 404 unless the run is approved and the report is granted | `run_routes._readable` |
| A non-admin calling admin routes | `require_admin` on the router; denials logged | `deps`, `admin_routes` |
| Editing the security record | Database trigger refuses UPDATE on `activity_log` | `migrate` |
| Formulas in exported CSV run in Excel | Leading apostrophe on risky text cells | `csvsafe` |
| Path tricks through the week label | `valid_week` before any path is built | `deps` |
| A huge upload filling the disk | per-file size limit, 413 | `week_routes._save_upload` |
| A browser caching client figures | `Cache-Control: no-store` on every response | `main.security_headers` |
| Clickjacking, MIME sniffing | `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy` | `main.security_headers` |
| Oversized input | Length limits on every sign-in and profile field | `auth_routes` models |

Still open, and listed so nobody assumes otherwise:

- The token is kept in `localStorage`. An httpOnly cookie would keep it away
  from any script on the page. That needs the page and the API on one domain
  behind nginx.
- `/docs` is on unless `SCORECARD_API_DOCS=0`. Turn it off on the server.
- The Vite dev server is for development. Serve `npm run build` output from
  nginx for anyone else.

---

## 10. Frontend

### Start-up and the gates (`main.jsx`, `auth.jsx`, `App.jsx`)

```
main.jsx:  <BrowserRouter><AuthProvider><App/></AuthProvider></BrowserRouter>

App:
  checking?                 → "Signing you in…"   (AuthProvider is calling /api/auth/me)
  no user?                  → <SignIn/>
  must_change_password?     → <ChangePassword/>   (nothing else is reachable)
  otherwise                 → sidebar + routes; admin routes exist only for admins
```

Hiding admin pages is for tidiness only. The API refuses anyway, so a missed
page cannot leak anything.

### `api.js`: every call to the backend

One `json()` helper adds the token, turns error bodies into `Error`s with
`.status` and `.detail`, and handles two cases globally:

- **401**: the token is dead. It is dropped and the page reloads to sign-in.
- **403 `password_change_required`**: it tells `AuthProvider` to show the
  change-password screen.

Downloads use `fetch` + a blob, because a plain `<a href>` cannot send the
`Authorization` header.

### `hooks.js`: `useLoad`

Every screen needs the same few steps: fetch, ignore a late answer for an
out-of-date filter, keep the error, and fetch again after an action. `useLoad`
does them once:

```jsx
const { data: runs, error, setError, reload } =
  useLoad(() => api.runs(report || undefined), [report]);

const remove = async (run) => {
  try { await api.deleteRun(run.id); await reload(); } catch (e) { setError(e); }
};
```

- `deps` works like `useEffect`'s: change `report` and it fetches again.
- `{ keep: true }` keeps the last answer on screen while the next one loads.
  The Case AR pivot uses it so the table does not blank out on every filter.
- `reload()` fetches in place without clearing the screen, and never throws.

`useDismiss` closes a popover or confirmation on an outside click or Escape.

### Pages

| Route | Page | Who | What it does |
|---|---|---|---|
| `/scorecard` | `Current.jsx` | everyone | The latest approved scorecard per report, who approved it, and whether a newer week is waiting |
| `/profile` | `Profile.jsx` | everyone | Name, password, signed-in devices, your recent activity |
| `/upload` | `Weeks.jsx` | admins | Drop files, see what each report still needs, set working days, Build, delete a week |
| `/runs` | `Runs.jsx` | admins | 12 weeks of builds, grouped by week |
| `/runs/:id` | `Review.jsx` | admins | The review: new providers, no data, duplicates; Approve / Unapprove |
| `/dashboard/:id` | `Dashboard.jsx` | admins | Any run's scorecard |
| `/admin/users` | `AdminUsers.jsx` | admins | Approve, roles, scorecard access, reset, disable, delete |
| `/admin/activity` | `AdminActivity.jsx` | admins | Alerts, the filtered log, CSV export; system admins can also delete events |

### The dashboard

`Dashboard.ScorecardView` is shared by `/dashboard/:id` and `/scorecard`; only
the heading differs. One tab at a time, in the workbook's order:

| Tab | Component | Model (pure, tested) |
|---|---|---|
| Settlement | `settlement.jsx` | `settlement-model.js`: grids, totals, the current month's weeks |
| Collections | `collections.jsx` | `collections-model.js` |
| Delta | `delta.jsx` | `delta-model.js`: the pivot and its filters, built in the browser from the delta rows |
| Delta raw data | `Dashboard.TablePage` | server-paged table |
| KPI | `kpi.jsx` | – |
| Case AR | `caseAr.jsx` | `caseAr-model.js`: Invalid / Valid sections with subtotals; the pivot itself is rebuilt on the server per filter |
| Raw data | `Dashboard.TablePage` | server-paged table |

**Why models are separate files:** "it looked right on screen" is not a way to
know a total is correct. `settlement-model.test.mjs` checks the arithmetic with
`node --test`, with no browser involved.

### Shared building blocks

| File | Gives you | Example |
|---|---|---|
| `components.jsx` | `DataTable`, `Card`, `Stat`, `Segmented`, `Picker`, `TextFilter`, `Notes`, `Status`, `Loading`, `ErrorBox`, `PasswordInput` | `<DataTable columns={cols} rows={rows} isTotal={(r) => r.group === "Total"} />` |
| `ui.jsx` | `TableCard` (a table in a card), `Stats` (a row of tiles, tinted in turn) | |
| `columns.js` | `col.money`, `col.pct`, `col.count`, `col.text`, `col.label` | `col.money("amount", "Settlement")` |
| `format.js` | `money`, `pct`, `count`, `bytes`, `when`, `stamp`, `weekRange`, `device` | `weekRange("2026-W38")` → `"14 to 20 Sep 2026"` |
| `buttons.jsx` | `Button` with tones (`primary`, `go`, `warn`, `danger`…), `ConfirmButton`, `DeleteButton` | `<DeleteButton onConfirm={remove} />` asks once more before calling |
| `icons.jsx` | every icon as inline SVG | |
| `reports.js` | `REPORT_OPTIONS`, `reportShort("gfs")` → `"GFS"` | |
| `activity-period.js` | `periodOf("week", "2026-10-01")` → Monday 28 Sep to Sunday 4 Oct, local time | |

---

## 11. Which endpoint feeds which screen

| Screen | Calls |
|---|---|
| Sign in | `POST /api/auth/login`, `POST /api/auth/signup` |
| Any page load | `GET /api/auth/me` |
| This week | `GET /api/scorecards/current`, then the dashboard calls below |
| Dashboard | `GET /api/runs/{id}`; `GET /api/runs/{id}/figures/{settlement, settlement_totals, settlement_pace, cp_settled, kpi, meta, collections_pace}`; `GET /api/runs/{id}/tables/{collections, delta_comparison}?limit=5000` |
| Case AR tab | `GET /api/runs/{id}/case-ar?group=…&validity=…` |
| Raw data tabs | `GET /api/runs/{id}/tables/{name}?offset=…&limit=50`; `…/csv` to export |
| Upload | `GET /api/weeks`, `GET /api/weeks/{week}`, `POST /api/weeks/{week}/uploads`, `GET/PUT /api/weeks/{week}/month`, `POST /api/runs?report=…&week=…`, `DELETE /api/weeks/{week}` |
| Run history | `GET /api/runs?weeks=12`, `DELETE /api/runs/{id}`, `POST /api/runs/{id}/unapprove` |
| Review | `GET /api/runs/{id}` (polled while building), `POST …/approve`, `POST …/unapprove` |
| Users | `GET /api/admin/users`, `GET /api/reports`, `POST /api/admin/users/{id}/{approve, role, access, active, unlock, reset-password, sign-out}`, `DELETE /api/admin/users/{id}` |
| Activity | `GET /api/admin/{actions, alerts, activity}`, `GET /api/admin/activity/csv`, `POST /api/admin/activity/delete` |
| Profile | `GET/PATCH /api/me`, `POST /api/me/password`, `GET /api/me/sessions`, `DELETE /api/me/sessions/{id}`, `POST /api/me/sessions/end-others`, `GET /api/me/activity` |

---

## 12. Configuration

Everything comes from environment variables, read once in `config.py`:

| Variable | Default | Meaning |
|---|---|---|
| `SCORECARD_DATA` | `<project>/data` | Where the database file, uploads, results and cache live |
| `SCORECARD_DB` | SQLite in the data folder | Database URL; `mysql://user:pass@host/scorecard` is completed to PyMySQL + utf8mb4 |
| `SCORECARD_TIMEZONE` | the server's clock | IANA zone for the out-of-hours alert, e.g. `Asia/Karachi` |
| `SCORECARD_WORK_HOURS` | `7-21` | Working hours for that alert |
| `SCORECARD_API_DOCS` | `1` | `0` turns off `/docs` and `/openapi.json` (do this on the server) |
| `SCORECARD_CORS_ORIGINS` | the two Vite dev addresses | Comma-separated; leave empty when page and API share an origin |
| `SCORECARD_MAX_UPLOAD_MB` | `1024` | Largest single uploaded file |
| `VITE_API` (frontend) | empty | Empty = same origin via the Vite proxy; set only to call a backend elsewhere |
| `SCORECARD_API_TARGET` (Vite) | `http://127.0.0.1:8000` | Where the dev proxy sends `/api` |

Business rules are not environment variables. They live in each report's
`rules.yml`.

---

## 13. Tests

```powershell
cd backend
..\.venv\Scripts\python -m pytest            # backend (about 4 minutes; password hashing is slow on purpose)
cd ..\frontend
node --test src\*.test.mjs                   # frontend models
npx oxlint                                   # lint
npx vite build                               # the production build compiles
```

| File | Covers |
|---|---|
| `test_api.py` | uploads, builds refused until ready, approve / unapprove, deleting runs and weeks with reference counting, table paging and CSV |
| `test_auth.py` | sign-up rules, sign-in, sessions, every data route refusing without a token |
| `test_roles.py` | viewer / admin / system admin: who may see and change what |
| `test_security.py` | the activity log, lockout, rate limits, CSV formulas, headers, upload limits, week labels, deleting activity |
| `test_ingest.py` | file classification (including the "- comments" copies), deduplication, Case AR per report |
| `test_review.py` | the week-on-week comparison of notes and tables |
| `test_case_ar_view.py` | the filtered Case AR pivot |
| `test_delta_comments.py` | Ongoing DOR lookup by Case Id, per sheet |
| `test_pacing.py` | the calendar, pace, Excel week numbers |
| `golden/` | a full build against a real week, compared with the old pipeline's output. **Skipped** unless the fixtures (real client data, never committed) are on the machine |

Tests use a fresh temporary data folder each (`settings.use(tmp_path)`), so
they never touch your database.

---

## 14. How to extend it

### Accept a new input file

1. Add a `SourceFile` to the registry in `reports/__init__.py`, with fragments
   that match its name and `excludes` for any look-alike:

   ```python
   SourceFile("lien_report", ("lien", "report"), label="Lien Report", required=False)
   ```

2. Add it to `SHARED_SOURCES`, or to one report's `extra_sources`.
3. Read it in that report's `readers.py` through `timed(...)`, so it is cached
   and recorded.
4. Add a line to `test_classifies_…` in `test_ingest.py`.

### Add an endpoint

Put it in the router for its area (`week_routes`, `run_routes`,
`admin_routes`, `auth_routes`). Keep the route thin: validate, call `service/`,
`audit.record(...)` anything that changes data or exports it, and add the
action to `audit.ACTIONS` so the Activity screen can filter on it. Add a test
that a viewer is refused if it is admin-only.

### Change a business rule

Change `rules.yml` if the rule is already a setting. If it is not, make it one:
read it from `rules` in `core/`, with the current behaviour as the default.
Future builds pick it up; existing runs keep what they produced.

### Add a review check

Return a `Note` from `review_notes.py` (both reports) or the report's
`pipeline.py`. Give it a stable `code` and put the numbers in `detail`, so the
review can say "changed since last week". Map the code to a review card in
`service/review.SECTIONS`.

### Add a page

Create `pages/Thing.jsx`, fetch with `useLoad`, build tables from
`DataTable` + `col.*`, and add a `<Route>` (inside the `user.is_admin` block
if it is admin-only) and a sidebar `<Item>` in `App.jsx`.

---

## 15. Conventions

- **Comments say why, not what.** Most modules open with a docstring or
  comment explaining the decision and the mistake it prevents. Keep that up
  when changing code.
- **Rules in `rules.yml`, never literals in `core/`.**
- **Match columns by name**, never by position; the source workbooks move
  columns without warning.
- **Service functions take the session** and `flush()`; the caller commits.
- **Anything that changes data or exports it is logged.**
- **Frontend tables go through `DataTable` and `columns.js`**, never a
  hand-rolled `<table>`, so every figure is formatted the same way.
- **Nothing under `data/` is committed.** Uploads and results are client data.
  `.gitignore` also excludes `*.xlsx`, `*.xlsb` and `*.csv` everywhere.
- **Line endings**: Git stores LF; on Windows the working copy may show CRLF.
  Either is fine.

---

## 16. Glossary

| Term | Meaning |
|---|---|
| **Week** | An ISO week label, `2026-W38` (Monday to Sunday) |
| **Report** | `gfs` (mailed Tuesday) or `all_providers` (mailed Thursday) |
| **Source / source key** | One kind of input file, e.g. `delta_wc` |
| **Shared file** | An input both reports use; `upload.report_key` is NULL |
| **Case AR files** | Owner and Custom Case AR, uploaded per report because each report uses its own day's copy |
| **Run** | One build of one report for one week |
| **Review** | The screen a run waits on until someone approves it |
| **Figures** | Sheet-shaped results (grids, KPI blocks) stored as JSON records |
| **Tables** | Row-shaped results (Raw Data, Delta Comparison…) stored as parquet |
| **Note** | One review check: code, severity, message, detail |
| **Bucket** | `W2` = week 2 of the current month; `M5` = May's total |
| **Pace** | Month-to-date ÷ working days elapsed × working days in the month |
| **Delta** | The Master Settlement & Collection Delta workbooks (WC, MLCR) and what is built from them |
| **Ongoing DOR** | Status and details the litigation team adds in Tuesday's "- comments" Delta copies |
| **Golden master** | A test that compares a full build with the old pipeline's verified output |
| **Viewer / admin / system admin** | Read approved scorecards / run the workspace / also manage admins |
