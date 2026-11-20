"""Il testo della Health scritto **da un modello in casa**, per la pagina Test
(todo: banco di prova).

Il report vero lo scrivono gli agenti di Claude, uno per sezione, e
l'orchestratore sta in `api/refresh.py`: quello non si tocca: la Day legge i
frammenti che quelli scrivono in `summary/01.daily/<giorno>/`. Qui si risponde
a un'altra domanda — *che cosa scriverebbe un modello locale, con lo stesso
prompt?* — e la risposta non si scrive da nessuna parte: nasce quando la
pagina Test la chiede e muore con la risposta HTTP. Nessun frammento, nessun
file, niente che il report possa poi leggere per sbaglio.

**Il prompt sta in `.ollama/agents/`**, accanto a quello di Claude e non
dentro: `01_health.md` per la sezione e `_style.md` per le regole di casa,
nello stesso ordine in cui li legge un agente. Senza `_style.md` il modello
non saprebbe come si leggono le fasce, e il file della sezione glielo da' per
letto ("the house rules say how bands work"). Quello che li' non c'e' si
pesca da `.claude/agents/`, cosi' una differenza di una riga costa una riga.

Due cose cambiano per forza, e sono le sole:

- **I fatti vanno nel messaggio.** L'agente di Claude legge il file dei fatti
  con Read; qui di attrezzi non ce n'e' nessuno, quindi il JSON si mette
  dentro al prompt. E ci va **solo la parte della Health** — le quattro
  misure che la card mostra — che e' comunque l'unica che quel prompt ha il
  permesso di guardare, e il giorno intero non starebbe nei 4096 gettoni di
  contesto del modello.
- **Il testo torna come risposta**, non come file: l'ultima riga del prompt
  dell'orchestratore ("scrivi il corpo in <file>") qui diventa "rispondi con
  il solo corpo".

**Le due sezioni si chiedono anche in un altro modo**, e ognuna sta affiancata
a se' stessa sulla pagina. `health` e `load` sono le sezioni come le scrive un
agente di Claude: un prompt, tutti i numeri, tutti i paragrafi chiesti a un
modello solo. `health_split` e `load_split` sono le stesse sezioni spezzate in
una domanda per paragrafo — a un modello che degli altri paragrafi non sa
niente — piu' una che apre la sezione. Il testo finito lo cuce `_split_text`,
quindi i paragrafi ci sono sempre e nell'ordine della card: la forma smette di
essere una cosa che il prompt deve chiedere. I file stanno in
`.ollama/agents/01_health_split/` e `.ollama/agents/02_load_split/`, e `Part`
qui sotto dice perche' i pezzi delle due non si somigliano.

Il modello e' quello che gira su questa macchina: `ollama serve` sulla sua
porta, `llama3.1:8b` di suo. Si cambia con `ATHLOS_OLLAMA_MODEL` e
`ATHLOS_OLLAMA_URL` senza toccare il codice, che su un banco di prova provare
un altro modello e' il mestiere della pagina.

Si parla con `urllib` e non con `httpx`: httpx nell'ambiente c'e' ma per
strade di altri (FastAPI, garminconnect), e una pagina di prova non e' un
buon motivo per farne una dipendenza vera. Una POST con un JSON la fa la
libreria standard.
"""

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Le quattro misure della card, nell'ordine in cui la card le mostra. Sono
# anche le sole che il prompt dell'agente ha il permesso di giudicare: dargli
# il resto del giorno sarebbe tentarlo con la roba di Recovery e Fitness.
HEALTH_MEASURES = ("resting_hr", "hrv_last_night", "resp_sleep", "stress_avg_yesterday")

# I due allarmi che parlano di queste quattro misure. Gli altri sono di altre
# sezioni, e `01_health.md` dice espressamente di lasciarli stare.
HEALTH_ALERTS = ("resting_hr_up", "sleep_breathing_up")

# **Il prompt di llama sta per conto suo**, in `.ollama/agents/`. Il nome
# dice il motore e non il modello, come `.claude/` dice Claude Code e non
# Opus: quale modello giri lo decide `ATHLOS_OLLAMA_MODEL` a ogni chiamata, e
# una cartella che si chiamasse come un modello sarebbe da rinominare al
# primo che si prova.
#
# Prima questi due file erano quelli dell'agente di Claude, letti direttamente
# da `.claude/agents/`, e una cartella sola voleva dire che non si poteva
# aggiustare il prompt di llama senza cambiare quello che Claude scrive sulla
# Day. E da aggiustare c'era: l'esempio in fondo a `01_health.md` llama lo
# ricopiava — l'HRV "down at the low edge of its own range" con un 46 in
# mezzo alla fascia — e la copia di qui l'esempio non ce l'ha. Il resto e'
# lo stesso testo, voce compresa: i due devono restare confrontabili, che e'
# tutto il punto della pagina Test.
AGENT_DIR = ".ollama/agents"
# Da dove si pesca quello che in `.ollama/agents/` non c'e'. Un file in meno
# li' dentro vuol dire "su questo vale quello che vale per Claude", non un
# guasto: cosi' si puo' tenere una riga sola di differenza invece di due
# copie intere che divergono da sole.
FALLBACK_DIR = ".claude/agents"
STYLE_FILE = "_style.md"

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.1:8b"

# **La finestra del contesto.** Ollama di suo ne da' 4096, che non sono i
# 4096 del modello — llama3.1 ne regge 131072 — ma il suo valore di partenza.
# Il prompt della Load, da quando legge anche le sedute della settimana, e'
# 3052 gettoni: ci stava dentro, ma con un palmo di spazio, e si vedeva — la
# struttura in cinque paragrafi si perdeva, il verdetto spariva e le regole
# si scambiavano. Otto mila sono il doppio del prompt piu' lungo che ci
# passa, e per un modello da 5 GB sulla scheda costano poco.
CONTEXT_TOKENS = 8192

# Il modello carica da disco alla prima domanda — sette secondi scarsi su
# questa macchina — e poi scrive cento parole. Due minuti e' largo per tutti e
# due, e stretto abbastanza da non lasciare la card a girare per sempre.
TIMEOUT_SECONDS = 120


class OllamaError(RuntimeError):
    """Ollama non c'e', non risponde, o risponde qualcosa che non si capisce."""


def _without_front_matter(text: str) -> str:
    """Il corpo di un file di agente: via il front matter YAML fra `---`.

    Quelle righe sono per Claude Code — il nome dell'agente, i suoi attrezzi —
    e a un modello che non ha ne' l'uno ne' gli altri direbbero solo di avere
    Read e Write, che e' l'unica cosa qui che non e' vera."""
    if not text.startswith("---"):
        return text.strip()
    end = text.find("\n---", 3)
    if end == -1:
        return text.strip()
    return text[end + 4 :].strip()


def _prompt_file(repo_root: Path, name: str) -> Path:
    """Il file del prompt: quello di `.ollama/agents/` se c'e', se no quello
    dell'agente di Claude. Alza `FileNotFoundError` se non c'e' ne' l'uno ne'
    l'altro, che e' un repo rotto e non un caso da gestire."""
    mine = repo_root / AGENT_DIR / name
    if mine.exists():
        return mine
    theirs = repo_root / FALLBACK_DIR / name
    if theirs.exists():
        return theirs
    raise FileNotFoundError(f"No prompt called {name} in {AGENT_DIR} nor in {FALLBACK_DIR}.")


@dataclass(frozen=True)
class Section:
    """Una sezione che il modello di casa sa scrivere.

    Il registro e' piccolo apposta: la pagina Test non vuole essere il
    report, vuole far vedere **la stessa card scritta da un altro**. Ogni
    sezione porta il suo file di prompt e la funzione che le ritaglia i fatti,
    che e' tutto quello per cui due sezioni sono diverse."""

    key: str
    """Il nome nell'URL e nello stato, lo stesso con cui la Day chiama la sua
    sezione (`health`, `load`)."""
    title: str
    """Il titolo della sezione, come lo scrive il prompt."""
    agent: str
    """Il file in `.ollama/agents/`, col numero davanti come in `.claude/`."""
    facts: "Callable[[dict, dict | None], dict]"
    """Che cosa arriva al modello: dai fatti del giorno e dal piano della
    settimana (che puo' non esserci), quello che questa sezione possiede."""


# **La stessa sezione scritta in cinque pezzi.** Una `Section` e' una domanda
# sola: tutto il prompt, tutti i fatti, tutta la risposta. Uno `Split` e' la
# stessa sezione chiesta a cinque modelli piccoli — uno per misura, piu' uno
# che legge i quattro paragrafi e scrive il verdetto in cima.
#
# Il motivo e' che `01_health.md` **e' gia' cinque paragrafi**: il verdetto e
# le quattro misure, in quest'ordine. Spezzarlo rende strutturale quello che
# li' dentro e' una preghiera, e sono le tre righe in grassetto del file:
# *ognuna delle quattro ha il suo paragrafo, nessuna si salta, nessuna sesta*
# diventa una `join` di quattro risposte; *il sonno e la batteria sono di
# Recovery, non toccarli* diventa un modello che quei numeri non ce li ha
# proprio; *nel verdetto nessun numero* diventa un modello a cui si danno
# frasi e non cifre.
#
# E i guasti di questa pagina sono tutti guasti da prompt saturo: la docstring
# di `_verdict_word` lo dice in chiaro — la regola e' scritta e il modello
# scrive lo stesso il contrario. Quattro prompt da una misura l'uno saturi non
# sono.
#
# Vive **accanto** alla `Section`, non al suo posto: le due si guardano una
# accanto all'altra sulla pagina Test, sullo stesso giorno e con gli stessi
# numeri, che e' il mestiere di quella pagina. Se vince lo `Split`, l'altra va
# via allora e non adesso.


@dataclass(frozen=True)
class Part:
    """Un pezzo di una sezione, e chi lo scrive.

    Un pezzo porta **tre cose e solo quelle**: i file del suo prompt, che
    cosa dei fatti della sezione gli tocca, e la domanda con cui gliela si
    chiede. Sono le tre cose per cui due pezzi sono diversi, ed e' tutto
    quello che la cucitura ha bisogno di sapere: chiedere in ordine e
    attaccare le risposte lo fa `_split_text`, che di che pezzo abbia in mano
    non guarda niente.

    Erano nati le quattro misure della Health e di Health parlavano — una
    misura, da che parte della fascia sta la cattiva notizia, quale allarme
    e' suo — e il ritaglio e la domanda stavano in due funzioni sole, perche'
    tutti e quattro i pezzi erano la stessa cosa quattro volte. **La Load
    spezzata ne ha sei e sono di quattro mestieri diversi**: tre carichi con
    la loro fascia, un rapporto, il foglio della settimana, e il verdetto in
    cima. Il ritaglio e la domanda sono diventati campi perche' erano la cosa
    che cambiava, e `bad_when` e `alert` sono scesi a essere quello che sono:
    due campi che i pezzi di un'altra sezione non usano."""

    key: str
    """Come si chiama nei fatti della sezione (`resting_hr`,
    `load_anaerobic`). Per i pezzi che una misura non sono — il rapporto, la
    settimana, il verdetto — e' solo un nome: lo leggono i test, e nel testo
    finito non entra."""
    label: str
    """Come lo chiama chi parla ("resting heart rate", "how much you are
    carrying"): va nel messaggio e nella prima frase del paragrafo."""
    agent: "tuple[str, ...]"
    """I file del prompt, **dal piu' stretto al piu' largo**: prima quello
    che di questo pezzo e' solo suo, poi quelli che condivide. Una tupla e
    non un nome perche' i paragrafi delle misure stanno su due file — il loro
    e `_measure.md` — e il verdetto sul suo e basta. La differenza stava in
    `Split.shared`, un campo che valeva per tutti i pezzi tranne uno, e un
    campo con un'eccezione dentro e' un campo che non dice la verita'. I nomi
    `_system_prompt` li prende a piu' di uno da sempre."""
    cut: "Callable[[Split, Part, dict], dict | None]"
    """Il recinto dentro al recinto: dai fatti della sezione, quello che
    tocca a questo pezzo.

    **`None` vuol dire che il paragrafo non si scrive.** E' il caso della
    settimana senza piano: il prompt intero quel buco deve chiederlo a parole
    ("e' nullo quando la settimana non ha un piano, e allora non c'e' niente
    da dirne"), qui il pezzo non si chiede e la sezione ha un paragrafo in
    meno. La forma la decide Python anche quando la forma cambia, che e' il
    punto di tutta questa strada."""
    asks: "Callable[[Split, Part, date, dict], str]"
    """Il messaggio: scrivi questo paragrafo, questi sono i fatti, leggili
    cosi'. Il `dict` e' quello che ha reso `cut`."""
    bad_when: str | None = None
    """Da che parte della fascia e' la cattiva notizia: `above` o `below`.
    **Non e' per questo agente** — il suo file glielo dice a parole — e' per
    chi apre la sezione, che le misure le ha tutte e quattro e non sono dalla
    stessa parte.

    **Nullo per i tre carichi della Load, e non per dimenticanza**: un carico
    sopra la sua fascia non e' una notizia cattiva ne' buona finche' non si
    sa che settimana era — l'anaerobico sopra fascia e' il piano che funziona
    in una settimana di qualita' e il piano disatteso in una di scarico — e
    `_reading`, che da `where` e da questo campo tira fuori la notizia, e'
    percio' della Health e non della cucitura."""
    alert: str | None = None
    """L'allarme che parla di questa misura, se ce n'e' uno. Gli altri non
    arrivano: un allarme in mano a chi non lo possiede e' un allarme che
    finisce nel testo."""


@dataclass(frozen=True)
class Split:
    """Una sezione scritta in piu' pezzi: un paragrafo per pezzo, e uno in
    cima che li apre."""

    key: str
    """Il nome nell'URL, accanto a quello della sezione intera."""
    title: str
    """Il titolo della sezione: lo stesso dell'altra, che e' la stessa
    sezione."""
    facts: "Callable[[dict, dict | None], dict]"
    """Gli stessi fatti della sezione intera, ritagliati dalla stessa
    funzione: il recinto e' quello, e il pezzo che tocca a ognuno si taglia
    dopo. Due ritagli vorrebbero dire due recinti che divergono."""
    opening: Part
    """Il pezzo che apre la sezione. **Sta fuori da `parts` perche' e' il solo
    che parla degli altri**: il suo ritaglio li legge tutti, e dentro `parts`
    leggerebbe anche se' stesso. Si chiama dal posto che occupa e non dal
    mestiere che fa — che per tutte e due le sezioni e' il verdetto — perche'
    il posto e' la sola cosa che la cucitura sappia di lui."""
    parts: "tuple[Part, ...]"
    """Gli altri pezzi, nell'ordine in cui vanno letti nel testo finito, che
    e' quello della card."""
def _system_prompt(repo_root: Path, *names: str) -> str:
    """Il prompt di sistema: i file dei prompt piu' le regole di casa, nello
    stesso ordine in cui li mette l'orchestratore degli agenti
    (`--append-system-prompt-file` attacca `_style.md` **dopo**).

    I nomi sono piu' di uno per i pezzi della Health spezzata, dove il prompt
    si compone: prima il file della misura — il solo che cambia fra i quattro
    — poi `_measure.md`, che vale per tutti e quattro. Dal piu' stretto al
    piu' largo, e le regole di casa in fondo che sono le piu' larghe di
    tutte. Cosi' una differenza fra due misure costa le righe in cui sono
    diverse, e non quattro copie delle stesse regole.

    Si leggono **a ogni chiamata**: una riga cambiata in `.ollama/agents/` si
    vede alla prossima domanda, senza riavviare niente. E' un banco di prova,
    e il giro e' scrivi, salva, ricarica la pagina."""
    agents = [_without_front_matter(_prompt_file(repo_root, name).read_text()) for name in names]
    style = _prompt_file(repo_root, STYLE_FILE).read_text().strip()
    return "\n\n".join([*agents, style])


def _where(measure: dict) -> str:
    """Dove sta un valore rispetto alla sua fascia, in parole.

    **Il conto lo fa l'API, come tutti gli altri.** Non e' il giudizio — se
    quel posto sia una buona o una cattiva notizia dipende dalla misura, e
    quello resta al prompt — e' la stessa aritmetica con cui la card disegna
    la barra, scritta a parole per chi i numeri non li confronta bene.

    Serve perche' senza, llama3.1 ricopiava l'esempio in fondo a
    `01_health.md` invece di guardare i numeri: diceva l'HRV "sotto la
    fascia" con un 46 dentro una fascia 38.8-53.6, e lo diceva anche dopo
    che il messaggio gli aveva chiesto di controllare. Con questo campo le
    quattro misure tornano al loro posto. L'agente di Claude il campo ce
    l'ha e non ne ha bisogno: legge la fascia da se'."""
    value, band = measure.get("value"), measure.get("band")
    if value is None or not band:
        return "unknown"
    if band["low"] <= value <= band["high"]:
        return "inside its band"
    if value > band["outer_high"]:
        return "far above its band"
    if value < band["outer_low"]:
        return "far below its band"
    return "above its band" if value > band["high"] else "below its band"


# Quanto della fascia e' "il mezzo": la meta' centrale. Fuori da quella, un
# quarto per parte, e quelli sono i due estremi. Tagliata qui e non ai terzi
# perche' **"in mezzo" deve voler dire il posto ordinario**: se un valore su
# tre finisse a un estremo, l'estremo non sarebbe piu' una cosa da dire.
MIDDLE_OF_THE_BAND = 0.25


def _sits(measure: dict) -> str | None:
    """Dove sta il valore **dentro** la sua fascia: in mezzo, o in uno dei
    due quarti agli estremi.

    Stessa divisione del lavoro di `_where`, un gradino piu' fine: il conto
    lo fa l'API, se quel posto sia una buona o una cattiva notizia dipende
    dalla misura e resta a `_reading`.

    Serve perche' *dentro la fascia* erano due notizie diverse dette con la
    stessa parola. Una frequenza a 52,4 con la fascia che chiude a 52,5 e'
    normale come lo e' una a 49, e `_measure.md` chiedeva espressamente di
    dire solo *normale* per tutte e due — era la riga giusta finche' il campo
    non c'era, perche' il posto dentro la fascia il modello se lo inventava.
    Dato il conto, la riga puo' cambiare: resta vietato chiamare fuori un
    valore che sta dentro, e si puo' dire da che parte di dentro sta.

    `None` quando il valore sta fuori dalla fascia o non c'e': li' non c'e'
    niente da collocare, e `where` ha gia' detto tutto."""
    value, band = measure.get("value"), measure.get("band")
    if value is None or not band:
        return None
    low, high = band["low"], band["high"]
    if not low <= value <= high:
        return None
    if high <= low:
        return "in the middle of its band"
    part = (value - low) / (high - low)
    if part <= MIDDLE_OF_THE_BAND:
        return "in the low quarter of its band"
    if part >= 1 - MIDDLE_OF_THE_BAND:
        return "in the high quarter of its band"
    return "in the middle of its band"


def health_facts(payload: dict, week: dict | None = None) -> dict:
    """La parte della Health dei fatti del giorno: le quattro misure con le
    loro fasce, gli allarmi che le riguardano, e quali misure mancano.

    `missing` resta perche' `_style.md` ci conta: una misura elencata li' non
    si commenta come se ci fosse.

    Il piano della settimana non le serve e lo ignora: come ha dormito il
    corpo stanotte non dipende da che cosa c'era scritto sul foglio."""
    morning = payload.get("morning", {})
    alerts = [a for a in payload.get("alerts", []) if _alert_key(a) in HEALTH_ALERTS]
    missing = [m for m in payload.get("missing", []) if m in HEALTH_MEASURES]
    return {
        "day": payload.get("day"),
        "morning": {
            k: {**morning[k], "where": _where(morning[k])}
            for k in HEALTH_MEASURES
            if k in morning
        },
        "alerts": alerts,
        "missing": missing,
    }


# Le tre parti del carico che la card disegna, nell'ordine in cui le disegna.
# Ognuna ha la sua fascia in `load.bands`: dove quel carico e' stato negli
# ultimi 28 giorni, che non e' un bersaglio.
LOAD_BALANCE = ("load_aerobic_low", "load_aerobic_high", "load_anaerobic")

# Quello che di `load.now` ha senso dare a chi scrive: il rapporto fra il
# carico della settimana e quello del mese, e le due parole in codice di
# Garmin che il prompt dice di leggere e poi tradurre da se'.
LOAD_STATE = ("acwr", "acwr_status", "training_status_phrase", "load_balance_phrase")

# I giorni di riposo e l'ultima seduta dura **non si mandano piu'**. Erano
# l'eccezione che il prompt di Claude concede — la card non li mostra, ma
# dicono se c'e' spazio per il lavoro che il bilancio chiede — e servivano a
# chiudere la sezione con un consiglio. Il consiglio e' andato via quando la
# sezione ha cominciato a leggere il piano della settimana: quello che c'e'
# da fare lo dice il piano, scritto da chi sa, e un modello che aggiunge
# "piu' facile e meno duro" in fondo a una settimana che chiede un lungo sta
# contraddicendo il piano, non commentandolo. Non darglieli e' il solo modo
# sicuro di non vederli tornare.


def _carrying(acwr: float | None) -> str | None:
    """Che cosa vuol dire il rapporto, in parole.

    Stessa ragione di `_where`: e' aritmetica, non giudizio — se portare meno
    del solito sia una buona o una cattiva notizia dipende da che settimana
    e', e quello resta al prompt. Senza, llama leggeva un 0,8 e scriveva "stai
    portando un carico pesante", che e' il contrario, e lo faceva anche con la
    regola scritta nel prompt: "ben sotto uno e' una settimana leggera".

    Gli estremi sono quelli di Garmin, gli stessi a cui guarda `acwr_status`:
    sotto 0,8 poco, sopra 1,3 molto."""
    if acwr is None:
        return None
    if acwr < 0.8:
        return "less than you usually carry"
    if acwr > 1.3:
        return "more than you usually carry"
    return "about what you usually carry"


def _when(session_day: object, day: date) -> str | None:
    """Come si chiama il giorno di una seduta: `today` per quella del giorno
    che si sta guardando, se no il nome del suo giorno della settimana."""
    if not isinstance(session_day, date):
        return None
    return "today" if session_day == day else session_day.strftime("%A")


def _verdict_word(carrying: str | None, parts: dict) -> str | None:
    """La parola con cui la Load apre, decisa qui.

    **Questa e' la riga che mi fa dire che il prompt e' saturo.** La regola e'
    scritta in `02_load.md` — *`carrying` ordinario piu' una parte fuori
    fascia fa lopsided, se no la parola la da' `carrying`* — e il modello la
    legge e scrive lo stesso "heavy" con un rapporto che lui stesso, due
    paragrafi piu' sotto, chiama ordinario. Contarla qui la raddrizza; il
    prezzo e' che la conclusione della sezione non la trova piu' chi scrive,
    e di suo gli resta la frase. Un modello che la regola la applica non ha
    bisogno di questo campo, e il campo non gli fa male."""
    if carrying is None:
        return None
    outside = any(p.get("where") != "inside its band" for p in parts.values())
    if carrying.startswith("about") and outside:
        return "lopsided"
    if carrying.startswith("less"):
        return "light"
    if carrying.startswith("more"):
        return "heavy"
    return "healthy"


def _day_of(payload: dict) -> date:
    """Il giorno dei fatti, come data. Nei fatti e' gia' una `date` quando
    arrivano da `daily_payload`, ma una stringa quando arrivano da un file o
    da un test, e le sedute si confrontano per data."""
    value = payload.get("day")
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def load_facts(payload: dict, week: dict | None = None) -> dict:
    """La parte della Load dei fatti del giorno.

    Il ritaglio qui conta piu' che per la Health, perche' quello che resta
    fuori il prompt lo nomina per dire di non usarlo: **`week_ago` non c'e'**
    — "non e' materiale tuo", e questa e' una sezione su oggi, non sul mese —
    e **`vo2max_change` nemmeno**, che sta in `load` per ragioni storiche ma
    e' della Fitness. Darglieli e poi chiedergli di non guardarli e' il modo
    piu' sicuro di vederli comparire nel testo."""
    load = payload.get("load", {})
    now = load.get("now", {})
    bands = load.get("bands", {})
    parts = {}
    for key in LOAD_BALANCE:
        if key not in now:
            continue
        measure = {"value": now[key], "band": bands.get(key)}
        parts[key] = {**measure, "where": _where(measure)}
    return {
        "day": payload.get("day"),
        "balance": parts,
        "state": {
            **{k: now[k] for k in LOAD_STATE if k in now},
            "carrying": _carrying(now.get("acwr")),
            "verdict_word": _verdict_word(_carrying(now.get("acwr")), parts),
        },
        "week": _week_sessions(week, _day_of(payload)),
    }


def _week_sessions(week: dict | None, day: date) -> dict | None:
    """Che cosa la settimana di quel giorno ha chiesto, da
    `summary/05.plan/<lunedi>.md`.

    **Il carico si giudica contro quello che la settimana aveva chiesto**, non
    contro se' stesso: un anaerobico sopra la sua fascia in una settimana che
    chiedeva due qualita' e' il piano che funziona, in una settimana di
    scarico e' il piano disatteso. Senza il foglio quelle due cose hanno gli
    stessi numeri e sono la cosa opposta.

    **La forma la conta questo modulo**, come la posizione nella fascia
    (`_where`): quante sedute chiede, quante dure, quanti riposi. Date al
    modello le sette righe e basta, si e' messo a contarle da se' e contava
    male — "due sedute dure ancora da fare" con una sola rimasta, "un giorno
    di riposo negli ultimi sette" con due nei fatti. Contare non e'
    giudicare, e chi sa contare conti.

    Restano in chiaro **le sedute che mancano**, da oggi in avanti: sono
    quelle di cui si parla quando si dice che cosa la settimana chiede
    ancora, e sono poche. Quelle passate no: la Load dice dove sta il carico
    oggi, e il racconto dei giorni e' di un'altra sezione.

    `None` quando quella settimana non ha un piano: e' il caso normale fuori
    da un blocco, non un guasto, e il prompt dice di non nominarlo."""
    if not week:
        return None
    sessions = week.get("sessions") or []
    kinds = [s.get("kind") for s in sessions]
    ahead = [s for s in sessions if s.get("day") and s["day"] >= day]
    # Quelle che restano da fare sono solo le sedute: un giorno di riposo non
    # e' una cosa che la settimana "chiede ancora".
    left = [s for s in ahead if s.get("sport") not in (None, "rest")]
    return {
        "phase": week.get("phase"),
        "block_week": week.get("block_week"),
        "block_weeks": week.get("block_weeks"),
        "asks_for": {
            "sessions": sum(1 for s in sessions if s.get("sport") not in (None, "rest")),
            "quality": kinds.count("quality"),
            "long": kinds.count("long"),
            "easy": kinds.count("easy"),
            "rest_days": sum(1 for s in sessions if s.get("sport") == "rest"),
        },
        # **Una lista sola, senza conteggi.** I conteggi ci sono stati per un
        # giro: senza, llama leggeva gli `asks_for` di tutta la settimana come
        # se fossero quello che resta. Con tutti e due davanti pero' scriveva
        # il numero invece del giorno — "1 quality session and 1 long
        # session" — e il giorno e' l'unica cosa per cui questa riga serve. I
        # conteggi dell'intera settimana restano in `asks_for`, dove la
        # domanda e' "quanto chiede"; qui c'e' solo chi manca.
        "still_to_come": [
            {
                **{k: s.get(k) for k in ("day", "sport", "kind", "distance_label")},
                # La seduta di oggi si chiama "today" e non col suo giorno:
                # col solo nome del giorno llama lo sbagliava — la qualita'
                # di giovedi' 12, guardata giovedi' 12, la chiamava
                # "venerdi'". Prima che le date fossero scritte diceva
                # "oggi", che era giusto: il nome del giorno in cui si e' non
                # e' un'informazione che serve.
                "weekday": _when(s.get("day"), day),
            }
            for s in left
        ],
    }


def _alert_key(alert: object) -> str:
    """Il nome di un allarme, che nei fatti e' una stringa o un oggetto con
    dentro la chiave."""
    if isinstance(alert, str):
        return alert
    if isinstance(alert, dict):
        return str(alert.get("key") or alert.get("name") or "")
    return ""


HEALTH = Section(key="health", title="Health", agent="01_health.md", facts=health_facts)
LOAD = Section(key="load", title="Load", agent="02_load.md", facts=load_facts)


def _user_prompt(section: Section, day: date, facts: dict) -> str:
    """Il messaggio: la stessa frase dell'orchestratore, con i fatti dentro
    invece che il percorso di un file, e la richiesta di rispondere col solo
    corpo invece che di scriverlo.

    Della forma e della lunghezza qui non si dice niente: sono cose della
    sezione, e stanno nel suo file in `.ollama/agents/` dove si possono
    cambiare senza toccare il codice. Qui resta quello che vale per tutte.

    Le due righe in fondo all'agente di Claude non servono: *l'esempio e'
    solo il tono* e *guarda `where`*. Un modello da otto miliardi di parametri
    l'esempio lo ricopia — alla prima prova ha detto l'HRV "sotto la fascia",
    che e' quello che dice l'esempio, con un 46 che stava dentro una fascia
    38.8-53.6 — e la fascia da solo la legge male. Non cambiano il compito,
    ricordano come si leggono le cose a chi non se le ricorda da solo."""
    return (
        f"Write the {section.title} section of the daily report "
        f"for {day:%A %-d %B %Y}. "
        "The facts are here, below: they are what your section owns, and nothing "
        "that belongs to another one is in them.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "Any example in your instructions is tone and length only: do not reuse its "
        "judgements. Each measure carries `where`, which says where its value falls "
        "against its own band: say what you make of that, and never contradict it. "
        "Answer with the body of the section and nothing else: no heading, no preamble, "
        "no sign-off, no quotes around it."
    )


def _measure_facts(split: "Split", part: Part, facts: dict) -> dict:
    """Quello che tocca a una delle quattro misure della Health: **la sua
    misura e nient'altro.**

    Il recinto della sezione l'ha gia' messo `health_facts`; questo e' il
    recinto dentro al recinto, e vale per la stessa ragione. Il prompt intero
    deve chiedere di non impastare due misure in un paragrafo e di non
    spiegare l'una con l'altra; qui le altre tre non ci sono, e una cosa che
    non si ha non si scrive.

    Con `where` va **`reading`**, per la stessa ragione per cui va al quinto
    (`_reading`): *sopra la fascia* non e' una notizia finche' non si sa di
    quale misura si parla. Il file della misura la direzione ce l'ha scritta
    e non bastava — la mattina del 5 novembre l'HRV stava sopra la sua fascia,
    che per l'HRV e' una buona notizia, e il paragrafo diceva "il sistema
    nervoso e' ancora sotto carico": il modello aveva preso la frase che gli
    stava piu' vicina invece di leggere da che parte era il valore. Il file
    adesso lega ogni frase al suo `reading`, e questo campo dice quale.

    **`sits` non ci entra, e ci entra il suo effetto.** Dentro la fascia il
    posto conta — il paragrafo di una misura normale e' quello che il
    giudizio categorico lasciava senza niente da dire — ma il campo in mano
    al modello sarebbe la posizione detta due volte, e llama3.1 la diceva due
    volte: "normal, but high in its range, sitting at the top end of its
    band". Il posto entra in `reading`, che e' il campo che il paragrafo
    legge per sapere che notizia e', e l'aritmetica resta qui dentro. La
    storia e' nella docstring di `_sits`.

    `missing` e' vero anche quando la misura dai fatti manca del tutto: per
    chi scrive sono la stessa cosa — stanotte non e' stata registrata — e la
    riga da scrivere e' una sola."""
    measure = facts.get("morning", {}).get(part.key) or {}
    alert = next((a for a in facts.get("alerts", []) if _alert_key(a) == part.alert), None)
    where = measure.get("where", "unknown")
    return {
        "day": facts.get("day"),
        "measure": part.label,
        "value": measure.get("value"),
        "band": measure.get("band"),
        "where": where,
        "reading": _reading(where, part.bad_when, _sits(measure)),
        "alert": alert,
        "missing": not measure or part.key in facts.get("missing", []),
    }


def _measure_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio di una misura: scrivi il paragrafo di questa misura.

    La riga sull'esempio, che c'e' in `_user_prompt`, qui non serve: nei file
    delle misure di esempi non ce n'e' nessuno, ed era quello il motivo per
    cui serviva."""
    return (
        f"Write the paragraph about {part.label} for the {split.title} section of the daily "
        f"report for {day:%A %-d %B %Y}. "
        "The facts are here, below, and they are all there is: the other three measures "
        "of the section are not yours and are not in them.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "`where` says where the value falls against its own band, and `reading` says "
        "what that means for this measure — down to whereabouts inside the band a "
        "normal value sits: say what you make of them, and never contradict them. "
        "Answer with the one paragraph and nothing else: no heading, "
        "no preamble, no sign-off, no quotes around it."
    )


# Da che parte della fascia sta la cattiva notizia, detta come la dice
# `_sits`. `bad_when` parla di sopra e di sotto la fascia, `_sits` di quarti
# dentro: sono la stessa direzione con due parole, e il confronto fra le due
# si fa qui una volta invece che a mano in mezzo a un `if`.
BAD_EDGE = {"above": "high", "below": "low"}

# I tre modi di essere normale, **scritti come si scriverebbero in un
# paragrafo**. E' la lezione di `VERDICT_WORDS`: un valore che in inglese sta
# in piedi da solo non ha bisogno di essere vietato. Le prime parole che
# avevano questi tre posti — *toward the bad edge*, *toward the good edge* —
# erano l'etichetta di un campo, llama3.1 le ricopiava di peso ("leaning
# towards the bad edge of its band", che e' una frase da modulo) e la riga di
# `_measure.md` che glielo vietava la seguiva per tre misure su quattro.
# Cosi' non c'e' niente da tradurre: se le ricopia, la frase e' una frase.
#
# **La notizia sta nella congiunzione**, non nella direzione: *but* e' la
# cosa da dire, *and* e' la cosa che va bene. La direzione — alto o basso —
# ci va solo dalla parte cattiva, dove serve a nominare il posto; dalla parte
# buona non serve a nessuno, e `sits` ce l'ha per chi la vuole.
NORMAL_MIDDLE = "comfortably normal"
NORMAL_GOOD_EDGE = "normal, and nowhere near trouble"
NORMAL_BAD_EDGE = "normal, but {edge} in its range"


def _reading(where: str, bad_when: str, sits: str | None = None) -> str:
    """Che cosa vuol dire quel `where` **per quella misura**: normale,
    peggio del solito, meglio del solito.

    Stessa ragione di `_where` e di `_verdict_word`, un giro piu' in la'.
    `_where` dice dove sta il valore e si ferma apposta — se quel posto sia
    una buona o una cattiva notizia dipende dalla misura, e per le quattro
    della Health non e' lo stesso: *sotto la fascia* e' buona in tre casi e
    cattiva nel quarto. Mettere le due cose insieme non e' giudicare, e'
    confrontare due parole.

    **E il quinto modello quel confronto non lo faceva.** Con `where` e
    `bad_when` in mano, la mattina del 18 ottobre — tutte e quattro fuori
    dalla parte cattiva, due volte fuori — ha aperto la sezione con *you are
    in good order*. Quattro paragrafi sotto che dicevano il contrario, e il
    verdetto piu' sbagliato che quella card possa dare. Con questa riga al
    posto di quelle due la frase torna quella giusta.

    Quanto pesi *peggio del solito* su una mattina intera non lo decide
    questa riga ma `_health_verdict`, e per lo stesso motivo: anche quello
    si e' rivelato un conto, non un giudizio.

    **Con `sits`, dentro la fascia non e' piu' una parola sola.** Un valore
    in mezzo alla fascia e uno appoggiato all'estremo che conta sono tutti e
    due normali e non sono la stessa notizia, e il giudizio categorico
    costringeva a dire di tutti e due soltanto *normale*. Le tre varianti che
    tornano da qui restano tutte e tre dentro al normale: nessuna conta per
    `_health_verdict`, nessuna si fa nominare da `_rests_on`, e un valore
    dentro la fascia non diventa mai una misura che va male. `sits` e' solo
    dei quattro paragrafi: il quinto chiama senza, e la sua riga non cambia —
    il paragrafo di apertura di fasce non parla."""
    if where == "unknown":
        return "not measured"
    if where == "inside its band":
        if sits is None or "middle" in sits:
            return NORMAL_MIDDLE if sits else "normal"
        edge = BAD_EDGE[bad_when]
        return NORMAL_BAD_EDGE.format(edge=edge) if edge in sits else NORMAL_GOOD_EDGE
    far = where.startswith("far ")
    bad = bad_when in where
    if bad:
        return "much worse than usual" if far else "worse than usual"
    return "much better than usual" if far else "better than usual"


# Il verdetto come lo legge chi scrive. **Le chiavi non escono di qui**: il
# quinto scriveva "your body is carrying a niggle this morning", che e'
# l'etichetta di un campo messa in bocca a un allenatore, e la riga che
# glielo vietava l'ha letta e ignorata quattro giorni su quattro. Un valore
# che in inglese sta in piedi da solo non ha bisogno di essere vietato: se lo
# ricopia di peso, la frase e' comunque una frase.
# **E i nomi dei campi non si toccano, che la lezione dei valori li' non
# vale.** Il quinto li legge ad alta voce — *"this verdict rests on that one
# measure"* — e per la stessa ragione per cui i valori sono stati riscritti ho
# provato a riscrivere le chiavi: `verdict` in `how_the_body_is`, e
# `what_it_rests_on` in `why`. Sei mattine su sei peggiori, e due in modo
# grave: `how_the_body_is` gli ha fatto incastrare il valore nella frase del
# nome (*"your body is something is not right this morning"*), `why` ha
# ridotto il paragrafo a una sola frase con un *because* dentro, la terza
# frase e' sparita da tutte e sei e le mattine tranquille sono tornate a
# inventare le misure di altre sezioni. Un nome di campo e' una cornice, e
# cambiarla ha cambiato la frase; un valore ricopiato e' solo una frase. Le
# due cose si somigliano e non sono la stessa.
VERDICT_WORDS = {
    "good": "the body is fine",
    "niggle": "broadly fine, with one measure out",
    "off": "something is not right",
    "fatigue": "a tired body",
}


def _health_verdict(readings: "list[str]") -> str:
    """Quanto va male la mattina, da quante delle quattro misure vanno male.

    **La terza riga che un modello non regge**, dopo `_where` e `_reading`, e
    la stessa storia di `_verdict_word` per la Load. Il conto gliel'ho dato
    fatto e la regola scritta in tabella, e restava di un gradino fuori: due
    misure fuori, una delle quali due volte fuori, gli facevano dire *a body
    carrying real fatigue* dove la tabella dice *something is off*. E
    leggendo la tabella copiava le parole della tabella, che per una card
    sono la frase di un modulo e non quella di un allenatore.

    Deciso qui, al quinto resta il suo mestiere: dire che cosa vuol dire per
    il corpo, con le sue parole e accanto a quello che i quattro paragrafi
    dicono. Che e' poi il mestiere per cui lo si e' aggiunto."""
    much = readings.count("much worse than usual")
    worse = readings.count("worse than usual")
    if not much and not worse:
        return "good"
    if not much and worse == 1:
        return "niggle"
    if much >= 2 or much + worse == 4 or (much and worse >= 2):
        return "fatigue"
    return "off"


def _rests_on(bad: "list[str]", good: "list[str]") -> dict:
    """Di che cosa parla la seconda frase del paragrafo di apertura, e quali
    misure nomina. **`about` nullo vuol dire che quella frase non c'e'.**

    **Il ramo lo prende Python.** Erano tre casi — c'e' qualcosa che va
    male, non c'e' niente che va male ma qualcosa va meglio del solito, non
    c'e' ne' l'uno ne' l'altro — scritti come tre regole nel prompt, e il
    quinto le mescolava: una mattina con due misure in cattivo stato chiusa
    con *"the morning is quiet, with nothing standing out as particularly
    positive or negative"*, che e' la terza regola applicata al primo caso e
    contraddice la frase prima della sua.

    Scelto qui, al prompt resta una regola sola: la seconda frase dice
    `about` e nomina `measures`.

    **E il terzo caso quella frase non la vuole.** Era "nothing reads badly,
    and all four sit where they should", una frase da dire senza nominare
    niente, ed e' la domanda che il quinto non sa reggere: una frase da
    scrivere e niente da metterci dentro se lo inventa. Nelle prove le
    mattine tranquille erano le sole due che sbagliavano — *"it rests on a
    neutral balance of sleep, body battery, readiness and breathing rate"*,
    tre dei quattro nomi di altre sezioni, e l'altra volta tre delle quattro
    misure che la riga di sopra gli vietava di nominare. Le mattine con una
    misura fuori, con due, o con una buona notizia da dare, tutte giuste: li'
    la frase ha un lavoro.

    Quindi li' la frase non si chiede: `about` e' nullo, `measures` e' vuoto,
    e il paragrafo ne ha due invece di tre. **Il campo si manda comunque**,
    nullo. Toltolo del tutto — che sarebbe la regola di casa, quello che non
    si ha non si scrive — il quinto e' tornato a nominare misure che non gli
    erano state date (*"resting on a normal heart rate and breathing rate"*,
    due delle quattro, la mattina in cui non doveva nominarne nessuna) e ha
    perso la terza frase. Col campo nullo in mano quelle due cose non le fa;
    gli scappa una riga sul campo invece che sul corpo — *"there's nothing to
    say about what it rests on"* — e quella la combatte il suo compito, dove
    sta scritto che una frase cosi' e' una frase sui campi. Un campo nullo e'
    una risposta, un campo che manca e' una domanda, e a una domanda il
    modello risponde da se'. Che un corpo a posto sia
    a posto lo dicono la prima frase e la terza, e i quattro paragrafi sotto
    lo dicono misura per misura: la seconda non serviva a nessuno. E' la
    ragione per cui "everything else is where it should be" era stata tolta
    dal suo compito, un giro piu' in la'.

    **E il singolare e il plurale li mette Python.** `about` e' una frase che
    il quinto riscrive con le sue parole, e con una misura sola *these read
    badly this morning* era una frase sbagliata in mano a chi non la
    controlla: con una misura fuori ha scritto *"resting heart rate is
    pointing in the wrong direction like the others that read badly this
    morning"* — le altre non c'erano, e il plurale del campo gliele ha fatte
    inventare. Contare uno e piu' di uno e' la stessa riga di
    `_health_verdict`, e si conta qui."""
    if bad:
        return {
            "about": (
                "this one reads badly this morning"
                if len(bad) == 1
                else "these read badly this morning"
            ),
            "measures": bad,
        }
    if good:
        return {
            "about": (
                "nothing reads badly, and this one reads better than usual"
                if len(good) == 1
                else "nothing reads badly, and these read better than usual"
            ),
            "measures": good,
        }
    return {"about": None, "measures": []}


def _health_opening_facts(split: "Split", part: Part, facts: dict) -> dict:
    """Quello che tocca al quinto: **i quattro `reading`, e non i quattro
    paragrafi.**

    **Le misure che portano il verdetto arrivano nominate.** Il paragrafo di
    apertura deve dire anche *per via di quali*, e trovarle vuol dire
    rileggere quattro `reading` e tenersi quelli che stanno fuori: e' un
    filtro, come il conto di `_health_verdict` era un conto, e di questi tre
    scivoloni basta la storia che c'e' gia' scritta qui sotto. Al quinto
    resta quello per cui lo si e' aggiunto: che cosa vogliano dire tutte e
    quattro insieme.

    Le frasi da sole non bastavano, ed e' la sola cosa che qui si fa diversa
    da come la domanda era stata posta. Tirare un verdetto fuori da quattro
    paragrafi in inglese e' una seconda inferenza, e un modello piccolo e'
    li' che scivola: la verita' la dicono i `where`.

    **E le frasi dei quattro sono andate via del tutto.** Stavano nel
    messaggio perche' il verdetto non contraddicesse quello che la sezione
    dice sotto, ed erano l'unica prosa che il quinto avesse in mano: tre
    mattine su tre con una misura fuori ha ricopiato la spiegazione del
    paragrafo che gli stava sotto — *"possibly a night cut short or something
    coming on"*, parola per parola, due centimetri sopra l'originale — e con
    lei la fascia, che il suo compito gli vieta in due righe diverse. Le
    regole c'erano tutte e due e le ha ignorate tutte e due, anche riscritte
    senza citare le parole che poi usava.

    Al loro posto va `reading`, misura per misura. E' la stessa verita' da
    cui quei paragrafi sono stati scritti — contraddirli e' diventato piu'
    difficile, non piu' facile — e non e' prosa, quindi non c'e' niente da
    saccheggiare: nelle prove le tre mattine cattive sono tornate pulite
    tutte e tre. Quello che non si ha non si scrive, la terza volta in questo
    file.

    **Cosi' il quinto non dipende piu' dai quattro.** Leggeva quello che
    avevano scritto e doveva aspettarli; adesso legge i fatti, che ci sono
    dal primo istante, e sta nello stesso giro di domande delle altre quattro
    (`_split_text`).

    E con i `where` va `reading`, che dice se quel posto per quella misura e'
    una buona o una cattiva notizia. Il confronto glielo avevo lasciato fare
    — `where` da una parte, `bad_when` dall'altra — e non lo faceva: la
    docstring di `_reading` racconta com'e' finita.

    **E le quattro si contano qui.** Il verdetto dipende da quante delle
    quattro stanno male, il prompt la regola ce l'ha scritta, e il modello
    contava male: due misure fuori dalla parte cattiva l'8 novembre gli
    hanno fatto scrivere *you are in good order*, e le stesse due il 31 ottobre
    *a body carrying real fatigue*, che sono i due estremi della scala per lo
    stesso conto. E' la lezione di `_week_sessions`, un'altra
    volta: contare non e' giudicare, e chi sa contare conti. Quanto pesino
    due misure su quattro resta a lui, e la frase pure."""
    morning = facts.get("morning", {})
    seen = [
        {
            "measure": measure.label,
            "where": (morning.get(measure.key) or {}).get("where", "unknown"),
            "reading": _reading(
                (morning.get(measure.key) or {}).get("where", "unknown"), measure.bad_when
            ),
        }
        for measure in split.parts
    ]
    named = lambda reading: [m["measure"] for m in seen if m["reading"] == reading]
    rests_on = named("much worse than usual") + named("worse than usual")
    good_news = named("much better than usual") + named("better than usual")
    # **Gli arrivano solo le misure di cui parlera', e di quelle solo come si
    # leggono.** Non il valore e non la fascia — dove sta una misura e' il
    # mestiere dei quattro paragrafi, che gli stanno sotto e che il lettore
    # ha — e **non le misure che stanno bene**: con tutte e quattro in mano
    # le elencava tutte e quattro, anche la mattina in cui la seconda frase
    # doveva dire "le altre stanno dove devono" e basta. La riga che glielo
    # diceva c'era, e l'ha letta quattro volte su quattro senza farci caso.
    # Quello che non si ha non si scrive: e' la stessa ragione per cui
    # `week_ago` non arriva alla Load.
    speaks_of = rests_on + good_news
    # **"Everything else is where it should be" non e' piu' roba sua.** Era
    # la seconda meta' della seconda frase, e il 18 ottobre — quattro misure
    # su quattro fuori, un "everything else" che non esisteva — l'ha scritto
    # lo stesso, in fondo a un elenco che le aveva gia' nominate tutte
    # quattro. Con un campo che diceva di no, letto e ignorato come le righe
    # prima di lui. Ed era una riga che non serviva a nessuno: che una
    # misura normale sia normale lo dice il suo paragrafo, due centimetri
    # piu' sotto. Tolta dal compito, non c'e' piu' niente da sbagliare.
    return {
        "verdict": VERDICT_WORDS[_health_verdict([m["reading"] for m in seen])],
        "what_it_rests_on": _rests_on(rests_on, good_news),
        "how_they_read": [
            {"measure": m["measure"], "reading": m["reading"]}
            for m in seen
            if m["measure"] in speaks_of
        ],
    }


def _health_opening_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio del quinto. Il recinto — che cosa gli arriva, e le tre
    cose che gli sono state tolte una per una — sta in
    `_health_opening_facts`, che e' dove quella storia e' stata scritta."""
    return (
        f"Write the opening paragraph of the {split.title} section of the daily report "
        f"for {day:%A %-d %B %Y}. "
        "It goes at the top of the section, above four paragraphs that are already "
        "written, one for each measure, and it says what they add up to.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "`verdict` is the verdict and you do not reopen it. `what_it_rests_on` says "
        "what the second sentence is about and names the only measures you may name "
        "anywhere in the paragraph — when its `about` is null the morning rests on "
        "nothing, and there is no second sentence to write and no measure to name; "
        "`how_they_read` is how each of those measures reads, so that your paragraph "
        "does not contradict the section it opens. "
        "Answer with the paragraph and nothing else: no number in it, no band in it, "
        "no heading, no list, no quotes around it."
    )


# **La Load spezzata.** Stessa idea della Health — un paragrafo per pezzo,
# nessun pezzo che sappia degli altri, la cucitura a Python — su una sezione
# che spezzandola si scopre fatta di quattro mestieri e non di uno. I pezzi
# della Health erano quattro misure, cioe' la stessa domanda quattro volte,
# e si vedeva nel codice: un ritaglio e un messaggio per tutti e quattro. Qui
# ce ne sono sei e si somigliano a tre a tre: i tre carichi hanno una fascia,
# il rapporto non ce l'ha, la settimana non e' un numero, il verdetto parla
# di tutti.
#
# **Ed e' la sezione che il prompt intero regge peggio**, che e' il motivo per
# cui questa e' la seconda a essere spezzata e non la terza. `_verdict_word`
# conta la parola dell'apertura perche' il modello scriveva *heavy* con un
# rapporto che lui stesso chiamava ordinario due paragrafi piu' sotto;
# `_week_sessions` conta le sedute perche' le contava male; `_carrying`
# traduce il rapporto perche' leggeva 0,8 e scriveva "stai portando un carico
# pesante". Tre campi calcolati in Python per raddrizzare tre righe di prompt
# lette e non applicate, e tutte e tre le volte la diagnosi scritta nelle
# docstring e' la stessa: il prompt e' saturo. Sei prompt da un paragrafo
# l'uno saturi non sono.


def _load_opening_facts(split: "Split", part: Part, facts: dict) -> dict | None:
    """Quello che tocca a chi apre la Load: **la parola, e nient'altro.**

    E' il recinto piu' stretto di tutto il file, ed e' stretto per la ragione
    scritta in `_verdict_word`: quella parola e' l'unica cosa della sezione
    che il prompt intero sbagliava a prompt pieno — *heavy* con un rapporto
    ordinario — e il prezzo di contarla in Python era che a chi scrive
    restava la frase e non la conclusione. Qui il prezzo non si paga: la
    frase e' tutto il pezzo, e un paragrafo che ha in mano una parola sola
    non ha niente con cui contraddire i cinque sotto di lui.

    **E la parola non si traduce**, che e' la differenza con `VERDICT_WORDS`.
    Le quattro chiavi della Health erano etichette di un campo e in bocca a
    un allenatore si sentivano (*"your body is carrying a niggle"*), quindi
    sono state riscritte in frasi. *Light*, *heavy*, *healthy* e *lopsided*
    sono gia' aggettivi che in inglese stanno in piedi da soli: ricopiata di
    peso, *your training load is lopsided* e' una frase e non un modulo. Un
    valore che si regge non ha bisogno di essere tradotto, e la tabella che
    non serve non si scrive.

    `None` quando il rapporto non c'e': senza di lui `_verdict_word` non da'
    nessuna parola, e un'apertura senza verdetto non e' un'apertura. La
    sezione comincia dal primo carico e ha un paragrafo in meno, che e' la
    verita' di quel giorno."""
    verdict = facts.get("state", {}).get("verdict_word")
    return {"verdict": verdict} if verdict else None


def _load_opening_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio di chi apre la Load: una frase sola, su quella parola."""
    return (
        f"Write the opening paragraph of the {split.title} section of the daily report "
        f"for {day:%A %-d %B %Y}. "
        "It goes at the top of the section, above the paragraphs that are already "
        "written — one for each of the three kinds of work, one for how much of it you "
        "are carrying, one for what the week still asks — and it is one short sentence "
        "on the load as it stands.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "`verdict` is the word for the load as a whole, counted already from the three "
        "kinds and from the ratio: the sentence is built around that word and no other, "
        "and you do not reopen it. "
        "Answer with the one sentence and nothing else: no number in it, no band in it, "
        "no kind of work named, no heading, no list, no quotes around it."
    )


def _week_shape(facts: dict) -> dict | None:
    """Che settimana e', per chi giudica un carico: la fase del blocco e
    quante sedute di che tipo la settimana aveva chiesto.

    **E' la meta' del foglio che serve ai tre carichi, e non l'altra.** Un
    anaerobico sopra la sua fascia e' il piano che funziona in una settimana
    che chiedeva due qualita' e il piano disatteso in una di scarico: senza
    `asks_for` quelle due cose hanno gli stessi numeri e sono la cosa
    opposta, ed e' la ragione per cui `_week_sessions` esiste. `still_to_come`
    invece e' il paragrafo in fondo alla sezione, non il loro: dato anche a
    loro, la seduta di venerdi' si leggerebbe quattro volte sulla stessa
    card.

    Fuori restano `block_week` e `block_weeks`, e qui non li ha nessuno:
    nessuno dei sei paragrafi risponde alla domanda *che settimana del blocco
    e'*, e un pezzo che se li trova in mano la risponde comunque. La fase
    dice quel che serve — che settimana e' — senza invitare a raccontare il
    blocco, che e' il mese e non oggi."""
    week = facts.get("week")
    if not week:
        return None
    return {"phase": week.get("phase"), "asks_for": week.get("asks_for")}


def _load_part_facts(split: "Split", part: Part, facts: dict) -> dict:
    """Quello che tocca a uno dei tre carichi: **il suo, e la settimana.**

    Stesso recinto dentro al recinto delle misure della Health, con una
    differenza che conta: li' il pezzo aveva bisogno della sua misura e
    basta, qui ha bisogno anche di che settimana era. Un carico si giudica
    contro quello che la settimana aveva chiesto — e' la prima riga in
    grassetto di `02_load.md` — e un pezzo che quel foglio non ce l'ha non
    sta scrivendo un paragrafo piu' stretto, sta tirando a indovinare.

    **Quello che non arriva e' `reading`**, e non c'e' niente da ritagliare al
    suo posto. Per una misura della Health la fascia ha una parte cattiva, ed
    e' una proprieta' della misura: `bad_when` la sa, `_reading` la mette
    insieme a `where`, e il paragrafo riceve la notizia gia' fatta. **Per un
    carico la parte cattiva non esiste**: sopra fascia e' buono o cattivo
    secondo il foglio, e metterlo in un campo vorrebbe dire decidere in
    Python la cosa per cui questa sezione ha un prompt. Ai tre carichi arriva
    `where`, che e' aritmetica, e `week`, che e' il foglio; il giudizio e'
    loro, ed e' l'unico pezzo di questo file a cui si lascia per intero.

    `missing` quando quel carico dai fatti manca: `load_facts` i carichi che
    Garmin non ha non li mette in `balance`, e per chi scrive e' una riga
    sola da scrivere.

    **La prima sera, e il conto da regolare.** Su llama3.1:8b, il 16 novembre,
    i tre paragrafi dei carichi hanno rispettato le regole di casa *peggio*
    di quanto le rispetti il prompt intero sulla stessa giornata: hanno
    scritto il valore ("692.24", che la card mostra due centimetri sopra),
    hanno detto *we* dove il prompt intero dice *you*, e hanno riletto ad
    alta voce i conteggi di `asks_for` — uno sbagliandoli, "tre sedute
    facili" per una settimana che ne chiede tre di cui una facile. Le regole
    c'erano tutte e tre, nel file del pezzo e poi anche in fondo al messaggio,
    che e' il posto in cui questo file ha imparato che le regole attaccano.
    **Quindi la tesi dei sei prompt piccoli, su questi tre pezzi, la prima
    sera non ha vinto.**

    Il sospetto e' il recinto e non il prompt: `asks_for` e' la cosa che
    viene ripetuta, ed e' la lezione di questo file dall'inizio — quello che
    non si ha non si scrive. Togliere i conteggi e lasciare solo `phase`
    pero' vorrebbe dire togliere proprio la differenza fra una settimana che
    chiedeva qualita' e una di facile, che e' quello contro cui un carico si
    giudica; e tradurli in una frase per tipo di lavoro vorrebbe dire
    decidere in Python mezzo giudizio, che e' una riga piu' in la' di dove
    `_where` e `_carrying` si fermano. **Non si sceglie qui**: si guardano le
    due card una accanto all'altra su qualche giorno storto, che e' il
    mestiere della pagina Test, e quello che si vede decide. Il paragrafo
    della settimana, intanto, quella prova l'ha vinta netta: il 20 settembre,
    fuori da un blocco, il prompt intero ha chiuso con "la settimana non
    chiede piu' niente" per una settimana che un piano non ce l'ha, e qui
    quel paragrafo non esiste."""
    measure = facts.get("balance", {}).get(part.key) or {}
    return {
        "day": facts.get("day"),
        "kind": part.label,
        "value": measure.get("value"),
        "band": measure.get("band"),
        "where": measure.get("where", "unknown"),
        "week": _week_shape(facts),
        "missing": not measure,
    }


def _load_part_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio di uno dei tre carichi: il suo paragrafo, e che settimana
    era."""
    return (
        f"Write the paragraph about {part.label} for the {split.title} section of the "
        f"daily report for {day:%A %-d %B %Y}. "
        "The facts are here, below, and they are all there is: the other two kinds of "
        "work in the section are not yours and are not in them.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "`where` says where today's value falls against its own band — where this kind "
        "of work has sat over the last 28 days, which is not a target — and never "
        "contradict it: `inside its band` means he is doing about as much of it as "
        "usual, and the right thing to say is that it is normal. `week` is what the "
        "week it belongs to asked for, and it is what decides the reading: the same "
        "value is the plan working in one week and the plan ignored in another — "
        "**judge with it, and do not report it**, because its sessions and its counts "
        "belong to the last paragraph of the section and not to you. Never write the "
        "figure in `value`: it is on the card, right above your text. Write it to him "
        "as **you** — never *we*, never *he*. "
        "Answer with the one paragraph and nothing else: no heading, no preamble, "
        "no sign-off, no quotes around it."
    )


def _carrying_facts(split: "Split", part: Part, facts: dict) -> dict | None:
    """Quello che tocca a chi dice quanto stai portando: **le parole del
    rapporto, e non il rapporto.**

    Il numero sta nella quarta casella della card, due centimetri sopra il
    testo, e la regola che lo vieta e' scritta nel prompt intero ("al massimo
    un numero per paragrafo, e solo se porta il punto") perche' il modello lo
    ricopiava comunque. Un pezzo che il numero non ce l'ha non ha niente da
    ricopiare, e la frase che gli resta e' quella per cui il paragrafo
    esiste: quanto stai portando, non quanto fa il rapporto.

    `carrying` lo scrive `_carrying`, e per la ragione che sta scritta li':
    llama leggeva 0,8 e diceva "stai portando un carico pesante", che e' il
    contrario, e lo diceva anche con la regola in chiaro nel prompt.

    `None` quando il rapporto non c'e': non c'e' la frase, e il paragrafo non
    si scrive."""
    carrying = facts.get("state", {}).get("carrying")
    return {"carrying": carrying} if carrying else None


def _carrying_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio di chi dice quanto stai portando: una frase, su quelle
    parole."""
    return (
        f"Write the paragraph about {part.label} for the {split.title} section of the "
        f"daily report for {day:%A %-d %B %Y}. "
        "It sits below the three paragraphs about the three kinds of work and it is one "
        "sentence: they answered what kind, and it answers how much.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "`carrying` is what the last week of training comes to against the last four, "
        "said in words: say what you make of it and never contradict it. "
        "Answer with the one sentence and nothing else: no heading, no preamble, "
        "no sign-off, no quotes around it."
    )


def _week_asks_facts(split: "Split", part: Part, facts: dict) -> dict | None:
    """Quello che tocca all'ultimo paragrafo: **le sedute che mancano.**

    Non la fase, non le sedute passate, non i conteggi di `asks_for`: quelli
    sono dei tre carichi, che contro la forma della settimana si giudicano
    (`_week_shape`). Qui c'e' la lista di chi manca, ed e' la sola cosa di
    cui questa frase parla.

    **La lista vuota e la settimana senza piano non sono la stessa cosa**, e
    si somigliano abbastanza da andarci piano. Vuota vuol dire che la
    settimana c'e' e non chiede piu' niente — la domenica sera, o un blocco
    che si chiude — e quella e' una frase da scrivere. `None` vuol dire che
    quella settimana un foglio non ce l'ha, che e' il caso normale fuori da un
    blocco: li' il paragrafo non esiste. Il prompt intero quella differenza
    la deve spiegare a parole e sperare; qui la seconda e' un pezzo che non
    si chiede."""
    week = facts.get("week")
    if week is None:
        return None
    return {"still_to_come": week.get("still_to_come", [])}


def _week_asks_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio dell'ultimo paragrafo: che cosa la settimana vuole
    ancora."""
    return (
        f"Write the paragraph about {part.label} for the {split.title} section of the "
        f"daily report for {day:%A %-d %B %Y}. "
        "It is the last paragraph of the section and it is one sentence.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "`still_to_come` is what the week has not had yet, each session with the day to "
        "call it by: name them by that day and by their distance, and name nothing "
        "else. An empty list is a week with nothing more to ask, and the sentence says "
        "so and stops. Do not say what to do about any of it: the week was written by "
        "somebody who knows the block, and your sentence reports it. "
        "Answer with the one sentence and nothing else: no heading, no preamble, "
        "no sign-off, no quotes around it."
    )


# Le quattro misure della Health una per una, nell'ordine in cui la sezione
# le legge — lo stesso di `HEALTH_MEASURES`, che e' quello della card. Qui
# ognuna porta in piu' le cose che la distinguono dalle altre: come si chiama
# parlando, chi scrive il suo paragrafo, e da che parte della fascia sta la
# cattiva notizia.
#
# **La direzione e' la cosa che si guadagna spezzando.** Il prompt intero la
# lasciava alle regole di casa, in una riga sola per tutte e quattro ("above
# per la frequenza, il respiro e lo stress; below per l'HRV"), e `_where` di
# proposito non giudica: dice dove sta il valore e non se e' una buona
# notizia. Con un file per misura quella riga si scrive dove serve, e l'HRV —
# la sola delle quattro che si legge al contrario — ce l'ha tutta per se'.
#
# Il ritaglio e la domanda sono gli stessi per tutte e quattro, e scritti in
# ogni riga perche' sono campi di `Part`: le misure della Health sono la
# stessa domanda quattro volte, ed e' il motivo per cui erano state spezzate
# per prime.

# I sei file della Health spezzata stanno in una cartella loro dentro
# `.ollama/agents/`: sono tanti e sono pezzi di una cosa sola, e sparsi
# accanto a `01_health.md` si leggerebbero come sei sezioni nuove.
HEALTH_SPLIT_DIR = "01_health_split"

HEALTH_PARTS = (
    Part(
        key="resting_hr",
        label="resting heart rate",
        agent=(f"{HEALTH_SPLIT_DIR}/resting_hr.md", f"{HEALTH_SPLIT_DIR}/_measure.md"),
        cut=_measure_facts,
        asks=_measure_prompt,
        bad_when="above",
        alert="resting_hr_up",
    ),
    Part(
        key="hrv_last_night",
        label="HRV of last night",
        agent=(f"{HEALTH_SPLIT_DIR}/hrv_last_night.md", f"{HEALTH_SPLIT_DIR}/_measure.md"),
        cut=_measure_facts,
        asks=_measure_prompt,
        bad_when="below",
    ),
    Part(
        key="resp_sleep",
        label="breathing rate in sleep",
        agent=(f"{HEALTH_SPLIT_DIR}/resp_sleep.md", f"{HEALTH_SPLIT_DIR}/_measure.md"),
        cut=_measure_facts,
        asks=_measure_prompt,
        bad_when="above",
        alert="sleep_breathing_up",
    ),
    Part(
        key="stress_avg_yesterday",
        label="stress yesterday",
        agent=(
            f"{HEALTH_SPLIT_DIR}/stress_avg_yesterday.md",
            f"{HEALTH_SPLIT_DIR}/_measure.md",
        ),
        cut=_measure_facts,
        asks=_measure_prompt,
        bad_when="above",
    ),
)

HEALTH_SPLIT = Split(
    key="health_split",
    title="Health",
    facts=health_facts,
    opening=Part(
        key="verdict",
        label="the opening",
        agent=(f"{HEALTH_SPLIT_DIR}/_verdict.md",),
        cut=_health_opening_facts,
        asks=_health_opening_prompt,
    ),
    parts=HEALTH_PARTS,
)

# I sette file della Load spezzata, nella loro cartella come quelli della
# Health: il verdetto, i tre carichi, `_part.md` che quei tre si dividono, il
# rapporto e la settimana.
LOAD_SPLIT_DIR = "02_load_split"

# I cinque pezzi sotto l'apertura, nell'ordine in cui la card li legge: i tre
# carichi come li disegna (`LOAD_BALANCE`), poi quanto stai portando, poi che
# cosa la settimana vuole ancora.
#
# **Gli ultimi due non si piegano in uno.** Il prompt intero quella riga ce
# l'ha scritta ("gli ultimi due non si uniscono mai: quanto stai portando e
# che cosa la settimana vuole ancora sono due risposte"), che e' una riga che
# si scrive quando qualcuno le ha unite. Qui sono due domande a due modelli,
# e unirle non e' una cosa che possa succedere.
LOAD_PARTS = (
    Part(
        key="load_aerobic_low",
        label="easy aerobic work",
        agent=(f"{LOAD_SPLIT_DIR}/load_aerobic_low.md", f"{LOAD_SPLIT_DIR}/_part.md"),
        cut=_load_part_facts,
        asks=_load_part_prompt,
    ),
    Part(
        key="load_aerobic_high",
        label="harder aerobic work",
        agent=(f"{LOAD_SPLIT_DIR}/load_aerobic_high.md", f"{LOAD_SPLIT_DIR}/_part.md"),
        cut=_load_part_facts,
        asks=_load_part_prompt,
    ),
    Part(
        key="load_anaerobic",
        label="anaerobic work",
        agent=(f"{LOAD_SPLIT_DIR}/load_anaerobic.md", f"{LOAD_SPLIT_DIR}/_part.md"),
        cut=_load_part_facts,
        asks=_load_part_prompt,
    ),
    Part(
        key="carrying",
        label="how much you are carrying",
        agent=(f"{LOAD_SPLIT_DIR}/_carrying.md",),
        cut=_carrying_facts,
        asks=_carrying_prompt,
    ),
    Part(
        key="week",
        label="what the week still asks for",
        agent=(f"{LOAD_SPLIT_DIR}/_week.md",),
        cut=_week_asks_facts,
        asks=_week_asks_prompt,
    ),
)

LOAD_SPLIT = Split(
    key="load_split",
    title="Load",
    facts=load_facts,
    opening=Part(
        key="verdict",
        label="the opening",
        agent=(f"{LOAD_SPLIT_DIR}/_verdict.md",),
        cut=_load_opening_facts,
        asks=_load_opening_prompt,
    ),
    parts=LOAD_PARTS,
)

SECTIONS: "dict[str, Section | Split]" = {
    section.key: section for section in (HEALTH, LOAD, HEALTH_SPLIT, LOAD_SPLIT)
}
"""Le sezioni che la pagina Test sa chiedere. Le altre cinque del giorno non
ci sono: si aggiungono quando servono, una alla volta, che ognuna vuole il
suo ritaglio dei fatti e la sua prova.

Sono **due sezioni chieste in due modi ciascuna**, e tutte e quattro nel
registro apposta: la pagina mette ogni sezione accanto a se' stessa, sullo
stesso giorno e sugli stessi numeri, ed e' il confronto a dover decidere
quale delle due strade resta. Quando lo decide, quella che ha perso va via
allora e non adesso."""


def _one_paragraph(text: str) -> str:
    """Una risposta ridotta a un paragrafo solo: via le righe vuote, via le
    intestazioni.

    **E' qui che la forma smette di essere una preghiera.** La sezione e'
    cinque paragrafi perche' sono cinque risposte attaccate, non perche'
    qualcuno l'abbia chiesto a un modello: ma una risposta che dentro ha una
    riga vuota ne farebbe sei, e tanto varrebbe non aver spezzato niente.
    Attaccata in una riga sola, la forma torna quella giusta e si legge la
    stessa cosa."""
    lines = [line.strip() for line in text.strip().splitlines()]
    return " ".join(line for line in lines if line and not line.startswith("#"))


def _ask(system: str, user: str) -> tuple[str, str]:
    """Una domanda al modello di casa: la risposta e il nome di chi l'ha
    scritta. Alza `OllamaError` se la macchina non risponde."""
    model = os.environ.get("ATHLOS_OLLAMA_MODEL", DEFAULT_MODEL)
    base = os.environ.get("ATHLOS_OLLAMA_URL", DEFAULT_URL).rstrip("/")
    body = json.dumps(
        {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # **Temperatura zero**, e non e' un gusto: a 0,3 due risposte su
            # otto contraddicevano il `where` che avevano in mano — l'HRV
            # "sotto la fascia" con un valore dentro — perche' il modello
            # ricadeva sull'esempio in fondo a `01_health.md` invece di
            # guardare i numeri. A zero, zero su otto, due volte (con
            # l'esempio e senza). Un verdetto sbagliato su una card non e'
            # varieta', e la stessa mattina con gli stessi numeri puo' avere
            # la stessa risposta.
            "options": {"temperature": 0, "num_ctx": CONTEXT_TOKENS},
        }
    ).encode()
    request = urllib.request.Request(
        f"{base}/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:
            parsed = json.loads(answer.read())
    except urllib.error.HTTPError as exc:
        # Il modello che non c'e' e' questo: ollama risponde 404 col nome.
        raise OllamaError(f"Ollama answered {exc.code}: {exc.read().decode()[:200]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OllamaError(f"Cannot reach Ollama at {base}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OllamaError("Ollama answered something that is not JSON.") from exc
    text = (parsed.get("message") or {}).get("content", "").strip()
    if not text:
        raise OllamaError(f"{model} answered with nothing.")
    return text, model


def section_text(
    section: "Section | Split",
    day: date,
    payload: dict,
    repo_root: Path,
    week: dict | None = None,
) -> tuple[str, str]:
    """Il testo di una sezione scritto dal modello locale, e il nome del
    modello che l'ha scritto. Alza `OllamaError` se la macchina non
    risponde.

    Una porta sola per tutte e due le strade: all'endpoint della pagina Test
    che una sezione sia una domanda o cinque non interessa — chiede il testo
    di una chiave e lo mette nella card."""
    if isinstance(section, Split):
        return _split_text(section, day, payload, repo_root, week)
    return _ask(
        _system_prompt(repo_root, section.agent),
        _user_prompt(section, day, section.facts(payload, week)),
    )


def _split_text(
    split: Split,
    day: date,
    payload: dict,
    repo_root: Path,
    week: dict | None = None,
) -> tuple[str, str]:
    """La sezione scritta in piu' pezzi: un paragrafo per pezzo e l'apertura
    in cima, attaccati qui.

    **La cucitura la fa Python**, ed e' il punto di tutto: l'ordine e'
    `split.parts` dietro `split.opening`, che e' quello della card, e i
    paragrafi sono tanti quante le domande. Non c'e' una riga di prompt che
    possa saltarne uno, impastarne due o aggiungerne un altro.

    **E un pezzo che non ha niente non si chiede.** `cut` che rende `None`
    e' un paragrafo che non c'e': la settimana senza piano, il rapporto che
    Garmin non ha ancora. Il prompt intero quei buchi li deve chiedere a
    parole — e sono le righe che un modello piccolo legge e non applica — e
    qui sono un pezzo in meno nella lista. La forma la decide Python anche
    quando la forma cambia, e cambiarla cosi' non e' il modello che si
    dimentica un paragrafo: e' la sezione che quel paragrafo non ce l'ha.

    **Le domande si fanno insieme**, in un pugno di thread: sono
    indipendenti — nessun pezzo sa degli altri, che e' tutta l'idea — e
    Ollama le mette in fila da se' se di posti ne ha uno solo
    (`OLLAMA_NUM_PARALLEL`). Sequenziali sarebbero cinque o sei attese in
    fila per niente, e un banco di prova che fa aspettare per un motivo che
    non e' il modello misura la cosa sbagliata.

    **L'apertura stava fuori dal giro, e non ci sta piu'.** Doveva venire
    dopo finche' leggeva quello che gli altri avevano scritto, ed era la
    ragione per cui questa strada non poteva essere veloce come una domanda
    sola. Le frasi degli altri gliele ho tolte — la docstring di
    `_health_opening_facts` dice perche', e non c'entrava la fretta: le
    ricopiava — e quello che legge adesso sono i fatti del giorno, che ci
    sono dal primo istante. Quindi parte con gli altri, e il tempo della
    sezione e' quello della domanda piu' lenta invece della somma di due."""
    facts = split.facts(payload, week)
    # I pezzi nell'ordine in cui il testo finito li legge: l'apertura in cima
    # e poi gli altri. **L'ordine e' qui e non nel prompt**, che e' il punto
    # di tutto.
    mine = [
        (piece, piece.cut(split, piece, facts)) for piece in (split.opening, *split.parts)
    ]
    asks = [
        (
            lambda piece=piece, owned=owned: _ask(
                _system_prompt(repo_root, *piece.agent),
                piece.asks(split, piece, day, owned),
            )
        )
        for piece, owned in mine
        if owned is not None
    ]
    with ThreadPoolExecutor(max_workers=len(asks)) as pool:
        # `map` tiene l'ordine di `asks` e rilancia la prima eccezione che
        # incontra: un pezzo che non risponde e' la sezione che non risponde,
        # come per la domanda sola.
        answers = list(pool.map(lambda ask: ask(), asks))
    # Il modello e' quello del primo pezzo che si e' chiesto: sono tutti lo
    # stesso, e la pagina ne mostra uno.
    model = answers[0][1]
    return "\n\n".join(_one_paragraph(text) for text, _ in answers), model
