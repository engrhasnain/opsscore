"""Language detection and intent cues for English, Spanish and Portuguese.

Deliberately simple and predictable: word lists, not a model. It runs on
every message, offline, in microseconds, and its mistakes are easy to explain.

Emergency detection is biased towards false alarms: "is there a fire
extinguisher at gate 3?" escalates. Waking a supervisor for nothing is cheap;
a bot calmly answering someone reporting a fire is not. Only a few phrasings
that are plainly routine ("stuck in the queue", "my battery is dead", "H2S
card") are let through.
"""

import re
import unicodedata
from typing import Literal

from app.enums import Locale

_WORD = re.compile(r"[a-z0-9]+")
_RAW_WORD = re.compile(r"\w+")

# fmt: off
# Words that are common in one language and rare in the other two.
_MARKERS: dict[Locale, frozenset[str]] = {
    Locale.EN: frozenset(
        "the is are what where when how can could would my your i you we they this that with "
        "have has need want please thanks thank hello hi hey truck gate delivery today tomorrow "
        "open closed time there here which morning afternoon evening".split()
    ),
    Locale.ES: frozenset(
        "el los las del usted ustedes donde cuando puedo necesito quiero gracias hola buenos "
        "buenas dias tardes noches camion porton salida hoy manana abierto cerrado hay cual "
        "estoy tengo llegar muchas senor contenedor contenedores vacio vacios turno paro huelga "
        "ahora cuanto tiempo mucha mucho cola ayuda tambien pueden puede".split()
    ),
    Locale.PT: frozenset(
        "voce voces nao sim obrigado obrigada oi ola bom boa dia tarde noite onde quando posso "
        "preciso quero caminhao portao portoes hoje amanha aberto fechado tem qual estou tenho "
        "chegar muito muita senhor conteiner conteineres vazio vazios agora quanto tempo greve "
        "paralisacao janela agendamento valeu pelo pela na tambem ate ajuda".split()
    ),
}
# Accented spellings only one language uses ("horário" is Portuguese, "horario" is not).
_ACCENTED_MARKERS: dict[Locale, frozenset[str]] = {
    Locale.PT: frozenset("horário você vocês até três contêiner contêineres é já só também pés".split()),
    Locale.ES: frozenset("qué cuál cuándo dónde cómo día días camión portón sí también".split()),
}
# fmt: on

_ACCENT_CUES = {Locale.PT: "ãõçêô", Locale.ES: "ñ¿¡"}

# ---------------------------------------------------------------- emergency

# fmt: off
_EMERGENCY_EXACT = frozenset(
    # English
    "hurt dead died crash crashed fell fallen trapped flipped mayday sos "
    # Spanish
    "fuego humo muerto muerta murio choque choco cayo caido caida atrapado atrapada socorro "
    "auxilio volco volcado "
    # Portuguese
    "fogo fumaca morto morta morreu batida bateu caiu preso presa tombou tombado".split()
)
# Word beginnings: "fires", "smoking", "spilled", "injuries", "vazando", "derramó", "incêndio".
_EMERGENCY_STEMS = (
    "fire", "smok", "spill", "injur", "leak", "explos", "explod", "bleed", "accident", "acident",
    "emergenc", "unconscio", "inconscien", "desmai", "desmay", "collaps", "colaps", "ambulanc",
    "incend", "derram", "vaza", "ferid", "herid", "lesionad", "sangr", "sangue", "electrocut",
    "eletrocut", "atropel", "overturn", "rollover", "capot",
)
_EMERGENCY_PHRASES = ("man down", "person down", "hombre caido", "homem caido", "se cayo", "pegando fogo")
_NOT_EMERGENCY_TOKENS = frozenset("firewall firewalls firestone".split())
_SMOKING_ROUTINE = ("smoking area", "smoking zone", "smoke break", "no smoking", "smoking allowed")
# "Stuck in the queue" is a complaint, not someone trapped.
_QUEUE_WORDS = frozenset(
    "line queue traffic fila cola trafico transito engarrafamento congestionamento".split()
)
_TRAPPED = frozenset("trapped atrapado atrapada preso presa".split())
_DEVICES = frozenset("battery batteries bateria phone telefone celular cell radio".split())
_DEAD = frozenset("dead died muerto muerta murio morto morta morreu".split())
# "Do I need an H2S card?" is a question about training, unless something is going off.
_H2S_ROUTINE = frozenset(
    "card cards training orientation class course certificate certification cert clear monitor "
    "tarjeta curso capacitacion certificado carnet cartao treinamento carteirinha".split()
)
_ALARM_WORDS = frozenset(
    "alarm alarms alarma alarme going beeping sounding ppm smell smells olor cheiro reading "
    "detected detector sonando apitando tocando disparou disparo".split()
)
_HELP = frozenset("help ayuda ajuda".split())
_HELP_SHOUTED = re.compile(r"\b(help|ayuda|ajuda)\s*!", re.IGNORECASE)
_HELP_CAPS = re.compile(r"\b(HELP|AYUDA|AJUDA)\b")
# fmt: on

# -------------------------------------------------------------------- humans

# Explicit requests for a person. Mentioning a person ("someone told me",
# "my supervisor sent me", "the customs agent") is not a request.
_HUMAN_REQUESTS = [
    re.compile(p)
    for p in (
        # English
        r"\b(talk|speak|chat)\s+(to|with)\b",
        r"\b(real|live|actual)\s+(person|human|agent|people)\b",
        r"\b(get|connect|transfer|put)\s+me\s+(to|with|through)\b",
        r"\b(call|ring)\s+me\b",
        r"\b(human|agent|operator|representative|person)\s+(please|pls)\b",
        r"\bi\s+(want|need)\s+(a|an)\s+(human|person|agent|operator|representative)\b",
        # Spanish
        r"\bhablar\s+con\b",
        r"\bpersona\s+real\b",
        r"\b(comunicarme|contactar|contactarme)\s+con\b",
        r"\b(llamenme|llameme)\b",
        r"\b(quiero|necesito)\s+(un|una)\s+(persona|humano|agente|operador|representante)\b",
        r"\b(agente|operador|humano|persona)\s+por\s+favor\b",
        # Portuguese
        r"\bfalar\s+com\b",
        r"\batendente\b",
        r"\bpessoa\s+(real|de\s+verdade)\b",
        r"\b(me\s+liga|me\s+ligue|me\s+ligar|liguem\s+para\s+mim)\b",
        r"\b(quero|preciso\s+de)\s+(um|uma)\s+(pessoa|humano|atendente|operador)\b",
    )
]
_HUMAN_ALONE = frozenset(
    "human agent operator representative person humano agente operador representante persona pessoa atendimento".split()
)

# ------------------------------------------------------------------ courtesy

# fmt: off
_THANKS = frozenset(
    "thanks thank thx ty tks appreciate appreciated gracias agradecido agradecida agradezco "
    "obrigado obrigada brigado brigada valeu".split()
)
_GREETINGS = frozenset(
    "hi hello hey hola oi ola buenos buenas bom boa morning afternoon evening".split()
)
# Words that may surround a greeting, a thanks or an acknowledgement and add nothing.
_COURTESY_FILL = frozenset(
    "ok okay okey kk cool great nice perfect perfecto perfeito excelente excellent alright fine "
    "sure yes yep yeah yup si sim claro vale dale listo beleza blz show certo entendi entendido "
    "understood noted got it you very much so lot muchas muchos mil muito muita muitos de nada "
    "por favor please good dia dias tarde tardes noche noches noite day night for the your all "
    "again help info information ayuda ajuda la el pela pelo a o tudo bem bye goodbye chau chao "
    "adios tchau logo luego later saludos abraco abrazo there team equipe equipo senor senora "
    "senhor senhora sir maam friend amigo amiga voce usted helped ajudou ayudo ayudaste".split()
)
# fmt: on

Courtesy = Literal["thanks", "greeting", "ack"]

# ------------------------------------------------------------------ matching

# fmt: off
STOPWORDS = frozenset(
    "a an the is are am be to of in on at for and or i you my me we it this that do does "
    "can could what where when how please el la los las de del en y o un una que es por "
    "para con se mi yo me lo al o os as um uma do da dos das no na nos nas e eu meu "
    "minha com por favor".split()
)
# Words that say nothing about the topic: greetings, courtesy and common verbs.
# They are ignored when judging how much of a question an answer covers.
FILLER = frozenset(
    # English
    "hi hello hey thanks thank thx pls ok okay good morning afternoon evening sir maam was were "
    "been have has had got get getting need needs want like know tell us your our will would "
    "should just also there here which who why did doing done any some much many very really "
    "im its "
    # Spanish
    "hola buenos buenas dias tardes noches gracias senor senora usted ustedes esta estoy estan "
    "son era fue hay tengo tiene tienen necesito quiero puedo puede pueden saber como cual "
    "cuales quien porque muy mucho mucha algo alguien su sus nuestro "
    # Portuguese
    "oi ola bom boa dia tarde noite obrigado obrigada voce voces senhor senhora estou estao sao "
    "foi tem tenho quero posso pode podem consigo qual quais quem muito muita isso esse essa "
    "aqui seu sua nosso pelo pela "
    # units after a number ("40 pés", "40ft")
    "pes pies ft feet foot pe".split()
)
# fmt: on


def fold(text: str) -> str:
    """Lowercase and strip accents: "Camión" -> "camion"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def words(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def content_words(text: str) -> set[str]:
    return {w for w in words(text) if w not in STOPWORDS and len(w) > 1}


def detect(text: str) -> Locale | None:
    """The language of a message, or None when there is not enough signal."""
    lowered = text.casefold()
    tokens = words(text)
    raw_tokens = _RAW_WORD.findall(lowered)
    scores = {locale: sum(1 for t in tokens if t in markers) for locale, markers in _MARKERS.items()}
    for locale, cues in _ACCENT_CUES.items():
        if any(c in lowered for c in cues):
            scores[locale] += 2
    for locale, accented in _ACCENTED_MARKERS.items():
        scores[locale] += 2 * sum(1 for t in raw_tokens if t in accented)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    (best, best_score), (_, second_score) = ranked[0], ranked[1]
    if best_score == 0 or best_score == second_score:
        return None
    return best


def is_emergency(text: str) -> bool:
    folded = fold(text)
    tokens = _WORD.findall(folded)
    token_set = set(tokens)
    if any(phrase in folded for phrase in _EMERGENCY_PHRASES):
        return True
    routine_smoking = any(phrase in folded for phrase in _SMOKING_ROUTINE)
    for token in tokens:
        if token in _NOT_EMERGENCY_TOKENS:
            continue
        if token in _TRAPPED and token_set & _QUEUE_WORDS:
            continue  # "preso na fila", "stuck in traffic"
        if token in _DEAD and token_set & _DEVICES:
            continue  # "my battery is dead"
        if token in _EMERGENCY_EXACT:
            return True
        if token.startswith(_EMERGENCY_STEMS):
            if token.startswith("smok") and routine_smoking:
                continue
            return True
    if "h2s" in token_set and (token_set & _ALARM_WORDS or not token_set & _H2S_ROUTINE):
        return True
    # "help!", "HELP", or a bare "help me" / "I need help" (but not "thanks for the help").
    shouted = _HELP_SHOUTED.search(text) or _HELP_CAPS.search(text) or len(tokens) <= 3
    return bool(token_set & _HELP and not token_set & _THANKS and shouted)


def wants_human(text: str) -> bool:
    folded = fold(text)
    if any(pattern.search(folded) for pattern in _HUMAN_REQUESTS):
        return True
    tokens = words(text)
    return 0 < len(tokens) <= 2 and all(t in _HUMAN_ALONE or t in STOPWORDS for t in tokens)


def courtesy(text: str) -> Courtesy | None:
    """Classify a message that is only a greeting, a thanks or an acknowledgement.

    "thanks!", "obrigado", "ok", "👍" and "hola buenos días" are courtesy;
    "hola, a qué hora abre el pad 7?" is not, because it asks something.
    Messages of only emoji or punctuation count as an acknowledgement.
    """
    tokens = words(text)
    if any(t.isdigit() for t in tokens):
        return None
    vocabulary = _THANKS | _GREETINGS | _COURTESY_FILL
    if len(tokens) > 8 or any(t not in vocabulary for t in tokens):
        return None
    token_set = set(tokens)
    if token_set & _THANKS:
        return "thanks"
    if token_set & _GREETINGS:
        return "greeting"
    return "ack"
