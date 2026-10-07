"""How Alembic reaches the database. Run through migrate.upgrade(), or from
backend/ with the alembic command (see alembic.ini).

The address always comes from the app's own settings (SCORECARD_DB), never
from alembic.ini - a second place to write the address is a second place for
it to be wrong.
"""
from __future__ import annotations

from alembic import context

from app.db.models import Base

target_metadata = Base.metadata


def run() -> None:
    # migrate.upgrade() hands over the engine it was given; the command line
    # has none to hand over and uses the app's.
    engine = context.config.attributes.get("engine")
    if engine is None:
        from app.db.session import engine as app_engine
        engine = app_engine()
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            # SQLite cannot ALTER a column or a constraint in place; batch
            # mode rebuilds the table instead. Other databases ignore it.
            render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported: several "
                     "steps look at the database to decide what to do.")
run()
