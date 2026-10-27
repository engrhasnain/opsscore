# ruff: noqa: E501  (data tables read better one record per line)
"""Demo data: four invented clients, one per market in the pain-point research.

| Client                       | Market         | Language | Leads with (research priority)      |
|------------------------------|----------------|----------|-------------------------------------|
| Permian Ridge Operating      | US oil & gas   | English  | Safety / compliance, coordination   |
| Andes Energy                 | LATAM oil & gas| Spanish  | Asset visibility, contractor safety |
| Bayou Container Terminal     | US maritime    | English  | Yard safety, congestion             |
| Terminal Atlântico           | LATAM maritime | Portuguese | Congestion, yard safety           |

Companies, people, phone numbers and places are invented on purpose: nothing here
should look like a real operator's records. Assistant answers are written for the
demo scenarios; a real client approves its own.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant import knowledge
from app.enums import ApiKeyScope, Industry, Locale, Module, Region, Role, Severity, UnitSystem
from app.models import EventType, Rule
from app.schemas.assistant import KnowledgeCreateIn
from app.schemas.catalog import AssetCreateIn, ContactCreateIn, RuleCreateIn, SiteCreateIn
from app.schemas.tenancy import ApiKeyCreateIn, MemberCreateIn, OrgCreateIn, OwnerIn
from app.services import catalog, tenancy
from app.services.context import Actor, Ctx

DEMO_PASSWORD = "demo-password-1234"  # noqa: S105  (demo only, printed on screen)


@dataclass
class Answer:
    title: str
    content: str
    keywords: list[str]
    locale: Locale
    site: str | None = None


@dataclass
class DemoClient:
    name: str
    slug: str
    owner_email: str
    owner_name: str  # the person signed in to the console during the demo
    industry: Industry
    region: Region
    locale: Locale
    units: UnitSystem
    timezone: str
    blurb: str
    sites: list[dict]
    assets: list[dict]
    contacts: list[dict]
    answers: list[Answer]
    rules: list[dict] = field(default_factory=list)
    extra_members: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- rules shared by the oil & gas clients

_OG_EXTRA_RULES = [
    {
        "name": "Person close to moving equipment",
        "description": "Struck-by / caught-in: one of OSHA's leading causes of on-site fatalities.",
        "event_type": "struck_by_hazard",
        "conditions": [{"field": "attributes.distance", "op": "lt", "value": 5}],
        "severity_override": Severity.CRITICAL,
        "actions": [
            {"type": "notify", "channels": ["sms", "whatsapp"], "contact_roles": ["site_supervisor", "safety_lead"]},
            {
                "type": "create_work_order",
                "title": "Stop work and review struck-by risk in {attributes.zone} at {site.name}",
                "priority": "urgent",
                "due_in_hours": 1,
            },
        ],
    },
    {
        "name": "Measurement ready for sign-off",
        "description": "A site or yard measurement becomes a number the operations manager signs off.",
        "event_type": "material_measurement",
        "actions": [
            {"type": "notify", "channels": ["email"], "contact_roles": ["operations_supervisor"]},
            {
                "type": "create_work_order",
                "title": "Sign off {attributes.material} measurement at {site.name}",
                "priority": "normal",
                "due_in_hours": 24,
            },
        ],
    },
    {
        "name": "Equipment fault on a critical asset",
        "event_type": "equipment_fault",
        "conditions": [{"field": "asset.criticality", "op": "gte", "value": 4}],
        "severity_override": Severity.HIGH,
        "actions": [
            {"type": "notify", "channels": ["sms"], "contact_roles": ["on_call_coordinator"]},
            {
                "type": "create_work_order",
                "title": "Check {asset.name} ({attributes.fault_code}) at {site.name}",
                "priority": "high",
                "due_in_hours": 4,
            },
        ],
    },
]

_PORT_EXTRA_RULES = [
    {
        "name": "Vessel delay over six hours",
        "event_type": "vessel_delay",
        "conditions": [{"field": "attributes.delay_hours", "op": "gte", "value": 6}],
        "severity_override": Severity.HIGH,
        "actions": [
            {
                "type": "notify",
                "channels": ["email"],
                "contact_roles": ["operations_supervisor", "customer_service_lead"],
            }
        ],
    },
    {
        "name": "Severe weather",
        "event_type": "weather_alert",
        "conditions": [{"field": "attributes.wind_speed", "op": "gte", "value": 35}],
        "severity_override": Severity.HIGH,
        "actions": [
            {"type": "notify", "channels": ["sms"], "contact_roles": ["operations_supervisor", "yard_supervisor"]},
            {
                "type": "create_work_order",
                "title": "Secure cranes and stacks: {attributes.condition}",
                "priority": "urgent",
                "due_in_hours": 1,
            },
        ],
    },
]


CLIENTS: list[DemoClient] = [
    # ------------------------------------------------------------------ US oil & gas
    DemoClient(
        name="Permian Ridge Operating",
        slug="demo-permian-ridge",
        owner_email="owner@permian.demo",
        owner_name="Jordan Hayes",
        industry=Industry.OIL_GAS,
        region=Region.US,
        locale=Locale.EN,
        units=UnitSystem.IMPERIAL,
        timezone="America/Chicago",
        blurb="US oil & gas · English · safety and after-hours coordination",
        sites=[
            {"code": "PAD-14", "name": "Pad 14", "kind": "well_pad", "latitude": 31.92, "longitude": -102.18},
            {"code": "PAD-22", "name": "Pad 22", "kind": "well_pad", "latitude": 31.88, "longitude": -102.25},
            {"code": "SWD-2", "name": "Saltwater disposal 2", "kind": "facility"},
            {"code": "YARD-M", "name": "Pipe yard", "kind": "yard"},
        ],
        assets=[
            {
                "site": "PAD-14",
                "code": "TB-14-1",
                "name": "Tank battery 14-1",
                "asset_type": "tank_battery",
                "criticality": 5,
            },
            {"site": "PAD-14", "code": "FL-14", "name": "Flare 14", "asset_type": "flare", "criticality": 5},
            {
                "site": "PAD-14",
                "code": "HT-14",
                "name": "Heater treater 14",
                "asset_type": "heater_treater",
                "criticality": 4,
            },
            {
                "site": "PAD-22",
                "code": "TB-22-1",
                "name": "Tank battery 22-1",
                "asset_type": "tank_battery",
                "criticality": 4,
            },
            {"site": "SWD-2", "code": "SWD-2-P1", "name": "Injection pump 1", "asset_type": "pump", "criticality": 3},
        ],
        contacts=[
            {
                "name": "Jordan Hayes",
                "role_label": "safety_lead",
                "email": "j.hayes@permianridgeop.com",
                "phone": "+14325550141",
                "locale": Locale.EN,
            },
            {
                "name": "Chris Delgado",
                "role_label": "on_call_coordinator",
                "phone": "+14325550142",
                "whatsapp": "+14325550142",
                "locale": Locale.EN,
            },
            {
                "name": "Kayla Brooks",
                "role_label": "operations_supervisor",
                "email": "k.brooks@permianridgeop.com",
                "phone": "+14325550143",
                "locale": Locale.EN,
            },
            {
                "name": "Ray Medina",
                "role_label": "site_supervisor",
                "phone": "+14325550144",
                "whatsapp": "+14325550144",
                "locale": Locale.ES,
            },
            {
                "name": "Sam Patel",
                "role_label": "environmental_lead",
                "email": "s.patel@permianridgeop.com",
                "phone": "+14325550145",
                "locale": Locale.EN,
            },
        ],
        rules=_OG_EXTRA_RULES,
        answers=[
            Answer(
                "Pad 14 gate hours",
                "Pad 14 is open to trucks 5:00 AM to 9:00 PM, every day. Check in at the guard shack with your ticket number.",
                ["pad 14", "gate", "hours", "open", "time", "check in", "entry", "access"],
                Locale.EN,
                "PAD-14",
            ),
            Answer(
                "Pad 22 gate hours",
                "Pad 22 is open to trucks 6:00 AM to 6:00 PM, Monday to Saturday. Radio channel 3 before the cattle guard.",
                ["pad 22", "gate", "hours", "open", "time", "entry", "access"],
                Locale.EN,
                "PAD-22",
            ),
            Answer(
                "Water haul tickets",
                "Every water haul needs a run ticket with the lease name and barrels. Drop the ticket in the box at the SWD-2 office or upload the photo in the hauler app.",
                ["ticket", "tickets", "run ticket", "water", "haul", "hauling", "barrels", "load", "paperwork", "swd"],
                Locale.EN,
            ),
            Answer(
                "H2S orientation",
                "You need a current H2S Clear card and a personal H2S monitor to enter any pad. No card, no entry.",
                ["h2s", "orientation", "card", "training", "monitor", "certificate", "requirements", "ppe"],
                Locale.EN,
            ),
            Answer(
                "Lease road speed limit",
                "Speed limit is 25 mph on lease roads and 10 mph on location. Headlights on at all times.",
                ["speed", "limit", "mph", "road", "lease"],
                Locale.EN,
            ),
            Answer(
                "Where to unload pipe",
                "Unload pipe and casing at the pipe yard (YARD-M), off County Road 1200, 6:00 AM to 4:00 PM on weekdays.",
                ["pipe", "casing", "unload", "drop", "deliver", "delivery", "yard", "where"],
                Locale.EN,
            ),
            Answer(
                "Horario del pad 14",
                "El pad 14 recibe camiones de 5:00 a 21:00, todos los días. Registrarse en la caseta con el número de ticket.",
                ["pad 14", "horario", "hora", "abierto", "entrada", "ingreso", "porton"],
                Locale.ES,
                "PAD-14",
            ),
            Answer(
                "Tickets de agua",
                "Cada viaje de agua necesita el ticket con el nombre del lease y los barriles. Dejar el ticket en la caja de la oficina SWD-2 o subir la foto en la app.",
                ["ticket", "tickets", "agua", "viaje", "barriles", "papeles", "documento", "carga"],
                Locale.ES,
            ),
        ],
    ),
    # ------------------------------------------------------------------ LATAM oil & gas
    DemoClient(
        name="Andes Energy",
        slug="demo-andes-energy",
        owner_email="owner@andes.demo",
        owner_name="Ana Quiroga",
        industry=Industry.OIL_GAS,
        region=Region.LATAM,
        locale=Locale.ES,
        units=UnitSystem.METRIC,
        timezone="America/Argentina/Buenos_Aires",
        blurb="LATAM oil & gas · Spanish · asset visibility and contractor oversight",
        sites=[
            {"code": "PAD-07", "name": "Pad 7", "kind": "well_pad", "latitude": -38.55, "longitude": -69.09},
            {"code": "PAD-12", "name": "Pad 12", "kind": "well_pad", "latitude": -38.61, "longitude": -69.02},
            {"code": "CPF-1", "name": "Planta de tratamiento CPF-1", "kind": "facility"},
            {"code": "YARD-1", "name": "Playa de materiales 1", "kind": "yard"},
        ],
        assets=[
            {
                "site": "PAD-07",
                "code": "TB-07-1",
                "name": "Batería 7-1",
                "asset_type": "tank_battery",
                "criticality": 4,
            },
            {"site": "PAD-07", "code": "FL-07", "name": "Antorcha 7", "asset_type": "flare", "criticality": 5},
            {
                "site": "PAD-07",
                "code": "WH-07-3",
                "name": "Boca de pozo 7-3",
                "asset_type": "wellhead",
                "criticality": 4,
            },
            {
                "site": "PAD-12",
                "code": "TB-12-1",
                "name": "Batería 12-1",
                "asset_type": "tank_battery",
                "criticality": 4,
            },
            {
                "site": "YARD-1",
                "code": "SP-ARENA",
                "name": "Acopio de arena de fractura",
                "asset_type": "stockpile",
                "criticality": 2,
            },
            {
                "site": "YARD-1",
                "code": "SP-GRAVA",
                "name": "Acopio de grava",
                "asset_type": "stockpile",
                "criticality": 2,
            },
        ],
        contacts=[
            {
                "name": "Lucía Ferreyra",
                "role_label": "safety_lead",
                "email": "seguridad@andesenergia.com.ar",
                "phone": "+5492995550101",
                "locale": Locale.ES,
            },
            {
                "name": "Martín Rojas",
                "role_label": "on_call_coordinator",
                "phone": "+5492995550102",
                "whatsapp": "+5492995550102",
                "locale": Locale.ES,
            },
            {
                "name": "Diego Sosa",
                "role_label": "site_supervisor",
                "phone": "+5492995550103",
                "whatsapp": "+5492995550103",
                "locale": Locale.ES,
            },
            {
                "name": "Ana Quiroga",
                "role_label": "operations_supervisor",
                "email": "operaciones@andesenergia.com.ar",
                "phone": "+5492995550104",
                "locale": Locale.ES,
            },
            {
                "name": "Valeria Paz",
                "role_label": "environmental_lead",
                "email": "ambiente@andesenergia.com.ar",
                "phone": "+5492995550105",
                "locale": Locale.ES,
            },
        ],
        rules=_OG_EXTRA_RULES,
        extra_members=[{"email": "supervisor@andes.demo", "full_name": "Diego Sosa", "role": Role.SUPERVISOR}],
        answers=[
            Answer(
                "Horario de ingreso al pad 7",
                "El ingreso de camiones al pad 7 es de 6:00 a 20:00. Presentar el remito en la garita.",
                ["horario", "ingreso", "pad 7", "camion", "entrada", "hora", "abierto"],
                Locale.ES,
                "PAD-07",
            ),
            Answer(
                "Horario de ingreso al pad 12",
                "El pad 12 recibe camiones de 7:00 a 19:00. Avisar por radio al llegar al km 3.",
                ["horario", "ingreso", "pad 12", "camion", "entrada", "hora", "abierto"],
                Locale.ES,
                "PAD-12",
            ),
            Answer(
                "Remito de entrega",
                "Cada carga necesita el remito firmado por el despachante. Entregalo en la garita al ingresar; sin remito no se puede descargar.",
                ["remito", "ticket", "entrega", "papeles", "documento", "documentos", "firma", "carga"],
                Locale.ES,
            ),
            Answer(
                "Dónde descargar arena y grava",
                "La arena y la grava se descargan en el patio de materiales 1 (YARD-1), en el km 5 del camino de acceso, de lunes a sábado de 6:00 a 18:00.",
                [
                    "arena",
                    "grava",
                    "descargar",
                    "descargo",
                    "descarga",
                    "material",
                    "materiales",
                    "patio",
                    "donde",
                    "dejo",
                ],
                Locale.ES,
            ),
            Answer(
                "Corte en la ruta 4",
                "La ruta 4 tiene un corte por obras entre el km 12 y el 15. Usar el desvío señalizado por la ruta 7.",
                ["ruta", "camino", "corte", "cortada", "desvio", "acceso", "ruta 4", "transito"],
                Locale.ES,
            ),
            Answer(
                "Elementos de protección",
                "Para ingresar a cualquier locación es obligatorio casco, botines de seguridad, ropa ignífuga, anteojos y detector personal de H2S.",
                ["epp", "casco", "ropa", "seguridad", "requisitos", "elementos", "proteccion", "botines"],
                Locale.ES,
            ),
            Answer(
                "Velocidad máxima",
                "La velocidad máxima es 40 km/h en caminos internos y 20 km/h dentro de la locación.",
                ["velocidad", "maxima", "limite", "km"],
                Locale.ES,
            ),
            Answer(
                "Pad 7 gate hours",
                "Trucks are received at pad 7 from 6:00 to 20:00. Hand the delivery note (remito) to the gatehouse.",
                ["pad 7", "gate", "hours", "open", "time", "entry", "access"],
                Locale.EN,
                "PAD-07",
            ),
        ],
    ),
    # ------------------------------------------------------------------ US maritime
    DemoClient(
        name="Bayou Container Terminal",
        slug="demo-bayou-terminal",
        owner_email="owner@bayou.demo",
        owner_name="Marcus Bell",
        industry=Industry.MARITIME,
        region=Region.US,
        locale=Locale.EN,
        units=UnitSystem.IMPERIAL,
        timezone="America/Chicago",
        blurb="US maritime · English · yard safety and congestion",
        sites=[
            {"code": "GATE-A", "name": "Truck gate A", "kind": "gate"},
            {"code": "GATE-B", "name": "Truck gate B", "kind": "gate"},
            {"code": "YARD-3", "name": "Container yard 3", "kind": "yard"},
            {"code": "BERTH-2", "name": "Berth 2", "kind": "berth"},
        ],
        assets=[
            {
                "site": "BERTH-2",
                "code": "QC-04",
                "name": "Ship-to-shore crane 4",
                "asset_type": "sts_crane",
                "criticality": 5,
            },
            {
                "site": "YARD-3",
                "code": "SC-17",
                "name": "Straddle carrier 17",
                "asset_type": "straddle_carrier",
                "criticality": 4,
            },
            {"site": "YARD-3", "code": "RTG-11", "name": "Yard crane 11", "asset_type": "rtg_crane", "criticality": 4},
            {
                "site": "YARD-3",
                "code": "RS-09",
                "name": "Reach stacker 9",
                "asset_type": "reach_stacker",
                "criticality": 3,
            },
        ],
        contacts=[
            {
                "name": "Dana Whitfield",
                "role_label": "operations_supervisor",
                "phone": "+15045550110",
                "email": "operations@bayouterminal.com",
                "locale": Locale.EN,
            },
            {"name": "Marcus Bell", "role_label": "yard_supervisor", "phone": "+15045550111", "locale": Locale.EN},
            {
                "name": "Priya Shah",
                "role_label": "security_lead",
                "phone": "+15045550112",
                "email": "security@bayouterminal.com",
                "locale": Locale.EN,
            },
            {
                "name": "Luis Ortega",
                "role_label": "customer_service_lead",
                "email": "customerservice@bayouterminal.com",
                "phone": "+15045550113",
                "locale": Locale.ES,
            },
            {
                "name": "Tom Reyes",
                "role_label": "on_call_coordinator",
                "phone": "+15045550114",
                "whatsapp": "+15045550114",
                "locale": Locale.EN,
            },
        ],
        rules=_PORT_EXTRA_RULES,
        answers=[
            Answer(
                "Gate hours",
                "Gates A and B are open Monday to Friday 6:00 AM to 7:00 PM and Saturday 7:00 AM to 3:00 PM.",
                ["gate", "gates", "hours", "open", "time", "saturday", "close", "closing"],
                Locale.EN,
            ),
            Answer(
                "Gate status today",
                "Import surge today: gate A is open with a wait of about 2 hours. Gate B is closed for a lane repair until 2:00 PM; use gate A. Appointments stay valid for 2 hours past their slot.",
                [
                    "status",
                    "today",
                    "now",
                    "wait",
                    "line",
                    "queue",
                    "gate b",
                    "gate a",
                    "delay",
                    "moving",
                    "closed",
                    "open",
                ],
                Locale.EN,
            ),
            Answer(
                "Rebook an appointment",
                "Missed or late for your slot? Rebook in the terminal appointment portal up to 2 hours before the new time. No fee for the first rebooking.",
                ["appointment", "rebook", "reschedule", "slot", "late", "missed", "booking", "change"],
                Locale.EN,
            ),
            Answer(
                "Empty container returns",
                "Return empties to yard 3, row E. Bring the EIR number; empties are accepted until 5:00 PM.",
                ["empty", "empties", "return", "drop", "container", "where"],
                Locale.EN,
            ),
            Answer(
                "Documents for pickup",
                "For an import pickup you need your TWIC card, the booking or BOL number and a confirmed appointment.",
                ["documents", "twic", "pickup", "pick", "need", "bol", "paperwork", "requirements", "import"],
                Locale.EN,
            ),
            Answer(
                "Estado del portón hoy",
                "Hoy hay alto volumen de importación: el portón A está abierto con una espera de unas 2 horas. El portón B está cerrado por reparación hasta las 14:00; usar el portón A. Los turnos valen hasta 2 horas después del horario.",
                ["estado", "hoy", "ahora", "espera", "fila", "porton", "abierto", "cerrado", "demora"],
                Locale.ES,
            ),
            Answer(
                "Vessel ETA",
                "MSC Aurora was held by weather and is now due at berth 2 Thursday at 6:00 AM. Its import containers can be picked up from Thursday 2:00 PM; check the vessel schedule page for updates.",
                [
                    "eta",
                    "vessel",
                    "ship",
                    "arrive",
                    "arriving",
                    "arrival",
                    "berth",
                    "aurora",
                    "available",
                    "discharge",
                    "container",
                ],
                Locale.EN,
            ),
            Answer(
                "Llegada del buque",
                "El MSC Aurora se demoró por el clima y ahora llega al muelle 2 el jueves a las 6:00. Sus contenedores de importación se pueden retirar desde el jueves a las 14:00.",
                ["eta", "buque", "barco", "llega", "llegada", "arribo", "muelle", "aurora", "disponible"],
                Locale.ES,
            ),
        ],
    ),
    # ------------------------------------------------------------------ LATAM maritime
    DemoClient(
        name="Terminal Atlântico",
        slug="demo-terminal-atlantico",
        owner_email="owner@atlantico.demo",
        owner_name="Rafael Lima",
        industry=Industry.MARITIME,
        region=Region.LATAM,
        locale=Locale.PT,
        units=UnitSystem.METRIC,
        timezone="America/Sao_Paulo",
        blurb="LATAM maritime · Portuguese · congestion on disruption days",
        sites=[
            {"code": "GATE-1", "name": "Portão 1", "kind": "gate"},
            {"code": "GATE-2", "name": "Portão 2", "kind": "gate"},
            {"code": "PATIO-B", "name": "Pátio B", "kind": "yard"},
            {"code": "BERCO-3", "name": "Berço 3", "kind": "berth"},
        ],
        assets=[
            {"site": "BERCO-3", "code": "PT-02", "name": "Portêiner 2", "asset_type": "sts_crane", "criticality": 5},
            {
                "site": "PATIO-B",
                "code": "RS-21",
                "name": "Empilhadeira RS-21",
                "asset_type": "reach_stacker",
                "criticality": 3,
            },
            {
                "site": "PATIO-B",
                "code": "TT-08",
                "name": "Caminhão de pátio TT-08",
                "asset_type": "terminal_tractor",
                "criticality": 3,
            },
        ],
        contacts=[
            {
                "name": "Rafael Lima",
                "role_label": "operations_supervisor",
                "phone": "+5513955550120",
                "email": "operacoes@terminalatlantico.com.br",
                "locale": Locale.PT,
            },
            {
                "name": "Camila Rocha",
                "role_label": "customer_service_lead",
                "email": "atendimento@terminalatlantico.com.br",
                "phone": "+5513955550121",
                "locale": Locale.PT,
            },
            {"name": "Bruno Alves", "role_label": "yard_supervisor", "phone": "+5513955550122", "locale": Locale.PT},
            {
                "name": "Joana Melo",
                "role_label": "on_call_coordinator",
                "phone": "+5513955550123",
                "whatsapp": "+5513955550123",
                "locale": Locale.PT,
            },
            {
                "name": "Paulo Reis",
                "role_label": "security_lead",
                "phone": "+5513955550124",
                "email": "seguranca@terminalatlantico.com.br",
                "locale": Locale.PT,
            },
        ],
        rules=_PORT_EXTRA_RULES,
        answers=[
            Answer(
                "Situação dos portões hoje",
                "Por causa da paralisação, o portão 1 está fechado. O portão 2 opera com espera de cerca de 3 horas. Janelas de hoje continuam válidas até as 22h.",
                [
                    "situacao",
                    "hoje",
                    "agora",
                    "portao",
                    "portoes",
                    "fila",
                    "espera",
                    "aberto",
                    "fechado",
                    "greve",
                    "paralisacao",
                    "entrar",
                    "status",
                ],
                Locale.PT,
            ),
            Answer(
                "Reagendar janela",
                "Perdeu a janela? Reagende no portal de agendamento até 2 horas antes do novo horário. Durante a paralisação, o reagendamento é gratuito.",
                [
                    "reagendar",
                    "reagendamento",
                    "janela",
                    "agendamento",
                    "perdi",
                    "atrasado",
                    "atraso",
                    "remarcar",
                    "horario",
                ],
                Locale.PT,
            ),
            Answer(
                "Documentos para retirada",
                "Para retirar contêiner de importação: CNH, documento do veículo, número da reserva ou BL e agendamento confirmado.",
                ["documentos", "documento", "retirada", "retirar", "cnh", "bl", "reserva", "preciso", "papeis"],
                Locale.PT,
            ),
            Answer(
                "Devolução de vazio",
                "Vazios são devolvidos no pátio B, quadra 4, até as 18h. Leve o número do EIR.",
                ["vazio", "vazios", "devolucao", "devolver", "onde", "entregar", "conteiner"],
                Locale.PT,
            ),
            Answer(
                "Estado del portón hoy",
                "Por el paro, el portón 1 está cerrado. El portón 2 opera con una espera de unas 3 horas. Los turnos de hoy siguen válidos hasta las 22 h.",
                [
                    "estado",
                    "hoy",
                    "ahora",
                    "porton",
                    "fila",
                    "espera",
                    "abierto",
                    "cerrado",
                    "paro",
                    "huelga",
                    "entrar",
                ],
                Locale.ES,
            ),
            Answer(
                "Gate status today",
                "Because of the strike, gate 1 is closed. Gate 2 is operating with a wait of about 3 hours. Today's slots stay valid until 10 PM.",
                ["status", "today", "now", "gate", "line", "queue", "wait", "open", "closed", "strike"],
                Locale.EN,
            ),
            Answer(
                "Previsão de atracação",
                "O Maersk Santos atrasou por causa da greve e tem nova previsão de atracação no berço 3 na quinta às 18h. A liberação dos contêineres começa na sexta às 8h.",
                [
                    "eta",
                    "navio",
                    "atracacao",
                    "atracar",
                    "chegada",
                    "chega",
                    "previsao",
                    "berco",
                    "maersk",
                    "liberacao",
                    "quando",
                ],
                Locale.PT,
            ),
            Answer(
                "Llegada del buque",
                "Por el paro, el Maersk Santos tiene nueva previsión de atraque en el muelle 3 el jueves a las 18 h. Los contenedores se liberan desde el viernes a las 8 h.",
                ["eta", "buque", "barco", "llega", "llegada", "atraque", "muelle", "maersk", "cuando"],
                Locale.ES,
            ),
            Answer(
                "Vessel ETA",
                "Because of the strike, Maersk Santos is now due at berth 3 on Thursday at 6:00 PM. Its containers are released from Friday 8:00 AM.",
                ["eta", "vessel", "ship", "arrive", "arriving", "arrival", "berth", "maersk", "when", "released"],
                Locale.EN,
            ),
        ],
    ),
]

# Starter packs are written in English. A Spanish or Portuguese client sees its rules,
# work orders and event types in its own language, as it would after onboarding.
_TRANSLATIONS: dict[Locale, dict[str, str]] = {
    Locale.ES: {
        "Assistant needs a person": "El asistente necesita a una persona",
        "Assistant handed a conversation to a person": "El asistente derivó una conversación",
        "Gas reading above threshold": "Lectura de gas sobre el umbral",
        "Vehicle incident with injuries": "Incidente vehicular con heridos",
        "Flare flashback": "Retroceso de llama en antorcha",
        "PPE violation": "Falta de EPP",
        "Spill reported": "Derrame reportado",
        "Person close to moving equipment": "Persona cerca de equipo en movimiento",
        "Measurement ready for sign-off": "Medición lista para aprobar",
        "Equipment fault on a critical asset": "Falla en equipo crítico",
        "Gas detection": "Detección de gas",
        "Vehicle incident": "Incidente vehicular",
        "Struck-by or caught-in hazard": "Riesgo de golpe o atrapamiento",
        "Spill": "Derrame",
        "Equipment fault": "Falla de equipo",
        "Material measurement": "Medición de material",
        "Investigate {attributes.gas} reading at {site.name}": "Investigar lectura de {attributes.gas} en {site.name}",
        "Inspect flare system at {site.name}": "Inspeccionar sistema de antorcha en {site.name}",
        "Contain and report spill at {site.name}": "Contener y reportar derrame en {site.name}",
        "Stop work and review struck-by risk in {attributes.zone} at {site.name}": (
            "Detener tareas y revisar riesgo de golpe: {attributes.zone}, {site.name}"
        ),
        "Sign off {attributes.material} measurement at {site.name}": (
            "Aprobar medición de {attributes.material} en {site.name}"
        ),
        "Check {asset.name} ({attributes.fault_code}) at {site.name}": (
            "Revisar {asset.name} ({attributes.fault_code}) en {site.name}"
        ),
    },
    Locale.PT: {
        "Assistant needs a person": "Assistente precisa de uma pessoa",
        "Assistant handed a conversation to a person": "Assistente encaminhou uma conversa",
        "Gate closed": "Portão fechado",
        "Truck wait over two hours": "Espera de caminhões acima de 2 horas",
        "Yard near miss": "Quase acidente no pátio",
        "Cyber incident": "Incidente cibernético",
        "Strike or blockade": "Greve ou bloqueio",
        "Vessel delay over six hours": "Navio com atraso acima de 6 horas",
        "Severe weather": "Tempo severo",
        "Gate status change": "Mudança no status do portão",
        "Truck queue": "Fila de caminhões",
        "Vessel delay": "Atraso de navio",
        "Weather alert": "Alerta de tempo",
        "Review near miss in {attributes.zone}": "Analisar quase acidente em {attributes.zone}",
        "Secure cranes and stacks: {attributes.condition}": "Travar guindastes e pilhas: {attributes.condition}",
    },
}


def _localize(session: Session, org_id, locale: Locale) -> None:
    words = _TRANSLATIONS.get(locale)
    if not words:
        return
    for rule in session.scalars(select(Rule).where(Rule.org_id == org_id)):
        rule.name = words.get(rule.name, rule.name)
        rule.actions = [
            {**a, "title": words.get(a["title"], a["title"])} if a.get("type") == "create_work_order" else a
            for a in rule.actions
        ]
    for event_type in session.scalars(select(EventType).where(EventType.org_id == org_id)):
        event_type.name = words.get(event_type.name, event_type.name)
    session.flush()


def load(session: Session) -> list[tuple[DemoClient, str]]:
    """Create the four demo clients. Returns each client with its device API key (shown once)."""
    actor = Actor.system("seed")
    created: list[tuple[DemoClient, str]] = []
    for spec in CLIENTS:
        org = tenancy.create_organization(
            session,
            actor,
            OrgCreateIn(
                name=spec.name,
                slug=spec.slug,
                industry=spec.industry,
                region=spec.region,
                default_locale=spec.locale,
                unit_system=spec.units,
                timezone=spec.timezone,
                enabled_modules=[Module.ASSISTANT],
                owner=OwnerIn(email=spec.owner_email, full_name=spec.owner_name, password=DEMO_PASSWORD),
            ),
        )
        ctx = Ctx(org=org, actor=actor, role=Role.OWNER)
        sites = {s["code"]: catalog.create_site(session, ctx, SiteCreateIn(**s)) for s in spec.sites}
        for a in spec.assets:
            data = {k: v for k, v in a.items() if k != "site"}
            catalog.create_asset(session, ctx, AssetCreateIn(site_id=sites[a["site"]].id, **data))
        for c in spec.contacts:
            catalog.create_contact(session, ctx, ContactCreateIn(**c))
        for r in spec.rules:
            catalog.create_rule(session, ctx, RuleCreateIn(**r))
        for ans in spec.answers:
            knowledge.create(
                session,
                ctx,
                KnowledgeCreateIn(
                    title=ans.title,
                    content=ans.content,
                    keywords=ans.keywords,
                    locale=ans.locale,
                    site_id=sites[ans.site].id if ans.site else None,
                ),
            )
        _localize(session, org.id, spec.locale)
        for m in spec.extra_members:
            tenancy.add_member(session, ctx, MemberCreateIn(password=DEMO_PASSWORD, **m))
        _, key = tenancy.create_api_key(
            session,
            ctx,
            ApiKeyCreateIn(name="Demo devices", scopes=[ApiKeyScope.EVENTS_WRITE, ApiKeyScope.MESSAGES_WRITE]),
        )
        created.append((spec, key))
    return created
