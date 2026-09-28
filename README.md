# Scorecard Platform

A web app that builds the two weekly client scorecards:

| Report | Sent on | What it covers |
|---|---|---|
| **GFS Weekly Scorecard** | Tuesday | GFS cases only |
| **All Providers Weekly Scorecard** | Thursday | Every provider |

Both reports used to be built on one laptop with a `.bat` script and Excel
(the [gfs-automation](https://github.com/Intelli-Ops/gfs-automation) project).
This app does the same calculations in a browser. You upload the week's files,
press **Build**, check the review screen, approve the run, then read the
scorecard.

For a longer, non-technical walkthrough, see [HOW-IT-WORKS.md](HOW-IT-WORKS.md).

---

## Contents

1. [How it works in one minute](#how-it-works-in-one-minute)
2. [Tech stack and tools](#tech-stack-and-tools)
3. [Project structure](#project-structure)
4. [Getting started](#getting-started)
5. [Using the app: a worked week](#using-the-app-a-worked-week)
6. [The input files](#the-input-files)
7. [What the calculations do](#what-the-calculations-do)
8. [The review screen](#the-review-screen)
9. [The API](#the-api)
10. [Changing the rules](#changing-the-rules)
11. [Tests](#tests)
12. [Where data is stored](#where-data-is-stored)
13. [Accounts, admins and the activity log](#accounts-admins-and-the-activity-log)

---

## How it works in one minute

```
  1. UPLOAD                2. BUILD                    3. REVIEW              4. READ
  ─────────                ────────                    ─────────              ───────
  Drag the week's    ──►   Background worker    ──►    What needs a     ──►   Dashboard with
  Excel / CSV files        reads the files,            person's eyes:         the same tabs as
  onto "Upload"            runs the calculations,      new providers,         the workbook
                           saves the results           missing data,          (Settlement,
                                                       duplicate cases        Collections, KPI…)
                                                       → Approve
```

- **A week** is labelled like `2026-W38` (ISO week 38 of 2026).
- **A run** is one build of one report for one week. Every run records who
  started it, which exact files it read (by fingerprint), what it produced, and
  who approved it.
- Nothing is recalculated when you look at an old run. Its results are stored,
  so a scorecard from three months ago opens instantly.

---

## Tech stack and tools

### Backend: Python

| Tool | Used for |
|---|---|
| **Python 3.11** | Language |
| **FastAPI** | The HTTP API (`/api/...`) |
| **Uvicorn** | Runs the FastAPI server |
| **Polars** | All the table calculations. Fast, and handles 280,000-row files easily |
| **fastexcel** (calamine) | Reads `.xlsx` / `.xlsb` quickly: about 2 s, where openpyxl took about 35 s |
| **PyArrow / Parquet** | Stores each run's result tables, and caches parsed Excel files |
| **SQLAlchemy 2** | Database access |
| **SQLite** | Default database on a laptop (one file, nothing to install) |
| **MySQL 8** + **PyMySQL** | The database on the server; see [Where data is stored](#where-data-is-stored) |
| **PyYAML** | Reads the business rules in `rules.yml` |
| **pytest** | Tests |

There is no queue server. Builds run on one background thread inside the web
process ([worker.py](backend/app/jobs/worker.py)). If a build dies, start it
again; its input files are still stored.

### Frontend: JavaScript

| Tool | Used for |
|---|---|
| **React 19** | The screens |
| **React Router 7** | Pages: `/upload`, `/runs`, `/runs/:id`, `/dashboard/:id` |
| **Vite 8** | Dev server and production build. Also forwards `/api` calls to the backend |
| **oxlint** | Linting |
| **node:test** | Tests for the table-shaping code (`*.test.mjs`) |

It uses no UI library and no chart library. The tables and styling are
hand-written ([components.jsx](frontend/src/components.jsx),
[theme.css](frontend/src/theme.css)).

---

## Project structure

```
scorecard-platform/
├── README.md                  ← this file
├── HOW-IT-WORKS.md            ← plain-English guide for the people using it
├── backend/                   ← Python API + calculations
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── app/
│   │   ├── main.py            ← creates the FastAPI app
│   │   ├── config.py          ← where data lives (data dir, database URL)
│   │   ├── api/               ← HTTP layer
│   │   ├── service/           ← what the API calls: ingest, run, review…
│   │   ├── jobs/              ← background build worker
│   │   ├── db/                ← database tables and session
│   │   ├── storage/           ← file store (content-addressed)
│   │   └── reports/           ← THE CALCULATIONS
│   │       ├── gfs/
│   │       └── all_providers/
│   └── tests/
└── frontend/                  ← React app
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── pages/             ← one file per screen
        └── *-model.js         ← turn API rows into sheet-shaped tables
```

### `backend/app/api/`: the HTTP layer
| File | What's in it |
|---|---|
| [routes.py](backend/app/api/routes.py) | Weeks, uploads, runs, approve and unapprove, figures, tables, CSV export |
| [auth_routes.py](backend/app/api/auth_routes.py) | Sign up, sign in, sign out, and your own profile (`/api/me`): name, password, sessions, recent activity |
| [admin_routes.py](backend/app/api/admin_routes.py) | Admin only: accounts, the activity log, alerts |
| [deps.py](backend/app/api/deps.py) | `signed_in`, `current_user` and `require_admin`: who may call what |

### `backend/app/service/`: the application logic
| File | What's in it |
|---|---|
| [ingest.py](backend/app/service/ingest.py) | Accepts uploaded files, recognises which input each one is by its name, and stores it once, even if uploaded twice |
| [runner.py](backend/app/service/runner.py) | Runs one build: find the files, read them, calculate, save the results, record the notes. Also approve, unapprove and delete |
| [review.py](backend/app/service/review.py) | Builds the review screen and compares each check with last week's |
| [figures.py](backend/app/service/figures.py) | Turns the sheet-shaped results (grids, KPI blocks) into rows the dashboard can read |
| [auth.py](backend/app/service/auth.py) | Accounts, password hashing, lockout, sessions, and the admin actions |
| [audit.py](backend/app/service/audit.py) | Writes and searches the activity log |
| [detect.py](backend/app/service/detect.py) | Reads the log for things to look at: password guessing, new addresses, bulk exports… |

### `backend/app/reports/`: the calculations
This is the heart of the project. It is kept apart from the web code so the
numbers can be tested against the old Excel pipeline.

| File / folder | What's in it |
|---|---|
| [\_\_init\_\_.py](backend/app/reports/__init__.py) | The list of reports and the input files each one needs |
| [locate.py](backend/app/reports/locate.py) | Matches uploaded files to inputs by name, e.g. a name containing `payment detail` is the Payment Detail Report |
| [period.py](backend/app/reports/period.py) | The calendar: which month a week belongs to, its weeks, working days, holidays |
| [pacing.py](backend/app/reports/pacing.py) | Run-rate projection ("where will the month land?") |
| [review_notes.py](backend/app/reports/review_notes.py) | The checks shown on the review screen |
| [notes.py](backend/app/reports/notes.py) | The `Note` type: code, severity, message, numbers |
| [cache.py](backend/app/reports/cache.py) | Parquet cache so a big Excel file is only parsed once |
| `gfs/` | The GFS report: `readers.py` (files → tables), `pipeline.py` (the steps in order), `core/` (each calculation), `rules.yml` (business rules) |
| `all_providers/` | The All Providers report, same layout, plus `layout.py`, which reads last week's workbook to find the KPI rows |

Inside each `core/` folder:

| File | Produces |
|---|---|
| `case_ar.py` | Raw Data and the Case AR summary |
| `delta.py` | Delta Comparison (live settlements) and, for All Providers, the settlement grids |
| `settlement.py` (GFS) | Settlement High-Level grids (In House / Board) and CP Settled Cases |
| `collections.py` | Collection High-Level: payments by group, week and payment type |
| `kpi.py` | KPI High-Level: SBR, DDE, DOR, NTP… per provider |

### `backend/app/db/`, `storage/`, `jobs/`
| File | What's in it |
|---|---|
| [db/models.py](backend/app/db/models.py) | Tables: `User`, `Session`, `ActivityLog`, `Upload`, `Run`, `RunInput`, `RunNote`, `RunFigure`, `RunTable` |
| [db/migrate.py](backend/app/db/migrate.py) | Adds new columns to an existing database, and the triggers that make the activity log append-only |
| [manage.py](backend/app/manage.py) | Command line for whoever runs the server: first admin, database checks, copying data across |
| [storage/files.py](backend/app/storage/files.py) | File store. Each file is saved under the hash of its bytes, so identical files are stored once |
| [jobs/worker.py](backend/app/jobs/worker.py) | Background thread that runs queued builds one at a time |

### `frontend/src/`
| File | What's in it |
|---|---|
| [App.jsx](frontend/src/App.jsx) | Sidebar and page routes |
| [api.js](frontend/src/api.js) | Every call to the backend |
| [auth.jsx](frontend/src/auth.jsx) | Sign-in state |
| `pages/Weeks.jsx` | **Upload**: drop files, see what is held and missing, press Build |
| `pages/Runs.jsx` | **Run history**: last 12 weeks of builds |
| `pages/Review.jsx` | **Review**: new providers, no-data items, duplicate case IDs, Approve |
| `pages/Dashboard.jsx` | **Scorecard**: tabs in workbook order |
| `settlement.jsx`, `collections.jsx`, `delta.jsx`, `kpi.jsx` | One file per dashboard tab |
| `*-model.js` | Pure functions that pivot API rows into the sheet's shape (tested in `*.test.mjs`) |
| `components.jsx`, `ui.jsx`, `columns.js`, `format.js` | Shared table, card, tile and number formatting |

---

## Getting started

### What you need
- Python 3.11+
- Node.js 20+

### 1. Install (once)

From the project root, `C:\dev\scorecard-platform`:

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements.txt

cd frontend
npm install
cd ..
```

### 2. Run (two terminals)

**Terminal 1: backend.** It must be started from inside `backend\`:
```powershell
cd C:\dev\scorecard-platform\backend
..\.venv\Scripts\python -m uvicorn app.main:app --reload
```
It listens on http://127.0.0.1:8000. Check http://127.0.0.1:8000/api/health.

**Terminal 2: frontend.** It must be started from inside `frontend\`:
```powershell
cd C:\dev\scorecard-platform\frontend
npm run dev
```
Open the address it prints, usually http://localhost:5173. Vite forwards
`/api/...` to the backend, so no other setup is needed.

### Common mistakes
| Error | Cause | Fix |
|---|---|---|
| `No module named 'app'` | uvicorn was started outside `backend\` | `cd backend` first |
| `Could not read package.json` | `npm` was run outside `frontend\` | `cd frontend` first |
| `..\.venv\Scripts\python is not recognized` | Run from the project root, where the path is `.\.venv` | `cd backend` first, or use `.\.venv\Scripts\python` |

### 3. Create an account
On first open, choose **Sign up**. There are two rules, checked by the server
as well as the form:
- the email must end in `@appedology.com`
- the APD ID is `APD-` plus four digits, e.g. `APD-1234` (typing `1234` is completed for you)

A new account **waits for an admin to approve it** before it can sign in.
On a fresh database there is no admin yet, so make the first one from the
command line (from `backend/`):

```powershell
..\.venv\Scripts\python -m app.manage create-admin you@appedology.com APD-1234
# or, for an account that already exists:
..\.venv\Scripts\python -m app.manage promote you@appedology.com
```

---

## Using the app: a worked week

Example: building **Week 38 of 2026** (Mon 14 – Fri 18 Sep).

**1. Upload.** Go to **Upload**, pick week `2026-W38`, and drop in the files:

```
Master Settlement & Collection Delta WC 09.21.2026.xlsb   → delta_wc          (shared)
Master Settlement & Collection Delta MLCR 09.21.26.xlsb   → delta_mlcr        (shared)
Payment Detail Report for 01st to 18th September.xlsx     → payment_detail    (shared)
Supporting File.xlsx                                      → supporting        (shared)
Hearing Calendar (Jan 2024 - 18th September 2026).xlsx    → hearing_calendar  (shared)
sqllab_document_log_query_20260921T130343.csv             → document_log      (shared)
KPI-Numbers.xlsx                                          → kpi_numbers       (shared, optional)
Combined Owner Case AR.xlsb                               → owner_case_ar     (per report)
Combined Custom Case AR.xlsb                              → custom_case_ar    (per report)
All Provider - Weekly Score Card (Week-37) 2026.xlsx      → template          (All Providers only)
```

Files are recognised by **words in their name**, so dates and suffixes can change
freely. A file that matches nothing (a finished workbook, say) is refused with
a reason, never stored by mistake.

The two Case AR files are uploaded **per report**, because GFS uses Tuesday's
copy and All Providers uses Thursday's.

**2. Build.** When a report has everything it needs, its **Build** button turns on.
The build takes about a minute, and the page updates itself.

**3. Review.** The review screen lists only what needs a person's eyes (see
[The review screen](#the-review-screen)). Check it, then press **Approve**.
**Unapprove** undoes this in one click.

**4. Read.** **Open scorecard** shows the tabs in the workbook's order:
Settlement → Collections → Delta → KPI → Case AR → Raw data. Every table can be
filtered and downloaded as CSV.

---

## The input files

| Key | File (name must contain) | Used for |
|---|---|---|
| `delta_wc` | `delta wc` | WC settlements → Delta, Settlement |
| `delta_mlcr` | `delta mlcr` | Med-Legal and IMR settlements → Delta, Settlement |
| `payment_detail` | `payment detail` | Collections |
| `supporting` | `supporting file` | Provider List: provider → group |
| `hearing_calendar` | `hearing calendar` | CP Settled Cases |
| `document_log` | `document_log` (.csv) | KPI: SBR and DDE counts |
| `kpi_numbers` | `kpi` + `number` | KPI: DOR, NTP, Liens… (optional) |
| `owner_case_ar` | `combined owner case ar` | Raw Data, Case AR, and the list of GFS cases |
| `custom_case_ar` | `combined custom` + `case ar` | Closing Order, Case Validity, File Status lookups |
| `template` | `provider` + `score` (.xlsx) | All Providers only: last week's workbook, read for its KPI rows |

---

## What the calculations do

The calculations are the same as in gfs-automation, step for step. Short
examples of the rules that matter most:

### Weeks belong to the month of their Wednesday
```
Mon 31 Aug – Fri 4 Sep   → September week 1 (shown as 1–4 Sep; 31 Aug counts in August's total)
Mon 28 Sep – Fri 2 Oct   → September week 5 (28–30 Sep); 1–2 Oct join October week 1 (1–9 Oct)
```
So a 2026-W38 build reports **September 2026, weeks 1–3**. Nothing dated after
Sun 20 Sep is counted, even if the delta files already contain it.

### Pacing uses working days
Pace = month-to-date ÷ working days so far × working days in the month.
Holidays in `rules.yml` are not working days.
```
September 2026: 22 weekdays − Labour Day (7 Sep) = 21 working days
Week 2 ends Fri 11 Sep: 4 + 4 = 8 working days elapsed
A group with 400 in week 1 and 400 in week 2 → (400 + 400) / 8 × 21 = 2,100
```

### Settlement types
Med-Legal counts **F&F settlements only**; its "Payments" and "Check" rows are
left out. WC and IMR count every type.

### Delta Comparison (live settlements)
Combine the three delta sheets → drop providers with no group → keep GFS cases
(GFS report) → drop closed files → for **Partial Paid**, use Remaining Payment
as the settlement amount → attach Closing Order, Case Validity and Lien Filed
→ bucket by age (1–30, 31–60, 61–90, 90+ days).

### Collections
Payments for the month being reported, by group × week × payment type
(BILLING, REBILLING, APPEAL, SETTLEMENT). GFS leaves out PI; All Providers
counts PI.

### KPI and new providers
Each KPI figure goes to a row named after the provider, or else to its group's
row. A provider with a figure and **no row** gets a new row of its own and is
counted in the total. The review lists it as a new provider.

---

## The review screen

It shows three kinds of check, and nothing routine:

```
NEW PROVIDERS
ACTION   New provider in KPI DOR: 'Dorian Chiropractic' has 1 and had no row -
         added as its own row and counted in the DOR total        new this week
WARNING  Provider(s) in the KPI-numbers file but not in the Supporting File -
         their figures are not counted: Azizi One & Only Chiro

NO DATA FOR THE WEEK
ACTION   No data for KPI 10635 (DDEL) this week - no column for it in the
         KPI-numbers file
WARNING  No data for KPI Enforcement Of Agreement in September 2026 -
         every provider is 0

DUPLICATE CASE IDS
WARNING  2 duplicate case id(s) in Delta Comparison: 81234, 90211
```

Each item is compared with the previous week's run: **new this week**,
**changed** (with before → after), **same as last week**, or **resolved since
last week**.

Rows dropped by the routine filters (inactive providers, closed files, no
Case AR match) are **not** shown. They happen every week and mean the filters
are working.

---

## The API

Every route is under `/api` and needs a signed-in session, except sign-up,
sign-in and `/api/health`.

| Method | Path | Does |
|---|---|---|
| `POST` | `/api/auth/signup` · `/login` · `/logout` | Accounts. Sign-up returns `{"pending": true}` - no token until approved |
| `GET` `PATCH` | `/api/me` | Your profile; `PATCH {"display_name": ...}` |
| `POST` | `/api/me/password` | `{"current", "new"}` - also signs out your other sessions |
| `GET` `DELETE` | `/api/me/sessions` · `/{id}` | Where you are signed in; end one |
| `GET` | `/api/me/activity` | Your last 25 events |
| `GET` | `/api/reports` | The two reports and the files each needs |
| `GET` | `/api/weeks` · `/api/weeks/{week}` | Weeks, and what is held or missing for each |
| `POST` | `/api/weeks/{week}/uploads` | Upload files (`files`, optional `for_report` for Case ARs) |
| `POST` | `/api/runs?report=gfs&week=2026-W38` | Queue a build → `{"run_id": 12}` |
| `GET` | `/api/runs?weeks=12` | Run history |
| `GET` | `/api/runs/{id}` | The review for one run |
| `POST` | `/api/runs/{id}/approve` · `/unapprove` | Approve, or undo it |
| `GET` | `/api/runs/{id}/figures/{name}` | `settlement`, `settlement_pace`, `collections_pace`, `cp_settled`, `kpi`, `meta` |
| `GET` | `/api/runs/{id}/tables/{name}` · `/csv` | `raw_data`, `case_ar`, `delta_comparison`, `collections` |

Admin only (everyone else gets `403`, and the attempt is logged):

| Method | Path | Does |
|---|---|---|
| `DELETE` | `/api/weeks/{week}` · `/api/runs/{id}` | Deleting is an admin's job |
| `GET` | `/api/admin/users` | Every account, waiting ones first |
| `POST` | `/api/admin/users/{id}/approve` · `/role` · `/active` · `/unlock` · `/reset-password` · `/sign-out` | Account actions |
| `GET` | `/api/admin/activity` · `/csv` | The log: filter by `action`, `email`, `outcome`, `ip`, `days`; page with `before_id` |
| `GET` | `/api/admin/alerts?days=7` | What the log says needs a look, and the headline counts |

Week labels must look like `2026-W38`; anything else is refused with `400`.

Example with `curl`, using the token from sign-in:
```bash
curl -X POST "http://127.0.0.1:8000/api/runs?report=gfs&week=2026-W38" \
     -H "Authorization: Bearer $TOKEN"
# {"run_id": 12, "status": "pending", "queued_ahead": 0}

curl "http://127.0.0.1:8000/api/runs/12" -H "Authorization: Bearer $TOKEN"
# {"run": {...,"status": "review"}, "notes": [...], "needs_attention": true, ...}
```

---

## Changing the rules

Business rules live in YAML, not code:
[backend/app/reports/gfs/rules.yml](backend/app/reports/gfs/rules.yml) and
[backend/app/reports/all_providers/rules.yml](backend/app/reports/all_providers/rules.yml).

Examples:

```yaml
# Add next year's holidays (pacing stops counting them as working days)
holidays:
  - 2027-01-01   # New Year

# Count only F&F settlements from a sheet
delta:
  keep_settlement_types:
    Med-Legal Delta: [F&F]

# Leave a case type out of Collections (GFS: [PI]; All Providers: [])
collections:
  drop_case_types: [PI]
```

Changes apply to the next build. Existing runs keep the numbers they were built
with.

---

## Tests

```powershell
cd backend
..\.venv\Scripts\python -m pytest -q          # backend

cd ..\frontend
node --test src/*.test.mjs                    # frontend table models
npm run lint
```

### The golden-master tests
`backend/tests/golden/` runs this app on a real week of input files and checks
that its four tables, and the All Providers settlement grids, **match the
gfs-automation output exactly** (row for row, money to the cent). They need the
gfs-automation folder, with its `inputs/` and `marts/`, on disk, and are
skipped otherwise:

```powershell
$env:GFS_LEGACY_ROOT = "C:\Users\<you>\OneDrive - MSFT\Desktop\gfs-automation"
$env:GFS_GOLDEN_WEEK = "2026-W38"
$env:GFS_GOLDEN_AS_OF = "2026-09-22"
..\.venv\Scripts\python -m pytest -q tests\golden
```

Run them after any change to `reports/`.

---

## Where data is stored

Everything goes in `data/` at the project root (git-ignored, because it holds
client case data):

```
data/
├── scorecard.db      ← SQLite: accounts, uploads, runs, notes, figures
├── objects/          ← uploaded files, named by the SHA-256 of their bytes
├── results/          ← each run's result tables as parquet
└── cache/            ← parsed Excel files, so rebuilds are fast
```

Environment variables change this:

| Variable | Default | Example |
|---|---|---|
| `SCORECARD_DATA` | `<project>/data` | `D:\scorecard-data` |
| `SCORECARD_DB` | SQLite in the data folder | `mysql://scorecard:secret@localhost/scorecard` |
| `SCORECARD_TIMEZONE` | the server's clock | `Asia/Karachi` - for the out-of-hours alert |
| `SCORECARD_WORK_HOURS` | `7-21` | sign-ins outside these hours are flagged |
| `SCORECARD_API_DOCS` | `1` | `0` on a server, to hide `/docs` |

A plain `mysql://` address is enough: the app adds the PyMySQL driver and the
`utf8mb4` character set itself. The app creates its own tables and adds new
columns to existing ones when it starts (`python -m app.manage upgrade` does
the same by hand).

**Moving from SQLite to MySQL.** Point `SCORECARD_DB` at an empty MySQL
database, then copy everything across:

```powershell
$env:SCORECARD_DB = "mysql://scorecard:secret@dbhost/scorecard"
..\.venv\Scripts\python -m app.manage check
..\.venv\Scripts\python -m app.manage copy-db "sqlite:///C:/dev/scorecard-platform/data/scorecard.db"
```

Then copy the `objects/` and `results/` folders too: the database only points
at the files, and they live on disk.

**Never commit** `data/`, `.xlsx`, `.xlsb` or `.csv` files. `.gitignore`
already blocks them.

---

## Accounts, admins and the activity log

### Roles
| Role | Can |
|---|---|
| **Viewer** | Read the **approved** scorecards an admin has given it: GFS, All Providers, or both. It sees only the **This week** tab. Everything else is refused by the API |
| **Admin** | Everything in the workspace: upload, build, approve, delete. Approve new accounts, and manage viewers (their scorecards, passwords, disabling, deleting). Sees **Users** and **Activity** |
| **System admin** | Everything an admin can do, plus make, change and delete admins |

Who can manage whom:
- A **viewer** is managed by any admin.
- An **admin** is managed only by a system admin.
- A **system admin's** account is changed by nobody but that person. A system
  admin can remove their own account only while another system admin remains,
  so there is always one.
- Nobody changes their own role or disables themselves from the Users screen.

New sign-ups are viewers with no scorecards, waiting for approval. Tick their
scorecards on the Users screen, then press **Approve**.

The first system admin comes from the command line:
`python -m app.manage create-admin EMAIL APD-1234`, or `promote EMAIL` for an
existing account. `set-role EMAIL viewer|admin|system_admin` sets any role.
Accounts from before roles existed become viewers of both reports.

### Account protections
| Protection | What it does |
|---|---|
| Approval | A new sign-up cannot sign in until an admin approves it. Anyone can *type* an `@appedology.com` address, so an admin vouches for each one |
| Lockout | 5 wrong passwords in a row locks the account for 15 minutes. An admin can unlock it sooner |
| Password reset | An admin issues a one-time temporary password (there is no email server for reset links). The person must choose their own at the next sign-in |
| Sessions | Every signed-in device is listed on **Your profile** and can be signed out. Changing your password signs out every other device; disabling an account signs out all of them |
| Tokens | The database stores a SHA-256 of each session token, never the token itself, so a copy of the database cannot be used to sign in |
| Admins | Nobody can demote or disable their own account, so the app always keeps at least one admin |

### Working days and pacing
Pace figures project the month: month-to-date ÷ working days elapsed × the
month's working days. The month's working days come from the calendar
(weekdays less the `holidays` in `rules.yml`), unless someone enters a
different number on **Upload a week**. That number is kept for the whole
month (table `month_setting`), so every build in that month uses it. Each
run records the number it used (`run.working_days`) and whether it was
entered or from the calendar. Builds already made keep theirs; build again to
use a new number.

### The activity log
The `activity_log` table records every sign-in (including failed ones),
sign-out, password change, upload, build, scorecard view, approval, deletion,
CSV export and admin action. Each row stores the time (UTC), the person, the IP
address, the browser, and whether it succeeded, failed or was refused.

**It is kept forever and cannot be changed.** Database triggers refuse any
`UPDATE` or `DELETE` on the table, whoever sends it. On MySQL, creating
triggers needs more privileges than the app's own database user should have,
so the database admin runs this once:

```bash
python -m app.manage protect-log --as "mysql://root:ROOTPASS@localhost/scorecard"
```

If the triggers are missing, the app still starts but logs a warning every
time it does. For the same reason the app's MySQL user should not have `DROP`
permission, because `TRUNCATE` would get around the triggers.

### Alerts
The **Activity** screen works these out from the log for the chosen period:

| Alert | Raised when |
|---|---|
| Password guessing | 5+ wrong passwords for one account |
| List attack | One IP address fails against 3+ different accounts |
| Account locked | The lockout above triggered |
| New address | A good sign-in from an IP that account has not used in 90 days |
| Out of hours | A sign-in outside `SCORECARD_WORK_HOURS` |
| Bulk export | 10+ whole-table CSV exports by one person within an hour |
| Refused | Someone who is not an admin tried an admin action |
| Deletions | Runs or weeks were deleted |

The thresholds are constants at the top of
[detect.py](backend/app/service/detect.py).
