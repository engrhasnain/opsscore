"""The rules engine: validation catches bad configuration, evaluation never crashes."""

from datetime import UTC, datetime

import pytest

from app.errors import ValidationFailed
from app.services.rules import build_context, evaluate, validate_actions, validate_conditions

SCHEMA = [
    {"name": "ppm", "type": "number", "required": True},
    {"name": "gas", "type": "string", "required": True},
    {"name": "injuries", "type": "boolean"},
]


def ctx(**attributes):
    return build_context(
        severity="high",
        event_type_key="gas_detection",
        source_type="api_key",
        occurred_at=datetime(2026, 10, 19, 23, 30, tzinfo=UTC),
        timezone="America/Argentina/Buenos_Aires",  # UTC-3: 20:30 local
        attributes=attributes,
        site={"code": "PAD-07", "kind": "well_pad", "name": "Well pad 7"},
        asset={"code": "TB-1", "type": "tank_battery", "name": "Tank battery", "criticality": 4},
    )


def check(conditions, values, match="all"):
    return evaluate(validate_conditions(conditions, attribute_schema=SCHEMA), match, values)


class TestValidation:
    @pytest.mark.parametrize(
        ("condition", "fragment"),
        [
            ({"field": "attributes.PPM", "op": "eq", "value": 1}, "unknown field"),
            ({"field": "site.secret", "op": "eq", "value": 1}, "unknown field"),
            ({"field": "attributes.ppm", "op": "between", "value": 1}, "must be one of"),
            ({"field": "attributes.ppm", "op": "gte"}, "value is required"),
            ({"field": "attributes.ppm", "op": "exists", "value": 1}, "takes no value"),
            ({"field": "attributes.ppm", "op": "gte", "value": "10"}, "must be a number"),
            ({"field": "attributes.ppm", "op": "in", "value": []}, "list of 1-100"),
            ({"field": "attributes.ppm", "op": "eq", "value": {"a": 1}}, "text, a number"),
            ({"field": "severity", "op": "gte", "value": "urgent"}, "severity"),
            ({"field": "severity", "op": "in", "value": ["high", "nope"]}, "severity"),
            ({"field": "local_hour", "op": "gte", "value": 24}, "0 to 23"),
            ({"field": "site.code", "op": "gt", "value": 3}, "is text"),
            ({"field": "attributes.unknown", "op": "exists"}, "not declared"),
            ({"field": "attributes.gas", "op": "gt", "value": 1}, "cannot be compared"),
            ({"field": "attributes.ppm", "op": "eq", "value": 1, "extra": True}, "unknown keys"),
        ],
    )
    def test_rejects_bad_conditions(self, condition, fragment):
        with pytest.raises(ValidationFailed) as exc:
            validate_conditions([condition], attribute_schema=SCHEMA)
        assert fragment in str(exc.value.details)

    def test_reports_every_problem_at_once(self):
        with pytest.raises(ValidationFailed) as exc:
            validate_conditions(
                [{"field": "nope", "op": "eq", "value": 1}, {"field": "attributes.ppm", "op": "zz", "value": 1}],
                attribute_schema=SCHEMA,
            )
        assert len(exc.value.details) == 2

    def test_rule_without_event_type_accepts_any_attribute(self):
        assert validate_conditions([{"field": "attributes.anything", "op": "exists"}], attribute_schema=None)

    def test_limits(self):
        with pytest.raises(ValidationFailed):
            validate_conditions([{"field": "severity", "op": "exists"}] * 21, attribute_schema=None)
        with pytest.raises(ValidationFailed):
            validate_conditions("not a list", attribute_schema=None)

    @pytest.mark.parametrize(
        "action",
        [
            {"type": "notify", "channels": [], "contact_roles": ["x"]},
            {"type": "notify", "channels": ["fax"], "contact_roles": ["x"]},
            {"type": "notify", "channels": ["sms"]},
            {"type": "notify", "channels": ["sms"], "contact_ids": ["not-a-uuid"]},
            {"type": "create_work_order", "title": ""},
            {"type": "create_work_order", "title": "Fix {asset.__class__}"},
            {"type": "create_work_order", "title": "ok", "priority": "asap"},
            {"type": "create_work_order", "title": "ok", "due_in_hours": 0},
            {"type": "launch_rocket"},
        ],
    )
    def test_rejects_bad_actions(self, action):
        with pytest.raises(ValidationFailed):
            validate_actions([action])

    def test_only_one_work_order_action(self):
        with pytest.raises(ValidationFailed):
            validate_actions([{"type": "create_work_order", "title": "a"}, {"type": "create_work_order", "title": "b"}])

    def test_normalizes_actions(self):
        [action] = validate_actions(
            [{"type": "notify", "channels": ["sms", "sms", "email"], "contact_roles": [" Safety_Lead "]}]
        )
        assert action == {
            "type": "notify",
            "channels": ["sms", "email"],
            "contact_ids": [],
            "contact_roles": ["safety_lead"],
        }


class TestEvaluation:
    def test_numeric_threshold(self):
        assert check([{"field": "attributes.ppm", "op": "gte", "value": 10}], ctx(ppm=10, gas="h2s"))
        assert not check([{"field": "attributes.ppm", "op": "gte", "value": 10}], ctx(ppm=9.99, gas="h2s"))

    def test_missing_attribute_never_triggers(self):
        values = ctx(gas="h2s")
        assert not check([{"field": "attributes.ppm", "op": "gte", "value": 0}], values)
        assert not check([{"field": "attributes.ppm", "op": "ne", "value": 5}], values)
        assert check([{"field": "attributes.ppm", "op": "not_exists"}], values)

    def test_booleans_are_not_numbers(self):
        values = ctx(injuries=True)
        assert check([{"field": "attributes.injuries", "op": "eq", "value": True}], values)
        assert not evaluate([{"field": "attributes.injuries", "op": "eq", "value": 1}], "all", ctx(injuries=True))

    def test_values_that_can_never_match_are_refused(self):
        for bad in (
            {"field": "attributes.injuries", "op": "eq", "value": "true"},
            {"field": "attributes.injuries", "op": "eq", "value": 1},
            {"field": "attributes.ppm", "op": "eq", "value": "10"},
            {"field": "attributes.gas", "op": "contains", "value": 5},
        ):
            with pytest.raises(ValidationFailed):
                validate_conditions([bad], attribute_schema=SCHEMA)

    def test_text_is_case_insensitive(self):
        assert check([{"field": "site.code", "op": "eq", "value": "pad-07"}], ctx())
        assert check([{"field": "attributes.gas", "op": "in", "value": ["CH4", "H2S"]}], ctx(gas="h2s"))
        assert check([{"field": "site.name", "op": "contains", "value": "PAD"}], ctx())

    def test_severity_is_ordered(self):
        assert check([{"field": "severity", "op": "gte", "value": "medium"}], ctx())
        assert not check([{"field": "severity", "op": "gt", "value": "high"}], ctx())

    def test_local_time_uses_site_timezone(self):
        assert check([{"field": "local_hour", "op": "eq", "value": 20}], ctx())  # after hours, local

    def test_any_versus_all(self):
        conditions = [
            {"field": "attributes.ppm", "op": "gte", "value": 100},
            {"field": "asset.criticality", "op": "gte", "value": 4},
        ]
        assert not check(conditions, ctx(ppm=5, gas="h2s"), match="all")
        assert check(conditions, ctx(ppm=5, gas="h2s"), match="any")

    def test_no_conditions_matches_everything(self):
        assert evaluate([], "all", ctx())

    def test_wrong_runtime_type_is_false_not_an_error(self):
        # Undeclared attributes are stored as sent, so a rule may meet text where it wanted a number.
        assert not evaluate([{"field": "attributes.ppm", "op": "gte", "value": 5}], "all", ctx(ppm="high"))
