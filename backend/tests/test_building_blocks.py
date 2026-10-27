"""Attribute schemas, units, translations, templates, validation and security helpers."""

import math

import pytest

from app import i18n
from app.config import Settings
from app.enums import Locale, UnitSystem
from app.errors import TooManyRequests, ValidationFailed
from app.ratelimit import RateLimiter
from app.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_password,
    parse_api_key_prefix,
    verify_password,
)
from app.services import attributes, templating
from app.services import validation as v
from app.units import convert, for_display, format_quantity


class TestAttributeSchemas:
    def test_valid_schema_is_normalized(self):
        schema = attributes.validate_schema([{"name": "volume", "type": "number", "unit": "bbl", "min": 0}])
        assert schema == [{"name": "volume", "type": "number", "required": False, "unit": "bbl", "min": 0}]

    @pytest.mark.parametrize(
        "item",
        [
            {"name": "Volume", "type": "number"},
            {"name": "v", "type": "decimal"},
            {"name": "v", "type": "string", "unit": "m"},
            {"name": "v", "type": "number", "unit": "furlongs"},
            {"name": "v", "type": "number", "min": 5, "max": 1},
            {"name": "v", "type": "string", "enum": ["a", "a"]},
            {"name": "v", "type": "string", "max_length": 0},
            {"name": "v", "type": "number", "color": "red"},
        ],
    )
    def test_bad_definitions(self, item):
        with pytest.raises(ValidationFailed):
            attributes.validate_schema([item])

    def test_duplicate_names(self):
        with pytest.raises(ValidationFailed):
            attributes.validate_schema([{"name": "a", "type": "string"}, {"name": "a", "type": "number"}])

    def test_values(self):
        schema = attributes.validate_schema(
            [
                {"name": "ppm", "type": "number", "required": True, "min": 0},
                {"name": "count", "type": "integer"},
                {"name": "gas", "type": "string", "enum": ["h2s", "co"]},
            ]
        )
        checked = attributes.validate_values(schema, {"ppm": 12.5, "count": 3.0, "gas": "h2s", "note": "x", "z": None})
        assert checked.values == {"ppm": 12.5, "count": 3, "gas": "h2s", "note": "x"}
        assert checked.warnings == ["attribute 'note' is not declared for this event type"]

    @pytest.mark.parametrize(
        "values",
        [
            {},  # required missing
            {"ppm": "12"},
            {"ppm": True},
            {"ppm": -1},
            {"ppm": math.inf},
            {"ppm": 1, "count": 1.5},
            {"ppm": 1, "gas": "methane"},
            {"ppm": 1, "nested": {"a": 1}},
            {"ppm": 1, "BadName": 1},
            {"ppm": 1, "long": "x" * 2001},
        ],
    )
    def test_bad_values(self, values):
        schema = attributes.validate_schema(
            [
                {"name": "ppm", "type": "number", "required": True, "min": 0},
                {"name": "count", "type": "integer"},
                {"name": "gas", "type": "string", "enum": ["h2s", "co"]},
            ]
        )
        with pytest.raises(ValidationFailed):
            attributes.validate_values(schema, values)


class TestUnits:
    def test_round_trips(self):
        assert convert(1, "bbl", "m3") == pytest.approx(0.158987, rel=1e-5)
        assert convert(212, "f", "c") == pytest.approx(100)
        assert convert(convert(37.5, "c", "f"), "f", "c") == pytest.approx(37.5)
        assert convert(100, "psi", "kpa") == pytest.approx(689.4757)

    def test_incompatible_units(self):
        with pytest.raises(ValueError):
            convert(1, "bbl", "psi")
        with pytest.raises(ValueError):
            convert(1, "bbl", "hogshead")

    def test_display_follows_client_units(self):
        assert for_display(10, "bbl", UnitSystem.METRIC) == pytest.approx((1.58987, "m3"), rel=1e-4)
        assert for_display(10, "bbl", UnitSystem.IMPERIAL) == (10, "bbl")
        assert for_display(12, "kn", UnitSystem.METRIC) == (12, "kn")  # knots everywhere at sea
        assert format_quantity(1000, "m3", UnitSystem.METRIC) == "1,000 m3"


class TestTranslations:
    def test_every_message_exists_in_every_language(self):
        assert i18n.missing_translations() == []

    def test_fallbacks(self):
        assert i18n.t("severity.high", "pt") == "Alta"
        assert i18n.t("severity.high", "fr") == "High"
        assert i18n.t("no.such.key", Locale.ES) == "no.such.key"


class TestTemplates:
    def test_render(self):
        assert (
            templating.render("Inspect {asset.name} ({attributes.gas})", {"asset.name": "TB-1"}) == "Inspect TB-1 (—)"
        )

    def test_cannot_reach_python_internals(self):
        with pytest.raises(ValidationFailed):
            templating.validate_template("{0.__class__}{site.__init__}", field="title", max_length=100)
        assert templating.render("{0.__class__}", {}) == "{0.__class__}"

    def test_truncates(self):
        assert len(templating.render("x" * 50, {}, max_length=10)) == 10


class TestValidators:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("+1 (713) 555-0100", "+17135550100"), ("0054 9 299 555 0101", "+5492995550101"), ("", None)],
    )
    def test_phone(self, raw, expected):
        assert v.phone(raw) == expected

    @pytest.mark.parametrize("raw", ["5550100", "+0123456789", "+1 call me"])
    def test_bad_phone(self, raw):
        with pytest.raises(ValidationFailed):
            v.phone(raw)

    def test_codes_are_case_insensitive(self):
        assert v.code(" fdp-14 ") == "FDP-14"
        with pytest.raises(ValidationFailed):
            v.code("pad 14")

    def test_timezones(self):
        assert v.timezone("America/Argentina/Buenos_Aires")
        with pytest.raises(ValidationFailed):
            v.timezone("Mars/Olympus_Mons")

    def test_coordinates(self):
        assert v.coordinate("-38.5", field="lat", low=-90, high=90) == -38.5
        for bad in ("abc", 91, True, float("nan")):
            with pytest.raises(ValidationFailed):
                v.coordinate(bad, field="lat", low=-90, high=90)


class TestSecurity:
    def test_long_passwords_are_not_truncated(self):
        base = "p" * 80
        hashed = hash_password(base + "A")
        assert verify_password(base + "A", hashed)
        assert not verify_password(base + "B", hashed)  # bcrypt alone would accept this

    def test_tokens(self):
        import uuid

        user, org = uuid.uuid4(), uuid.uuid4()
        claims = decode_access_token(create_access_token(user, org, 3))
        assert (claims.user_id, claims.org_id, claims.token_version) == (user, org, 3)
        assert decode_access_token("not.a.token") is None
        assert decode_access_token(create_access_token(user, org, 3) + "x") is None

    def test_api_keys(self):
        key = generate_api_key()
        assert parse_api_key_prefix(key.plaintext) == key.prefix
        assert parse_api_key_prefix("ok__secret") is None
        assert parse_api_key_prefix("sk_abc_def") is None


class TestRateLimiter:
    def test_window(self):
        limiter = RateLimiter(2, window_seconds=60)
        limiter.hit("k", now=0)
        limiter.hit("k", now=1)
        with pytest.raises(TooManyRequests) as exc:
            limiter.hit("k", now=2)
        assert exc.value.retry_after == 58
        limiter.hit("k", now=61)  # first hit expired
        limiter.hit("other", now=2)  # keys are independent


class TestProductionGuard:
    def test_refuses_development_defaults(self):
        with pytest.raises(ValueError, match="Unsafe production configuration"):
            Settings(environment="production", _env_file=None)

    def test_accepts_proper_configuration(self):
        settings = Settings(
            environment="production",
            database_url="postgresql+psycopg://app@db/opscore",
            jwt_secret="x" * 48,
            bcrypt_rounds=12,
            _env_file=None,
        )
        assert settings.is_production
