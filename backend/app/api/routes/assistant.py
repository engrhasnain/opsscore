"""Ops Assistant: knowledge base, the inbound webhook, and the agent console."""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from sqlalchemy import select

from app.api.deps import DB, PageParams, require
from app.api.routes.operations import schedule_delivery
from app.assistant import knowledge, language
from app.assistant import service as assistant
from app.enums import ConversationStatus, Locale, Module
from app.models import Conversation, KnowledgeEntry, Message
from app.schemas.assistant import (
    AgentReplyIn,
    ConversationDetailOut,
    ConversationOut,
    InboundIn,
    InboundOut,
    KnowledgeCreateIn,
    KnowledgeOut,
    KnowledgeUpdateIn,
    MessageOut,
)
from app.schemas.common import Page
from app.services.context import Ctx
from app.services.permissions import Permission
from app.services.scoping import get_or_404, paginate, scoped

router = APIRouter(prefix="/assistant", tags=["assistant"])

_A = Module.ASSISTANT
Reader = Annotated[Ctx, Depends(require(Permission.READ, module=_A))]
Configurer = Annotated[Ctx, Depends(require(Permission.CONFIGURE, module=_A))]
Handler = Annotated[Ctx, Depends(require(Permission.CONVERSATIONS_HANDLE, module=_A))]
Inbound = Annotated[Ctx, Depends(require(Permission.ASSISTANT_INBOUND, module=_A))]


def _page(session, stmt, page) -> Page:
    items, total = paginate(session, stmt, limit=page.limit, offset=page.offset)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


# --------------------------------------------------------------- knowledge


@router.get("/knowledge", response_model=Page[KnowledgeOut])
def list_knowledge(ctx: Reader, session: DB, page: PageParams, locale: Locale | None = None):
    stmt = scoped(KnowledgeEntry, ctx.org_id).order_by(KnowledgeEntry.title)
    if locale is not None:
        stmt = stmt.where(KnowledgeEntry.locale == locale)
    return _page(session, stmt, page)


@router.post("/knowledge", response_model=KnowledgeOut, status_code=status.HTTP_201_CREATED)
def create_knowledge(body: KnowledgeCreateIn, ctx: Configurer, session: DB):
    entry = knowledge.create(session, ctx, body)
    session.commit()
    return entry


@router.patch("/knowledge/{entry_id}", response_model=KnowledgeOut)
def update_knowledge(entry_id: uuid.UUID, body: KnowledgeUpdateIn, ctx: Configurer, session: DB):
    entry = knowledge.update(session, ctx, entry_id, body)
    session.commit()
    return entry


@router.delete("/knowledge/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge(entry_id: uuid.UUID, ctx: Configurer, session: DB) -> None:
    knowledge.delete(session, ctx, entry_id)
    session.commit()


# ----------------------------------------------------------------- inbound


@router.post("/inbound", response_model=InboundOut)
def inbound(body: InboundIn, ctx: Inbound, session: DB, request: Request, background: BackgroundTasks):
    """Called by the messaging integration for every message a sender writes.

    The reply comes back in the response for the integration to send. Resending
    the same ``provider_message_id`` returns the original reply.
    """
    limits = request.app.state
    limits.inbound_limiter.hit(f"org:{ctx.org_id}")
    # A webhook retry is answered from the record and never counts against the sender.
    result = assistant.find_duplicate(session, ctx, body.provider_message_id) if body.provider_message_id else None
    if result is None:
        # One sender cannot run up the bill, but a report of danger always gets through.
        if not language.is_emergency(body.body):
            limits.sender_limiter.hit(f"sender:{ctx.org_id}:{body.channel}:{body.sender}")
        result = assistant.handle_inbound(session, ctx, body)
    session.commit()
    schedule_delivery(background, result.pending_notification_ids)
    return InboundOut(
        conversation_id=result.conversation.id,
        message_id=result.message.id,
        status=result.conversation.status,
        reply=result.reply.body if result.reply else None,
        reply_message_id=result.reply.id if result.reply else None,
        escalated=result.escalated,
        duplicate=result.duplicate,
        locale=result.conversation.locale,
    )


# ----------------------------------------------------------- conversations


@router.get("/conversations", response_model=Page[ConversationOut])
def list_conversations(
    ctx: Reader,
    session: DB,
    page: PageParams,
    conv_status: Annotated[list[ConversationStatus] | None, Query(alias="status")] = None,
):
    stmt = scoped(Conversation, ctx.org_id).order_by(Conversation.last_message_at.desc())
    if conv_status:
        stmt = stmt.where(Conversation.status.in_(conv_status))
    return _page(session, stmt, page)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(conversation_id: uuid.UUID, ctx: Reader, session: DB):
    conversation = get_or_404(session, Conversation, ctx.org_id, conversation_id, label="Conversation")
    messages = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id, Message.org_id == ctx.org_id)
        .order_by(Message.created_at)
        .limit(1000)
    )
    return ConversationDetailOut(
        **ConversationOut.model_validate(conversation).model_dump(),
        messages=[MessageOut.model_validate(m) for m in messages],
    )


@router.post("/conversations/{conversation_id}/reply", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def reply(conversation_id: uuid.UUID, body: AgentReplyIn, ctx: Handler, session: DB):
    message = assistant.agent_reply(session, ctx, conversation_id, body.body)
    session.commit()
    return message


@router.post("/conversations/{conversation_id}/hand-back", response_model=ConversationOut)
def hand_back(conversation_id: uuid.UUID, ctx: Handler, session: DB):
    conversation = assistant.hand_back(session, ctx, conversation_id)
    session.commit()
    return conversation


@router.post("/conversations/{conversation_id}/close", response_model=ConversationOut)
def close(conversation_id: uuid.UUID, ctx: Handler, session: DB):
    conversation = assistant.close(session, ctx, conversation_id)
    session.commit()
    return conversation
