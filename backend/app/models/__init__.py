"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.models.assistant import Conversation, KnowledgeEntry, Message
from app.models.audit import AuditEntry
from app.models.catalog import Asset, Contact, EventType, Site
from app.models.operations import (
    Alert,
    AlertEvent,
    Event,
    Notification,
    Rule,
    WorkOrder,
)
from app.models.tenancy import ApiKey, Membership, Organization, User

TENANT_MODELS = [
    Membership,
    ApiKey,
    Site,
    Asset,
    Contact,
    EventType,
    Rule,
    Event,
    Alert,
    AlertEvent,
    WorkOrder,
    Notification,
    AuditEntry,
    KnowledgeEntry,
    Conversation,
    Message,
]

__all__ = [
    "TENANT_MODELS",
    "Alert",
    "AlertEvent",
    "ApiKey",
    "Asset",
    "AuditEntry",
    "Contact",
    "Conversation",
    "Event",
    "EventType",
    "KnowledgeEntry",
    "Membership",
    "Message",
    "Notification",
    "Organization",
    "Rule",
    "Site",
    "User",
    "WorkOrder",
]
