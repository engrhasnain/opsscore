"""Event intake through alerts, work orders and notifications."""

from datetime import UTC, datetime, timedelta

import pytest

from app.enums import NotificationStatus
from app.notify.dispatcher import backoff, deliver_pending
from app.notify.providers import DeliveryError
from tests.conftest import api_key

API = "/api/v1"


@pytest.fixture
def setup(client, acme_headers):
    """Acme (US oil & gas, starter pack): one pad, one tank battery, a safety lead."""
    site = client.post(
        f"{API}/sites",
        headers=acme_headers,
        json={"code": "pad-1", "name": "Pad 1", "kind": "well_pad", "timezone": "America/Denver"},
    ).json()
    asset = client.post(
        f"{API}/assets",
        headers=acme_headers,
        json={
            "site_code": "PAD-1",
            "code": "TB-1",
            "name": "Tank battery 1",
            "asset_type": "tank_battery",
            "criticality": 4,
        },
    ).json()
    lead = client.post(
        f"{API}/contacts",
        headers=acme_headers,
        json={
            "name": "Sam Safety",
            "role_label": "Safety_Lead",
            "phone": "+1 713 555 0100",
            "email": "sam@acme.example.com",
        },
    ).json()
    key = api_key(client, acme_headers, ["events:write", "events:read"])
    return {"site": site, "asset": asset, "lead": lead, "key": key, "headers": acme_headers}


def gas(ppm, **extra):
    return {"event_type": "gas_detection", "asset_code": "tb-1", "attributes": {"gas": "h2s", "ppm": ppm}, **extra}


def post_event(client, setup, body, **headers):
    return client.post(f"{API}/events", headers={**setup["key"], **headers}, json=body)


class TestIntake:
    def test_threshold_breach_raises_alert_work_order_and_notifications(self, client, setup, provider):
        response = post_event(client, setup, gas(25))
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["created"] is True
        assert body["event"]["site_id"] == setup["site"]["id"]  # site inferred from the asset
        [outcome] = body["alerts"]
        assert outcome["outcome"] == "created"
        assert outcome["severity"] == "critical"  # rule override
        assert outcome["notifications"] == 2  # sms + email
        assert outcome["work_order_id"]

        sent = {m.channel.value: m for m in provider.sent}
        assert set(sent) == {"sms", "email"}
        assert sent["sms"].recipient == "+17135550100"
        assert "[CRITICAL]" in sent["email"].subject
        assert "MDT" not in sent["email"].body and "America/Denver" in sent["email"].body

        wo = client.get(f"{API}/work-orders/{outcome['work_order_id']}", headers=setup["headers"]).json()
        assert wo["title"] == "Investigate h2s reading at Pad 1"
        assert wo["priority"] == "urgent" and wo["due_at"]

    def test_below_threshold_is_stored_but_raises_nothing(self, client, setup, provider):
        body = post_event(client, setup, gas(3)).json()
        assert body["alerts"] == [] and provider.sent == []
        assert client.get(f"{API}/events", headers=setup["key"]).json()["total"] == 1

    def test_storm_of_repeats_folds_into_one_alert(self, client, setup, provider):
        for _ in range(5):
            post_event(client, setup, gas(30))
        alerts = client.get(f"{API}/alerts", headers=setup["headers"]).json()
        assert alerts["total"] == 1
        assert alerts["items"][0]["occurrence_count"] == 5
        assert len(provider.sent) == 2  # notified once, not five times
        detail = client.get(f"{API}/alerts/{alerts['items'][0]['id']}", headers=setup["headers"]).json()
        assert len(detail["events"]) == 5

    def test_higher_severity_re_notifies(self, client, setup, provider):
        client.post(
            f"{API}/rules",
            headers=setup["headers"],
            json={
                "name": "Any spill",
                "event_type": "spill",
                "actions": [{"type": "notify", "channels": ["sms"], "contact_roles": ["safety_lead"]}],
            },
        )
        post_event(client, setup, {"event_type": "spill", "site_code": "PAD-1", "severity": "medium"})
        post_event(client, setup, {"event_type": "spill", "site_code": "PAD-1", "severity": "low"})
        sms_count = len([m for m in provider.sent if m.channel == "sms"])
        result = post_event(client, setup, {"event_type": "spill", "site_code": "PAD-1", "severity": "critical"}).json()
        outcomes = {o["outcome"] for o in result["alerts"]}
        assert "escalated" in outcomes
        assert len([m for m in provider.sent if m.channel == "sms"]) > sms_count
        assert any("Severity raised" in m.subject for m in provider.sent)

    def test_resolved_alert_is_not_reused(self, client, setup):
        first = post_event(client, setup, gas(30)).json()["alerts"][0]["alert_id"]
        client.post(f"{API}/alerts/{first}/resolve", headers=setup["headers"], json={"note": "vented"})
        second = post_event(client, setup, gas(30)).json()["alerts"][0]
        assert second["outcome"] == "created" and second["alert_id"] != first
        reopen = client.post(f"{API}/alerts/{first}/reopen", headers=setup["headers"])
        assert reopen.status_code == 409 and reopen.json()["error"]["code"] == "LIVE_ALERT_EXISTS"

    def test_contact_without_a_channel_is_recorded_as_skipped(self, client, setup):
        client.patch(f"{API}/contacts/{setup['lead']['id']}", headers=setup["headers"], json={"phone": None})
        post_event(client, setup, gas(30))
        notes = client.get(f"{API}/notifications", headers=setup["headers"]).json()["items"]
        skipped = [n for n in notes if n["status"] == "skipped"]
        assert len(skipped) == 1 and "no sms address" in skipped[0]["last_error"]

    def test_rule_with_nobody_to_notify_is_audited(self, client, setup):
        client.patch(f"{API}/contacts/{setup['lead']['id']}", headers=setup["headers"], json={"is_active": False})
        post_event(client, setup, gas(30))
        entries = client.get(f"{API}/audit?action=alert.no_recipients", headers=setup["headers"]).json()
        assert entries["total"] == 1

    def test_recipient_language_and_client_units(self, client, setup, provider):
        client.patch(f"{API}/contacts/{setup['lead']['id']}", headers=setup["headers"], json={"locale": "es"})
        client.patch(f"{API}/organization", headers=setup["headers"], json={"unit_system": "metric"})
        client.post(
            f"{API}/rules",
            headers=setup["headers"],
            json={
                "name": "Big spill",
                "event_type": "spill",
                "actions": [{"type": "notify", "channels": ["email"], "contact_roles": ["safety_lead"]}],
            },
        )
        post_event(client, setup, {"event_type": "spill", "site_code": "PAD-1", "attributes": {"volume": 100}})
        email = next(m for m in provider.sent if m.channel == "email")
        assert email.subject.startswith("[ALTA]")
        assert "Sitio: Pad 1 (PAD-1)" in email.body
        assert "15,9 m3" in email.body  # 100 bbl shown in cubic metres, with a Spanish decimal comma


class TestIdempotency:
    def test_retry_with_same_key_returns_original(self, client, setup, provider):
        first = post_event(client, setup, gas(30), **{"Idempotency-Key": "dev-42-0001"})
        again = post_event(client, setup, gas(30), **{"Idempotency-Key": "dev-42-0001"})
        assert first.status_code == 201 and again.status_code == 200
        assert again.json()["created"] is False
        assert again.json()["event"]["id"] == first.json()["event"]["id"]
        assert again.json()["alerts"][0]["outcome"] == "duplicate"
        assert len(provider.sent) == 2

    def test_reusing_a_key_for_a_different_event_is_refused(self, client, setup):
        post_event(client, setup, gas(30, idempotency_key="k1"))
        clash = post_event(client, setup, {"event_type": "spill", "site_code": "PAD-1", "idempotency_key": "k1"})
        assert clash.status_code == 409

    def test_header_and_body_keys_must_agree(self, client, setup):
        response = post_event(client, setup, gas(30, idempotency_key="a"), **{"Idempotency-Key": "b"})
        assert response.status_code == 422


class TestRejections:
    @pytest.mark.parametrize(
        ("body", "code"),
        [
            ({"event_type": "nope"}, "UNKNOWN_EVENT_TYPE"),
            (gas(5, asset_code="NOPE"), "UNKNOWN_ASSET"),
            (gas(5, site_code="NOPE"), "UNKNOWN_SITE"),
            ({**gas(5), "attributes": {"gas": "h2s"}}, "VALIDATION_FAILED"),
            ({**gas(5), "attributes": {"gas": "h2s", "ppm": "lots"}}, "VALIDATION_FAILED"),
            ({**gas(5), "occurred_at": "2026-01-01T10:00:00"}, "VALIDATION_FAILED"),  # no time zone
        ],
    )
    def test_bad_events(self, client, setup, body, code):
        response = post_event(client, setup, body)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == code

    def test_clock_problems(self, client, setup):
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        stale = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        assert post_event(client, setup, gas(5, occurred_at=future)).json()["error"]["code"] == "EVENT_IN_FUTURE"
        assert post_event(client, setup, gas(5, occurred_at=stale)).json()["error"]["code"] == "EVENT_TOO_OLD"

    def test_asset_must_be_at_the_named_site(self, client, setup):
        client.post(f"{API}/sites", headers=setup["headers"], json={"code": "PAD-2", "name": "Pad 2"})
        response = post_event(client, setup, gas(5, site_code="PAD-2"))
        assert response.json()["error"]["code"] == "ASSET_NOT_AT_SITE"

    def test_deactivated_places_refuse_events(self, client, setup):
        client.patch(f"{API}/sites/{setup['site']['id']}", headers=setup["headers"], json={"is_active": False})
        assert post_event(client, setup, gas(5)).json()["error"]["code"] == "SITE_INACTIVE"

    def test_undeclared_attributes_are_kept_with_a_warning(self, client, setup):
        body = post_event(client, setup, {**gas(5), "attributes": {"gas": "h2s", "ppm": 5, "sensor": "S-9"}}).json()
        assert body["event"]["attributes"]["sensor"] == "S-9"
        assert body["warnings"]


class TestConfiguration:
    def test_rule_dry_run_writes_nothing(self, client, setup, provider):
        rules = client.get(f"{API}/rules", headers=setup["headers"]).json()["items"]
        gas_rule = next(r for r in rules if r["name"] == "Gas reading above threshold")
        result = client.post(f"{API}/rules/{gas_rule['id']}/test", headers=setup["headers"], json={"event": gas(50)})
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["matched"] and body["severity"] == "critical"
        assert {r["channel"] for r in body["recipients"]} == {"sms", "email"}
        assert body["work_order_title"] == "Investigate h2s reading at Pad 1"
        assert client.get(f"{API}/events", headers=setup["key"]).json()["total"] == 0
        assert provider.sent == []

    def test_schema_change_that_breaks_a_rule_is_refused(self, client, setup):
        types = client.get(f"{API}/event-types?limit=200", headers=setup["headers"]).json()["items"]
        gas_type = next(t for t in types if t["key"] == "gas_detection")
        response = client.patch(
            f"{API}/event-types/{gas_type['id']}",
            headers=setup["headers"],
            json={"attributes_schema": [{"name": "gas", "type": "string"}]},  # drops ppm, used by a rule
        )
        assert response.status_code == 409 and response.json()["error"]["code"] == "RULES_DEPEND_ON_SCHEMA"

    def test_system_event_type_cannot_be_switched_off(self, client, setup):
        client.patch(f"{API}/organization", headers=setup["headers"], json={"enabled_modules": ["assistant"]})
        types = client.get(f"{API}/event-types?limit=200", headers=setup["headers"]).json()["items"]
        system = next(t for t in types if t["key"] == "assistant.escalation")
        response = client.patch(
            f"{API}/event-types/{system['id']}", headers=setup["headers"], json={"is_active": False}
        )
        assert response.status_code == 409

    def test_duplicate_codes(self, client, setup):
        response = client.post(f"{API}/sites", headers=setup["headers"], json={"code": "PAD-1", "name": "Again"})
        assert response.status_code == 409 and response.json()["error"]["code"] == "DUPLICATE_CODE"

    def test_unknown_fields_are_rejected(self, client, setup):
        response = client.post(
            f"{API}/sites", headers=setup["headers"], json={"code": "X", "name": "X", "nmae": "typo"}
        )
        assert response.status_code == 422


class TestWorkflow:
    def test_alert_lifecycle(self, client, setup):
        alert_id = post_event(client, setup, gas(30)).json()["alerts"][0]["alert_id"]
        url = f"{API}/alerts/{alert_id}"
        assert client.post(f"{url}/acknowledge", headers=setup["headers"]).json()["status"] == "acknowledged"
        assert client.post(f"{url}/acknowledge", headers=setup["headers"]).status_code == 200  # repeat is harmless
        assert (
            client.post(f"{url}/resolve", headers=setup["headers"], json={"note": "ok"}).json()["status"] == "resolved"
        )
        assert client.post(f"{url}/acknowledge", headers=setup["headers"]).status_code == 409
        assert client.post(f"{url}/reopen", headers=setup["headers"]).json()["status"] == "open"

    def test_work_order_transitions(self, client, setup):
        wo = client.post(
            f"{API}/work-orders",
            headers=setup["headers"],
            json={"title": "Check valve", "asset_id": setup["asset"]["id"]},
        ).json()
        assert wo["site_id"] == setup["site"]["id"]
        url = f"{API}/work-orders/{wo['id']}/transition"
        done = client.post(url, headers=setup["headers"], json={"status": "done", "note": "replaced"}).json()
        assert done["completed_at"] and done["completion_note"] == "replaced"
        bad = client.post(url, headers=setup["headers"], json={"status": "in_progress"})
        assert bad.status_code == 409 and bad.json()["error"]["details"]["allowed"] == ["open"]
        reopened = client.post(url, headers=setup["headers"], json={"status": "open"}).json()
        assert reopened["completed_at"] is None


class TestDelivery:
    def test_transient_failures_retry_with_backoff_then_give_up(self, client, setup, provider, settings):
        provider.fail_with = DeliveryError("gateway timeout")
        post_event(client, setup, gas(30))
        pending = client.get(f"{API}/notifications?status=pending", headers=setup["headers"]).json()["items"]
        assert len(pending) == 2 and all(n["attempts"] == 1 and n["next_attempt_at"] for n in pending)

        later = datetime.now(UTC)
        for attempt in range(2, settings.notification_max_attempts + 1):
            later += backoff(attempt) + timedelta(seconds=1)
            deliver_pending(now=later)
        failed = client.get(f"{API}/notifications?status=failed", headers=setup["headers"]).json()
        assert failed["total"] == 2

    def test_permanent_failure_stops_immediately(self, client, setup, provider):
        provider.fail_with = DeliveryError("invalid number", permanent=True)
        post_event(client, setup, gas(30))
        statuses = {n["status"] for n in client.get(f"{API}/notifications", headers=setup["headers"]).json()["items"]}
        assert statuses == {NotificationStatus.FAILED}

    def test_recovery_after_outage(self, client, setup, provider):
        provider.fail_with = DeliveryError("down")
        post_event(client, setup, gas(30))
        provider.fail_with = None
        stats = deliver_pending(now=datetime.now(UTC) + timedelta(minutes=5))
        assert stats.sent == 2

    def test_backoff_is_capped(self):
        assert backoff(1) == timedelta(seconds=30)
        assert backoff(20) == timedelta(hours=1)
