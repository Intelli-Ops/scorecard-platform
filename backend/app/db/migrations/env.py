"""Alembic environment: connects migrations to the app's database."""
from __future__ import annotations

from alembic import context

from app.db.models import Base

target_metadata = Base.metadata


def run() -> None:
    engine = context.config.attributes.get("engine")
    if engine is None:
        from app.db.session import engine as app_engine
        engine = app_engine()
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported: several "
                     "steps look at the database to decide what to do.")
run()
