"""The Ops Assistant: answers from approved knowledge, hands everything else to a person."""

import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.assistant.answerers import AnswererUnavailable, ClaudeAnswerer, KeywordAnswerer, KnowledgeView, Turn
from app.assistant.language import detect, is_emergency, wants_human
from app.enums import Locale
from tests.conftest import api_key

API = "/api/v1"


@pytest.fixture
def bot(client, portco, portco_headers):
    """Porto Sul (LATAM maritime, Portuguese) with one gate, an on-call person and two answers."""
    gate = client.post(f"{API}/sites", headers=portco_headers, json={"code": "GATE-2", "name": "Portão 2"}).json()
    client.post(
        f"{API}/contacts",
        headers=portco_headers,
        json={"name": "Ana Plantão", "role_label": "on_call_coordinator", "whatsapp": "+5513955550100", "locale": "pt"},
    )
    for entry in (
        {
            "title": "Horário do portão 2",
            "content": "O portão 2 funciona das 6h às 22h, todos os dias.",
            "keywords": ["horário", "portão", "abre", "fecha"],
            "locale": "pt",
            "site_id": gate["id"],
        },
        {
            "title": "Horario del portón 2",
            "content": "El portón 2 abre de 6 a 22 h todos los días.",
            "keywords": ["horario", "porton", "abre", "cierra"],
            "locale": "es",
        },
    ):
        assert client.post(f"{API}/assistant/knowledge", headers=portco_headers, json=entry).status_code == 201
    return {"key": api_key(client, portco_headers, ["messages:write"]), "headers": portco_headers}


def say(client, bot, text, sender="+5513900000001", **extra):
    body = {"channel": "whatsapp", "sender": sender, "body": text, **extra}
    response = client.post(f"{API}/assistant/inbound", headers=bot["key"], json=body)
    assert response.status_code == 200, response.text
    return response.json()


def alerts(client, bot):
    return client.get(f"{API}/alerts", headers=bot["headers"]).json()["items"]


class TestConversations:
    def test_answers_from_knowledge_in_the_senders_language(self, client, bot):
        pt = say(client, bot, "Que horário o portão 2 abre?")
        assert pt["locale"] == "pt" and "6h às 22h" in pt["reply"] and not pt["escalated"]
        es = say(client, bot, "Hola, a qué horario abre el portón 2?", sender="+5491100000002")
        assert es["locale"] == "es" and "6 a 22 h" in es["reply"]

    def test_unknown_question_goes_to_a_person(self, client, bot, provider):
        reply = say(client, bot, "Vocês aceitam pagamento em dinheiro?")
        assert reply["escalated"] and reply["status"] == "escalated"
        assert "pessoa da nossa equipe" in reply["reply"]
        [alert] = alerts(client, bot)
        assert alert["title"].startswith("Assistant needs a person")
        assert any(m.recipient == "+5513955550100" for m in provider.sent)

    def test_emergency_is_critical_and_still_alerts_after_handoff(self, client, bot):
        say(client, bot, "quero falar com atendente")
        reply = say(client, bot, "tem um caminhão pegando fogo no portão!")
        assert "emergência" in reply["reply"]
        severities = {a["severity"] for a in alerts(client, bot)}
        assert "critical" in severities

    def test_person_owns_escalated_conversation(self, client, bot):
        first = say(client, bot, "preciso falar com uma pessoa")
        assert first["escalated"]
        quiet = say(client, bot, "Que horário o portão 2 abre?")
        assert quiet["reply"] is None  # the bot does not talk over the person

        conversation = first["conversation_id"]
        reply = client.post(
            f"{API}/assistant/conversations/{conversation}/reply",
            headers=bot["headers"],
            json={"body": "Oi, aqui é a Ana."},
        )
        assert reply.status_code == 201 and reply.json()["delivery_status"] == "sent"
        back = client.post(f"{API}/assistant/conversations/{conversation}/hand-back", headers=bot["headers"])
        assert back.json()["status"] == "bot"
        assert "6h às 22h" in say(client, bot, "Que horário o portão 2 abre?")["reply"]

    def test_duplicate_webhook_delivery_returns_the_same_reply(self, client, bot):
        first = say(client, bot, "Que horário o portão 2 abre?", provider_message_id="wamid.1")
        again = say(client, bot, "Que horário o portão 2 abre?", provider_message_id="wamid.1")
        assert again["duplicate"] and again["reply"] == first["reply"] and again["message_id"] == first["message_id"]
        detail = client.get(f"{API}/assistant/conversations/{first['conversation_id']}", headers=bot["headers"]).json()
        assert len(detail["messages"]) == 2

    def test_media_and_empty_messages(self, client, bot):
        media = say(client, bot, "", has_media=True)
        assert "texto" in media["reply"]
        empty = client.post(
            f"{API}/assistant/inbound", headers=bot["key"], json={"channel": "whatsapp", "sender": "+1", "body": "  "}
        )
        assert empty.status_code == 422

    def test_closed_conversation_starts_fresh(self, client, bot):
        first = say(client, bot, "Que horário o portão 2 abre?")
        client.post(f"{API}/assistant/conversations/{first['conversation_id']}/close", headers=bot["headers"])
        second = say(client, bot, "Que horário o portão 2 abre?")
        assert second["conversation_id"] != first["conversation_id"]
        closed = client.post(
            f"{API}/assistant/conversations/{first['conversation_id']}/reply",
            headers=bot["headers"],
            json={"body": "x"},
        )
        assert closed.status_code == 409

    def test_one_sender_cannot_flood(self, client, bot):
        codes = [
            client.post(
                f"{API}/assistant/inbound",
                headers=bot["key"],
                json={"channel": "whatsapp", "sender": "+5513911111111", "body": "oi"},
            ).status_code
            for _ in range(21)
        ]
        assert codes[-1] == 429

    def test_only_message_keys_can_post_inbound(self, client, bot):
        user_call = client.post(
            f"{API}/assistant/inbound", headers=bot["headers"], json={"channel": "sms", "sender": "+1", "body": "hi"}
        )
        assert user_call.status_code == 403


class TestLanguage:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("What time does the gate open today?", Locale.EN),
            ("¿A qué hora abre el portón hoy?", Locale.ES),
            ("Que horas o portão abre hoje?", Locale.PT),
            ("Obrigado, você ajudou muito", Locale.PT),
            ("Muchas gracias señor", Locale.ES),
            ("ok", None),
        ],
    )
    def test_detect(self, text, expected):
        assert detect(text) == expected

    @pytest.mark.parametrize("text", ["There's a FIRE at gate 3", "hay un herido en el pad", "vazamento no tanque"])
    def test_emergencies(self, text):
        assert is_emergency(text)

    def test_handoff_requests(self):
        assert wants_human("can I talk to someone?")
        assert wants_human("quiero hablar con un operador")
        assert not wants_human("what time does the gate open")


ENTRIES = [
    KnowledgeView("e1", "Gate hours", "Gate 2 is open 6am to 10pm.", ("gate", "hours", "open"), Locale.EN, None),
    KnowledgeView("e2", "Pad 7 access", "Pad 7 trucks need a permit.", ("pad", "permit"), Locale.EN, "PAD-7"),
]


class TestKeywordAnswerer:
    def test_best_match(self):
        answer = KeywordAnswerer().answer("When is the gate open?", ENTRIES, Locale.EN, [])
        assert answer.entry_ids == ["e1"]

    def test_site_specific_entries_need_the_site(self):
        assert KeywordAnswerer().answer("do I need a permit", ENTRIES, Locale.EN, []) is None
        assert KeywordAnswerer().answer("do I need a permit for PAD-7", ENTRIES, Locale.EN, []).entry_ids == ["e2"]

    @pytest.mark.parametrize("question", ["permit for pad 7?", "permit for PAD-07", "permit at Pad 7 please"])
    def test_sites_are_matched_the_way_people_type_them(self, question):
        entries = [ENTRIES[0], KnowledgeView("e3", "Permit", "Pad 7 needs a permit.", ("permit",), Locale.EN, "PAD-07")]
        assert KeywordAnswerer().answer(question, entries, Locale.EN, []).entry_ids == ["e3"]

    def test_similar_site_numbers_do_not_match(self):
        entries = [KnowledgeView("e3", "Permit", "Pad 7 needs a permit.", ("permit",), Locale.EN, "PAD-07")]
        assert KeywordAnswerer().answer("permit for pad 17", entries, Locale.EN, []) is None
        assert KeywordAnswerer().answer("permit for pad 70", entries, Locale.EN, []) is None

    def test_unrelated_question(self):
        assert KeywordAnswerer().answer("Where can I buy lunch?", ENTRIES, Locale.EN, []) is None


def _patched(handler):
    """A real SDK client whose one API call is answered by ``handler``."""
    client = anthropic.Anthropic(api_key="test", max_retries=0, base_url="http://test")
    client.beta.messages.create = handler  # the only call the answerer makes
    return client


def message(payload, stop_reason="end_turn"):
    text = json.dumps(payload) if isinstance(payload, dict) else payload
    return SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)], _request_id="req_test"
    )


class TestClaudeAnswerer:
    def answerer(self, handler):
        return ClaudeAnswerer(org_name="Porto Sul", model="claude-opus-5-5", timeout=5, client=_patched(handler))

    def test_cited_answer_is_used_and_request_is_well_formed(self):
        seen = {}

        def handler(**kwargs):
            seen.update(kwargs)
            return message({"answerable": True, "needs_human": False, "answer": "6am to 10pm.", "entry_ids": ["e1"]})

        history = [Turn("assistant", "Hi!"), Turn("user", "hello"), Turn("user", "again")]
        answer = self.answerer(handler).answer("gate hours?", ENTRIES, Locale.EN, history)
        assert answer.text == "6am to 10pm." and answer.answered_by == "llm"
        assert seen["model"] == "claude-opus-5-5" and seen["fallbacks"] == "default"
        assert seen["output_config"]["format"]["type"] == "json_schema"
        roles = [m["role"] for m in seen["messages"]]
        assert roles == ["user"]  # leading assistant dropped, consecutive user turns merged
        assert "untrusted" in seen["system"][0]["text"]

    @pytest.mark.parametrize(
        "reply",
        [
            {"answerable": True, "needs_human": False, "answer": "Made up.", "entry_ids": ["e999"]},  # uncited
            {"answerable": False, "needs_human": False, "answer": "", "entry_ids": []},
            {"answerable": True, "needs_human": True, "answer": "x", "entry_ids": ["e1"]},
            "not json",
        ],
    )
    def test_declines(self, reply):
        assert self.answerer(lambda **_: message(reply)).answer("q", ENTRIES, Locale.EN, []) is None

    def test_refusal_and_truncation_decline(self):
        ok = {"answerable": True, "needs_human": False, "answer": "x", "entry_ids": ["e1"]}
        assert self.answerer(lambda **_: message(ok, "refusal")).answer("q", ENTRIES, Locale.EN, []) is None
        assert self.answerer(lambda **_: message(ok, "max_tokens")).answer("q", ENTRIES, Locale.EN, []) is None

    def test_outage_is_reported_so_the_keyword_answerer_takes_over(self):
        request = httpx.Request("POST", "http://test/v1/messages")

        def down(**_):
            raise anthropic.APIConnectionError(request=request)

        with pytest.raises(AnswererUnavailable):
            self.answerer(down).answer("q", ENTRIES, Locale.EN, [])

    def test_service_falls_back_when_claude_is_down(self, client, bot, monkeypatch):
        from app.assistant import service

        request = httpx.Request("POST", "http://test/v1/messages")

        def down(**_):
            raise anthropic.APIStatusError("overloaded", response=httpx.Response(529, request=request), body=None)

        monkeypatch.setattr(service, "default_answerers", lambda name: [self.answerer(down), KeywordAnswerer()])
        assert "6h às 22h" in say(client, bot, "Que horário o portão 2 abre?")["reply"]
