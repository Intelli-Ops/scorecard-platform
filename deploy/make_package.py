"""Builds the release zip: runs the tests, builds the frontend, packs one commit."""
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

LF_SUFFIXES = {".sh", ".service", ".conf", ".example", ".md", ".py", ".yml",
               ".txt", ".ini", ".json", ".js", ".jsx", ".css", ".html", ".svg",
               ".env"}
LF_NAMES = {"scorecard-manage"}
EXECUTABLE = {"deploy/install.sh", "deploy/scorecard-manage"}
MAIL_ENV = "mail.env"
PRIVATE = {MAIL_ENV}


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> str:
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
    """The whole backend suite."""
    run([sys.executable, "-m", "pytest", "-q"], ROOT / "backend")


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
    mode = 0o755 if rel in EXECUTABLE else 0o600 if rel in PRIVATE else 0o644
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
    require_clean()
    if (ROOT / MAIL_ENV).is_file():
        files.append(MAIL_ENV)
        print(f"including {MAIL_ENV}: this zip holds the mail password - "
              f"share it as you would the password itself", flush=True)
    else:
        print(f"no {MAIL_ENV}: the server keeps the mail settings it has "
              f"(see mail.env.example)", flush=True)

    OUT_DIR.mkdir(exist_ok=True)
    target = OUT_DIR / name
    with zipfile.ZipFile(target, "w") as z:
        for rel in files:
            add(z, rel)

    size = target.stat().st_size / 1_048_576
    print(f"wrote {target.relative_to(ROOT)}  ({len(files)} files, {size:.1f} MB)")


if __name__ == "__main__":
    main()
