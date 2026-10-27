"""PostgreSQL row-level security: the database itself keeps clients apart.

Runs only against PostgreSQL. The test role must NOT be a superuser, because
superusers bypass row-level security entirely:

    OPSCORE_TEST_DATABASE_URL=postgresql+psycopg://opscore_app:...@localhost:5433/opscore_test
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db import get_session_factory, set_tenant, system_session
from app.models import Site
from tests.conftest import IS_POSTGRES, make_tenant

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not IS_POSTGRES, reason="set OPSCORE_TEST_DATABASE_URL to a PostgreSQL database"),
]


@pytest.fixture
def two_sites():
    a, b = make_tenant("rls-a"), make_tenant("rls-b")
    with system_session() as session:
        session.add_all([Site(org_id=a.org.id, code="A1", name="A"), Site(org_id=b.org.id, code="B1", name="B")])
    return a, b


def test_role_is_subject_to_rls():
    with get_session_factory()() as session:
        is_super = session.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar()
    assert not is_super, "connect as a non-superuser role; superusers bypass row-level security"


def test_queries_without_a_filter_only_see_the_current_tenant(two_sites):
    a, _b = two_sites
    with get_session_factory()() as session:
        set_tenant(session, a.org.id)
        # Deliberately no org_id filter: this is the bug RLS protects against.
        codes = set(session.scalars(select(Site.code)))
    assert codes == {"A1"}


def test_no_tenant_means_no_rows(two_sites):
    with get_session_factory()() as session:
        assert list(session.scalars(select(Site))) == []


def test_cannot_write_into_another_tenant(two_sites):
    a, b = two_sites
    with get_session_factory()() as session:
        set_tenant(session, a.org.id)
        session.add(Site(id=uuid.uuid4(), org_id=b.org.id, code="SNEAKY", name="x"))
        with pytest.raises(DBAPIError):
            session.flush()
        session.rollback()


def test_tenant_setting_does_not_leak_between_transactions(two_sites):
    a, _b = two_sites
    factory = get_session_factory()
    with factory() as session:
        set_tenant(session, a.org.id)
        assert session.scalar(select(Site.code)) == "A1"
        session.commit()
    with factory() as fresh:  # likely the same pooled connection
        assert list(fresh.scalars(select(Site))) == []
