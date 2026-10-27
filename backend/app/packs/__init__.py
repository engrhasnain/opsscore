"""Starter packs: sensible defaults for a new client, by industry.

A pack creates event types and rules a client can edit or switch off. Rules
address people by role ("safety_lead"), so they start working as soon as the
client adds contacts with those roles.

Packs never create knowledge-base answers. An assistant that tells a real
driver an invented gate time is worse than one that says "a person will reply".
"""

from sqlalchemy.orm import Session

from app.enums import EventCategory, Industry, Module, Severity
from app.models import Rule
from app.schemas.catalog import EventTypeCreateIn, RuleCreateIn
from app.services import catalog
from app.services.context import Ctx
from app.services.scoping import scoped

ESCALATION_TYPE_KEY = "assistant.escalation"

_ESCALATION_TYPE = {
    "key": ESCALATION_TYPE_KEY,
    "name": "Assistant handed a conversation to a person",
    "category": EventCategory.COMMUNICATIONS,
    "default_severity": Severity.MEDIUM,
    "attributes_schema": [
        {"name": "reason", "type": "string", "required": True, "enum": ["emergency", "human_requested", "no_answer"]},
        {"name": "channel", "type": "string", "required": True},
        {"name": "sender", "type": "string", "required": True},
        {"name": "conversation_id", "type": "string", "required": True},
        {"name": "excerpt", "type": "string", "max_length": 500},
    ],
}

_ESCALATION_RULE = {
    "name": "Assistant needs a person",
    "event_type": ESCALATION_TYPE_KEY,
    "actions": [{"type": "notify", "channels": ["whatsapp", "sms"], "contact_roles": ["on_call_coordinator"]}],
    "renotify_after_seconds": 0,
}

_OIL_GAS_TYPES = [
    {
        "key": "gas_detection",
        "name": "Gas detection",
        "category": EventCategory.SAFETY,
        "default_severity": Severity.HIGH,
        "attributes_schema": [
            {"name": "gas", "type": "string", "required": True, "enum": ["h2s", "ch4", "co", "lel", "other"]},
            {"name": "ppm", "type": "number", "required": True, "unit": "ppm", "min": 0, "label": "Reading"},
        ],
    },
    {
        "name": "PPE violation",
        "key": "ppe_violation",
        "category": EventCategory.SAFETY,
        "default_severity": Severity.MEDIUM,
        "attributes_schema": [
            {
                "name": "missing_item",
                "type": "string",
                "required": True,
                "enum": ["hard_hat", "vest", "gloves", "glasses", "fr_clothing", "harness", "other"],
            },
            {"name": "zone", "type": "string"},
        ],
    },
    {
        "key": "vehicle_incident",
        "name": "Vehicle incident",
        "category": EventCategory.SAFETY,
        "default_severity": Severity.HIGH,
        "attributes_schema": [
            {"name": "injuries", "type": "boolean", "required": True},
            {"name": "vehicle_id", "type": "string"},
        ],
    },
    {
        "key": "struck_by_hazard",
        "name": "Struck-by or caught-in hazard",
        "category": EventCategory.SAFETY,
        "default_severity": Severity.HIGH,
        "attributes_schema": [
            {"name": "zone", "type": "string"},
            {"name": "distance", "type": "number", "unit": "m", "min": 0},
        ],
    },
    {
        "key": "flare_flashback",
        "name": "Flare flashback",
        "category": EventCategory.SAFETY,
        "default_severity": Severity.CRITICAL,
        "attributes_schema": [{"name": "tank_battery", "type": "string"}],
    },
    {
        "key": "spill",
        "name": "Spill",
        "category": EventCategory.SAFETY,
        "default_severity": Severity.HIGH,
        "attributes_schema": [
            {"name": "volume", "type": "number", "unit": "bbl", "min": 0},
            {"name": "substance", "type": "string"},
        ],
    },
    {
        "key": "equipment_fault",
        "name": "Equipment fault",
        "category": EventCategory.OPERATIONS,
        "default_severity": Severity.MEDIUM,
        "attributes_schema": [
            {"name": "fault_code", "type": "string"},
            {"name": "pressure", "type": "number", "unit": "psi"},
        ],
    },
    {
        "key": "material_measurement",
        "name": "Material measurement",
        "category": EventCategory.LOGISTICS,
        "default_severity": Severity.INFO,
        "attributes_schema": [
            {"name": "material", "type": "string", "required": True},
            {"name": "volume", "type": "number", "unit": "m3", "min": 0, "required": True},
            {"name": "measured_by", "type": "string"},
        ],
    },
]

_OIL_GAS_RULES = [
    {
        "name": "Gas reading above threshold",
        "event_type": "gas_detection",
        "conditions": [{"field": "attributes.ppm", "op": "gte", "value": 10}],
        "severity_override": Severity.CRITICAL,
        "renotify_after_seconds": 900,
        "actions": [
            {"type": "notify", "channels": ["sms", "email"], "contact_roles": ["safety_lead"]},
            {
                "type": "create_work_order",
                "title": "Investigate {attributes.gas} reading at {site.name}",
                "priority": "urgent",
                "due_in_hours": 2,
            },
        ],
    },
    {
        "name": "Vehicle incident with injuries",
        "event_type": "vehicle_incident",
        "conditions": [{"field": "attributes.injuries", "op": "eq", "value": True}],
        "severity_override": Severity.CRITICAL,
        "actions": [
            {"type": "notify", "channels": ["sms", "email"], "contact_roles": ["safety_lead", "operations_supervisor"]}
        ],
    },
    {
        "name": "Flare flashback",
        "event_type": "flare_flashback",
        "actions": [
            {"type": "notify", "channels": ["sms", "email"], "contact_roles": ["safety_lead"]},
            {
                "type": "create_work_order",
                "title": "Inspect flare system at {site.name}",
                "priority": "urgent",
                "due_in_hours": 4,
            },
        ],
    },
    {
        "name": "PPE violation",
        "event_type": "ppe_violation",
        "actions": [{"type": "notify", "channels": ["whatsapp"], "contact_roles": ["site_supervisor"]}],
    },
    {
        "name": "Spill reported",
        "event_type": "spill",
        "actions": [
            {"type": "notify", "channels": ["sms", "email"], "contact_roles": ["safety_lead", "environmental_lead"]},
            {
                "type": "create_work_order",
                "title": "Contain and report spill at {site.name}",
                "priority": "high",
                "due_in_hours": 8,
            },
        ],
    },
]

_MARITIME_TYPES = [
    {
        "key": "gate_status",
        "name": "Gate status change",
        "category": EventCategory.OPERATIONS,
        "default_severity": Severity.MEDIUM,
        "attributes_schema": [
            {"name": "gate", "type": "string", "required": True},
            {"name": "status", "type": "string", "required": True, "enum": ["open", "closed", "delayed"]},
            {"name": "reason", "type": "string"},
        ],
    },
    {
        "key": "truck_queue",
        "name": "Truck queue",
        "category": EventCategory.LOGISTICS,
        "default_severity": Severity.MEDIUM,
        "attributes_schema": [
            {"name": "gate", "type": "string"},
            {"name": "wait_minutes", "type": "number", "required": True, "unit": "min", "min": 0, "label": "Wait"},
            {"name": "trucks", "type": "integer", "min": 0},
        ],
    },
    {
        "key": "vessel_delay",
        "name": "Vessel delay",
        "category": EventCategory.LOGISTICS,
        "default_severity": Severity.MEDIUM,
        "attributes_schema": [
            {"name": "vessel", "type": "string", "required": True},
            {"name": "delay_hours", "type": "number", "required": True, "unit": "h", "min": 0, "label": "Delay"},
            {"name": "berth", "type": "string"},
        ],
    },
    {
        "key": "yard_near_miss",
        "name": "Yard near miss",
        "category": EventCategory.SAFETY,
        "default_severity": Severity.HIGH,
        "attributes_schema": [
            {"name": "zone", "type": "string"},
            {"name": "equipment", "type": "string"},
            {"name": "people_involved", "type": "integer", "min": 0},
        ],
    },
    {
        "key": "strike_disruption",
        "name": "Strike or blockade",
        "category": EventCategory.OPERATIONS,
        "default_severity": Severity.HIGH,
        "attributes_schema": [
            {"name": "scope", "type": "string"},
            {"name": "expected_hours", "type": "number", "unit": "h", "min": 0},
        ],
    },
    {
        "key": "weather_alert",
        "name": "Weather alert",
        "category": EventCategory.OPERATIONS,
        "default_severity": Severity.MEDIUM,
        "attributes_schema": [
            {"name": "condition", "type": "string", "required": True},
            {"name": "wind_speed", "type": "number", "unit": "kn", "min": 0},
        ],
    },
    {
        "key": "cyber_incident",
        "name": "Cyber incident",
        "category": EventCategory.SECURITY,
        "default_severity": Severity.HIGH,
        "attributes_schema": [{"name": "system", "type": "string", "required": True}],
    },
]

_MARITIME_RULES = [
    {
        "name": "Gate closed",
        "event_type": "gate_status",
        "conditions": [{"field": "attributes.status", "op": "eq", "value": "closed"}],
        "severity_override": Severity.HIGH,
        "actions": [{"type": "notify", "channels": ["sms", "whatsapp"], "contact_roles": ["operations_supervisor"]}],
    },
    {
        "name": "Truck wait over two hours",
        "event_type": "truck_queue",
        "conditions": [{"field": "attributes.wait_minutes", "op": "gte", "value": 120}],
        "renotify_after_seconds": 3600,
        "actions": [{"type": "notify", "channels": ["whatsapp"], "contact_roles": ["operations_supervisor"]}],
    },
    {
        "name": "Yard near miss",
        "event_type": "yard_near_miss",
        "actions": [
            {"type": "notify", "channels": ["sms"], "contact_roles": ["yard_supervisor"]},
            {
                "type": "create_work_order",
                "title": "Review near miss in {attributes.zone}",
                "priority": "high",
                "due_in_hours": 24,
            },
        ],
    },
    {
        "name": "Cyber incident",
        "event_type": "cyber_incident",
        "severity_override": Severity.CRITICAL,
        "actions": [{"type": "notify", "channels": ["sms", "email"], "contact_roles": ["security_lead"]}],
    },
    {
        "name": "Strike or blockade",
        "event_type": "strike_disruption",
        "actions": [
            {
                "type": "notify",
                "channels": ["email", "sms"],
                "contact_roles": ["operations_supervisor", "customer_service_lead"],
            }
        ],
    },
]

_PACKS = {
    Industry.OIL_GAS: (_OIL_GAS_TYPES, _OIL_GAS_RULES),
    Industry.MARITIME: (_MARITIME_TYPES, _MARITIME_RULES),
    Industry.OTHER: ([], []),
}

CONTACT_ROLES = sorted(
    {
        role
        for _types, rules in [*_PACKS.values(), ([], [_ESCALATION_RULE])]
        for rule in rules
        for action in rule["actions"]
        for role in action.get("contact_roles", [])
    }
)


def _rule_exists(session: Session, ctx: Ctx, name: str) -> bool:
    return session.scalar(scoped(Rule, ctx.org_id).where(Rule.name == name)) is not None


def _ensure_types_and_rules(session: Session, ctx: Ctx, types: list[dict], rules: list[dict], *, system: bool) -> dict:
    created = {"event_types": 0, "rules": 0}
    for spec in types:
        if catalog.event_type_by_key(session, ctx.org_id, spec["key"]) is None:
            catalog.create_event_type(session, ctx, EventTypeCreateIn(**spec), is_system=system)
            created["event_types"] += 1
    for spec in rules:
        if not _rule_exists(session, ctx, spec["name"]):
            catalog.create_rule(session, ctx, RuleCreateIn(**spec))
            created["rules"] += 1
    return created


def apply_starter_pack(session: Session, ctx: Ctx, industry: Industry) -> dict:
    """Idempotent: running it twice creates nothing new."""
    types, rules = _PACKS[Industry(industry)]
    return _ensure_types_and_rules(session, ctx, types, rules, system=False)


def ensure_module_setup(session: Session, ctx: Ctx, modules: list[str]) -> None:
    """Create what an enabled module needs to work (idempotent)."""
    if Module.ASSISTANT in modules:
        _ensure_types_and_rules(session, ctx, [_ESCALATION_TYPE], [_ESCALATION_RULE], system=True)
