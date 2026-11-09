from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def get_url() -> str:
    url = config.get_main_option("sqlalchemy.url") or ""
    if not url or url.startswith("driver://"):
        import os

        url = os.environ.get("PUBLISH_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("PUBLISH_DATABASE_URL or sqlalchemy.url is required for migrations")
    # Alembic runs synchronously; strip the async driver.
    return url.replace("postgresql+asyncpg://", "postgresql://")


def run_migrations_offline() -> None:
    context.configure(url=get_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
