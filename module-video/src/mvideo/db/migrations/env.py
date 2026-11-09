"""Alembic environment. Migrations run on the connection handed in by `mvideo.db.migrate`,
which holds a PostgreSQL advisory lock for the whole run."""

from alembic import context

from mvideo.db.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        raise RuntimeError("run migrations through mvideo.db.migrate.upgrade()")
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
