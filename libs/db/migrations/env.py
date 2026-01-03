# ruff: noqa: F401
import asyncio
import os
from logging.config import fileConfig
from sqlalchemy import event, pool
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# Import your models here
from libs.db.base import Base
from libs.db.models.identity import Tenant, Principal
from libs.db.models.resource import Resource, ResourceEdge, ResourceVersion, ResourceRef
from libs.db.models.rbac import RoleBinding, RolePermission
from libs.db.models.activity import Activity, Outbox
from libs.db.models.agent import AgentPolicy, AgentCursor
from libs.db.models.chat import Channel, Message, MessageAttachment, ReadReceipt
from libs.db.models.merge import MergeRequest, Approval
from libs.db.models.notification import Notification, AuditLog
from libs.db.models.promotion import PromotionRequest, RbacTemplate
from libs.db.models.subscription import Subscription

# This is the Alembic Config object, which provides access to the values within the .ini file in use.
config = context.config

db_url = os.getenv("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw) -> str:
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_sqlite(_type, _compiler, **_kw) -> str:
    return "JSON"


def _is_sqlite_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        return make_url(url).get_backend_name() == "sqlite"
    except Exception:
        return url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    is_sqlite = _is_sqlite_url(url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=is_sqlite,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    is_sqlite = connection.dialect.name == "sqlite"
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=is_sqlite,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    if connectable.url.get_backend_name() == "sqlite":

        @event.listens_for(connectable.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
