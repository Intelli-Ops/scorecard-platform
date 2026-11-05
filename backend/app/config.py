"""Settings, read from environment variables."""
from __future__ import annotations
from pathlib import Path
from zoneinfo import ZoneInfo
import datetime as dt
import os


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def database_url(url: str) -> str:
    """Tidy a database address into the form SQLAlchemy needs."""
    if url.startswith("mysql://"):
        url = "mysql+pymysql://" + url[len("mysql://"):]
    if url.startswith("mysql") and "charset=" not in url:
        url += ("&" if "?" in url else "?") + "charset=utf8mb4"
    return url


MAIL_KEYS = ("SCORECARD_SMTP_HOST", "SCORECARD_SMTP_PORT", "SCORECARD_SMTP_USER",
             "SCORECARD_SMTP_PASSWORD", "SCORECARD_MAIL_FROM",
             "SCORECARD_PUBLIC_URL")


def load_mail_env(path: Path) -> None:
    """The mail settings from mail.env, beside the code - on a laptop."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key in MAIL_KEYS:
            os.environ.setdefault(key, value.strip())


class Settings:
    def __init__(self) -> None:
        root = os.environ.get("SCORECARD_DATA", str(PROJECT_ROOT / "data"))
        self.data_dir = Path(root)
        self.object_dir = self.data_dir / "objects"     # uploaded source files
        self.results_dir = self.data_dir / "results"    # parquet the runs produce
        self.database_url = database_url(os.environ.get(
            "SCORECARD_DB", f"sqlite:///{(self.data_dir / 'scorecard.db').as_posix()}"))

        self.timezone = os.environ.get("SCORECARD_TIMEZONE") or "Asia/Karachi"
        start, _, end = os.environ.get("SCORECARD_WORK_HOURS", "7-21").partition("-")
        self.work_hours = (int(start), int(end or 24))

        self.api_docs = os.environ.get("SCORECARD_API_DOCS", "1") == "1"

        self.cors_origins = [o.strip() for o in os.environ.get(
            "SCORECARD_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

        self.max_upload_mb = int(os.environ.get("SCORECARD_MAX_UPLOAD_MB", "1024"))

        self.require_https = os.environ.get("SCORECARD_REQUIRE_HTTPS", "0") == "1"

        # Email domains sign-up refuses on top of the bundled temporary-email list,
        # comma separated: SCORECARD_BLOCKED_EMAIL_DOMAINS=newtempmail.com,another.net
        self.blocked_email_domains = frozenset(
            d.strip().lower().lstrip("@") for d in
            os.environ.get("SCORECARD_BLOCKED_EMAIL_DOMAINS", "").split(",") if d.strip())

        migrate_url = os.environ.get("SCORECARD_MIGRATE_DB", "").strip()
        self.migrate_database_url = database_url(migrate_url) if migrate_url else None
        self.auto_migrate = os.environ.get("SCORECARD_AUTO_MIGRATE", "1") == "1"

        self.smtp_host = os.environ.get("SCORECARD_SMTP_HOST", "").strip()
        self.smtp_port = int(os.environ.get("SCORECARD_SMTP_PORT", "587"))
        self.smtp_user = os.environ.get("SCORECARD_SMTP_USER", "")
        self.smtp_password = os.environ.get("SCORECARD_SMTP_PASSWORD", "")
        self.mail_from = (os.environ.get("SCORECARD_MAIL_FROM", "").strip()
                          or self.smtp_user or "scorecard@appedology.com")
        self.public_url = (os.environ.get("SCORECARD_PUBLIC_URL", "").strip()
                           or "http://localhost:5173").rstrip("/")

    def today(self) -> dt.date:
        """Today's date where the business is - not where the server is."""
        try:
            return dt.datetime.now(ZoneInfo(self.timezone)).date()
        except Exception:                     # unknown name, or no tz data
            return dt.date.today()

    def ensure(self) -> None:
        for d in (self.data_dir, self.object_dir, self.results_dir):
            d.mkdir(parents=True, exist_ok=True)

    def use(self, data_dir: Path) -> None:
        """Point everything at another directory."""
        self.data_dir = Path(data_dir)
        self.object_dir = self.data_dir / "objects"
        self.results_dir = self.data_dir / "results"
        self.database_url = f"sqlite:///{(self.data_dir / 'scorecard.db').as_posix()}"
        self.migrate_database_url = None
        self.ensure()


load_mail_env(PROJECT_ROOT / "mail.env")
settings = Settings()
