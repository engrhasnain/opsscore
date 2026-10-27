"""Sign-in, permissions, and the wall between clients."""

from datetime import UTC, datetime, timedelta

import pytest

from app.enums import Role
from tests.conftest import PASSWORD, add_member, api_key, login, make_platform_admin, make_tenant

API = "/api/v1"


class TestLogin:
    def test_wrong_password_and_unknown_email_look_the_same(self, client, acme):
        wrong = client.post(f"{API}/auth/login", json={"email": acme.owner_email, "password": "nope-nope-nope"})
        unknown = client.post(f"{API}/auth/login", json={"email": "ghost@x.example.com", "password": "nope-nope-nope"})
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_email_is_case_insensitive(self, client, acme):
        response = client.post(f"{API}/auth/login", json={"email": acme.owner_email.upper(), "password": PASSWORD})
        assert response.status_code == 200

    def test_brute_force_is_throttled(self, client, acme):
        codes = [
            client.post(f"{API}/auth/login", json={"email": acme.owner_email, "password": "wrong-password"}).status_code
            for _ in range(11)
        ]
        assert codes[-1] == 429
        assert (
            "Retry-After"
            in client.post(f"{API}/auth/login", json={"email": acme.owner_email, "password": PASSWORD}).headers
        )

    def test_people_in_several_organizations_must_choose(self, client, acme):
        other = make_tenant("second-co")
        add_member(other, acme.owner_email, Role.VIEWER)
        response = client.post(f"{API}/auth/login", json={"email": acme.owner_email, "password": PASSWORD})
        assert response.status_code == 422
        assert {o["slug"] for o in response.json()["error"]["details"]} == {"acme-energy", "second-co"}
        assert login(client, acme.owner_email, org="second-co")
        forbidden = client.post(
            f"{API}/auth/login", json={"email": acme.owner_email, "password": PASSWORD, "organization": "nope"}
        )
        assert forbidden.status_code == 403

    def test_password_change_signs_out_old_tokens(self, client, acme, acme_headers):
        new_password = "a-brand-new-passphrase"
        weak = client.post(
            f"{API}/auth/password", headers=acme_headers, json={"current_password": PASSWORD, "new_password": "short"}
        )
        assert weak.status_code == 422
        ok = client.post(
            f"{API}/auth/password",
            headers=acme_headers,
            json={"current_password": PASSWORD, "new_password": new_password},
        )
        assert ok.status_code == 204
        assert client.get(f"{API}/auth/me", headers=acme_headers).status_code == 401

    def test_logout_everywhere(self, client, acme_headers):
        assert client.post(f"{API}/auth/logout-all", headers=acme_headers).status_code == 204
        assert client.get(f"{API}/sites", headers=acme_headers).status_code == 401

    @pytest.mark.parametrize("header", ["Bearer garbage", "Bearer ", "Basic abc", "Bearer ok_fake_key"])
    def test_bad_credentials(self, client, header):
        response = client.get(f"{API}/sites", headers={"Authorization": header})
        assert response.status_code in (401, 403)
        assert response.json()["error"]["request_id"]

    def test_no_credentials(self, client):
        assert client.get(f"{API}/sites").status_code == 401

    def test_me(self, client, acme_headers):
        body = client.get(f"{API}/auth/me", headers=acme_headers).json()
        assert body["role"] == "owner"
        assert body["organization"]["slug"] == "acme-energy"


class TestApiKeys:
    def test_scopes_limit_what_a_key_can_do(self, client, acme_headers):
        key = api_key(client, acme_headers, ["events:write"])
        assert client.get(f"{API}/alerts", headers=key).status_code == 403
        assert client.get(f"{API}/events", headers=key).status_code == 403
        assert client.get(f"{API}/auth/me", headers=key).status_code == 403

    def test_key_secret_is_shown_once(self, client, acme_headers):
        api_key(client, acme_headers, ["events:write"])
        listed = client.get(f"{API}/api-keys", headers=acme_headers).json()["items"]
        assert "key" not in listed[0] and "key_hash" not in listed[0]

    def test_revoked_and_expired_keys_stop_working(self, client, acme_headers):
        created = client.post(
            f"{API}/api-keys", headers=acme_headers, json={"name": "k", "scopes": ["events:read"]}
        ).json()
        key = {"X-API-Key": created["key"]}
        assert client.get(f"{API}/events", headers=key).status_code == 200
        assert client.delete(f"{API}/api-keys/{created['id']}", headers=acme_headers).status_code == 200
        assert client.delete(f"{API}/api-keys/{created['id']}", headers=acme_headers).status_code == 200  # idempotent
        assert client.get(f"{API}/events", headers=key).status_code == 401

        past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        rejected = client.post(
            f"{API}/api-keys", headers=acme_headers, json={"name": "k", "scopes": ["events:read"], "expires_at": past}
        )
        assert rejected.status_code == 422

    def test_tampered_key_is_rejected(self, client, acme_headers):
        key = api_key(client, acme_headers, ["events:read"])["X-API-Key"]
        assert client.get(f"{API}/events", headers={"X-API-Key": key[:-2] + "zz"}).status_code == 401


class TestPermissions:
    def test_roles(self, client, acme):
        add_member(acme, "viewer@acme.example.com", Role.VIEWER)
        add_member(acme, "super@acme.example.com", Role.SUPERVISOR)
        viewer = login(client, "viewer@acme.example.com")
        supervisor = login(client, "super@acme.example.com")
        site = {"code": "S1", "name": "Site 1"}
        assert client.get(f"{API}/sites", headers=viewer).status_code == 200
        assert client.post(f"{API}/sites", headers=viewer, json=site).status_code == 403
        assert client.post(f"{API}/sites", headers=supervisor, json=site).status_code == 403
        assert client.get(f"{API}/audit", headers=supervisor).status_code == 403

    def test_admins_cannot_create_owners_or_admins(self, client, acme):
        add_member(acme, "admin@acme.example.com", Role.ADMIN)
        admin = login(client, "admin@acme.example.com")
        for role in ("owner", "admin"):
            response = client.post(
                f"{API}/members",
                headers=admin,
                json={"email": f"{role}2@acme.example.com", "full_name": "X", "role": role, "password": PASSWORD},
            )
            assert response.status_code == 403
        ok = client.post(
            f"{API}/members",
            headers=admin,
            json={"email": "member2@acme.example.com", "full_name": "X", "role": "member", "password": PASSWORD},
        )
        assert ok.status_code == 201

    def test_last_owner_cannot_be_removed_or_demoted(self, client, acme_headers):
        members = client.get(f"{API}/members", headers=acme_headers).json()["items"]
        owner = next(m for m in members if m["role"] == "owner")
        demote = client.patch(f"{API}/members/{owner['id']}", headers=acme_headers, json={"role": "admin"})
        assert demote.status_code == 409 and demote.json()["error"]["code"] == "LAST_OWNER"
        assert client.delete(f"{API}/members/{owner['id']}", headers=acme_headers).status_code == 409

    def test_existing_account_keeps_its_password(self, client, acme, acme_headers):
        other = make_tenant("other-co")
        response = client.post(
            f"{API}/members",
            headers=acme_headers,
            json={
                "email": other.owner_email,
                "full_name": "Hijack",
                "role": "viewer",
                "password": "attacker-chosen-pw",
            },
        )
        assert response.status_code == 201
        bad = client.post(
            f"{API}/auth/login",
            json={"email": other.owner_email, "password": "attacker-chosen-pw", "organization": "acme-energy"},
        )
        assert bad.status_code == 401

    def test_module_must_be_enabled(self, client, acme_headers):
        response = client.get(f"{API}/assistant/conversations", headers=acme_headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "MODULE_NOT_ENABLED"
        enabled = client.patch(f"{API}/organization", headers=acme_headers, json={"enabled_modules": ["assistant"]})
        assert enabled.status_code == 200
        assert client.get(f"{API}/assistant/conversations", headers=acme_headers).status_code == 200


class TestPlatformOnboarding:
    def test_platform_admin_onboards_a_client(self, client):
        admin = login(client, make_platform_admin())
        body = {
            "name": "Rio Ports",
            "slug": "rio-ports",
            "industry": "maritime",
            "region": "latam",
            "timezone": "America/Sao_Paulo",
            "default_locale": "pt",
            "enabled_modules": ["assistant"],
            "owner": {"email": "boss@rio.example.com", "full_name": "Boss", "password": PASSWORD},
        }
        created = client.post(f"{API}/platform/organizations", headers=admin, json=body)
        assert created.status_code == 201, created.text
        assert created.json()["unit_system"] == "metric"
        assert client.post(f"{API}/platform/organizations", headers=admin, json=body).status_code == 409

        owner = login(client, "boss@rio.example.com")
        types = {t["key"] for t in client.get(f"{API}/event-types?limit=200", headers=owner).json()["items"]}
        assert {"gate_status", "truck_queue", "assistant.escalation"} <= types
        assert client.get(f"{API}/rules", headers=owner).json()["total"] >= 5

    def test_only_platform_admins(self, client, acme_headers):
        assert client.get(f"{API}/platform/organizations", headers=acme_headers).status_code == 403

    def test_bad_onboarding_input(self, client):
        admin = login(client, make_platform_admin())
        base = {
            "name": "X",
            "slug": "x-co",
            "industry": "oil_gas",
            "region": "us",
            "timezone": "America/Chicago",
            "owner": {"email": "o@x.example.com", "full_name": "O", "password": PASSWORD},
        }
        for change in (
            {"slug": "Bad Slug!"},
            {"timezone": "Nowhere/City"},
            {"owner": {**base["owner"], "password": "weak"}},
        ):
            assert (
                client.post(f"{API}/platform/organizations", headers=admin, json={**base, **change}).status_code == 422
            )
        assert (
            client.post(f"{API}/platform/organizations", headers=admin, json={**base, "surprise": 1}).status_code == 422
        )


class TestIsolation:
    """A client must never see, touch or reference another client's data."""

    def test_ids_from_another_client_are_not_found(self, client, acme_headers, portco_headers):
        site = client.post(f"{API}/sites", headers=portco_headers, json={"code": "T1", "name": "Terminal"}).json()
        contact = client.post(
            f"{API}/contacts", headers=portco_headers, json={"name": "C", "phone": "+5511955550100"}
        ).json()
        for path in (f"/sites/{site['id']}", f"/contacts/{contact['id']}"):
            assert client.get(API + path, headers=acme_headers).status_code == 404
        patch = client.patch(f"{API}/sites/{site['id']}", headers=acme_headers, json={"name": "pwned"})
        assert patch.status_code == 404
        assert client.get(f"{API}/sites/{site['id']}", headers=portco_headers).json()["name"] == "Terminal"

    def test_lists_only_show_own_data(self, client, acme_headers, portco_headers):
        client.post(f"{API}/sites", headers=portco_headers, json={"code": "T1", "name": "Terminal"})
        assert client.get(f"{API}/sites", headers=acme_headers).json()["total"] == 0
        acme_types = client.get(f"{API}/event-types?limit=200", headers=acme_headers).json()["items"]
        assert all(t["key"] != "gate_status" for t in acme_types)

    def test_same_codes_in_two_clients_do_not_collide(self, client, acme_headers, portco_headers):
        for headers in (acme_headers, portco_headers):
            assert client.post(f"{API}/sites", headers=headers, json={"code": "HQ", "name": "HQ"}).status_code == 201

    def test_cannot_reference_another_clients_records(self, client, acme_headers, portco_headers):
        site = client.post(f"{API}/sites", headers=portco_headers, json={"code": "T1", "name": "Terminal"}).json()
        contact = client.post(
            f"{API}/contacts", headers=portco_headers, json={"name": "C", "phone": "+5511955550100"}
        ).json()
        asset = client.post(
            f"{API}/assets",
            headers=acme_headers,
            json={"site_id": site["id"], "code": "A", "name": "A", "asset_type": "x"},
        )
        assert asset.status_code == 404
        rule = client.post(
            f"{API}/rules",
            headers=acme_headers,
            json={"name": "r", "actions": [{"type": "notify", "channels": ["sms"], "contact_ids": [contact["id"]]}]},
        )
        assert rule.status_code == 422 and rule.json()["error"]["code"] == "UNKNOWN_CONTACT"
        key = api_key(client, acme_headers, ["events:write"])
        event = client.post(f"{API}/events", headers=key, json={"event_type": "spill", "site_id": site["id"]})
        assert event.status_code == 422 and event.json()["error"]["code"] == "UNKNOWN_SITE"
