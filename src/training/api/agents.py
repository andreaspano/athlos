"""La chiamata al modello: un agente, un prompt, una risposta (todo 94).

Prima ogni sezione era un processo `claude -p`, cioe' una sessione intera di
Claude Code con il suo prompt di sistema, le definizioni dei suoi tool e un
giro di agente che leggeva i fatti da un file e scriveva il frammento. Era
l'1% di token utili: 46.000 in ingresso per 1.500 di testo, cinque o sei
richieste al modello, e tutto quello che l'agente andava a leggere lo aveva
gia' in mano chi lo lanciava (misurato sui transcript, todo 94).

Adesso e' **una chiamata sola**: il prompt dell'agente e lo stile fanno il
blocco di sistema, i fatti e i documenti vanno nel messaggio, e il testo
torna qui. Il file lo scrive chi ha chiamato, che e' anche chi controlla.

**Niente tool.** Non c'e' nessun giro da fare: senza tool non ci sono
permessi da scrivere, non c'e' un file da controllare dopo, e non c'e' il
modo in cui un agente puo' uscire con esito 0 senza aver scritto niente.

**Niente cache.** Una richiesta per sezione, un prefisso diverso per agente
e dodici ore fra un giro e l'altro: non c'e' niente da riusare, e pagare la
scrittura in cache (1,25x) per non rileggerla mai sarebbe solo piu' caro.
"""

import re
from pathlib import Path

import anthropic

# Dove stanno i prompt. Sono gli stessi file che Claude Code usa come agenti
# — si tiene il corpo e si butta il front matter (`name`, `description`,
# `tools`), che era roba sua — cosi' restano modificabili a mano e provabili
# con `claude --agent` senza doverli tenere in due posti.
AGENTS_DIR = ".claude/agents"
# Le regole che valgono per tutte le sezioni (voce, numeri, fasce) stanno in
# un file solo invece che copiate in tredici prompt.
STYLE_FILE = f"{AGENTS_DIR}/_style.md"

# Quello su cui gli agenti girano da sempre: lo dicono i transcript dei giri
# passati, non e' una scelta nuova.
MODEL = "claude-opus-5"
# Largo per una sezione da 300 token, e non e' spreco: su Opus 5 il
# ragionamento e' acceso per difetto e `max_tokens` e' il tetto di
# ragionamento **piu'** testo. Con un tetto stretto la sezione si troncava a
# meta', e il motivo non si sarebbe visto da nessuna parte.
MAX_TOKENS = 8000
# Un agente solo, non il giro intero (era il timeout del sottoprocesso).
TIMEOUT_SECONDS = 10 * 60

# Il front matter dei file di agente: fra due righe di soli tre trattini, in
# cima. Un file che non ce l'ha si prende tutto, che e' il caso giusto —
# `_style.md` non ne ha.
_FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*\r?\n", re.DOTALL)


class AgentError(RuntimeError):
    """Il modello non ha reso un testo usabile.

    Il messaggio e' in inglese perche' finisce nei banner della pagina, come
    tutti gli altri."""


def _body(text: str) -> str:
    """Il file senza il suo front matter."""
    return _FRONT_MATTER.sub("", text, count=1).strip()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentError(f"{path.name} could not be read: {exc}") from exc


def system_prompt(repo_root: Path, agent: str) -> str:
    """Il blocco di sistema di un agente: il suo prompt **e poi** lo stile.

    L'ordine non e' un dettaglio. Lo stile dice "solo il corpo, nessun
    preambolo", e arriva dopo perche' e' la regola che vince: era cosi' anche
    col sottoprocesso (`--append-system-prompt-file` attacca in coda), e il
    commento su `refresh.VERDICT_LINE` racconta che cosa si rompe quando
    quella parte manca. Invertirlo per far cachare lo stile fra agenti
    diversi guadagnerebbe mille token e rischierebbe una cosa provata."""
    root = Path(repo_root)
    agent_file = _body(_read(root / AGENTS_DIR / f"{agent}.md"))
    style = _read(root / STYLE_FILE).strip()
    return f"{agent_file}\n\n{style}"


def user_message(prompt: str, documents: dict[str, str]) -> str:
    """Il messaggio: prima i documenti, poi il lavoro.

    I documenti stanno davanti perche' il lavoro e' l'ultima cosa che si
    legge, e in un tag col suo nome perche' i prompt degli agenti li chiamano
    per nome ("the facts", "the plan for the week")."""
    blocks = "".join(
        f"<{name}>\n{text.strip()}\n</{name}>\n\n" for name, text in documents.items()
    )
    return f"{blocks}{prompt}"


def write(
    repo_root: Path,
    agent: str,
    prompt: str,
    documents: dict[str, str],
    client: anthropic.Anthropic | None = None,
) -> str:
    """Il testo che l'agente ha scritto. Alza `AgentError` se non c'e'.

    `client` si passa nei test: la suite non chiama l'API, come non chiama
    Garmin."""
    try:
        client = client or anthropic.Anthropic(timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - manca la chiave, o e' storta
        raise AgentError(
            f"The Anthropic client could not be built ({exc}). "
            "ANTHROPIC_API_KEY must be set for the service and the timers: "
            "see docs/service.md."
        ) from exc
    try:
        answer = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt(repo_root, agent),
            messages=[{"role": "user", "content": user_message(prompt, documents)}],
        )
    except anthropic.APIStatusError as exc:
        raise AgentError(f"{agent}: the model answered {exc.status_code} ({exc.message}).") from exc
    except anthropic.APIConnectionError as exc:
        raise AgentError(f"{agent}: the model could not be reached ({exc}).") from exc
    # Prima del testo si guarda **perche'** ha smesso: una risposta troncata
    # a meta' frase e una rifiutata hanno entrambe dei blocchi dentro, e
    # passerebbero per testo buono.
    if answer.stop_reason == "refusal":
        raise AgentError(f"{agent}: the model declined to answer.")
    if answer.stop_reason == "max_tokens":
        raise AgentError(
            f"{agent}: the answer hit the {MAX_TOKENS}-token ceiling and is cut off."
        )
    # Solo i blocchi di testo: su questo modello la risposta porta anche i
    # blocchi di ragionamento, che hanno il testo vuoto.
    text = "\n".join(
        block.text for block in answer.content if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise AgentError(f"{agent}: the model answered nothing.")
    return text
