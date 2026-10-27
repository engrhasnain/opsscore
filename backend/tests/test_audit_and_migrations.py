"""The audit chain detects tampering; migrations match the models exactly."""

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, select, text, update

from alembic import command
from app.db import Base, system_session
from app.models import AuditEntry, Organization
from tests.conftest import IS_POSTGRES

API = "/api/v1"
BACKEND = Path(__file__).resolve().parent.parent


def _make_history(client, headers):
    client.post(f"{API}/sites", headers=headers, json={"code": "A", "name": "Alpha"})
    client.post(f"{API}/sites", headers=headers, json={"code": "B", "name": "Bravo"})


def test_chain_is_valid_after_normal_use(client, acme_headers):
    _make_history(client, acme_headers)
    report = client.get(f"{API}/audit/verify", headers=acme_headers).json()
    assert report["valid"] and report["entries_checked"] > 5


def test_editing_an_entry_is_detected(client, acme, acme_headers):
    _make_history(client, acme_headers)
    with system_session() as session:
        target = session.scalar(
            select(AuditEntry).where(AuditEntry.org_id == acme.org.id, AuditEntry.action == "site.created")
        )
        seq = target.seq
        session.execute(update(AuditEntry).where(AuditEntry.id == target.id).values(changes={"name": "forged"}))
    report = client.get(f"{API}/audit/verify", headers=acme_headers).json()
    assert not report["valid"] and report["first_invalid_seq"] == seq
    assert report["reason"] == "entry content was modified"


def test_deleting_the_latest_entry_is_detected(client, acme, acme_headers):
    _make_history(client, acme_headers)
    with system_session() as session:
        org = session.get(Organization, acme.org.id)
        session.execute(
            text("DELETE FROM audit_entries WHERE org_id = :org AND seq = :seq"),
            {"org": org.id if IS_POSTGRES else org.id.hex, "seq": org.audit_seq},
        )
    report = client.get(f"{API}/audit/verify", headers=acme_headers).json()
    assert not report["valid"] and report["reason"] == "entries removed from the end"


def test_audit_log_records_who_did_what(client, acme_headers):
    _make_history(client, acme_headers)
    entries = client.get(f"{API}/audit?entity_type=site", headers=acme_headers).json()["items"]
    assert {e["action"] for e in entries} == {"site.created"}
    assert all(e["actor_type"] == "user" and e["request_id"] for e in entries)


def test_migrations_build_exactly_the_model_schema(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
    assert diff == []
    command.downgrade(config, "base")
    engine.dispose()
