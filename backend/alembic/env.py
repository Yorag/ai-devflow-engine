from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from backend.app.db.base import ROLE_METADATA, DatabaseRole
from backend.app.db.session import enable_sqlite_foreign_key_enforcement
import backend.app.db.models.control  # noqa: F401
import backend.app.db.models.event  # noqa: F401
import backend.app.db.models.graph  # noqa: F401
import backend.app.db.models.log  # noqa: F401
import backend.app.db.models.runtime  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = {role.value: ROLE_METADATA[role] for role in DatabaseRole}


def _role_sections() -> list[tuple[DatabaseRole, dict[str, str]]]:
    sections: list[tuple[DatabaseRole, dict[str, str]]] = []
    for role in DatabaseRole:
        section = config.get_section(f"alembic:{role.value}")
        if section is None:
            raise RuntimeError(f"Missing Alembic section for {role.value}")
        sections.append((role, section))
    return sections


def _ensure_sqlite_parent_exists(url: str) -> None:
    database = make_url(url).database
    if database and database != ":memory:":
        Path(database).expanduser().resolve(strict=False).parent.mkdir(parents=True, exist_ok=True)


def run_migrations_offline() -> None:
    for role, section in _role_sections():
        url = section["sqlalchemy.url"]
        context.configure(
            url=url,
            target_metadata=ROLE_METADATA[role],
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            version_table=f"alembic_version_{role.value}",
        )
        with context.begin_transaction():
            context.run_migrations(database_role=role.value)


def run_migrations_online() -> None:
    for role, section in _role_sections():
        _ensure_sqlite_parent_exists(section["sqlalchemy.url"])
        connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
        enable_sqlite_foreign_key_enforcement(connectable)
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=ROLE_METADATA[role],
                version_table=f"alembic_version_{role.value}",
            )
            with context.begin_transaction():
                context.run_migrations(database_role=role.value)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
