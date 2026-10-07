"""Make the zip that goes to the server.

Run on your own machine, from the project folder:

    .venv\\Scripts\\python deploy\\make_package.py

It refuses to start unless the zip would be exactly one commit, then runs the
tests, builds the React app (npm ci, npm run build) and writes
release/scorecard-<date>-<commit>.zip with:

  * every file in that commit - so never .venv, node_modules, data/ (client
    case data), the golden-master fixtures or anything else .gitignore keeps
    out;
  * frontend/dist, the built app, so the server needs no Node.js.

Files for the server get Unix line endings, whatever the checkout has: bash
reads a Windows line ending as part of the command. Scripts are marked
executable inside the zip.

Three things a release must be, each of which this used to let slide:

  * COMMITTED. Changed or new files that are not in git stop it. A zip made
    from a working folder "as it is" cannot be rebuilt, or compared with
    what was reviewed, by anyone else - the name said "-modified", which
    recorded the problem without preventing it. Commit (a branch is fine),
    then package.
  * TESTED. The backend tests run first, the golden master included, and
    here a golden master with no reference data FAILS rather than skips
    (see backend/tests/golden/conftest.py).
  * BUILT FROM THE LOCKFILE. `npm ci` every time: it throws node_modules
    away and installs exactly what package-lock.json says. Reusing whatever
    node_modules was already there built the release from one developer's
    own tree.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
OUT_DIR = ROOT / "release"
TOP = "scorecard"                       # the folder the zip unpacks into

# Given Unix line endings in the zip.
LF_SUFFIXES = {".sh", ".service", ".conf", ".example", ".md", ".py", ".yml",
               ".txt", ".ini", ".json", ".js", ".jsx", ".css", ".html", ".svg"}
LF_NAMES = {"scorecard-manage"}
EXECUTABLE = {"deploy/install.sh", "deploy/scorecard-manage"}


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> str:
    # shell=True on Windows so "npm" finds npm.cmd.
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env,
                          shell=sys.platform == "win32")
    if done.returncode:
        sys.exit(f"{' '.join(cmd)} failed:\n{done.stdout}\n{done.stderr}")
    return done.stdout


def require_clean() -> None:
    """Stop unless the working folder is exactly the commit it is on."""
    changed = run(["git", "status", "--porcelain"], ROOT).rstrip()
    if changed:
        sys.exit("not packaging: these are not committed -\n\n"
                 f"{changed}\n\n"
                 "A release is one commit, so it can be traced and rebuilt. "
                 "Commit them (or remove them) and run this again.")


def run_tests() -> None:
    """The whole backend suite. GFS_GOLDEN_OPTIONAL is taken OUT of the
    environment, so a shell that had it set for everyday work cannot let a
    release through with the golden master skipped."""
    env = {k: v for k, v in os.environ.items() if k != "GFS_GOLDEN_OPTIONAL"}
    run([sys.executable, "-m", "pytest", "-q"], ROOT / "backend", env)


def project_files() -> list[str]:
    """Every file in the commit being packaged."""
    out = run(["git", "ls-files", "--cached", "-z"], ROOT)
    return sorted(p for p in set(out.split("\0"))
                  if p and (ROOT / p).is_file())


def build_frontend() -> list[str]:
    run(["npm", "ci"], FRONTEND)
    run(["npm", "run", "build"], FRONTEND)
    dist = FRONTEND / "dist"
    if not (dist / "index.html").is_file():
        sys.exit("npm run build made no frontend/dist/index.html")
    return sorted(p.relative_to(ROOT).as_posix()
                  for p in dist.rglob("*") if p.is_file())


def add(z: zipfile.ZipFile, rel: str) -> None:
    data = (ROOT / rel).read_bytes()
    path = Path(rel)
    if path.suffix in LF_SUFFIXES or path.name in LF_NAMES:
        data = data.replace(b"\r\n", b"\n")
    info = zipfile.ZipInfo(f"{TOP}/{rel}", date_time=(
        dt.datetime.fromtimestamp((ROOT / rel).stat().st_mtime).timetuple()[:6]))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3              # Unix, so the modes below are honoured
    mode = 0o755 if rel in EXECUTABLE else 0o644
    info.external_attr = (0o100000 | mode) << 16
    z.writestr(info, data)


def main() -> None:
    require_clean()
    commit = run(["git", "rev-parse", "--short", "HEAD"], ROOT).strip()
    name = f"scorecard-{dt.date.today():%Y%m%d}-{commit}.zip"

    print("running the tests ...", flush=True)
    run_tests()
    print("building the frontend ...", flush=True)
    files = project_files() + build_frontend()
    # npm must not have rewritten anything tracked (package-lock.json, say):
    # the zip would then no longer be the commit its name claims.
    require_clean()

    OUT_DIR.mkdir(exist_ok=True)
    target = OUT_DIR / name
    with zipfile.ZipFile(target, "w") as z:
        for rel in files:
            add(z, rel)

    size = target.stat().st_size / 1_048_576
    print(f"wrote {target.relative_to(ROOT)}  ({len(files)} files, {size:.1f} MB)")


if __name__ == "__main__":
    main()
