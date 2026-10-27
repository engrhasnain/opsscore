"""Ops Assistant hardening: courtesy, matching precision, emergencies, hand-offs,
the escalation lifecycle, sender identity, rate limits and configuration guards."""

import json
from datetime import timedelta
from types import SimpleNamespace

import anthropic
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.assistant import service
from app.assistant.answerers import (
    AnswererUnavailable,
    ClaudeAnswerer,
    KeywordAnswerer,
    KnowledgeView,
)
from app.assistant.language import courtesy, detect, is_emergency, wants_human
from app.config import DEV_JWT_SECRET, Settings, get_settings
from app.db import system_session, utcnow
from app.demo_seed import CLIENTS
from app.enums import ConversationChannel, ConversationStatus, Locale, MessageAuthor, Module, Region
from app.models import AuditEntry, Conversation, Message
from app.schemas.assistant import InboundIn
from tests.conftest import api_key, make_tenant
from tests.test_assistant import API, ENTRIES, alerts, bot, say  # noqa: F401  (bot is a fixture)

# ------------------------------------------------------------------ 1. courtesy


class TestCourtesy:
    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("thanks", "thanks"),
            ("Thank you so much!", "thanks"),
            ("obrigado!", "thanks"),
            ("Obrigado, você ajudou muito", "thanks"),
            ("gracias", "thanks"),
            ("muchas gracias por la ayuda", "thanks"),
            ("hi", "greeting"),
            ("hola", "greeting"),
            ("Oi", "greeting"),
            ("Bom dia", "greeting"),
            ("ok", "ack"),
            ("👍", "ack"),
            ("😀😀", "ack"),
            ("ok 👍", "ack"),
        ],
    )
    def test_classified(self, text, kind):
        assert courtesy(text) == kind

    @pytest.mark.parametrize(
        "text",
        ["hola, a qué hora abre el pad 7?", "thanks, and where do I drop the ticket?", "ok gate 2", "pad 14"],
    )
    def test_questions_are_not_courtesy(self, text):
        assert courtesy(text) is None

    def test_thanks_gets_a_short_reply_and_never_escalates(self, client, bot, provider):
        assert "6h às 22h" in say(client, bot, "Que horário o portão 2 abre?")["reply"]
        sent = len(provider.sent)
        thanks = say(client, bot, "obrigado!")
        assert thanks["reply"] == "Por nada." and not thanks["escalated"] and thanks["status"] == "bot"
        ack = say(client, bot, "👍")
        assert ack["reply"] is None and not ack["escalated"]
        assert say(client, bot, "gracias")["reply"] == "De nada."
        assert len(provider.sent) == sent  # nobody was paged
        assert alerts(client, bot) == []

    def test_greeting_then_question_is_answered(self, client, bot):
        hello = say(client, bot, "hi", sender="+15045550101")
        assert hello["reply"] == "Hi! How can I help you?" and not hello["escalated"]
        answer = say(client, bot, "Hola, a qué horario abre el portón 2?", sender="+15045550101")
        assert "6 a 22 h" in answer["reply"]


# ------------------------------------------------------- 2. keyword precision


def _views(spec) -> list[KnowledgeView]:
    names = {s["code"]: s["name"] for s in spec.sites}
    return [
        KnowledgeView(
            a.title,
            a.title,
            a.content,
            tuple(k.casefold() for k in a.keywords),
            a.locale,
            a.site,
            names.get(a.site) if a.site else None,
        )
        for a in spec.answers
    ]


# Realistic questions for every approved answer of every demo client (titles are the ids).
DEMO_QUESTIONS = {
    "demo-permian-ridge": [
        ("What time does pad 14 open?", "Pad 14 gate hours"),
        ("When can I get into pad 22?", "Pad 22 gate hours"),
        ("Where do I drop the run ticket for my water haul?", "Water haul tickets"),
        ("Do I need an H2S card for orientation?", "H2S orientation"),
        ("What's the speed limit on the lease road?", "Lease road speed limit"),
        ("Where do I unload pipe?", "Where to unload pipe"),
        ("A que hora abre el pad 14?", "Horario del pad 14"),
        ("Dónde dejo el ticket del viaje de agua?", "Tickets de agua"),
    ],
    "demo-andes-energy": [
        ("Hola, cual es el horario de ingreso al pad 7?", "Horario de ingreso al pad 7"),
        ("A qué hora abre el pad 12?", "Horario de ingreso al pad 12"),
        ("Qué papeles necesito para entregar la carga?", "Remito de entrega"),
        ("Dónde descargo la arena?", "Dónde descargar arena y grava"),
        ("Está cortada la ruta 4?", "Corte en la ruta 4"),
        ("Qué elementos de protección necesito?", "Elementos de protección"),
        ("Cuál es la velocidad máxima?", "Velocidad máxima"),
        ("What time is pad 7 open?", "Pad 7 gate hours"),
    ],
    "demo-bayou-terminal": [
        ("What are the gate hours on Saturday?", "Gate hours"),
        ("What's the gate status today?", "Gate status today"),
        ("What's the wait at gate A right now?", "Gate status today"),
        ("I missed my appointment, how do I rebook?", "Rebook an appointment"),
        ("Where do I return an empty container?", "Empty container returns"),
        ("What documents do I need for a pickup?", "Documents for pickup"),
        ("Cuál es el estado del portón hoy?", "Estado del portón hoy"),
        ("When is the MSC Aurora arriving?", "Vessel ETA"),
        ("What's the ETA for the vessel at berth 2?", "Vessel ETA"),
        ("Cuándo llega el buque MSC Aurora?", "Llegada del buque"),
    ],
    # The strike-day flood from the demo console, plus one English question.
    "demo-terminal-atlantico": [
        ("Bom dia, o portão 1 está aberto hoje?", "Situação dos portões hoje"),
        ("Qual a situação da fila agora?", "Situação dos portões hoje"),
        ("Perdi minha janela por causa da greve, como reagendar?", "Reagendar janela"),
        ("Que documentos preciso para retirar o contêiner?", "Documentos para retirada"),
        ("Onde devolvo o vazio?", "Devolução de vazio"),
        ("Hola, el porton esta abierto hoy?", "Estado del portón hoy"),
        ("O portão 2 está com muita fila?", "Situação dos portões hoje"),
        ("Tem greve hoje? Posso entrar pelo portão 1?", "Situação dos portões hoje"),
        ("Minha janela era 8h, perdi. Como remarcar?", "Reagendar janela"),
        ("Quanto tempo de espera no portão hoje?", "Situação dos portões hoje"),
        ("Cual es el estado del porton ahora? hay mucha fila?", "Estado del portón hoy"),
        ("Is the gate open today?", "Gate status today"),
        ("Preciso de quais documentos para retirada de importação?", "Documentos para retirada"),
        ("Onde entregar o contêiner vazio?", "Devolução de vazio"),
        ("O portão está fechado por causa da greve?", "Situação dos portões hoje"),
        ("Perdi o agendamento, consigo reagendar sem custo?", "Reagendar janela"),
        ("Situação dos portões agora?", "Situação dos portões hoje"),
        ("Hola, hay paro? el porton esta cerrado?", "Estado del portón hoy"),
        ("Qual portão está aberto hoje?", "Situação dos portões hoje"),
        ("Onde devolvo vazio de 40 pés?", "Devolução de vazio"),
        ("Que documento preciso levar para retirar?", "Documentos para retirada"),
        ("A fila do portão 2 está andando?", "Situação dos portões hoje"),
        ("Perdi minha janela, como faço para reagendar?", "Reagendar janela"),
        ("O portão 1 abre hoje?", "Situação dos portões hoje"),
        ("What's the gate status now? Is there a strike?", "Gate status today"),
        ("Tem espera no portão hoje?", "Situação dos portões hoje"),
        ("Onde é a devolução de vazios?", "Devolução de vazio"),
        ("Situação da fila agora, por favor", "Situação dos portões hoje"),
        ("Qual a previsão de atracação do Maersk Santos?", "Previsão de atracação"),
        ("Quando o navio chega no berço 3?", "Previsão de atracação"),
        ("Cuándo llega el buque Maersk Santos?", "Llegada del buque"),
        ("When is the vessel arriving?", "Vessel ETA"),
    ],
}

# Questions that share a word with an answer but are about something else.
FALSE_POSITIVES = {
    "demo-bayou-terminal": [
        "My truck broke down at gate A",
        "The guard at gate A was rude to me",
        "my container is stuck at gate B closed lane, I am trapped",
        "I will be late, my truck has a flat tire",
        "I need a tow truck",
        "Is there somewhere to sleep in the truck overnight?",
    ],
    "demo-permian-ridge": [
        "I got a speeding ticket on the lease road",
        "My truck broke down on the lease road",
        "Is there somewhere to sleep in the truck overnight?",
    ],
}

_CLIENTS = {spec.slug: spec for spec in CLIENTS}


class TestKeywordPrecision:
    def test_every_demo_answer_has_a_question(self):
        for spec in CLIENTS:
            asked = {title for _q, title in DEMO_QUESTIONS[spec.slug]}
            assert asked == {a.title for a in spec.answers}, spec.slug

    @pytest.mark.parametrize(
        ("slug", "question", "title"),
        [(slug, q, title) for slug, pairs in DEMO_QUESTIONS.items() for q, title in pairs],
    )
    def test_demo_questions_get_the_right_answer(self, slug, question, title):
        spec = _CLIENTS[slug]
        locale = detect(question) or spec.locale
        answer = KeywordAnswerer().answer(question, _views(spec), locale, [])
        assert answer is not None and answer.entry_ids == [title]

    @pytest.mark.parametrize(
        ("slug", "question"),
        [(slug, q) for slug, questions in FALSE_POSITIVES.items() for q in questions],
    )
    def test_shared_words_are_not_enough(self, slug, question):
        assert KeywordAnswerer().answer(question, _views(_CLIENTS[slug]), Locale.EN, []) is None

    def test_detected_language_is_preferred(self):
        entries = [
            KnowledgeView("en", "Gate hours", "Open 6 to 22.", ("gate", "hours", "open"), Locale.EN, None),
            KnowledgeView(
                "pt", "Horário do portão", "Abre das 6h às 22h.", ("horario", "portao", "abre"), Locale.PT, None
            ),
        ]
        question = "Que horário abre o portão?"
        assert KeywordAnswerer().answer(question, entries, detect(question), []).entry_ids == ["pt"]


# ---------------------------------------------------------- 3. emergencies


class TestEmergencies:
    @pytest.mark.parametrize(
        "text",
        [
            "there are fires at tank 3",
            "help! man down",
            "HELP",
            "I need help",
            "smoke coming from the truck",
            "oil spilled on the road",
            "injuries at pad 7",
            "trapped",
            "socorro",
            "ayuda, se cayó un trabajador",
            "está vazando gás",
            "derramó gasoil en el pad",
            "incêndio no pátio",
            "explosión en el tanque",
            "motorista ferido",
            "hay un herido",
            "my h2s monitor is going off",
            "H2S!",
            "is there a fire extinguisher at gate 3?",  # safety first: a false alarm is fine
        ],
    )
    def test_detected(self, text):
        assert is_emergency(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Do I need an H2S card?",
            "my battery is dead",
            "estou preso na fila há 5 horas",
            "can you help me rebook my appointment?",
            "thanks for the help",
            "where is the smoking area",
            "the firewall blocked my login",
            "What time does pad 14 open?",
        ],
    )
    def test_routine_messages_are_not(self, text):
        assert not is_emergency(text)

    def test_emergency_in_a_conversation_still_escalates(self, client, bot):
        reply = say(client, bot, "help! man down at gate 2")
        assert reply["escalated"] and "emergency number" in reply["reply"]
        assert {a["severity"] for a in alerts(client, bot)} == {"critical"}


# ------------------------------------------------------------ 4. hand-offs


class TestWantsHuman:
    @pytest.mark.parametrize(
        "text",
        [
            "can I talk to someone?",
            "I want to speak with a person",
            "real person please",
            "quiero hablar con un operador",
            "necesito una persona real",
            "quero falar com atendente",
            "preciso falar com uma pessoa",
            "atendente",
            "agent",
        ],
    )
    def test_explicit_requests(self, text):
        assert wants_human(text)

    @pytest.mark.parametrize(
        "text",
        [
            "someone told me the gate opens at 6",
            "my supervisor sent me to pad 7",
            "is the customs agent at gate A?",
            "the person at the gate",
            "what time does the gate open",
        ],
    )
    def test_mentions_are_not_requests(self, text):
        assert not wants_human(text)


# --------------------------------------------------------------- 5. Claude


def _client(handler):
    sdk = anthropic.Anthropic(api_key="test", max_retries=0, base_url="http://test")
    sdk.beta.messages.create = handler
    return sdk


def _reply(payload):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        _request_id="req_test",
    )


class TestClaudeAnswerer:
    def answerer(self, handler):
        return ClaudeAnswerer(org_name="Porto Sul", model="claude-opus-5-5", timeout=5, client=_client(handler))

    @pytest.mark.parametrize("error", [TypeError("Could not resolve authentication method"), RuntimeError("boom")])
    def test_any_failure_is_reported_as_unavailable(self, error):
        def broken(**_):
            raise error

        with pytest.raises(AnswererUnavailable):
            self.answerer(broken).answer("gate hours?", ENTRIES, Locale.EN, [])

    def test_missing_api_key_falls_back_instead_of_500(self, client, bot, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        keyless = ClaudeAnswerer(
            org_name="Porto Sul",
            model="claude-opus-5-5",
            timeout=1,
            client=anthropic.Anthropic(api_key=None, base_url="http://127.0.0.1:9", max_retries=0),
        )
        monkeypatch.setattr(service, "default_answerers", lambda name: [keyless, KeywordAnswerer()])
        assert "6h às 22h" in say(client, bot, "Que horário o portão 2 abre?")["reply"]

    def test_site_answers_need_the_site_named(self):
        cites_pad = {"answerable": True, "needs_human": False, "answer": "Bring a permit.", "entry_ids": ["e2"]}
        answerer = self.answerer(lambda **_: _reply(cites_pad))
        assert answerer.answer("do I need a permit?", ENTRIES, Locale.EN, []) is None
        assert answerer.answer("do I need a permit for pad 7?", ENTRIES, Locale.EN, []).entry_ids == ["e2"]

    def test_one_client_is_reused(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "assistant_llm_enabled", True)
        monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("sk-test"))
        first = service.default_answerers("A")[0]
        second = service.default_answerers("B")[0]
        assert isinstance(first, ClaudeAnswerer) and first.client is second.client


class TestConfiguration:
    def test_llm_needs_an_api_key(self):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            Settings(assistant_llm_enabled=True, anthropic_api_key=None, _env_file=None)
        assert Settings(assistant_llm_enabled=True, anthropic_api_key="sk-test", _env_file=None).anthropic_api_key

    def test_dev_secret_is_refused_outside_sqlite(self):
        with pytest.raises(ValueError, match="development secret"):
            Settings(database_url="postgresql+psycopg://app@db/opscore", jwt_secret=DEV_JWT_SECRET, _env_file=None)
        assert Settings(database_url="postgresql+psycopg://app@db/opscore", jwt_secret="y" * 40, _env_file=None)
        assert Settings(database_url="sqlite://", jwt_secret=DEV_JWT_SECRET, _env_file=None)


# ---------------------------------------------------- 6. escalation lifecycle


def _escalate(client, bot, sender="+5513900000001"):
    reply = say(client, bot, "Vocês aceitam pagamento em dinheiro?", sender=sender)
    assert reply["escalated"]
    return reply["conversation_id"]


def _alert_status(client, bot):
    [alert] = alerts(client, bot)
    return alert["status"]


def _sweep(hours: float) -> int:
    with system_session() as session:
        return service.sweep_escalations(session, now=utcnow() + timedelta(hours=hours))


class TestEscalationLifecycle:
    def test_agent_reply_acknowledges_and_hand_back_resolves(self, client, bot):
        conversation = _escalate(client, bot)
        assert _alert_status(client, bot) == "open"
        reply = client.post(
            f"{API}/assistant/conversations/{conversation}/reply", headers=bot["headers"], json={"body": "Olá!"}
        )
        assert reply.status_code == 201
        assert _alert_status(client, bot) == "acknowledged"
        client.post(f"{API}/assistant/conversations/{conversation}/hand-back", headers=bot["headers"])
        assert _alert_status(client, bot) == "resolved"

    def test_close_resolves(self, client, bot):
        conversation = _escalate(client, bot)
        client.post(f"{API}/assistant/conversations/{conversation}/close", headers=bot["headers"])
        assert _alert_status(client, bot) == "resolved"

    def test_messages_into_an_escalated_chat_are_kept(self, client, bot):
        conversation = _escalate(client, bot)
        quiet = say(client, bot, "alguém aí?")
        assert quiet["reply"] is None and quiet["conversation_id"] == conversation
        detail = client.get(f"{API}/assistant/conversations/{conversation}", headers=bot["headers"]).json()
        assert detail["messages"][-1]["body"] == "alguém aí?"

    def test_blank_agent_reply_is_rejected(self, client, bot):
        conversation = _escalate(client, bot)
        for body in ("   ", "\n\t"):
            response = client.post(
                f"{API}/assistant/conversations/{conversation}/reply", headers=bot["headers"], json={"body": body}
            )
            assert response.status_code == 422

    def test_unanswered_conversation_is_handed_back_once(self, client, bot, provider):
        conversation = _escalate(client, bot)
        assert _sweep(hours=7) == 0
        sent = len(provider.sent)
        assert _sweep(hours=9) == 1
        assert _sweep(hours=9.5) == 0  # idempotent
        detail = client.get(f"{API}/assistant/conversations/{conversation}", headers=bot["headers"]).json()
        assert detail["status"] == "bot"
        note = detail["messages"][-1]
        assert note["author"] == "bot" and note["body"].startswith("Desculpe a demora")
        assert note["delivery_status"] == "sent"
        assert [m.recipient for m in provider.sent[sent:]] == ["+5513900000001"]
        assert _alert_status(client, bot) == "resolved"
        with system_session() as session:
            actions = session.scalars(select(AuditEntry.action).where(AuditEntry.entity_id == conversation)).all()
        assert "conversation.auto_handed_back" in actions
        # The assistant answers again.
        assert "6h às 22h" in say(client, bot, "Que horário o portão 2 abre?")["reply"]

    def test_answered_conversation_is_not_handed_back_until_the_sender_waits(self, client, bot):
        conversation = _escalate(client, bot)
        client.post(f"{API}/assistant/conversations/{conversation}/reply", headers=bot["headers"], json={"body": "Oi"})
        assert _sweep(hours=9) == 0
        say(client, bot, "e então?")
        assert _sweep(hours=7) == 0
        assert _sweep(hours=9) == 1

    def test_sweep_covers_every_tenant(self, client, bot):
        _escalate(client, bot)
        other = make_tenant("other-port", region=Region.LATAM, modules=(Module.ASSISTANT,))
        with system_session() as session:
            session.add(other.org)
            service.handle_inbound(
                session,
                other.ctx(),
                InboundIn(channel=ConversationChannel.SMS, sender="+5491100000009", body="Tienen baño para choferes?"),
            )
        assert _sweep(hours=9) == 2
        with system_session() as session:
            statuses = set(session.scalars(select(Conversation.status)))
        assert statuses == {ConversationStatus.BOT}

    def test_close_idle_closes_escalations_the_team_answered(self, client, bot):
        answered = _escalate(client, bot, sender="+5513900000001")
        client.post(f"{API}/assistant/conversations/{answered}/reply", headers=bot["headers"], json={"body": "Ok"})
        waiting = _escalate(client, bot, sender="+5513900000002")
        with system_session() as session:
            assert service.close_idle(session, now=utcnow() + timedelta(hours=25)) == 1
            statuses = {str(c.id): c.status for c in session.scalars(select(Conversation))}
        assert statuses == {answered: ConversationStatus.CLOSED, waiting: ConversationStatus.ESCALATED}


# ------------------------------------------------------- 7. member privacy


class TestMemberPrivacy:
    def test_adding_another_clients_user_reveals_nothing(self, client, acme, acme_headers):
        other = make_tenant("other-co")
        existing = client.post(
            f"{API}/members",
            headers=acme_headers,
            json={
                "email": other.owner_email,
                "full_name": "Typed Name",
                "role": "viewer",
                "password": "long-enough-pw-1",
            },
        )
        new = client.post(
            f"{API}/members",
            headers=acme_headers,
            json={
                "email": "brand-new@acme.example.com",
                "full_name": "Typed Name",
                "role": "viewer",
                "password": "long-enough-pw-1",
            },
        )
        assert existing.status_code == new.status_code == 201
        assert existing.json()["full_name"] == "Typed Name"  # not "Owner other-co"
        assert set(existing.json()) == set(new.json())

    def test_same_inputs_are_required_either_way(self, client, acme, acme_headers):
        other = make_tenant("other-co")
        for email in (other.owner_email, "nobody@nowhere.example.com"):
            response = client.post(
                f"{API}/members", headers=acme_headers, json={"email": email, "full_name": "x", "role": "viewer"}
            )
            assert response.status_code == 422
            assert response.json()["error"]["message"] == "A password is required for a new account."


# ---------------------------------------------------- 8. sender identity


class TestSenders:
    def test_one_phone_one_conversation(self, client, bot):
        ids = {
            say(client, bot, "Que horário o portão 2 abre?", sender=sender)["conversation_id"]
            for sender in ("+5513900000001", "+55 13 90000-0001", "whatsapp:+5513900000001", "0055 13 900000001")
        }
        assert len(ids) == 1
        with system_session() as session:
            assert set(session.scalars(select(Conversation.external_ref))) == {"+5513900000001"}

    @pytest.mark.parametrize("sender", ["12345", "whatsapp:abc", "+0123", "hello"])
    def test_invalid_numbers_are_rejected(self, client, bot, sender):
        response = client.post(
            f"{API}/assistant/inbound",
            headers=bot["key"],
            json={"channel": "whatsapp", "sender": sender, "body": "oi"},
        )
        assert response.status_code == 422

    def test_app_channels_keep_their_ids(self):
        assert InboundIn(channel=ConversationChannel.WEB, sender=" user-42 ", body="hi").sender == "user-42"


# ------------------------------------------------------ 9. rate limits


class TestRateLimits:
    def test_emergencies_are_never_dropped_by_the_sender_limit(self, client, bot):
        sender = "+5513911111111"
        for _ in range(20):
            client.post(
                f"{API}/assistant/inbound",
                headers=bot["key"],
                json={"channel": "whatsapp", "sender": sender, "body": "oi"},
            )
        limited = client.post(
            f"{API}/assistant/inbound", headers=bot["key"], json={"channel": "whatsapp", "sender": sender, "body": "oi"}
        )
        assert limited.status_code == 429
        emergency = client.post(
            f"{API}/assistant/inbound",
            headers=bot["key"],
            json={"channel": "whatsapp", "sender": sender, "body": "socorro, caminhão pegando fogo"},
        )
        assert emergency.status_code == 200 and emergency.json()["escalated"]

    def test_webhook_retries_do_not_count(self, client, bot):
        body = {"channel": "whatsapp", "sender": "+5513922222222", "body": "Que horário o portão 2 abre?"}
        codes = {
            client.post(
                f"{API}/assistant/inbound", headers=bot["key"], json={**body, "provider_message_id": "wamid.same"}
            ).status_code
            for _ in range(30)
        }
        assert codes == {200}


# ---------------------------------------------------------- 10. language


class TestLanguageDetection:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Que horário abre?", Locale.PT),
            ("Oi", Locale.PT),
            ("Está aberto?", Locale.PT),
            ("Tem fila hoje?", Locale.PT),
            ("Onde devolvo o contêiner vazio?", Locale.PT),
            ("O caminhão pode entrar?", Locale.PT),
            ("Hola", Locale.ES),
            ("hay fila?", Locale.ES),
            ("¿Dónde dejo el contenedor vacío?", Locale.ES),
            ("El camión puede entrar?", Locale.ES),
            ("Is the gate open?", Locale.EN),
        ],
    )
    def test_short_messages(self, text, expected):
        assert detect(text) == expected

    def test_portuguese_in_a_spanish_default_org_is_answered_in_portuguese(self, client, bot):
        reply = say(client, bot, "Que horário o portão 2 abre?")
        assert reply["locale"] == "pt"
        with system_session() as session:
            [conversation] = session.scalars(select(Conversation)).all()
            bot_reply = session.scalars(
                select(Message).where(Message.author == MessageAuthor.BOT, Message.conversation_id == conversation.id)
            ).first()
        assert "6h às 22h" in bot_reply.body


# --------------------------------------------------- api keys still needed


def test_inbound_still_requires_a_message_key(client, portco, portco_headers):
    key = api_key(client, portco_headers, ["events:write"])
    response = client.post(
        f"{API}/assistant/inbound", headers=key, json={"channel": "sms", "sender": "+5513900000001", "body": "oi"}
    )
    assert response.status_code == 403
