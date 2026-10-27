"""Closed vocabularies shared by models, schemas and services."""

from enum import StrEnum


class Industry(StrEnum):
    OIL_GAS = "oil_gas"
    MARITIME = "maritime"
    OTHER = "other"


class Region(StrEnum):
    US = "us"
    LATAM = "latam"
    OTHER = "other"


class Locale(StrEnum):
    EN = "en"
    ES = "es"
    PT = "pt"


class UnitSystem(StrEnum):
    IMPERIAL = "imperial"
    METRIC = "metric"


class Module(StrEnum):
    ASSISTANT = "assistant"


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    MEMBER = "member"
    VIEWER = "viewer"


ROLE_RANK = {
    Role.VIEWER: 0,
    Role.MEMBER: 1,
    Role.SUPERVISOR: 2,
    Role.ADMIN: 3,
    Role.OWNER: 4,
}


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class EventCategory(StrEnum):
    SAFETY = "safety"
    OPERATIONS = "operations"
    LOGISTICS = "logistics"
    SECURITY = "security"
    COMPLIANCE = "compliance"
    COMMUNICATIONS = "communications"


class ActorType(StrEnum):
    USER = "user"
    API_KEY = "api_key"
    SYSTEM = "system"


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class WorkOrderStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class WorkOrderPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Channel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class ApiKeyScope(StrEnum):
    EVENTS_WRITE = "events:write"
    EVENTS_READ = "events:read"
    MESSAGES_WRITE = "messages:write"


class ConversationChannel(StrEnum):
    WHATSAPP = "whatsapp"
    SMS = "sms"
    VOICE = "voice"
    WEB = "web"


class ConversationStatus(StrEnum):
    BOT = "bot"
    ESCALATED = "escalated"
    CLOSED = "closed"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageAuthor(StrEnum):
    CUSTOMER = "customer"
    BOT = "bot"
    AGENT = "agent"


class DeliveryStatus(StrEnum):
    RETURNED = "returned"  # handed back to the integration in the webhook response
    SENT = "sent"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
