"""Ops Assistant: knowledge base, conversations and messages."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, JSONType, UTCDateTime
from app.enums import (
    ConversationChannel,
    ConversationStatus,
    DeliveryStatus,
    Locale,
    MessageAuthor,
    MessageDirection,
)
from app.models.base import IdMixin, TenantMixin, TimestampMixin, enum_column


class KnowledgeEntry(IdMixin, TimestampMixin, TenantMixin, Base):
    """An approved answer the assistant may give, written by the client."""

    __tablename__ = "knowledge_entries"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    locale: Mapped[Locale] = enum_column(Locale, "locale", nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Conversation(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # At most one live conversation per sender and channel.
        Index(
            "uq_conversations_live_sender",
            "org_id",
            "channel",
            "external_ref",
            unique=True,
            postgresql_where=text("status <> 'closed'"),
            sqlite_where=text("status <> 'closed'"),
        ),
    )

    channel: Mapped[ConversationChannel] = enum_column(ConversationChannel, "channel", nullable=False)
    external_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    locale: Mapped[Locale] = enum_column(Locale, "locale", nullable=False)
    status: Mapped[ConversationStatus] = enum_column(ConversationStatus, "status", nullable=False)
    escalated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    escalation_reason: Mapped[str | None] = mapped_column(String(40))
    escalation_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("events.id", ondelete="SET NULL"))
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_message_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class Message(IdMixin, TenantMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("org_id", "provider_message_id"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    direction: Mapped[MessageDirection] = enum_column(MessageDirection, "direction", nullable=False)
    author: Mapped[MessageAuthor] = enum_column(MessageAuthor, "author", nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    in_reply_to_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("messages.id", ondelete="SET NULL"))
    knowledge_entry_ids: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    answered_by: Mapped[str | None] = mapped_column(String(20))
    agent_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    delivery_status: Mapped[DeliveryStatus] = enum_column(DeliveryStatus, "delivery_status", nullable=False)
    delivery_error: Mapped[str | None] = mapped_column(String(1000))
