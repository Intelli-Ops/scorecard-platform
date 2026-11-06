# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A web app that turns a week's uploaded client Excel/CSV files into two weekly scorecards, **GFS** (sent Tuesday) and **All Providers** (sent Thursday). FastAPI + SQLAlchemy + polars backend in `backend/`, React 19 + Vite frontend in `frontend/`. It is developed on a Windows laptop (SQLite) and deployed to one Ubuntu server (MySQL 8, nginx, systemd); [DEPLOY.md](DEPLOY.md) covers the server side.

## Commands

Backend (Python venv lives at the repo root, `.venv`; run from `backend/`):

```powershell
python -m venv ..\.venv                                       # once; make_package.py expects it at the repo root
..\.venv\Scripts\python -m pip install -r requirements.txt   # exact pins, via constraints.txt
..\.venv\Scripts\python -m pytest                             # all tests (pytest.ini sets pythonpath=. and -q)
..\.venv\Scripts\python -m pytest tests/test_api.py::test_uploads_are_recorded_against_the_signed_in_account
..\.venv\Scripts\uvicorn app.main:app --reload --port 8000    # dev server
..\.venv\Scripts\python -m app.manage check                   # also: upgrade, create-admin, set-role, reset-password, copy-db, protect-log
```

Frontend (from `frontend/`):

```powershell
npm run dev        # Vite; proxies /api to 127.0.0.1:8000 (override with SCORECARD_API_TARGET)
npm run build
npm run lint       # oxlint
node --test "src/*.test.mjs"   # unit tests are *.test.mjs files using node:test, next to the module they test
node --test src/format.test.mjs
```

Release zip: commit everything first, then `.venv\Scripts\python deploy\make_package.py` from the repo root. It refuses a dirty tree, runs the backend tests, does `npm ci` + build, and writes `release/scorecard-<date>-<commit>.zip` containing only that commit's files (plus `mail.env` if present).

## Architecture

### Request → build flow

1. **Upload** (`POST /api/weeks/{week}/uploads`, one file per request). `service/ingest.py` matches the filename against the `SourceFile` fragments in `reports/__init__.py` to decide which input it is, stores the bytes in the content-addressed `storage/files.py` store (`data/objects/`, keyed by SHA-256), and records an `Upload` row. Weeks are ISO week strings like `2026-W38`. Upload requests are size-checked in middleware in `main.py` before the body is read; every other route is capped at 1 MB.
2. **Queue** (`service/runner.queue`). Creates a `Run` row with status `pending` and pins exactly which uploads (`RunInput`) and working-day settings it will use. The database itself refuses a second active build for the same report/week.
3. **Build** (`jobs/worker.py`). A single in-process background thread claims pending runs from the database (a durable queue: it survives restarts; runs whose heartbeat goes stale are marked failed by `recover()`). Each build is three short transactions around a long calculation: `runner.plan` → `runner.compute` (no transaction open) → `runner.record`.
4. **Calculate** (`reports/<report>/`). `runner._PIPELINES` maps each report key to a `readers.py` function (Excel → polars, via fastexcel/calamine, cached as parquet by `reports/cache.py`; both build on `reading.read_sources`) and a `pipeline.run`. The pipeline calls its `core/` modules (`case_ar`, `delta`, `kpi`, and `settlement` for GFS only), each building one section of the scorecard. Steps both reports take the same way live once: `reports/common.py` (provider groups, the GFS case flag, Case AR joins, CP Settled, SQL-Doc counts), `reports/collection_sheet.py` (Collections) and `reports/result.py` (`RunResult` and the sections built the same way). Put shared logic there, not in both `core/` folders.
5. **Results** are written as parquet in `data/results/` (`RunTable`), plus headline numbers (`RunFigure`) and notes (`RunNote`), and served to the frontend by `api/run_routes.py`.

### Business rules live in YAML

Each report's rules (filters, mappings, column lists, KPI layout) are in `reports/<report>/rules.yml`, loaded by `reports.load_rules`. Comments there quote the client's own process document ("PHASE 1", "PHASE 2"...). Change a rule in the YAML rather than hard-coding it in the pipeline. Holidays and the provider list are stored in the database and edited from admin screens. `service/holidays.with_holidays` and `service/providers.with_providers` merge them into the rules when a build is planned.

### Partial builds

A build runs even when some files haven't been uploaded yet. A section whose inputs are missing comes out as an empty table with the schema from the pipeline's `EMPTY` dict, plus a `section_waiting` note (`reports/partial.py`, `reports/notes.py`). If you add a column to a section's output, add it to `EMPTY` too.

### Backend layers

- `api/`: routers. `deps.py` holds auth/role dependencies. `auth_routes` is open, `week_routes`/`run_routes` need a signed-in user, `admin_routes` need an admin. Roles: `viewer`, `admin`, `system_admin`, plus per-user `report_access`.
- `service/`: the logic. `audit.py` writes the activity log, and an action is refused (503) when the log can't be written. `detect.py` derives security alerts from that log. `blobs.py` deletes stored files only after the DB commit that drops their last reference (`db.session.after_commit`/`after_rollback` hooks).
- `db/`: `models.py` is the current schema. Migrations are Alembic in `db/migrations/versions/` (`0001`, `0002`, ...); `db/migrate.py` applies them, and `baseline.py` is a frozen copy of the pre-Alembic schema (do not edit). A schema change needs a new numbered migration as well as the `models.py` change. With `SCORECARD_AUTO_MIGRATE=1` (laptop default) the app migrates itself on startup. On the server it runs as a rows-only DB account, refuses to start if the schema is behind, and migrations run through `scorecard-manage upgrade` as a separate account. A DB trigger stops activity-log rows being edited.
- `config.py`: all settings come from `SCORECARD_*` env vars (listed in DEPLOY.md). Defaults to SQLite at `data/scorecard.db`. On a laptop, mail settings are read from `mail.env` at the repo root (git-ignored). Use `settings.today()` (business time zone, default Asia/Karachi) for "today" and `clock.utcnow()` for timestamps.

### Frontend

Plain JSX, no TypeScript, no state library. `api.js` wraps every backend call; `VITE_API` is empty in both env files on purpose, so the page and API share one origin (the Vite proxy in dev, nginx in production). Pages are in `src/pages/`. Each scorecard section has a view (`caseAr.jsx`, `collections.jsx`, `delta.jsx`, `kpi.jsx`, `settlement.jsx`) and a pure `*-model.js` that reshapes API rows for display. Put logic in the model file and test it in the matching `.test.mjs`. `reports.js` repeats the report keys and send days from the backend's `REPORTS`.

### Tests

Backend tests use stand-in files, never real client data (`*.xlsx`, `*.xlsb`, `*.csv` and `data/` are git-ignored, because client files must not be committed). Each test fixture points `settings.use(tmp_path / "data")` at a temp directory, calls `db_session.reset()` + `create_all()`, and signs in with `tests/accounts.account(...)`. `conftest.py` turns off real SMTP (sent mail goes to `mail.outbox`) and lowers the password-hashing rounds.

## Conventions

- Docstrings and comments are short, plain sentences that say what something is or why, often in the business's own terms. Match that style. User-facing error messages are full sentences that tell the reader what to do.
- Commit messages are plain-English summaries of the user-visible change (see `git log`).
