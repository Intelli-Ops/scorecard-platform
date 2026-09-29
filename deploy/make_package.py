"""Make the zip that goes to the server.

Run on your own machine, from the project folder:

    .venv\\Scripts\\python deploy\\make_package.py

It builds the React app (npm run build) and writes
release/scorecard-<date>-<commit>.zip with:

  * every file git knows about or would commit - so never .venv,
    node_modules, data/ (client case data), the golden-master fixtures or
    anything else .gitignore keeps out;
  * frontend/dist, the built app, so the server needs no Node.js.

Files for the server get Unix line endings, whatever the checkout has: bash
reads a Windows line ending as part of the command. Scripts are marked
executable inside the zip.

Uncommitted changes ARE included - the zip is the working folder as it is.
The name says so ("-modified"), so a zip can always be traced to a commit.
"""
from __future__ import annotations

import datetime as dt
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


def run(cmd: list[str], cwd: Path) -> str:
    # shell=True on Windows so "npm" finds npm.cmd.
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          shell=sys.platform == "win32")
    if done.returncode:
        sys.exit(f"{' '.join(cmd)} failed:\n{done.stdout}\n{done.stderr}")
    return done.stdout


def project_files() -> list[str]:
    """Tracked files plus new ones not ignored - what `git add -A` would take."""
    out = run(["git", "ls-files", "--cached", "--others", "--exclude-standard",
               "-z"], ROOT)
    return sorted(p for p in set(out.split("\0"))
                  if p and (ROOT / p).is_file())


def build_frontend() -> list[str]:
    if not (FRONTEND / "node_modules").is_dir():
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
    commit = run(["git", "rev-parse", "--short", "HEAD"], ROOT).strip()
    dirty = bool(run(["git", "status", "--porcelain"], ROOT).strip())
    name = f"scorecard-{dt.date.today():%Y%m%d}-{commit}{'-modified' if dirty else ''}.zip"

    print("building the frontend ...", flush=True)
    files = project_files() + build_frontend()

    OUT_DIR.mkdir(exist_ok=True)
    target = OUT_DIR / name
    with zipfile.ZipFile(target, "w") as z:
        for rel in files:
            add(z, rel)

    size = target.stat().st_size / 1_048_576
    print(f"wrote {target.relative_to(ROOT)}  ({len(files)} files, {size:.1f} MB)")
    if dirty:
        print("note: includes changes not yet committed to git")


if __name__ == "__main__":
    main()
