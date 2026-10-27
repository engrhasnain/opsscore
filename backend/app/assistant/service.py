"""Conversation handling for the Ops Assistant.

    inbound message -> stored -> emergency?      -> escalate (critical) + safety reply
                              -> escalated chat? -> stay quiet, a person owns it
                              -> only courtesy?  -> "you're welcome" / greeting / nothing
                              -> asks for human? -> escalate + handoff reply
                              -> answer found?   -> reply from approved knowledge
                              -> otherwise       -> escalate + "a person will reply"

Escalations are ordinary events (``assistant.escalation``), so they flow
through the same rules, alerts and notifications as everything else. The
escalation alert follows the conversation: a team reply acknowledges it, and
handing back or closing the conversation resolves it. A conversation nobody
answers is handed back to the assistant by ``sweep_escalations``.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assistant import language
from app.assistant.answerers import (
    Answer,
    Answerer,
    AnswererUnavailable,
    ClaudeAnswerer,
    KeywordAnswerer,
    KnowledgeView,
    Turn,
)
from app.config import get_settings
from app.db import utcnow
from app.enums import (
    AlertStatus,
    Channel,
    ConversationChannel,
    ConversationStatus,
    DeliveryStatus,
    Locale,
    MessageAuthor,
    MessageDirection,
    Severity,
)
from app.errors import Conflict, ValidationFailed
from app.i18n import t
from app.models import Alert, AlertEvent, Conversation, KnowledgeEntry, Message, Organization, Site
from app.notify.providers import DeliveryError, get_router
from app.packs import ESCALATION_TYPE_KEY, ensure_module_setup
from app.schemas.assistant import InboundIn
from app.schemas.operations import EventIn
from app.services import audit, events, workflow
from app.services.context import Actor, Ctx
from app.services.scoping import get_or_404, scoped

logger = logging.getLogger("opscore.assistant")

_ESCALATION_SEVERITY = {
    "emergency": Severity.CRITICAL,
    "human_requested": Severity.MEDIUM,
    "no_answer": Severity.LOW,
}

# Short replies the assistant sends on its own. Kept here, next to the only code that uses them.
_TEXTS: dict[str, dict[Locale, str]] = {
    "courtesy.thanks": {Locale.EN: "You're welcome.", Locale.ES: "De nada.", Locale.PT: "Por nada."},
    "courtesy.greeting": {
        Locale.EN: "Hi! How can I help you?",
        Locale.ES: "¡Hola! ¿En qué le puedo ayudar?",
        Locale.PT: "Olá! Como posso ajudar?",
    },
    "handback": {
        Locale.EN: "Sorry for the wait — our team is still on it. You can keep asking me questions here.",
        Locale.ES: "Disculpe la espera: nuestro equipo sigue con su consulta. Puede seguir haciéndome preguntas aquí.",
        Locale.PT: (
            "Desculpe a demora: nossa equipe continua cuidando disso. Você pode continuar me fazendo perguntas aqui."
        ),
    },
}


def _text(key: str, locale: Locale) -> str:
    return _TEXTS[key].get(locale) or _TEXTS[key][Locale.EN]


# How a conversation channel maps onto an outbound delivery channel.
_DELIVERY_CHANNEL = {
    ConversationChannel.WHATSAPP: Channel.WHATSAPP,
    ConversationChannel.SMS: Channel.SMS,
}


@dataclass
class InboundResult:
    conversation: Conversation
    message: Message
    reply: Message | None
    escalated: bool
    duplicate: bool
    pending_notification_ids: list[uuid.UUID]


def default_answerers(org_name: str) -> list[Answerer]:
    settings = get_settings()
    answerers: list[Answerer] = []
    if settings.assistant_llm_enabled:
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        answerers.append(
            ClaudeAnswerer(
                org_name=org_name,
                model=settings.assistant_model,
                timeout=settings.assistant_timeout_seconds,
                api_key=key,
            )
        )
    answerers.append(KeywordAnswerer())
    return answerers


def _knowledge(session: Session, ctx: Ctx) -> list[KnowledgeView]:
    rows = session.execute(
        select(KnowledgeEntry, Site.code, Site.name)
        .outerjoin(Site, Site.id == KnowledgeEntry.site_id)
        .where(KnowledgeEntry.org_id == ctx.org_id, KnowledgeEntry.is_active.is_(True))
        .order_by(KnowledgeEntry.created_at)
    ).all()
    return [
        KnowledgeView(
            id=str(entry.id),
            title=entry.title,
            content=entry.content,
            keywords=tuple(entry.keywords),
            locale=Locale(entry.locale),
            site_code=site_code,
            site_name=site_name,
        )
        for entry, site_code, site_name in rows
    ]


def _history(session: Session, conversation: Conversation, before: Message) -> list[Turn]:
    limit = get_settings().assistant_history_messages
    if limit == 0:
        return []
    rows = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id, Message.id != before.id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    )
    return [
        Turn("user" if m.direction == MessageDirection.INBOUND else "assistant", m.body)
        for m in reversed(rows)
        if m.body
    ]


def _find_answer(answerers: list[Answerer], question, entries, locale, history) -> Answer | None:
    for answerer in answerers:
        try:
            return answerer.answer(question, entries, locale, history)
        except AnswererUnavailable as exc:
            logger.warning("answerer unavailable, trying the next one", extra={"reason": str(exc)})
        except Exception:  # an answerer bug must not lose the message; the next one tries
            logger.exception("answerer failed, trying the next one")
    return None


def _live_conversation(session: Session, ctx: Ctx, channel, sender: str) -> Conversation | None:
    return session.scalar(
        scoped(Conversation, ctx.org_id)
        .where(
            Conversation.channel == channel,
            Conversation.external_ref == sender,
            Conversation.status != ConversationStatus.CLOSED,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _open_conversation(session: Session, ctx: Ctx, data: InboundIn, locale: Locale, now) -> Conversation:
    conversation = _live_conversation(session, ctx, data.channel, data.sender)
    if conversation is not None:
        return conversation
    conversation = Conversation(
        org_id=ctx.org_id,
        channel=data.channel,
        external_ref=data.sender,
        display_name=data.display_name,
        locale=locale,
        status=ConversationStatus.BOT,
        last_message_at=now,
    )
    try:
        with session.begin_nested():
            session.add(conversation)
            session.flush()
    except IntegrityError:
        # Two messages from the same sender arrived together; use the winner's conversation.
        conversation = _live_conversation(session, ctx, data.channel, data.sender)
        if conversation is None:
            raise
    return conversation


def find_duplicate(session: Session, ctx: Ctx, provider_message_id: str) -> InboundResult | None:
    """The stored result of an earlier delivery of the same provider message, if any."""
    return _duplicate(session, ctx, provider_message_id)


def _duplicate(session: Session, ctx: Ctx, provider_message_id: str) -> InboundResult | None:
    inbound = session.scalar(scoped(Message, ctx.org_id).where(Message.provider_message_id == provider_message_id))
    if inbound is None:
        return None
    reply = session.scalar(scoped(Message, ctx.org_id).where(Message.in_reply_to_id == inbound.id))
    conversation = session.get(Conversation, inbound.conversation_id)
    return InboundResult(
        conversation,
        inbound,
        reply,
        conversation.status == ConversationStatus.ESCALATED,
        duplicate=True,
        pending_notification_ids=[],
    )


def handle_inbound(
    session: Session, ctx: Ctx, data: InboundIn, *, answerers: list[Answerer] | None = None
) -> InboundResult:
    now = utcnow()
    if data.provider_message_id:
        duplicate = _duplicate(session, ctx, data.provider_message_id)
        if duplicate is not None:
            return duplicate

    body = data.body.strip()
    if not body and not data.has_media:
        raise ValidationFailed("The message has no text and no media.", code="EMPTY_MESSAGE")
    detected = language.detect(body) if body else None
    conversation = _open_conversation(session, ctx, data, detected or Locale(ctx.org.default_locale), now)
    if detected and detected != conversation.locale:
        conversation.locale = detected  # the sender switched language
    if data.display_name and not conversation.display_name:
        conversation.display_name = data.display_name
    locale = Locale(conversation.locale)

    inbound = Message(
        org_id=ctx.org_id,
        conversation_id=conversation.id,
        created_at=now,
        direction=MessageDirection.INBOUND,
        author=MessageAuthor.CUSTOMER,
        body=body,
        provider_message_id=data.provider_message_id,
        delivery_status=DeliveryStatus.NOT_APPLICABLE,
    )
    try:
        with session.begin_nested():
            session.add(inbound)
            session.flush()
    except IntegrityError:
        duplicate = _duplicate(session, ctx, data.provider_message_id) if data.provider_message_id else None
        if duplicate is None:
            raise
        return duplicate
    conversation.last_message_at = now

    escalation_reason: str | None = None
    reply_text: str | None = None
    answer: Answer | None = None

    if not body:
        reply_text = t("assistant.non_text", locale)
    elif language.is_emergency(body):
        escalation_reason = "emergency"
        reply_text = t("assistant.emergency", locale)
    elif conversation.status == ConversationStatus.ESCALATED:
        reply_text = None  # a person owns this conversation now; the alert sweep keeps reminding them
    elif (kind := language.courtesy(body)) is not None:
        # "thanks", "ok", "hola", 👍: nothing to answer and nothing to escalate.
        reply_text = _text(f"courtesy.{kind}", locale) if kind in ("thanks", "greeting") else None
    elif language.wants_human(body):
        escalation_reason = "human_requested"
        reply_text = t("assistant.handoff", locale)
    else:
        answer = _find_answer(
            answerers if answerers is not None else default_answerers(ctx.org.name),
            body,
            _knowledge(session, ctx),
            locale,
            _history(session, conversation, inbound),
        )
        if answer is not None:
            reply_text = answer.text
        else:
            escalation_reason = "no_answer"
            reply_text = t("assistant.no_answer", locale)

    pending: list[uuid.UUID] = []
    if escalation_reason:
        pending = _escalate(session, ctx, conversation, escalation_reason, body, now)

    reply = None
    if reply_text:
        reply = Message(
            org_id=ctx.org_id,
            conversation_id=conversation.id,
            created_at=utcnow(),
            direction=MessageDirection.OUTBOUND,
            author=MessageAuthor.BOT,
            body=reply_text,
            in_reply_to_id=inbound.id,
            knowledge_entry_ids=answer.entry_ids if answer else [],
            confidence=answer.confidence if answer else None,
            answered_by=answer.answered_by if answer else "template",
            delivery_status=DeliveryStatus.RETURNED,
        )
        session.add(reply)
    session.flush()
    return InboundResult(
        conversation=conversation,
        message=inbound,
        reply=reply,
        escalated=conversation.status == ConversationStatus.ESCALATED,
        duplicate=False,
        pending_notification_ids=pending,
    )


def _escalate(session: Session, ctx: Ctx, conversation: Conversation, reason: str, body: str, now) -> list[uuid.UUID]:
    """Hand the conversation to a person by raising an ordinary event.

    An emergency always raises an event, even in a conversation that a person
    already owns, because the people on call may not be watching it.
    """
    already = conversation.status == ConversationStatus.ESCALATED
    if already and reason != "emergency":
        return []
    if not already:
        conversation.status = ConversationStatus.ESCALATED
        conversation.escalated_at = now
        conversation.escalation_reason = reason

    ensure_module_setup(session, ctx, ["assistant"])
    system_ctx = Ctx(org=ctx.org, actor=Actor.system("assistant"))
    result = events.ingest(
        session,
        system_ctx,
        EventIn(
            event_type=ESCALATION_TYPE_KEY,
            severity=_ESCALATION_SEVERITY[reason],
            attributes={
                "reason": reason,
                "channel": str(conversation.channel),
                "sender": conversation.external_ref,
                "conversation_id": str(conversation.id),
                "excerpt": body[:500],
            },
            description=f"{conversation.display_name or conversation.external_ref}: {body[:300]}",
        ),
    )
    conversation.escalation_event_id = result.event.id
    audit.record(
        session,
        system_ctx,
        "conversation.escalated",
        "conversation",
        conversation.id,
        {"reason": reason, "event_id": result.event.id},
    )
    return result.pending_notification_ids


# ------------------------------------------------------------ people's side


def _push(conversation: Conversation, message: Message) -> None:
    """Send a message the sender did not just ask for (agent replies, hand-back notes)."""
    channel = _DELIVERY_CHANNEL.get(ConversationChannel(conversation.channel))
    if channel is None:
        message.delivery_status = DeliveryStatus.NOT_APPLICABLE
        message.delivery_error = f"{conversation.channel} conversations are read by the client app"
        return
    try:
        get_router().for_channel(channel).send(channel, conversation.external_ref, "", message.body)
        message.delivery_status = DeliveryStatus.SENT
    except DeliveryError as exc:
        message.delivery_status = DeliveryStatus.FAILED
        message.delivery_error = str(exc)[:1000]


def _escalation_alerts(session: Session, conversation: Conversation) -> list[Alert]:
    """The alert(s) raised for this conversation's latest escalation."""
    if conversation.escalation_event_id is None:
        return []
    return list(
        session.scalars(
            select(Alert)
            .join(AlertEvent, AlertEvent.alert_id == Alert.id)
            .where(
                AlertEvent.event_id == conversation.escalation_event_id,
                AlertEvent.org_id == conversation.org_id,
                Alert.org_id == conversation.org_id,
            )
        )
    )


def _acknowledge_escalation(session: Session, ctx: Ctx, conversation: Conversation, note: str) -> None:
    for alert in _escalation_alerts(session, conversation):
        if alert.status == AlertStatus.OPEN:
            workflow.acknowledge_alert(session, ctx, alert.id, note)


def _resolve_escalation(session: Session, ctx: Ctx, conversation: Conversation, note: str) -> None:
    for alert in _escalation_alerts(session, conversation):
        if alert.status != AlertStatus.RESOLVED:
            workflow.resolve_alert(session, ctx, alert.id, note)


def agent_reply(session: Session, ctx: Ctx, conversation_id: uuid.UUID, body: str) -> Message:
    text = (body or "").strip()
    if not text:
        raise ValidationFailed("The reply is empty.", code="EMPTY_MESSAGE")
    conversation = get_or_404(session, Conversation, ctx.org_id, conversation_id, label="Conversation", for_update=True)
    if conversation.status == ConversationStatus.CLOSED:
        raise Conflict("This conversation is closed.", code="CONVERSATION_CLOSED")
    now = utcnow()
    message = Message(
        org_id=ctx.org_id,
        conversation_id=conversation.id,
        created_at=now,
        direction=MessageDirection.OUTBOUND,
        author=MessageAuthor.AGENT,
        body=text,
        answered_by="agent",
        agent_user_id=ctx.actor.user_id,
        delivery_status=DeliveryStatus.NOT_APPLICABLE,
    )
    _push(conversation, message)
    if conversation.status == ConversationStatus.BOT:
        # A person stepped in; the bot stops answering this conversation.
        conversation.status = ConversationStatus.ESCALATED
        conversation.escalated_at = now
        conversation.escalation_reason = "agent_took_over"
    conversation.last_message_at = now
    session.add(message)
    session.flush()
    audit.record(
        session,
        ctx,
        "conversation.agent_replied",
        "conversation",
        conversation.id,
        {"message_id": message.id, "delivery": message.delivery_status},
    )
    _acknowledge_escalation(session, ctx, conversation, "Team replied in the conversation.")
    return message


def hand_back(session: Session, ctx: Ctx, conversation_id: uuid.UUID) -> Conversation:
    conversation = get_or_404(session, Conversation, ctx.org_id, conversation_id, label="Conversation", for_update=True)
    if conversation.status == ConversationStatus.CLOSED:
        raise Conflict("This conversation is closed.", code="CONVERSATION_CLOSED")
    if conversation.status == ConversationStatus.ESCALATED:
        conversation.status = ConversationStatus.BOT
        session.flush()
        audit.record(session, ctx, "conversation.handed_back", "conversation", conversation.id, {})
        _resolve_escalation(session, ctx, conversation, "Conversation handed back to the assistant.")
    return conversation


def close(session: Session, ctx: Ctx, conversation_id: uuid.UUID) -> Conversation:
    conversation = get_or_404(session, Conversation, ctx.org_id, conversation_id, label="Conversation", for_update=True)
    if conversation.status != ConversationStatus.CLOSED:
        conversation.status = ConversationStatus.CLOSED
        conversation.closed_at = utcnow()
        session.flush()
        audit.record(session, ctx, "conversation.closed", "conversation", conversation.id, {})
        _resolve_escalation(session, ctx, conversation, "Conversation closed.")
    return conversation


# ------------------------------------------------------------ background work


def _waiting_since(session: Session, conversation: Conversation) -> datetime | None:
    """Since when the sender has been waiting for a person, or None if the team had the last word.

    That is the escalation itself when no agent has replied since, otherwise the
    first message the sender wrote after the latest agent reply.
    """
    last_agent = session.scalar(
        select(func.max(Message.created_at)).where(
            Message.conversation_id == conversation.id,
            Message.org_id == conversation.org_id,
            Message.author == MessageAuthor.AGENT,
        )
    )
    escalated_at = conversation.escalated_at
    if last_agent is None or (escalated_at is not None and last_agent < escalated_at):
        return escalated_at or conversation.last_message_at
    return session.scalar(
        select(func.min(Message.created_at)).where(
            Message.conversation_id == conversation.id,
            Message.org_id == conversation.org_id,
            Message.direction == MessageDirection.INBOUND,
            Message.created_at > last_agent,
        )
    )


def _system_ctx(session: Session, org_id: uuid.UUID, cache: dict[uuid.UUID, Ctx]) -> Ctx:
    if org_id not in cache:
        cache[org_id] = Ctx(org=session.get(Organization, org_id), actor=Actor.system("worker"))
    return cache[org_id]


def sweep_escalations(session: Session, *, now=None, limit: int = 500) -> int:
    """Hand back to the assistant every escalated conversation nobody answered (all tenants).

    After ``assistant_escalation_handback_hours`` without a reply from the team,
    the sender gets a short "sorry for the wait" note, the assistant answers
    again, and the escalation alert is resolved. Until then the alert sweep keeps
    reminding the people on call. Safe to run repeatedly and from several
    workers. Returns how many conversations were handed back.
    """
    now = now or utcnow()
    hours = get_settings().assistant_escalation_handback_hours
    cutoff = now - timedelta(hours=hours)
    candidates = list(
        session.scalars(
            select(Conversation)
            .where(Conversation.status == ConversationStatus.ESCALATED, Conversation.escalated_at <= cutoff)
            .order_by(Conversation.escalated_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    contexts: dict[uuid.UUID, Ctx] = {}
    handed_back = 0
    for conversation in candidates:
        waiting_since = _waiting_since(session, conversation)
        if waiting_since is None or waiting_since > cutoff:
            continue  # the team replied, or the sender has not waited long enough yet
        ctx = _system_ctx(session, conversation.org_id, contexts)
        conversation.status = ConversationStatus.BOT
        message = Message(
            org_id=conversation.org_id,
            conversation_id=conversation.id,
            created_at=now,
            direction=MessageDirection.OUTBOUND,
            author=MessageAuthor.BOT,
            body=_text("handback", Locale(conversation.locale)),
            answered_by="template",
            delivery_status=DeliveryStatus.NOT_APPLICABLE,
        )
        _push(conversation, message)
        conversation.last_message_at = now
        session.add(message)
        session.flush()
        audit.record(
            session,
            ctx,
            "conversation.auto_handed_back",
            "conversation",
            conversation.id,
            {"waiting_since": waiting_since, "after_hours": hours, "message_id": message.id},
        )
        _resolve_escalation(
            session, ctx, conversation, f"No reply from the team in {hours:g} h; handed back to the assistant."
        )
        handed_back += 1
    return handed_back


def close_idle(session: Session, *, now=None) -> int:
    """Close conversations that have been quiet for a while (all tenants).

    Bot conversations close after ``assistant_idle_close_hours`` of silence.
    Escalated ones close too once the team had the last word and nobody wrote
    since; one where the sender is still waiting is left to ``sweep_escalations``.
    """
    now = now or utcnow()
    cutoff = now - timedelta(hours=get_settings().assistant_idle_close_hours)
    idle = list(
        session.scalars(
            select(Conversation).where(
                Conversation.status.in_([ConversationStatus.BOT, ConversationStatus.ESCALATED]),
                Conversation.last_message_at < cutoff,
            )
        )
    )
    contexts: dict[uuid.UUID, Ctx] = {}
    closed = 0
    for conversation in idle:
        if conversation.status == ConversationStatus.ESCALATED:
            if _waiting_since(session, conversation) is not None:
                continue
            ctx = _system_ctx(session, conversation.org_id, contexts)
            conversation.status = ConversationStatus.CLOSED
            conversation.closed_at = now
            session.flush()
            audit.record(session, ctx, "conversation.closed", "conversation", conversation.id, {"reason": "idle"})
            _resolve_escalation(session, ctx, conversation, "Conversation closed after the team replied.")
        else:
            conversation.status = ConversationStatus.CLOSED
            conversation.closed_at = now
        closed += 1
    session.flush()
    return closed
