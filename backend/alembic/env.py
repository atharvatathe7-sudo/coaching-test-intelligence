"""
Alembic environment.

The database URL comes from the application's settings (COACHING_DB_PATH),
so migrations always target the same file the API uses.

Migrations run with foreign-key enforcement switched off (SQLite batch
mode rebuilds tables, which would otherwise trip foreign keys mid-way)
and then run PRAGMA foreign_key_check, failing the migration if any
foreign key is violated afterwards.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from backend.app.database.connection import DATABASE_URL, Base
from backend.app.database import models  # noqa: F401  (registers tables)

config = context.config

if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")

    if connectable is None:
        engine = create_engine(
            DATABASE_URL,
            poolclass=pool.NullPool,
            hide_parameters=True,
        )
        with engine.connect() as connection:
            _run(connection)
        engine.dispose()
    else:
        _run(connectable)


def _run(connection) -> None:
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    # The PRAGMA autobegins a transaction; end it so Alembic owns (and
    # commits) the migration transaction.
    connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()

    violations = connection.exec_driver_sql(
        "PRAGMA foreign_key_check"
    ).fetchall()

    if violations:
        raise RuntimeError(
            f"Migration left {len(violations)} foreign-key violation(s); "
            "restore the pre-migration backup."
        )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
