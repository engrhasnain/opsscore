"""Message catalogs for everything the platform says to people.

English, Spanish and Portuguese cover the US and Latin America. A missing key
in a language falls back to English rather than failing a notification.
"""

from app.enums import Locale, Severity

_CATALOG: dict[str, dict[Locale, str]] = {
    "severity.info": {Locale.EN: "Info", Locale.ES: "Info", Locale.PT: "Info"},
    "severity.low": {Locale.EN: "Low", Locale.ES: "Baja", Locale.PT: "Baixa"},
    "severity.medium": {Locale.EN: "Medium", Locale.ES: "Media", Locale.PT: "Média"},
    "severity.high": {Locale.EN: "High", Locale.ES: "Alta", Locale.PT: "Alta"},
    "severity.critical": {Locale.EN: "Critical", Locale.ES: "Crítica", Locale.PT: "Crítica"},
    "notify.label.event": {Locale.EN: "Event", Locale.ES: "Evento", Locale.PT: "Evento"},
    "notify.label.site": {Locale.EN: "Site", Locale.ES: "Sitio", Locale.PT: "Local"},
    "notify.label.asset": {Locale.EN: "Asset", Locale.ES: "Equipo", Locale.PT: "Equipamento"},
    "notify.label.time": {Locale.EN: "Time", Locale.ES: "Hora", Locale.PT: "Hora"},
    "notify.label.details": {Locale.EN: "Details", Locale.ES: "Detalles", Locale.PT: "Detalhes"},
    "notify.label.occurrences": {
        Locale.EN: "Occurrences",
        Locale.ES: "Ocurrencias",
        Locale.PT: "Ocorrências",
    },
    "notify.label.reference": {
        Locale.EN: "Reference",
        Locale.ES: "Referencia",
        Locale.PT: "Referência",
    },
    "notify.escalated": {
        Locale.EN: "Severity raised",
        Locale.ES: "Severidad aumentada",
        Locale.PT: "Severidade elevada",
    },
    "notify.reminder": {
        Locale.EN: "Still open",
        Locale.ES: "Sigue abierta",
        Locale.PT: "Ainda aberto",
    },
    "notify.work_order.new": {
        Locale.EN: "New work order",
        Locale.ES: "Nueva orden de trabajo",
        Locale.PT: "Nova ordem de serviço",
    },
    "notify.work_order.overdue": {
        Locale.EN: "Work order past due",
        Locale.ES: "Orden de trabajo vencida",
        Locale.PT: "Ordem de serviço atrasada",
    },
    "notify.late_report": {
        Locale.EN: "Reported late: received {minutes} min after it happened",
        Locale.ES: "Reporte tardío: recibido {minutes} min después del hecho",
        Locale.PT: "Relato atrasado: recebido {minutes} min depois do ocorrido",
    },
    "notify.label.priority": {Locale.EN: "Priority", Locale.ES: "Prioridad", Locale.PT: "Prioridade"},
    "notify.label.due": {Locale.EN: "Due", Locale.ES: "Vence", Locale.PT: "Prazo"},
    "priority.low": {Locale.EN: "Low", Locale.ES: "Baja", Locale.PT: "Baixa"},
    "priority.normal": {Locale.EN: "Normal", Locale.ES: "Normal", Locale.PT: "Normal"},
    "priority.high": {Locale.EN: "High", Locale.ES: "Alta", Locale.PT: "Alta"},
    "priority.urgent": {Locale.EN: "Urgent", Locale.ES: "Urgente", Locale.PT: "Urgente"},
    "assistant.emergency": {
        Locale.EN: (
            "If anyone is hurt or in danger, call your site emergency number now. "
            "I have alerted the person on duty and they will contact you."
        ),
        Locale.ES: (
            "Si alguien está herido o en peligro, llame ahora al número de emergencia del "
            "sitio. Ya avisé a la persona de guardia y se comunicará con usted."
        ),
        Locale.PT: (
            "Se alguém estiver ferido ou em perigo, ligue agora para o número de emergência "
            "do local. Já avisei a pessoa de plantão e ela entrará em contato."
        ),
    },
    "assistant.handoff": {
        Locale.EN: "I'm passing you to a person on our team. They will reply here shortly.",
        Locale.ES: "Le paso con una persona de nuestro equipo. Le responderá aquí en breve.",
        Locale.PT: "Vou passar você para uma pessoa da nossa equipe. Ela responderá aqui em breve.",
    },
    "assistant.no_answer": {
        Locale.EN: ("I don't have a confirmed answer for that. I've asked a person on our team to reply to you here."),
        Locale.ES: (
            "No tengo una respuesta confirmada para eso. Le pedí a una persona de nuestro equipo que le responda aquí."
        ),
        Locale.PT: (
            "Não tenho uma resposta confirmada para isso. Pedi a uma pessoa da nossa equipe que responda aqui."
        ),
    },
    "assistant.non_text": {
        Locale.EN: "I can only read text messages. Please type your question.",
        Locale.ES: "Solo puedo leer mensajes de texto. Por favor escriba su pregunta.",
        Locale.PT: "Só consigo ler mensagens de texto. Por favor, digite sua pergunta.",
    },
}


def t(key: str, locale: Locale | str | None) -> str:
    entry = _CATALOG.get(key)
    if entry is None:
        return key
    try:
        loc = Locale(locale) if locale else Locale.EN
    except ValueError:
        loc = Locale.EN
    return entry.get(loc) or entry[Locale.EN]


def severity_label(severity: Severity | str, locale: Locale | str | None) -> str:
    return t(f"severity.{Severity(severity).value}", locale)


def all_keys() -> list[str]:
    return list(_CATALOG)


def missing_translations() -> list[tuple[str, Locale]]:
    return [(key, loc) for key, entry in _CATALOG.items() for loc in Locale if loc not in entry]
