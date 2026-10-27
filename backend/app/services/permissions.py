"""Role and scope based permissions.

Roles are cumulative: each role can do everything the role below it can.
API keys never get a role; they get narrow scopes.
"""

from enum import StrEnum

from app.enums import ROLE_RANK, ApiKeyScope, Role


class Permission(StrEnum):
    READ = "read"
    EVENTS_READ = "events.read"
    EVENTS_CREATE = "events.create"
    WORK_ORDERS_UPDATE = "work_orders.update"
    ALERTS_MANAGE = "alerts.manage"
    WORK_ORDERS_MANAGE = "work_orders.manage"
    CONVERSATIONS_HANDLE = "conversations.handle"
    CONFIGURE = "configure"
    MEMBERS_MANAGE = "members.manage"
    ORG_SETTINGS = "org.settings"
    AUDIT_READ = "audit.read"
    ASSISTANT_INBOUND = "assistant.inbound"


_MIN_ROLE: dict[Permission, Role] = {
    Permission.READ: Role.VIEWER,
    Permission.EVENTS_READ: Role.VIEWER,
    Permission.EVENTS_CREATE: Role.MEMBER,
    Permission.WORK_ORDERS_UPDATE: Role.MEMBER,
    Permission.ALERTS_MANAGE: Role.SUPERVISOR,
    Permission.WORK_ORDERS_MANAGE: Role.SUPERVISOR,
    Permission.CONVERSATIONS_HANDLE: Role.SUPERVISOR,
    Permission.CONFIGURE: Role.ADMIN,
    Permission.MEMBERS_MANAGE: Role.ADMIN,
    Permission.ORG_SETTINGS: Role.ADMIN,
    Permission.AUDIT_READ: Role.ADMIN,
}

_SCOPE_GRANTS: dict[ApiKeyScope, frozenset[Permission]] = {
    ApiKeyScope.EVENTS_WRITE: frozenset({Permission.EVENTS_CREATE}),
    ApiKeyScope.EVENTS_READ: frozenset({Permission.EVENTS_READ}),
    ApiKeyScope.MESSAGES_WRITE: frozenset({Permission.ASSISTANT_INBOUND}),
}


def role_allows(role: Role | None, permission: Permission) -> bool:
    minimum = _MIN_ROLE.get(permission)
    if role is None or minimum is None:
        return False
    return ROLE_RANK[role] >= ROLE_RANK[minimum]


def scopes_allow(scopes: frozenset[str], permission: Permission) -> bool:
    for scope in scopes:
        try:
            if permission in _SCOPE_GRANTS[ApiKeyScope(scope)]:
                return True
        except ValueError:
            continue
    return False
