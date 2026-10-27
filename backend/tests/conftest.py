"""Test fixtures.

Tests run on in-memory SQLite by default. To run the same suite, plus the
row-level-security tests, against PostgreSQL set:

    OPSCORE_TEST_DATABASE_URL             app role (not a superuser, not the table owner)
    OPSCORE_TEST_MIGRATION_DATABASE_URL   table owner (runs migrations, resets data)
"""

import os

os.environ["OPSCORE_ENVIRONMENT"] = "test"
os.environ["OPSCORE_DATABASE_URL"] = os.environ.get("OPSCORE_TEST_DATABASE_URL", "sqlite://")
# The table owner migrates and resets data between tests; the app role runs the tests.
if os.environ.get("OPSCORE_TEST_MIGRATION_DATABASE_URL"):
    os.environ["OPSCORE_MIGRATION_DATABASE_URL"] = os.environ["OPSCORE_TEST_MIGRATION_DATABASE_URL"]
if not os.environ["OPSCORE_DATABASE_URL"].startswith("sqlite"):
    # The public development secret is refused on any shared database.
    os.environ.setdefault("OPSCORE_JWT_SECRET", "test-only-secret-for-postgres-runs-0123456789")
os.environ["OPSCORE_BCRYPT_ROUNDS"] = "4"
os.environ["OPSCORE_ASSISTANT_LLM_ENABLED"] = "false"
os.environ["OPSCORE_NOTIFY_INLINE"] = "true"
os.environ["OPSCORE_LOG_LEVEL"] = "WARNING"

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db
from app.config import get_settings
from app.db import Base, build_engine, system_session
from app.enums import Industry, Module, Region, Role
from app.main import create_app
from app.models import Organization, User
from app.notify.providers import MemoryProvider, Router, set_router
from app.schemas.tenancy import MemberCreateIn, OrgCreateIn, OwnerIn
from app.security import hash_password
from app.services import tenancy
from app.services.context import Actor, Ctx

PASSWORD = "correct-horse-battery-9"
DATABASE_URL = os.environ["OPSCORE_DATABASE_URL"]
IS_POSTGRES = DATABASE_URL.startswith("postgresql")


def _truncate_all(engine) -> None:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.rls_bypass', 'on', false)"))
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture(scope="session")
def _pg_engine():
    if not IS_POSTGRES:
        yield None
        return
    from app.cli import migrate

    migrate()
    owner = build_engine(os.environ.get("OPSCORE_MIGRATION_DATABASE_URL", DATABASE_URL))
    app_engine = build_engine(DATABASE_URL)
    yield owner, app_engine
    owner.dispose()
    app_engine.dispose()


@pytest.fixture(autouse=True)
def database(_pg_engine) -> Iterator[None]:
    if IS_POSTGRES:
        owner, app_engine = _pg_engine
        _truncate_all(owner)
        db.configure(app_engine)
        yield
        return
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    db.configure(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def provider() -> Iterator[MemoryProvider]:
    memory = MemoryProvider()
    set_router(Router.everything(memory))
    yield memory
    set_router(None)


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@dataclass
class Tenant:
    org: Organization
    slug: str
    owner_email: str

    def ctx(self, role: Role = Role.OWNER) -> Ctx:
        return Ctx(org=self.org, actor=Actor.system("test"), role=role)


def make_tenant(
    slug: str,
    *,
    industry: Industry = Industry.OIL_GAS,
    region: Region = Region.US,
    modules: tuple[Module, ...] = (),
    timezone: str = "America/Chicago",
) -> Tenant:
    with system_session() as session:
        org = tenancy.create_organization(
            session,
            Actor.system("test"),
            OrgCreateIn(
                name=slug.replace("-", " ").title(),
                slug=slug,
                industry=industry,
                region=region,
                timezone=timezone,
                enabled_modules=list(modules),
                owner=OwnerIn(email=f"owner@{slug}.example.com", full_name=f"Owner {slug}", password=PASSWORD),
            ),
        )
        session.flush()
        session.expunge(org)
    return Tenant(org=org, slug=slug, owner_email=f"owner@{slug}.example.com")


def add_member(tenant: Tenant, email: str, role: Role) -> None:
    with system_session() as session:
        session.add(tenant.org)
        tenancy.add_member(
            session,
            tenant.ctx(),
            MemberCreateIn(email=email, full_name=email.split("@")[0], role=role, password=PASSWORD),
        )
        session.expunge(tenant.org)


def login(client: TestClient, email: str, org: str | None = None) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD, "organization": org})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def make_platform_admin(email: str = "admin@platform.example.com") -> str:
    with system_session() as session:
        session.add(User(email=email, full_name="Admin", password_hash=hash_password(PASSWORD), is_platform_admin=True))
    return email


@pytest.fixture
def acme() -> Tenant:
    return make_tenant("acme-energy", industry=Industry.OIL_GAS, region=Region.US)


@pytest.fixture
def portco() -> Tenant:
    return make_tenant(
        "porto-sul",
        industry=Industry.MARITIME,
        region=Region.LATAM,
        modules=(Module.ASSISTANT,),
        timezone="America/Sao_Paulo",
    )


@pytest.fixture
def acme_headers(client, acme) -> dict[str, str]:
    return login(client, acme.owner_email)


@pytest.fixture
def portco_headers(client, portco) -> dict[str, str]:
    return login(client, portco.owner_email)


def api_key(client: TestClient, headers: dict[str, str], scopes: list[str]) -> dict[str, str]:
    response = client.post("/api/v1/api-keys", headers=headers, json={"name": "test key", "scopes": scopes})
    assert response.status_code == 201, response.text
    return {"X-API-Key": response.json()["key"]}
