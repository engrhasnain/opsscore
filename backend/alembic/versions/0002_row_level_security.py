"""Row-level security: PostgreSQL itself keeps each client's rows apart.

Every tenant table gets a policy that only exposes rows whose org_id matches
the transaction's ``app.current_org`` setting (applied by app.db on every
transaction). ``app.rls_bypass`` is for trusted cross-tenant work (sign-in
lookups, the notification worker, onboarding).

FORCE makes the policies apply to the table owner too. Superusers always
bypass RLS, so the API must connect as an ordinary role; see README.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = [
    "memberships",
    "api_keys",
    "sites",
    "assets",
    "contacts",
    "event_types",
    "rules",
    "events",
    "alerts",
    "alert_events",
    "work_orders",
    "notifications",
    "audit_entries",
    "knowledge_entries",
    "conversations",
    "messages",
]

_BYPASS = "current_setting('app.rls_bypass', true) = 'on'"


def _policy(column: str) -> str:
    return f"({_BYPASS} OR {column}::text = current_setting('app.current_org', true))"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in [("organizations", "id"), *[(t, "org_id") for t in TENANT_TABLES]]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        condition = _policy(column)
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING {condition} WITH CHECK {condition}")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in ["organizations", *TENANT_TABLES]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
