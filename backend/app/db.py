"""Database engine, sessions, column types and the tenant isolation hook.

Tenant isolation is enforced twice:

1. In the application: every query on tenant data filters on ``org_id``
   (see ``app.services.scoping``).
2. In PostgreSQL: row-level security policies (migration 0001) only return rows
   whose ``org_id`` matches ``app.current_org``. That setting is applied at the
   start of every transaction from ``session.info``, so a forgotten filter in
   the application still cannot leak another client's data.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Engine, MetaData, create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

TENANT_KEY = "opscore.org_id"
BYPASS_KEY = "opscore.rls_bypass"

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC timestamps on every backend.

    SQLite has no timezone support and returns naive values; this type stores
    UTC and always hands back an aware ``datetime``. Naive input is rejected so
    a local-time bug cannot silently shift evidence timestamps.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime given; timestamps must be timezone-aware")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


JSONType = JSON().with_variant(JSONB(), "postgresql")


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def build_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        # No server-side prepared statements, so a pooled connection (PgBouncer, as Neon
        # and Vercel Postgres use) can hand the connection to another client between queries.
        kwargs["connect_args"] = {"prepare_threshold": None}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    if engine.dialect.name == "sqlite":
        # pysqlite starts transactions lazily and commits behind SQLAlchemy's back, which
        # turns a SAVEPOINT opened before any write into the outer transaction (so a later
        # failure leaves half a request committed). Take over transaction control, as the
        # SQLAlchemy docs recommend, and begin IMMEDIATE so concurrent writers queue on the
        # busy timeout instead of failing on a read-to-write upgrade.

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        @event.listens_for(engine, "begin")
        def _sqlite_begin(conn) -> None:
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


@event.listens_for(Session, "after_begin")
def _apply_tenant_to_transaction(session: Session, _transaction, connection) -> None:
    """Pin the PostgreSQL RLS context for the transaction that just began.

    ``set_config(..., true)`` is transaction-local, so the value can never leak
    to the next request that borrows this pooled connection.
    """
    if connection.dialect.name != "postgresql":
        return
    org_id = session.info.get(TENANT_KEY)
    bypass = bool(session.info.get(BYPASS_KEY))
    connection.execute(
        text("SELECT set_config('app.current_org', :org, true), set_config('app.rls_bypass', :bypass, true)"),
        {"org": str(org_id) if org_id else "", "bypass": "on" if bypass else "off"},
    )


def set_tenant(session: Session, org_id: uuid.UUID | None, *, bypass: bool = False) -> None:
    """Set the tenant for the session's *next* transaction.

    Ends any open transaction first so the new context takes effect.
    """
    if session.in_transaction():
        session.commit()
    session.info[TENANT_KEY] = org_id
    session.info[BYPASS_KEY] = bypass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = build_engine(get_settings().database_url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def configure(engine: Engine) -> None:
    """Point the application at a specific engine (used by tests and the CLI)."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def system_session() -> Iterator[Session]:
    """A session for trusted background work that spans tenants (worker, CLI)."""
    session = get_session_factory()()
    session.info[BYPASS_KEY] = True
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
