"""Loops the engine must close: no half-written requests, no silent escalations,
reminders for alerts nobody acknowledges, overdue work orders, failed deliveries."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db import system_session
from app.notify.dispatcher import deliver_pending
from app.notify.providers import DeliveryError
from app.services import notifications, sweeps
from app.units import format_number
from tests.test_assistant import alerts, bot, say  # noqa: F401
from tests.test_events_and_alerts import gas, post_event, setup  # noqa: F401

API = "/api/v1"


def audit_actions(client, headers):
    return [e["action"] for e in client.get(f"{API}/audit?limit=200", headers=headers).json()["items"]]


def test_a_failure_mid_request_leaves_nothing_behind(client, setup, monkeypatch):
    real = notifications.enqueue_for_alert

    def boom(*_a, **_k):
        raise RuntimeError("provider table unavailable")

    monkeypatch.setattr(notifications, "enqueue_for_alert", boom)
    with pytest.raises(RuntimeError):
        post_event(client, setup, gas(30), **{"Idempotency-Key": "dev-1"})
    monkeypatch.setattr(notifications, "enqueue_for_alert", real)

    # The device retries with the same key: the event is processed in full, not "duplicate".
    retry = post_event(client, setup, gas(30), **{"Idempotency-Key": "dev-1"}).json()
    assert retry["created"] is True
    [outcome] = retry["alerts"]
    assert outcome["notifications"] == 2 and outcome["work_order_id"]
    assert client.get(f"{API}/alerts", headers=setup["headers"]).json()["total"] == 1


def test_each_driver_escalation_is_its_own_alert_and_notifies(client, bot, provider):
    say(client, bot, "Vocês aceitam pagamento em dinheiro?", sender="+5513900000001")
    first = len(provider.sent)
    say(client, bot, "Vocês aceitam cartão de crédito na balança?", sender="+5513900000002")
    assert len(provider.sent) > first, "a second driver's escalation must reach on-call"
    assert len(alerts(client, bot)) == 2


def test_acknowledged_alert_gets_no_still_open_reminder(client, setup, provider, monkeypatch):
    alert_id = post_event(client, setup, gas(30)).json()["alerts"][0]["alert_id"]
    client.post(f"{API}/alerts/{alert_id}/acknowledge", headers=setup["headers"])
    before = len(provider.sent)
    import app.services.events as events

    real = events.utcnow
    monkeypatch.setattr(events, "utcnow", lambda: real() + timedelta(hours=2))
    post_event(client, setup, gas(30, occurred_at=real().isoformat()))
    assert len(provider.sent) == before


def test_escalation_reopens_an_acknowledged_alert(client, bot, provider):
    say(client, bot, "Vocês aceitam pagamento em dinheiro?")
    [alert] = alerts(client, bot)
    client.post(f"{API}/alerts/{alert['id']}/acknowledge", headers=bot["headers"])
    before = len(provider.sent)
    say(client, bot, "socorro, tem um caminhão pegando fogo no portão!")  # same driver, now an emergency
    [alert] = alerts(client, bot)
    assert alert["severity"] == "critical" and alert["status"] == "open"
    assert len(provider.sent) > before


def test_contacts_without_an_address_do_not_count_as_notified(client, setup):
    client.patch(
        f"{API}/contacts/{setup['lead']['id']}",
        headers=setup["headers"],
        json={"phone": None, "email": None, "whatsapp": "+17135550199"},
    )  # reachable on WhatsApp only; the gas rule sends SMS and email
    alert_id = post_event(client, setup, gas(30)).json()["alerts"][0]["alert_id"]
    assert "alert.no_recipients" in audit_actions(client, setup["headers"])
    alert = client.get(f"{API}/alerts/{alert_id}", headers=setup["headers"]).json()
    assert alert.get("last_notified_at") is None


def test_unacknowledged_alert_is_reminded_on_an_interval(client, setup, provider):
    alert_id = post_event(client, setup, gas(30)).json()["alerts"][0]["alert_id"]
    before = len(provider.sent)
    now = datetime.now(UTC)
    with system_session() as session:
        assert sweeps.sweep_alerts(session, now=now + timedelta(minutes=5)) == 0
    with system_session() as session:
        assert sweeps.sweep_alerts(session, now=now + timedelta(hours=1)) == 1
    deliver_pending(now=now + timedelta(hours=1))
    assert len(provider.sent) > before
    assert any("Still open" in m.subject for m in provider.sent[before:])
    assert "alert.reminder_sent" in audit_actions(client, setup["headers"])

    # Acknowledged: the reminders stop.
    client.post(f"{API}/alerts/{alert_id}/acknowledge", headers=setup["headers"])
    with system_session() as session:
        assert sweeps.sweep_alerts(session, now=now + timedelta(hours=3)) == 0


def test_overdue_work_order_is_reported_once(client, setup, provider):
    wo_id = post_event(client, setup, gas(30)).json()["alerts"][0]["work_order_id"]
    wo = client.get(f"{API}/work-orders/{wo_id}", headers=setup["headers"]).json()
    due = datetime.fromisoformat(wo["due_at"])
    before = len(provider.sent)
    with system_session() as session:
        assert sweeps.sweep_work_orders(session, now=due - timedelta(minutes=1)) == 0
    with system_session() as session:
        assert sweeps.sweep_work_orders(session, now=due + timedelta(minutes=5)) == 1
    with system_session() as session:
        assert sweeps.sweep_work_orders(session, now=due + timedelta(hours=5)) == 0
    deliver_pending(now=due + timedelta(minutes=5))
    overdue = [m for m in provider.sent[before:] if "past due" in m.subject]
    assert overdue, [m.subject for m in provider.sent[before:]]
    assert "work_order.overdue" in audit_actions(client, setup["headers"])


def test_done_work_order_is_never_reported_overdue(client, setup):
    wo_id = post_event(client, setup, gas(30)).json()["alerts"][0]["work_order_id"]
    client.post(
        f"{API}/work-orders/{wo_id}/transition", headers=setup["headers"], json={"status": "done", "note": "ok"}
    )
    with system_session() as session:
        assert sweeps.sweep_work_orders(session, now=datetime.now(UTC) + timedelta(days=3)) == 0


def test_a_delivery_that_finally_fails_is_on_the_record(client, setup, provider):
    provider.fail_with = DeliveryError("carrier down")
    post_event(client, setup, gas(30))
    later = datetime.now(UTC)
    for _ in range(25):
        later += timedelta(hours=1)
        deliver_pending(now=later)
    statuses = {n["status"] for n in client.get(f"{API}/notifications", headers=setup["headers"]).json()["items"]}
    assert statuses == {"failed"}
    assert "notification.failed" in audit_actions(client, setup["headers"])


def test_numbers_use_the_readers_separators_and_keep_small_readings():
    assert format_number(1234.5, "en") == "1,234.5"
    assert format_number(1234.5, "es") == "1.234,5"
    assert format_number(1240, "pt") == "1.240"
    assert format_number(0.004, "en") == "0.004"


def test_a_late_reading_is_labelled_late(client, setup, provider):
    an_hour_ago = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    post_event(client, setup, gas(30, occurred_at=an_hour_ago))
    assert any("Reported late" in m.body for m in provider.sent)
