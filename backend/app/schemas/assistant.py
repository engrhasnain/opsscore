"""Ops Assistant: knowledge entries, inbound messages and conversations."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.enums import (
    ConversationChannel,
    ConversationStatus,
    DeliveryStatus,
    Locale,
    MessageAuthor,
    MessageDirection,
)
from app.errors import ValidationFailed
from app.schemas.common import In, Out
from app.services import validation

MAX_MESSAGE_LENGTH = 4096  # WhatsApp's own limit


class KnowledgeCreateIn(In):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    content: Annotated[str, Field(min_length=1, max_length=4000)]
    keywords: Annotated[list[Annotated[str, Field(min_length=1, max_length=60)]], Field(max_length=40)] = Field(
        default_factory=list
    )
    locale: Locale
    site_id: uuid.UUID | None = None


class KnowledgeUpdateIn(In):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    content: Annotated[str, Field(min_length=1, max_length=4000)] | None = None
    keywords: Annotated[list[Annotated[str, Field(min_length=1, max_length=60)]], Field(max_length=40)] | None = None
    locale: Locale | None = None
    site_id: uuid.UUID | None = None
    is_active: bool | None = None


class KnowledgeOut(Out):
    id: uuid.UUID
    title: str
    content: str
    keywords: list[str]
    locale: Locale
    site_id: uuid.UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InboundIn(In):
    channel: ConversationChannel
    sender: Annotated[str, Field(min_length=1, max_length=128, description="Phone number or user id")]
    body: Annotated[str, Field(max_length=MAX_MESSAGE_LENGTH)] = ""
    has_media: bool = False
    display_name: Annotated[str, Field(max_length=200)] | None = None
    provider_message_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    sent_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _normalize_sender(self) -> "InboundIn":
        """One sender, one conversation: "+55 13 90000-0001", "whatsapp:+5513900000001"
        and "+5513900000001" are the same phone."""
        sender = self.sender.strip()
        if self.channel in _PHONE_CHANNELS:
            prefix, _, rest = sender.partition(":")
            if rest and prefix.strip().lower() in _SENDER_PREFIXES:
                sender = rest.strip()
            try:
                sender = validation.phone(sender, field="sender") or ""
            except ValidationFailed as exc:
                raise ValueError(exc.message) from None
            if not sender:
                raise ValueError("sender must be an international number, e.g. +5491155550100.")
        elif not sender:
            raise ValueError("sender must not be empty.")
        self.sender = sender
        return self


_PHONE_CHANNELS = {ConversationChannel.WHATSAPP, ConversationChannel.SMS}
_SENDER_PREFIXES = {"whatsapp", "sms", "tel"}


class InboundOut(Out):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    status: ConversationStatus
    reply: str | None
    reply_message_id: uuid.UUID | None
    escalated: bool
    duplicate: bool
    locale: Locale


class MessageOut(Out):
    id: uuid.UUID
    created_at: datetime
    direction: MessageDirection
    author: MessageAuthor
    body: str
    answered_by: str | None
    confidence: float | None
    knowledge_entry_ids: list[str]
    delivery_status: DeliveryStatus
    delivery_error: str | None


class ConversationOut(Out):
    id: uuid.UUID
    channel: ConversationChannel
    external_ref: str
    display_name: str | None
    locale: Locale
    status: ConversationStatus
    escalated_at: datetime | None
    escalation_reason: str | None
    closed_at: datetime | None
    last_message_at: datetime
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]


class AgentReplyIn(In):
    body: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)]

    @field_validator("body")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body must not be blank.")
        return value
