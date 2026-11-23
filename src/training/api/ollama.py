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
dentro: una cartella per sezione — `01_health_split/` e le altre tre, un
file per paragrafo — e `_style.md` per le regole di casa, nello stesso
ordine in cui li legge un agente. Senza `_style.md` il modello
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
# sezioni, e `.claude/agents/01_health.md` dice espressamente di lasciarli stare.
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
# Day. E da aggiustare c'era: l'esempio in fondo a `.claude/agents/01_health.md` llama lo
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

# Quanto il modello resta in memoria fra una domanda e l'altra. Il perche' sta
# in `_ask`, dove si manda: non e' per fare presto, e' perche' un modello
# ricaricato non rende lo stesso testo.
KEEP_ALIVE = "15m"

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


# **La stessa sezione scritta in cinque pezzi.** Chiederla intera era una
# domanda sola: tutto il prompt, tutti i fatti, tutta la risposta. Uno `Split`
# e' la stessa sezione chiesta a cinque modelli piccoli — uno per misura, piu'
# uno che legge i quattro paragrafi e scrive il verdetto in cima.
#
# Il motivo e' che `.claude/agents/01_health.md` **e' gia' cinque paragrafi**:
# il verdetto e le quattro misure, in quest'ordine. Spezzarlo rende strutturale quello che
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
# **Per un po' ha vissuto accanto alla sezione intera**, non al suo posto: le
# due si guardavano una accanto all'altra sulla pagina Test, sullo stesso
# giorno e con gli stessi numeri, che e' il mestiere di quella pagina. Lo
# `Split` e' la strada che e' restata, e l'intera e' andata via — con una
# riserva che va detta, perche' il quaderno la dice: alla pari, prima che
# il ciclo tarasse qualcosa, l'intera aveva **zero errori gravi** contro 1 e
# 9, era piu' vicina ai testi di Claude e ci arrivava in 76 parole contro
# 153. Lo `Split` l'ha superata **dopo** quattro giri di taratura, che
# all'intera non sono mai stati dati. Chi riaprisse la questione parta da
# li': le righe del giro `2026-11-20-1638` nel quaderno del banco.


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
    measures_in: str = "morning"
    """Sotto quale chiave dei fatti della sezione stanno le misure dei pezzi.

    `morning` per la Health e per la Recovery, che le loro quattro misure le
    prendono da li'; `scores` per la Fitness. **E' la sola cosa che impediva
    alla macchina delle misure di servire anche la terza sezione**: il
    ritaglio di un pezzo e il conto delle letture leggevano `morning` scritto
    a mano, e un punteggio di Garmin sotto una chiave che si chiama *mattina*
    non ci starebbe — quei numeri non sono di stamattina, sono di mesi.

    Un campo e non un ritaglio diverso: il taglio di una misura e' lo stesso
    per tutte e tre, e cambia solo dove la si va a prendere."""
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
    `.claude/agents/01_health.md` invece di guardare i numeri: diceva l'HRV "sotto la
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
    scritta in `.claude/agents/02_load.md` — *`carrying` ordinario piu' una parte fuori
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


# Le quattro misure della card Recovery, nell'ordine in cui la card le mostra.
# Sono anche le sole che il prompt ha il permesso di giudicare, e qui la
# tentazione e' nominata nel prompt stesso: una readiness bassa si spiega
# bene con l'HRV, che e' di Health, e il modo sicuro di non vederlo fare e'
# non darglielo.
RECOVERY_MEASURES = (
    "readiness",
    "sleep_hours",
    "body_battery_morning",
    "body_battery_low_yesterday",
)

# L'unico allarme che parla di queste quattro. Gli altri tre sono di Health o
# di nessuno, e `.claude/agents/03_recovery.md` dice che questo e' suo.
RECOVERY_ALERTS = ("short_sleep",)


def recovery_facts(payload: dict, week: dict | None = None) -> dict:
    """La parte della Recovery dei fatti del giorno: le quattro misure con le
    loro fasce, il suo allarme, e quali misure mancano.

    Stesso ritaglio di `health_facts`, che e' la stessa forma — quattro misure
    della mattina, ognuna con la sua fascia — con una cosa in piu': **la notte
    arriva in due scritture**. La card scrive il sonno in ore e minuti
    (`sleep_minutes`, 489 che fa 8h09) e la fascia e' in ore
    (`sleep_hours.value`, 8.2): sono lo stesso fatto in due lingue, e tutti e
    due servono — il numero grande e la barra sotto di lui. Al modello vanno
    entrambi, come all'agente di Claude, e il prompt dice quale delle due si
    scrive: quella della card. E' il posto in cui questa sezione puo'
    sbagliare da sola, e la docstring di `_sits` racconta cosa fa llama con un
    fatto che ha due scritture.

    Il piano della settimana non le serve e lo ignora, come alla Health: come
    il corpo ha dormito stanotte non dipende da che cosa c'era scritto sul
    foglio.

    **La prima sera, e una sorpresa.** Il 19 novembre la readiness stava a 88
    con la fascia che chiude a 79,3, cioe' sopra. Il frammento dell'agente di
    Claude, quello che la Day mostra, dice *"readiness sits inside its usual
    range and near the top of it"*: **la fascia l'ha letta male**, ed e' la
    sola cosa di quel testo che non torni. llama, con lo stesso prompt, ha
    scritto *"readiness is above its band"*, che e' giusto — perche' quel
    confronto gliel'ha fatto `_where` e a lui restava da dirlo. I fatti che
    l'orchestratore scrive per gli agenti di Claude `where` non ce l'hanno: la
    fascia la legge da se', ed e' li' che e' scivolato. **Non si tocca niente
    di la'** — questa pagina non scrive in `summary/` e non e' il suo mestiere
    — ma e' la cosa che il banco serviva a far vedere, e andava scritta.

    llama di suo ne ha sbagliate tre, e sono le tre che il prompt nomina.
    Ha aperto con *"the body is not fully rested today"* e due righe sotto ha
    dato tre buone notizie su quattro, cioe' ha contraddetto il suo stesso
    verdetto — che e' la riga per cui Health e Load hanno finito per avere
    `_health_verdict` e `_verdict_word`, e qui quel campo non c'e'. Ha scritto
    *"almost eight hours"* per 8h09, che e' il fatto in due scritture di cui
    sopra, e pure dalla parte sbagliata. E ha impastato i due body battery in
    una frase — *"body battery this morning is also within its band, but only
    just: it was down to 14.0 yesterday"* — che e' il paragrafo in grassetto
    di `.claude/agents/03_recovery.md` letto e non applicato. Tre righe per tre buchi:
    **sono i tre che, nelle altre due sezioni, hanno portato a spezzare.**

    **E hanno portato a spezzare anche questa**, il giro dopo: la card di
    destra adesso e' `recovery_split`, e quei tre buchi sono diventati tre cose
    che non possono succedere — il verdetto lo conta `_recovery_verdict`, la
    scrittura della notte la dice `SLEEP_READS`, e i due body battery sono due
    modelli che l'uno dell'altro non sanno niente. La sezione intera resta nel
    registro: e' il termine di paragone, ed e' chiedibile a mano."""
    morning = payload.get("morning", {})
    alerts = [a for a in payload.get("alerts", []) if _alert_key(a) in RECOVERY_ALERTS]
    missing = [m for m in payload.get("missing", []) if m in RECOVERY_MEASURES]
    return {
        "day": payload.get("day"),
        "morning": {
            k: {**morning[k], "where": _where(morning[k])}
            for k in RECOVERY_MEASURES
            if k in morning
        },
        "sleep_minutes": payload.get("sleep_minutes"),
        "alerts": alerts,
        "missing": missing,
    }


# I tre punteggi della card Fitness, nell'ordine in cui la card li mostra.
# Sono i soli che una fascia ce l'hanno, e percio' i soli che il verdetto
# conta.
FITNESS_SCORES = ("vo2max", "endurance", "hill")

# Come si chiamano parlando. La chiave non basta: *hill* da solo non e' una
# cosa, e *vo2max* si scrive in un modo solo.
FITNESS_LABELS = {
    "vo2max": "VO2max",
    "endurance": "the endurance score",
    "hill": "the hill score",
}


def _pace_label(seconds_per_km: object) -> str | None:
    """Il passo di soglia come si dice: `343` fa "5:43 per kilometre".

    **E' una delle poche cifre che la card non mostra e che si possono
    dare**, perche' il senso pratico di una frequenza di soglia e' il passo a
    cui corrisponde: lo dice `.claude/agents/04_fitness.md`, ed e' l'eccezione che quel
    prompt si concede. Il conto lo fa qui, come tutti gli altri: 343 secondi
    diviso 60 e il resto, che a un modello che non sa contare non si chiede."""
    if not isinstance(seconds_per_km, (int, float)) or seconds_per_km <= 0:
        return None
    seconds = round(seconds_per_km)
    return f"{seconds // 60}:{seconds % 60:02d} per kilometre"


def _threshold_facts(fitness: dict) -> dict | None:
    """La soglia, che sulla card e' una casella sola con due nomi possibili.

    Garmin una soglia del lattato la rileva di rado, e finche' non lo fa la
    card mostra quella dell'orologio: sono due misure diverse con lo stesso
    posto, e **chi scrive deve sapere quale delle due ha in mano** — una e'
    stata letta in una seduta e ha un passo attaccato, l'altra e' una stima.
    Il nome arriva nei fatti e non nel prompt perche' cambia col giorno.

    `None` quando non c'e' ne' l'una ne' l'altra: la casella sulla card e' un
    trattino, e il paragrafo non si scrive."""
    lactate = fitness.get("lactate_threshold") or {}
    watch = fitness.get("threshold_hr") or {}
    if lactate.get("heart_rate"):
        return {
            "measure": "the lactate threshold",
            "heart_rate": lactate["heart_rate"],
            "pace": _pace_label(lactate.get("pace_s_per_km")),
            "read_on": lactate.get("as_of"),
            "detected": True,
        }
    if watch.get("value"):
        return {
            "measure": "the threshold heart rate",
            "heart_rate": watch["value"],
            "pace": None,
            "read_on": watch.get("as_of"),
            "detected": False,
        }
    return None


def fitness_facts(payload: dict, week: dict | None = None) -> dict:
    """La parte della Fitness dei fatti del giorno: i tre punteggi con le loro
    fasce, la soglia, e i due acclimatamenti.

    **I punteggi arrivano normalizzati**, come i carichi della Load: nei fatti
    del giorno il valore di oggi si chiama `now`, e `_where` e `_sits`
    leggono `value`. Rinominarlo qui costa una riga e fa funzionare per questa
    sezione tutta la macchina delle misure; il contrario sarebbe tre funzioni
    che sanno di Fitness.

    **Quello che resta fuori il prompt lo nomina per dire di non usarlo**, ed
    e' il solito motivo per cui si taglia: `change` e `days_ago_28` sono il
    racconto del mese — "non sono roba tua", e la card non li disegna — e
    darglieli e poi chiedergli di non guardarli e' il modo piu' sicuro di
    vederli comparire. Via anche `level` dell'endurance, che e' una parola di
    Garmin che la card non mostra.

    Gli acclimatamenti ci sono **anche a zero**, che e' il loro valore per
    quasi tutto l'anno: il recinto della sezione e' quello che la card mostra,
    e se quel paragrafo si scriva o no e' una decisione del pezzo
    (`_altitude_facts`), non del ritaglio.

    Il piano della settimana non le serve e lo ignora: quello che il corpo sa
    fare oggi e' il frutto di mesi, non del foglio di questa settimana.

    **La prima sera, e il divario piu' netto del banco.** Col prompt intero,
    il 19 novembre, llama ha scritto un paragrafo solo cosi': *"Your VO2max is
    inside its band today, at 42.9. Endurance is above its band, at 5156. The
    hill score is below its band, at 56. Your lactate threshold heart rate is
    151... You are not acclimatised to any altitude or heat."* **Quattro
    regole del suo prompt rotte in cinque righe**: nessun verdetto in testa
    (la prima riga del compito), tutti e quattro i numeri scritti (la card li
    mostra due centimetri sopra), nessun giudizio su niente, e in fondo
    proprio la frase che quel prompt vieta — *"non sei acclimatato a nessuna
    quota" non vale una parola*.

    Spezzata, la stessa giornata e' tornata cinque paragrafi col verdetto in
    cima e gli acclimatamenti assenti invece che negati. Il prezzo l'hanno
    pagato i prompt dei pezzi, e tre volte di fila: **ogni motivazione che ho
    scritto per spiegare un campo e' finita nella card parola per parola** —
    *"above its band is the good side, it's at its best in a month"*,
    *"everything hard is run off this number"*, *"the plainest reason is there
    hasn't been any climbing"*. Le prime due erano regole mie e sono state
    riscritte come vincoli (`SCORE_READS`, `THRESHOLD_READS`); la terza viene
    dal file del punteggio ed e' una frase da allenatore, che in una card ci
    sta: la differenza fra le due cose e' se la frase parla del corpo o del
    prompt.

    Quello che resta da decidere guardando la pagina: i punteggi scrivono
    ancora il loro numero, e l'apertura scivola nel mese e in *this morning* —
    che per punteggi fatti di settimane e' la parola sbagliata."""
    fitness = payload.get("fitness", {})
    scores = {}
    for key in FITNESS_SCORES:
        score = fitness.get(key) or {}
        if score.get("now") is None:
            continue
        measure = {"value": score["now"], "band": score.get("band")}
        scores[key] = {**measure, "where": _where(measure)}
    return {
        "day": payload.get("day"),
        "scores": scores,
        "threshold": _threshold_facts(fitness),
        "altitude_acclimation": fitness.get("altitude_acclimation") or {},
        "heat_acclimation": fitness.get("heat_acclimation") or {},
    }


def _alert_key(alert: object) -> str:
    """Il nome di un allarme, che nei fatti e' una stringa o un oggetto con
    dentro la chiave."""
    if isinstance(alert, str):
        return alert
    if isinstance(alert, dict):
        return str(alert.get("key") or alert.get("name") or "")
    return ""


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
    riga da scrivere e' una sola.

    **Lo usa anche la Recovery**, che e' la stessa forma: quattro misure della
    mattina, una per paragrafo, ognuna con la sua fascia. Il testo che ne esce
    e' lo stesso perche' di Health non c'e' niente dentro — il titolo lo da'
    `split.title` e il nome della misura `part.label` — e un secondo ritaglio
    identico sarebbero due recinti che divergono da soli.

    **E `reading` c'e' solo se la misura ha una parte cattiva.** Le quattro
    della Health ce l'hanno tutte; il minimo del body battery di ieri no, e
    per la stessa ragione dei tre carichi della Load: piu' giu' del solito
    vuol dire che ieri e' costata, che e' un fatto sull'allenamento e non un
    difetto del recupero (`.claude/agents/03_recovery.md` lo dice in grassetto). Dargli una
    direzione vorrebbe dire far contare una giornata dura come una cattiva
    notizia sul corpo. Senza `bad_when` il campo non c'e', e il prompt di quel
    pezzo non lo nomina."""
    measure = facts.get(split.measures_in, {}).get(part.key) or {}
    alert = next((a for a in facts.get("alerts", []) if _alert_key(a) == part.alert), None)
    where = measure.get("where", "unknown")
    return {
        "day": facts.get("day"),
        "measure": part.label,
        "value": measure.get("value"),
        "band": measure.get("band"),
        "where": where,
        **(
            {"reading": _reading(where, part.bad_when, _sits(measure))}
            if part.bad_when
            else {}
        ),
        "alert": alert,
        "missing": not measure or part.key in facts.get("missing", []),
    }


def _measure_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio di una misura: scrivi il paragrafo di questa misura.

    La riga sull'esempio, che c'e' in `_user_prompt`, qui non serve: nei file
    delle misure di esempi non ce n'e' nessuno, ed era quello il motivo per
    cui serviva.

    **La cornice sta in `_one_measure_prompt`**, che la Recovery usa con le
    sue righe: di questa funzione resta la riga che dice come si leggono i
    campi, perche' e' la sola cosa che fra una misura e l'altra cambia."""
    return _one_measure_prompt(split, part, day, facts, MEASURE_READS)


# Le righe che dicono a un paragrafo come si leggono i campi che ha in mano.
# **Sono la sola cosa che cambia fra il messaggio di una misura e quello di
# un'altra**, e stanno fuori dalla cornice per questo: la cornice — scrivi il
# paragrafo di questa misura della sezione tale, le altre non sono tue,
# rispondi col solo paragrafo — e' la stessa per tutte, e tenerla in un posto
# solo vuol dire che non puo' divergere fra una sezione e l'altra mentre si
# aggiusta una riga.
#
# Vanno **in fondo al messaggio**, che e' il posto in cui questo file ha
# imparato che le regole attaccano: la storia e' nella docstring di
# `_user_prompt`, e in quella di `_load_part_facts` c'e' la volta in cui la
# stessa regola scritta nel file del pezzo e' stata letta e non applicata.
MEASURE_READS = (
    "`where` says where the value falls against its own band, and `reading` says "
    "what that means for this measure — down to whereabouts inside the band a "
    "normal value sits: say what you make of them, and never contradict them. "
)

# **La persona, e il consiglio.** Le due righe che i quattro paragrafi della
# Recovery si dividono, e che quelli della Health non hanno: la prima sera in
# cinque pezzi, il paragrafo della readiness ha scritto *"my body came back
# further than usual"* e quello del minimo di ieri *"yesterday cost him"* —
# prima e terza persona sulla stessa card, con le regole di casa che dicono la
# seconda e `_measure.md` che vieta la prima. E quello della batteria ha
# chiuso con *"this is good news for today's training session"*, che e' un
# consiglio.
#
# Alla Health non succede con le stesse regole, e non e' un mistero: la
# readiness e il sonno sono cose che uno *ha*, e in bocca vengono *mie*; una
# frequenza a riposo no. Quindi la riga sta qui e non in `MEASURE_READS`, che
# e' condivisa — alla Health un prompt non si cambia per un guaio che non ha.
#
# **E la riga parla a lui, non di lui.** Il giro dopo il paragrafo del minimo
# di ieri chiudeva ancora con "taking neither more nor less out of him than
# usual", con la coda che gli vietava *he* due righe sotto: `COST_READS`
# spiegava i tre casi della fascia dicendo *"yesterday took more out of him"*,
# e lui ha ricopiato la mia frase invece di seguire la mia regola. Le righe che
# spiegano un campo sono anche un esempio di come si scrive, che si voglia o
# no, e quindi si scrivono nella persona giusta.
#
# **E la riga non nomina nessuna misura**, che e' la lezione piu' vecchia di
# questo file imparata un'altra volta. La prima versione diceva "scrivigli
# *your readiness*, *you slept*", due esempi per far sentire la persona, e il
# giro dopo il paragrafo del sonno ha aperto con *"your readiness was
# comfortably normal last night"* e quello della readiness ha infilato *"you
# slept well enough"*: **i due esempi sono finiti nei due paragrafi
# sbagliati**, ognuno nell'altro. E' la ragione per cui **nessun file di
# `.ollama/agents/` ha un `## Example`**, che quello di Claude invece ce
# l'ha, e un esempio di tre parole non e' piu' innocente di uno di sei
# righe: se nomina una misura, quella misura ricompare. La persona si chiede senza dare un esempio.
RECOVERY_TAIL = (
    "**The reader is spoken to as *you***, in every sentence: *your* readiness, "
    "*your* night, what *you* can be asked for. And say nothing about what to train "
    "today: that is nobody's business on this card. "
)

# Le quattro misure della Recovery: come si legge una misura, piu' le due
# righe di sopra.
RECOVERY_READS = MEASURE_READS + RECOVERY_TAIL

# Il sonno: lo stesso, piu' la scrittura da usare. Il fatto arriva in tre
# lingue — i minuti della card, le ore della fascia (`recovery_facts`) e le
# parole di `_clock_words` — e questa riga dice quale delle tre si scrive.
#
# **Niente esempio con un numero dentro, mai piu'** (23 novembre 2026). La storia di
# questa riga e' una lezione in due tempi. La prima sera llama ha scritto
# "almost eight hours" per 8h09: scrittura vaga e dalla parte sbagliata. La
# riga allora ha aggiunto l'esempio giusto, "eight hours nine" — e il modello
# ha cominciato a **copiarlo** invece di convertire i minuti, dicendo otto ore
# e nove minuti a chi aveva dormito 7h04, ogni volta e identico. Un esempio
# numerico in un prompt, per un modello da otto miliardi, non e' un esempio:
# e' la risposta. Adesso la conversione la fa Python e qui si chiede solo di
# ricopiare.
SLEEP_READS = (
    "`where` says where the night falls against its own band, and `reading` says what "
    "that means: say what you make of them, and never contradict them. **Give the "
    "night's length by copying `sleep_clock` word for word**: it is already written the "
    "way the card reads it, and it is the only writing of the night allowed in the "
    "paragraph. Do no arithmetic on it, and do not quote `sleep_minutes` or the hours "
    "in `value` — those are there to be read against the band, not written. "
) + RECOVERY_TAIL

# Il minimo del body battery di ieri, la misura senza parte cattiva: `reading`
# non ce l'ha, e questa riga non lo nomina — un campo che manca e' una domanda,
# e a una domanda il modello risponde da se'.
#
# **E dice tutti e tre i casi della fascia, non solo quello cattivo.** La prima
# sera gliene avevo descritto uno — sotto la fascia e' una giornata che e'
# costata — e con un valore *dentro* la fascia ha scritto comunque "yesterday
# cost him a deep low, the day took more out of him than usual", che e' il caso
# che gli era stato spiegato applicato al caso che non era. Un campo con un
# caso solo descritto e' un campo che ha un caso solo.
COST_READS = (
    "`where` says where yesterday's low falls against its own band, and it is the "
    "truth. **Below its band** is a low that went deeper than usual: yesterday took "
    "more out of you than a day usually does. **Inside its band** is a day that cost "
    "about what a day costs, and that is the whole of what to say about it — never a "
    "deep low, never a day that took a lot. **Above its band** is a day that cost "
    "less than usual. Whichever it is, **that is a fact about the training and not a "
    "fault in the recovery** — there is no good or bad side to this one — so say what "
    "the day cost and stop there. Whether the morning came back anyway is the opening "
    "paragraph's to say, and not yours. "
) + RECOVERY_TAIL


def _one_measure_prompt(
    split: "Split", part: Part, day: date, facts: dict, reads: str
) -> str:
    """La cornice del messaggio di un paragrafo che parla di una misura della
    mattina: la stessa per la Health e per la Recovery, che e' la stessa
    domanda — una misura, la sua fascia, il suo paragrafo.

    Di quale sezione si tratti lo dice `split.title` e di quale misura
    `part.label`: dentro non c'e' il nome ne' dell'una ne' dell'altra, ed e'
    il motivo per cui la cornice e' una sola."""
    return (
        f"Write the paragraph about {part.label} for the {split.title} section of the daily "
        f"report for {day:%A %-d %B %Y}. "
        "The facts are here, below, and they are all there is: the other three measures "
        "of the section are not yours and are not in them.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        f"{reads}"
        "Answer with the one paragraph and nothing else: no heading, "
        "no preamble, no sign-off, no quotes around it."
    )


_UNITS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS = ("", "", "twenty", "thirty", "forty", "fifty")


def _words(number: int) -> str:
    """Un numero sotto il sessanta, in parole. Tanto basta: ore di sonno e
    minuti di un'ora non vanno piu' in la'."""
    if number < 20:
        return _UNITS[number]
    tens, units = divmod(number, 10)
    return _TENS[tens] + (f"-{_UNITS[units]}" if units else "")


def _clock_words(minutes: float | None) -> str | None:
    """I minuti della card scritti come si leggono: *seven hours and four
    minutes*, *eight hours* in punto, *forty minutes* sotto l'ora.

    **Lo scrive Python, non il modello** (23 novembre 2026). La regola della casa lo
    dice gia' per tutti — «every number comes from the JSON: nothing computed
    by you» (`_style.md`) — e convertire 424 minuti in ore e minuti e' un
    conto. Chiederlo a un modello da otto miliardi e' la cosa che e' andata
    storta due volte di fila: prima «almost eight hours» per 8h09, poi
    l'esempio della riga stessa copiato di peso."""
    if minutes is None:
        return None
    hours, rest = divmod(int(round(minutes)), 60)
    minutes_words = f"{_words(rest)} minute" + ("s" if rest != 1 else "")
    if not hours:
        return minutes_words
    head = f"{_words(hours)} hour" + ("s" if hours != 1 else "")
    return head if not rest else f"{head} and {minutes_words}"


def _sleep_facts(split: "Split", part: Part, facts: dict) -> dict:
    """La notte: la sua misura, piu' **i minuti che la card mostra** e come si
    scrivono.

    E' il solo dei quattro pezzi che prende dei campi in piu' dai fatti della
    sezione, e la ragione sta in `recovery_facts`: il sonno e' lo stesso fatto
    scritto in due lingue, 424 minuti e 7,1 ore, e tutte e due servono — una
    e' il numero grande della card, l'altra e' quella che la fascia confronta.
    Darne una sola vorrebbe dire o un paragrafo che scrive una scrittura che
    sulla card non c'e', o un paragrafo che non puo' leggere la sua fascia.

    La terza, `sleep_clock`, e' la prima in parole: il paragrafo la copia e
    non la calcola."""
    return {
        **_measure_facts(split, part, facts),
        "sleep_minutes": facts.get("sleep_minutes"),
        "sleep_clock": _clock_words(facts.get("sleep_minutes")),
    }


def _sleep_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio della notte: la cornice delle misure, con la riga che dice
    in che scrittura si scrive."""
    return _one_measure_prompt(split, part, day, facts, SLEEP_READS)


def _recovery_measure_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio di una misura della Recovery: la cornice delle misure, con
    la riga delle misure e quelle della persona e del consiglio."""
    return _one_measure_prompt(split, part, day, facts, RECOVERY_READS)


def _cost_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio del minimo di ieri: la cornice delle misure, con la riga
    di una misura che non ha una parte cattiva."""
    return _one_measure_prompt(split, part, day, facts, COST_READS)


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


def _leans_bad(reading: str) -> bool:
    """Una misura **dentro la fascia ma appoggiata al lato che preoccupa**.

    Sono le letture che `NORMAL_BAD_EDGE` produce — *normal, but high in its
    range* per una misura che si legge in alto, *low* per una che si legge al
    contrario — e per un giro intero non contavano niente: `_reading` le
    calcolava, i paragrafi delle misure le ricevevano, e il verdetto le
    buttava.

    **La mattina del 20 novembre ha fatto vedere che era troppo stretto.**
    Tutte e quattro le misure dentro la fascia, quindi verdetto *«the body is
    fine»* e niente da nominare — ma la frequenza a riposo stava all'88% della
    sua fascia e l'HRV al 5% della sua, cioe' **entrambe appoggiate al loro
    lato cattivo, e dalla stessa parte**. Il frammento di Claude di quel
    giorno apriva con *«slightly off — nothing wrong, but a body that has not
    quite put yesterday behind it»*, che e' la lettura giusta della
    configurazione, e la nostra diceva che andava tutto bene.

    Resta vero che **una** misura appoggiata al bordo non e' una notizia: era
    la ragione per cui `_sits` non doveva pesare, e vale ancora. Due dalla
    stessa parte lo sono."""
    return reading.startswith("normal, but")


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
#
# **E c'era una terza strada, che non era rinominare.** Il nome che si leggeva
# ad alta voce piu' di tutti era `what_it_rests_on`, e li' non si e' rinominato
# niente: si e' tolto l'involucro e i due campi dentro sono saliti in cima
# (`_rests_on`, `_spoken_of`). Un nome con una relazione dentro — *rests on* —
# diventa un verbo in bocca a chi scrive; `about` da solo no. Quindi la lezione
# di qui vale per i nomi che restano, non dice che un campo non si possa
# smontare.
VERDICT_WORDS = {
    "good": "the body is fine",
    # Il gradino fra «sta bene» e «una misura fuori»: niente fuori fascia, ma
    # due o piu' appoggiate al loro lato cattivo. Il perche' sta in
    # `_leans_bad`.
    "leaning": "fine, but leaning tired",
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
    leaning = sum(1 for reading in readings if _leans_bad(reading))
    if not much and not worse:
        # **Due appoggiate al lato cattivo non sono una mattina tranquilla**,
        # anche se nessuna e' fuori. La storia sta in `_leans_bad`.
        return "leaning" if leaning >= 2 else "good"
    if not much and worse == 1:
        return "niggle"
    if much >= 2 or much + worse == 4 or (much and worse >= 2):
        return "fatigue"
    return "off"


def _rests_on(bad: "list[str]", leaning: "list[str]", good: "list[str]") -> str | None:
    """Di che cosa parla la seconda frase del paragrafo di apertura. **Nullo
    vuol dire che quella frase non c'e'.** Quali misure nomina lo dice
    `_spoken_of`, qui sotto.

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
    `_health_verdict`, e si conta qui.

    **E questa frase non sta piu' dentro a un campo che si chiamava
    `what_it_rests_on`.** Era un oggetto con dentro `about` e `measures`, e il
    suo nome e' finito nel testo su **otto aperture di prova su otto**: *"this
    rests on your readiness measure being higher than usual"*, *"it rests on a
    wake-up body battery that reads worse than usual"*, *"which is what your
    morning rests on"*. E sulla mattina tranquilla la cosa che il compito del
    quinto vieta in due righe diverse: *"there's nothing for it to rest on this
    morning"*, una frase sul campo che non c'era.

    Rinominarlo era gia' stato provato, e aveva peggiorato sei mattine su sei:
    la storia e' in `VERDICT_WORDS`, e la conclusione era che un nome di campo
    e' una cornice. **Quello che non era stato provato e' non avere una
    cornice.** *Rests on* non era un nome, era una relazione, e una relazione
    in un nome diventa un verbo in bocca a chi scrive; `about` e
    `how_they_read`, in cima e per conto loro, un verbo non ce l'hanno.
    Dieci aperture su dieci dopo, il nome del campo si legge una volta — e in
    piu' la frase e' tornata a non sbagliare i numeri (togliendo invece
    `about`, per vedere se era lei la colpevole, una mattina con due buone
    notizie e' diventata *"resting heart rate is much worse than usual"*: la
    prosa che si fa saccheggiare ancorava anche la direzione, e quella e' la
    ragione per cui e' rimasta).

    Le parole dentro `about` restano quelle che erano: una frase che in inglese
    sta in piedi da sola, ricopiata di peso, resta una frase."""
    if bad:
        return (
            "this one reads badly this morning"
            if len(bad) == 1
            else "these read badly this morning"
        )
    if leaning:
        # Nessuna fuori fascia, ma due appoggiate al lato che conta: la frase
        # dice che pendono, non che vanno male, perche' non vanno male.
        return "nothing is out of range, and these are leaning the tired way"
    if good:
        return (
            "nothing reads badly, and this one reads better than usual"
            if len(good) == 1
            else "nothing reads badly, and these read better than usual"
        )
    return None


# Come una misura appoggiata al lato cattivo arriva all'apertura. **Senza la
# fascia dentro**: il paragrafo di apertura di fasce non parla — e' scritto nel
# suo compito in due righe — e passargli *«normal, but high in its range»*
# vorrebbe dire mettergli in mano proprio quello. Questa frase dice la stessa
# cosa e non nomina niente da ricopiare.
LEANING_READING = "leaning the tired way"


def _spoken_of(
    seen: "list[dict]", bad: "list[str]", leaning: "list[str]", good: "list[str]"
) -> "list[dict]":
    """Le misure che il paragrafo di apertura puo' nominare, **le peggiori per
    prime**, e come si legge ognuna. Vuota vuol dire che non ce n'e' nessuna
    da nominare, e che la seconda frase non c'e'.

    **Erano due campi e sono uno.** Accanto ad `about` c'era un `measures`
    con gli stessi nomi dentro, e di `how_they_read` quei nomi sono le
    chiavi: la stessa cosa scritta due volte, che e' la cosa che questo file
    non fa (`_part_facts`, `_sits`). Per un giro e' passata perche' i due
    campi stavano dentro un involucro che li teneva insieme; tolto
    l'involucro, `measures` nudo e' diventato **il nome di tutte le misure
    della sezione** in bocca a chi scrive — *"only readiness was measured"*,
    una mattina in cui ne erano state misurate quattro. Non era un campo
    letto ad alta voce: era un campo capito male, e capito male perche' il
    suo nome prometteva piu' di quello che conteneva.

    `how_they_read` quel nome non lo promette, e in tutte le prove e' stato
    usato bene: *"body battery at wake-up reads worse than usual"*, misura
    per misura, mai una in piu'. Quindi i nomi si leggono da li', l'ordine
    e' quello di `_carried_by` — la peggiore prima, che e' quella da nominare
    per prima — e la lunghezza della lista resta un fatto da cui il
    singolare e il plurale si vedono senza contarli.

    **E unendoli e' venuta fuori un'incoerenza che c'era da sempre.** Il
    vecchio `measures` conteneva le cattive se c'erano cattive, e le buone
    solo quando di cattive non ce n'era nessuna — una mattina non da' una
    buona notizia e una cattiva nella stessa frase. `how_they_read` invece
    elencava le une e le altre, sempre: su una mattina con una misura fuori e
    una che andava meglio del solito, al quinto arrivava una misura **in
    `how_they_read` ma non in `measures`**, cioe' una misura che vedeva e che
    la riga sopra gli vietava di nominare. Non si e' mai visto nel testo, che
    quella riga per una volta e' stata seguita, ma era un recinto con un buco
    e il buco l'ha trovato un test. Adesso la lista e' una e la regola e'
    quella di `measures`: le cattive, o le buone se cattive non ce ne
    sono."""
    reading = {
        m["measure"]: LEANING_READING if _leans_bad(m["reading"]) else m["reading"]
        for m in seen
    }
    return [{"measure": name, "reading": reading[name]} for name in (bad or leaning or good)]


def _readings_of(split: "Split", facts: dict) -> "list[dict]":
    """Come si legge ognuna delle misure **che portano il verdetto**: il nome
    con cui si chiama parlando e la notizia che e'.

    Lo chiamano i paragrafi di apertura della Health e della Recovery, che la
    stessa domanda se la fanno: che cosa vogliono dire tutte insieme. Il
    posto, il valore e la fascia qui non passano — sono il mestiere dei
    paragrafi sotto — e la ragione sta in `_health_opening_facts`, dove la
    storia di come ci si e' arrivati e' scritta per intero.

    **`bad_when` e' il filtro**, e non e' un dettaglio: una misura senza parte
    cattiva non e' una misura che va male o che va bene, quindi in un conto
    non entra. Alla Health non toglie niente, che le sue quattro ce l'hanno
    tutte; alla Recovery toglie il minimo del body battery di ieri, che e'
    esattamente quello che `.claude/agents/03_recovery.md` chiede — una giornata che e'
    costata e' un fatto sull'allenamento, e non deve poter spostare il
    verdetto sul corpo."""
    measures = facts.get(split.measures_in, {})
    return [
        {
            "measure": part.label,
            # **Col posto dentro la fascia**, e prima senza. La riga diceva che
            # all'apertura `sits` non serve, perche' di fasce non parla — vero
            # per quello che l'apertura *scrive*, falso per quello che il
            # verdetto deve *contare*: senza, due misure appoggiate al loro
            # lato cattivo leggevano «normal» e la mattina del 20 novembre
            # prendeva «il corpo sta bene» (`_leans_bad`).
            #
            # Il linguaggio della fascia non le arriva comunque: `_spoken_of`
            # traduce quelle letture prima di passarle.
            "reading": _reading(
                (measures.get(part.key) or {}).get("where", "unknown"),
                part.bad_when,
                _sits(measures.get(part.key) or {}),
            ),
        }
        for part in split.parts
        if part.bad_when
    ]


def _carried_by(seen: "list[dict]") -> "tuple[list[str], list[str], list[str]]":
    """Quali misure portano il verdetto, quali pendono dalla parte stanca e
    quali danno una buona notizia, **le peggiori per prime**.

    L'ordine e' quello con cui `_rests_on` le nomina, e per questo si conta
    qui una volta per tutte e due le sezioni: due copie di queste righe
    sarebbero due ordini che divergono al primo che le ritocca.

    **Il gruppo di mezzo e' nato dopo**, e il perche' sta in `_leans_bad`: una
    mattina con due misure appoggiate al loro lato cattivo prende un verdetto
    suo, e un verdetto senza niente da nominare e' il paragrafo che si
    inventa la seconda frase o la salta."""
    named = lambda reading: [m["measure"] for m in seen if m["reading"] == reading]
    bad = named("much worse than usual") + named("worse than usual")
    leaning = [m["measure"] for m in seen if _leans_bad(m["reading"])]
    good = named("much better than usual") + named("better than usual")
    return bad, leaning, good


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
    seen = _readings_of(split, facts)
    rests_on, leaning, good_news = _carried_by(seen)
    # **Gli arrivano solo le misure di cui parlera', e di quelle solo come si
    # leggono.** Non il valore e non la fascia — dove sta una misura e' il
    # mestiere dei quattro paragrafi, che gli stanno sotto e che il lettore
    # ha — e **non le misure che stanno bene**: con tutte e quattro in mano
    # le elencava tutte e quattro, anche la mattina in cui la seconda frase
    # doveva dire "le altre stanno dove devono" e basta. La riga che glielo
    # diceva c'era, e l'ha letta quattro volte su quattro senza farci caso.
    # Quello che non si ha non si scrive: e' la stessa ragione per cui
    # `week_ago` non arriva alla Load.
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
        "about": _rests_on(rests_on, leaning, good_news),
        "how_they_read": _spoken_of(seen, rests_on, leaning, good_news),
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
        "`verdict` is the verdict and you do not reopen it. `measures` names the only "
        "measures you may name anywhere in the paragraph, worst first, and `about` is "
        "what the second sentence makes of them: put both in your own words and not in "
        "these. **An empty `measures` is no measure to name and no second sentence at "
        "all** — write the first sentence and the third, and leave the missing one "
        "unmentioned. `how_they_read` is how each of those measures reads, so that your "
        "paragraph does not contradict the section it opens — **say each one as its reading says "
        "it and no further**: the reading has already chosen how strongly it puts "
        "itself. The reader is looking at a "
        "card about a body, not a report on how it was assembled: **no field is named in "
        "no sentence of it is about the card**. "
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
    grassetto di `.claude/agents/02_load.md` — e un pezzo che quel foglio non ce l'ha non
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
        "contradict it: `inside its band` means you are doing about as much of it as "
        "usual, and the right thing to say is that it is normal. `week` is what the "
        "week it belongs to asked for, and it is what decides the reading: the same "
        "value is the plan working in one week and the plan ignored in another — "
        "**judge with it, and do not report it**, because its sessions and its counts "
        "belong to the last paragraph of the section and not to you. Never write the "
        "figure in `value`: it is on the card, right above your text. **The reader is "
        "spoken to as *you***, in every sentence. "
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


# **La Recovery spezzata.** La terza, ed e' quella che somiglia di piu' alla
# Health: quattro misure della mattina, una per paragrafo, e un quinto che
# legge come si leggono e dice quanto il corpo era pronto. Per questo i suoi
# pezzi riusano la cornice delle misure (`_one_measure_prompt`) e il conto
# delle letture (`_readings_of`): la domanda e' la stessa, e due copie
# sarebbero due cose che divergono.
#
# **Perche' spezzarla.** La prima sera, con il prompt intero, llama ha
# sbagliato tre cose e sono le tre che hanno portato a spezzare le altre due:
# ha aperto con un verdetto che due righe sotto contraddiceva da se', ha
# scritto la notte nella scrittura sbagliata, e ha impastato i due body
# battery in una frase — che e' il paragrafo in grassetto di `.claude/agents/03_recovery.md`
# letto e non applicato. La storia per intero sta in `recovery_facts`. Qui il
# verdetto lo conta Python, la scrittura la dice la riga del pezzo
# (`SLEEP_READS`), e i due body battery sono due modelli che l'uno dell'altro
# non sanno niente: le tre righe diventano tre cose che non possono piu'
# succedere.

# Come si legge il verdetto della Recovery. **Sono le tre frasi che
# `.claude/agents/03_recovery.md` da' come esempi di prendere posizione**, e per la ragione
# di `VERDICT_WORDS`: un valore che in inglese sta in piedi da solo non ha
# bisogno di essere vietato, e ricopiato di peso resta una frase e non
# l'etichetta di un campo.
RECOVERY_VERDICT_WORDS = {
    "ready": "you woke up ready",
    # Lo stesso gradino della Health, per la stessa ragione (`_leans_bad`).
    "leaning": "ready, but not fresh",
    "workable": "good enough to work, not to race",
    "flat": "the body is not rested",
}


def _recovery_verdict(readings: "list[str]") -> str:
    """Quanto il corpo era pronto, da quante delle **tre** misure che portano
    il verdetto vanno male.

    Stessa divisione del lavoro di `_health_verdict`, e stessa ragione: il
    conto non e' un giudizio, e un modello piccolo lo sbaglia anche con la
    regola scritta davanti. Quanto pesi una misura su tre resta al quinto, e
    la frase pure.

    **Tre gradini e non quattro.** La Health ne ha quattro perche' ha quattro
    misure da contare; qui sono tre — la readiness, la notte e il body battery
    al risveglio — e il minimo di ieri non entra (`_readings_of` dice
    perche'). Su tre, una scala a quattro gradini avrebbe un gradino che
    nessuna combinazione raggiunge, e un gradino che non si puo' toccare e'
    una riga che non si puo' provare."""
    much = readings.count("much worse than usual")
    worse = readings.count("worse than usual")
    leaning = sum(1 for reading in readings if _leans_bad(reading))
    if not much and not worse:
        return "leaning" if leaning >= 2 else "ready"
    if much >= 2 or much + worse == 3:
        return "flat"
    return "workable"


def _cost_of_yesterday(where: str) -> str | None:
    """Quanto e' costata la giornata di ieri, in parole, dal posto del minimo
    del body battery nella sua fascia.

    Stessa ragione di `_carrying` per la Load: e' aritmetica detta a parole, e
    **non e' il verdetto**. Un minimo piu' basso del solito vuol dire che ieri
    ha chiesto molto, che in una settimana di qualita' e' il piano che
    funziona: percio' questa frase arriva al quinto come contesto e non come
    un termine del conto, e il suo prompt ha una riga che glielo dice.

    `None` quando la misura non c'e': la frase non si scrive, e il paragrafo
    di apertura ne ha una in meno invece di inventarsela."""
    if where == "unknown":
        return None
    if where.startswith("far below"):
        return "yesterday took a great deal more out of you than a day usually does"
    if where.startswith("below"):
        return "yesterday took more out of you than a day usually does"
    if "above" in where:
        return "yesterday cost you less than a day usually does"
    return "yesterday cost you about what a day usually costs"


def _recovery_opening_facts(split: "Split", part: Part, facts: dict) -> dict:
    """Quello che tocca al quinto della Recovery: **come si leggono le tre che
    contano, e quanto e' costata ieri.**

    Le prime due cose sono quelle del quinto della Health, contate dagli
    stessi attrezzi e per le stesse ragioni, che in
    `_health_opening_facts` sono scritte per intero: il verdetto gia' deciso,
    le sole misure che puo' nominare, e come si leggono quelle — non i valori
    e non le fasce, che sono il mestiere dei quattro paragrafi sotto.

    **La terza cosa e' sua.** Il minimo del body battery di ieri nel verdetto
    non entra, ma nel paragrafo di apertura ci deve entrare: la frase che
    `.claude/agents/03_recovery.md` chiede e' proprio quella — *la giornata ti ha svuotato
    piu' del solito, e la mattina e' tornata su comunque* — e senza il costo
    di ieri in mano quella frase non si puo' scrivere. Arriva per quello che
    e': una cosa da dire, non un termine del conto. La riga che glielo dice
    sta nel messaggio."""
    seen = _readings_of(split, facts)
    rests_on, leaning, good_news = _carried_by(seen)
    # Il pezzo senza parte cattiva e' il minimo di ieri, e di lui al quinto
    # arriva il costo della giornata e non il posto nella fascia: dove sta un
    # valore e' del paragrafo che lo possiede, due centimetri piu' sotto.
    cost = next((p for p in split.parts if not p.bad_when), None)
    low = facts.get(split.measures_in, {}).get(cost.key, {}) if cost else {}
    return {
        "verdict": RECOVERY_VERDICT_WORDS[_recovery_verdict([m["reading"] for m in seen])],
        "about": _rests_on(rests_on, leaning, good_news),
        "how_they_read": _spoken_of(seen, rests_on, leaning, good_news),
        "what_yesterday_cost": _cost_of_yesterday(low.get("where", "unknown")),
    }


def _recovery_opening_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio del quinto della Recovery. Il recinto e il perche' stanno
    in `_recovery_opening_facts`; qui c'e' in piu' la riga sul costo di ieri,
    che e' la sola cosa che questo paragrafo ha e quello della Health no."""
    return (
        f"Write the opening paragraph of the {split.title} section of the daily report "
        f"for {day:%A %-d %B %Y}. "
        "It goes at the top of the section, above four paragraphs that are already "
        "written, one for each measure, and it says how ready the body was this "
        "morning.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "`verdict` is the verdict and you do not reopen it. `measures` names the only "
        "measures you may name anywhere in the paragraph, worst first, and `about` is "
        "what the second sentence makes of them: put both in your own words and not in "
        "these. **An empty `measures` is no measure to name and no second sentence at "
        "all** — write the first sentence and the third, and leave the missing one "
        "unmentioned. `how_they_read` is how each of those measures reads, so that your "
        "paragraph does not contradict the section it opens — **say each one as its reading says "
        "it and no further**: the reading has already chosen how strongly it puts "
        "itself. The reader is looking at a "
        "card about a body, not a report on how it was assembled: **no field is named in "
        "no sentence of it is about the card**. "
        "`what_yesterday_cost` is what the day before took out of you: **it is "
        "not part of the verdict and it never softens it** — a day that cost a lot is a "
        "fact about the training, and what matters is whether the morning came back "
        "anyway. Say it as the one thing worth knowing alongside the verdict, and never "
        "as the reason for it. **Never name a field and never say what a sentence of "
        "yours is doing**: you are writing to the person whose body it is, not a report "
        "on how it was assembled. "
        "Answer with the paragraph and nothing else: no number in it, no band in it, "
        "no heading, no list, no quotes around it."
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
# nella cartella si leggerebbero come sei sezioni nuove.
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

# I sei file della Recovery spezzata, nella loro cartella come quelli delle
# altre due: il quinto, le quattro misure, e `_measure.md` che quelle quattro
# si dividono.
RECOVERY_SPLIT_DIR = "03_recovery_split"


def _recovery_measure(key: str, label: str, **extra) -> Part:
    """Una delle quattro misure della Recovery. Il file si chiama come la
    chiave e le regole condivise vengono dopo, dal piu' stretto al piu' largo;
    il ritaglio e la domanda sono quelli delle misure della Health, che e' la
    stessa domanda, e chi ne vuole di suoi li passa in `extra`."""
    return Part(
        key=key,
        label=label,
        agent=(f"{RECOVERY_SPLIT_DIR}/{key}.md", f"{RECOVERY_SPLIT_DIR}/_measure.md"),
        **{"cut": _measure_facts, "asks": _recovery_measure_prompt, **extra},
    )


# Le quattro misure della Recovery una per una, nell'ordine in cui la card le
# mostra — lo stesso di `RECOVERY_MEASURES`.
#
# **Tre hanno la parte cattiva in basso e la quarta non ce l'ha.** Readiness,
# notte e body battery al risveglio sono *below* tutte e tre, che e' la riga
# delle regole di casa: poco riposo, poco sonno, poca batteria. Il minimo di
# ieri no, e non e' una dimenticanza — `_readings_of` e `_measure_facts`
# dicono perche', ed e' la riga in grassetto di `.claude/agents/03_recovery.md`: un minimo
# piu' basso del solito e' quanto e' costata la giornata, non un difetto del
# recupero.
#
# **E i due body battery sono due pezzi, che e' mezzo motivo per spezzare.**
# Sono lo stesso numero a due ore diverse e il prompt intero deve chiedere di
# non confonderli; la prima sera llama li ha impastati in una frase. Due
# modelli che l'uno dell'altro non sanno niente non possono farlo.
RECOVERY_PARTS = (
    _recovery_measure("readiness", "readiness", bad_when="below"),
    _recovery_measure(
        "sleep_hours",
        "last night's sleep",
        bad_when="below",
        cut=_sleep_facts,
        asks=_sleep_prompt,
        alert="short_sleep",
    ),
    _recovery_measure(
        "body_battery_morning", "body battery at wake-up", bad_when="below"
    ),
    # Senza `bad_when`: `_measure_facts` non gli mette `reading`, e il suo
    # messaggio non lo nomina.
    _recovery_measure(
        "body_battery_low_yesterday", "yesterday's body battery low", asks=_cost_prompt
    ),
)

RECOVERY_SPLIT = Split(
    key="recovery_split",
    title="Recovery",
    facts=recovery_facts,
    opening=Part(
        key="verdict",
        label="the opening",
        agent=(f"{RECOVERY_SPLIT_DIR}/_verdict.md",),
        cut=_recovery_opening_facts,
        asks=_recovery_opening_prompt,
    ),
    parts=RECOVERY_PARTS,
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

# **La Fitness spezzata.** La quarta, e quella con i pezzi piu' diversi fra
# loro: tre punteggi con la loro fascia, una soglia che fascia non ha, e due
# acclimatamenti che per quasi tutto l'anno sono zero. I tre punteggi usano la
# macchina delle misure delle altre due sezioni — stesso ritaglio, stessa
# cornice del messaggio — e gli altri tre pezzi hanno il loro.
#
# **E qui il paragrafo che non c'e' e' la regola, non l'eccezione.** Gli
# acclimatamenti a zero sono il caso normale, e il prompt intero quel buco lo
# deve chiedere a parole — *"nominane uno solo quando non e' zero, e 'non sei
# acclimatato a nessuna quota' non vale una parola"*. Qui quei due pezzi non si
# chiedono: cinque paragrafi d'inverno, sei o sette nelle settimane in
# montagna, e nessuna riga di prompt che possa sbagliarlo.

# **La persona e il consiglio, per i pezzi della Fitness.** La stessa coda
# della Recovery e per lo stesso motivo: la prima sera il paragrafo della
# soglia ha chiuso con *"should be considered in training decisions"*, che e'
# un consiglio, e i punteggi scivolavano nel *we*.
FITNESS_TAIL = (
    "**The reader is spoken to as *you***, in every sentence: *your* scores, *your* "
    "shape, what *you* can do today. And say nothing about what to train: that is "
    "nobody's business on this card. "
)

# Le righe che dicono a un punteggio come si leggono i suoi campi.
#
# **Della direzione non dicono niente, e non e' una dimenticanza.** La prima
# versione la spiegava — *sopra la fascia e' la parte buona, cioe' al suo
# massimo del mese* — e il paragrafo del VO2max ha scritto *"since above its
# band is the good side - it's at its best in a month"*: la mia spiegazione
# ricopiata di peso, dentro una card. E' la terza volta in questo file
# (`RECOVERY_TAIL`, `COST_READS`), e la regola che ne viene e' sempre la
# stessa: **una motivazione in un prompt e' un esempio.** La direzione del
# resto `reading` ce l'ha gia' dentro — *better than usual* per un punteggio
# sopra la fascia — quindi spiegarla era anche inutile: il confronto l'ha
# fatto `_reading`, e a chi scrive resta da dire che notizia e'.
SCORE_READS = (
    "`where` says which side of its own band today's value falls on, and `reading` "
    "says what that means for this score — it is what decides whether your paragraph "
    "is good news or bad news, and you never work it out again from the band "
    "yourself. Say what you make of them and contradict neither. **The band is where "
    "this score has sat over the last 28 days and it moves on its own: it is not a "
    "target.** "
) + FITNESS_TAIL

# La soglia: nessuna fascia, e le due cifre che la card non mostra. Anche qui
# niente motivazioni — *everything hard is run off this number* era una frase
# mia, ed e' finita nella card parola per parola.
THRESHOLD_READS = (
    "`measure` says which of the two you have — a lactate threshold Garmin read in a "
    "session, or the watch's own estimate — and they are not the same thing. There is "
    "no band here and nothing to compare with. **`pace` and `read_on` are the two "
    "figures the card does not show that you may give.** "
) + FITNESS_TAIL

# Gli acclimatamenti: una cifra che c'e' solo quando c'e'.
ACCLIMATION_READS = (
    "`trend` is Garmin's code for which way it is going: say the meaning in plain "
    "words and never the code. You are given this paragraph only because the figure "
    "is not zero, so never a word about what it would mean if it were. "
) + FITNESS_TAIL


def _score_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio di un punteggio: la cornice delle misure, con la riga che
    dice da che parte della fascia sta la buona notizia.

    La cornice e' quella della Health e della Recovery — una misura, la sua
    fascia, il suo paragrafo — e dice "le altre tre misure della sezione non
    sono tue", che qui sono i due punteggi e la soglia."""
    return _one_measure_prompt(split, part, day, facts, SCORE_READS)


def _threshold_piece_facts(split: "Split", part: Part, facts: dict) -> dict | None:
    """Quello che tocca alla soglia: **il numero, il passo e il giorno.**

    Il ritaglio l'ha gia' fatto `_threshold_facts`, che decide anche quale
    delle due soglie sia: a questo pezzo arriva quella e nient'altro — nessun
    punteggio, nessuna fascia, che qui una fascia non c'e'.

    `None` quando Garmin non ha ne' l'una ne' l'altra: sulla card quella
    casella e' un trattino, e il paragrafo non si scrive."""
    threshold = facts.get("threshold")
    return dict(threshold) if threshold else None


def _threshold_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio della soglia: **il pezzo che vale piu' parole di tutti.**

    E' la riga di `.claude/agents/04_fitness.md`: la soglia e' la sola di queste misure che
    cambi quello che si fa in allenamento, e percio' merita piu' spazio dei
    punteggi. Nei prompt in pezzi quella frase diventa un pezzo che ha il suo
    paragrafo e non deve dividerlo con nessuno."""
    return (
        f"Write the paragraph about {part.label} for the {split.title} section of the "
        f"daily report for {day:%A %-d %B %Y}. "
        "The facts are here, below, and they are all there is: the scores of the "
        "section are not yours and are not in them.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        f"{THRESHOLD_READS}"
        "Two or three sentences, where a score gets one. "
        "Answer with the one paragraph and nothing else: no heading, no preamble, "
        "no sign-off, no quotes around it."
    )


def _altitude_facts(split: "Split", part: Part, facts: dict) -> dict | None:
    """Quello che tocca alla quota: **i metri, e solo quando non sono zero.**

    Zero e' il valore di casa, e per quasi tutto l'anno e' quello: *"non sei
    acclimatato a nessuna quota" non vale una parola*, dice il prompt intero,
    e li' quella e' una riga da ricordarsi. Qui e' un pezzo che non si chiede,
    quindi il paragrafo non c'e' — e non c'e' nemmeno il modo di scriverlo."""
    altitude = facts.get("altitude_acclimation") or {}
    metres = altitude.get("metres")
    if not metres:
        return None
    return {"measure": part.label, "metres": metres, "trend": altitude.get("trend")}


def _heat_facts(split: "Split", part: Part, facts: dict) -> dict | None:
    """Quello che tocca al caldo: **la percentuale, e solo quando non e'
    zero.** Stessa ragione della quota."""
    heat = facts.get("heat_acclimation") or {}
    percent = heat.get("percent")
    if not percent:
        return None
    return {"measure": part.label, "percent": percent, "trend": heat.get("trend")}


def _acclimation_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio di un acclimatamento: una o due clausole, su una cosa che
    oggi c'e'."""
    return (
        f"Write the paragraph about {part.label} for the {split.title} section of the "
        f"daily report for {day:%A %-d %B %Y}. "
        "The facts are here, below, and they are all there is: the scores, the "
        "threshold and the other acclimatisation are not yours and are not in them."
        "\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        f"{ACCLIMATION_READS}"
        "One sentence, two at the most. "
        "Answer with the one paragraph and nothing else: no heading, no preamble, "
        "no sign-off, no quotes around it."
    )


# Come si legge il verdetto della Fitness. **Sono le tre frasi che
# `.claude/agents/04_fitness.md` da' come esempi di prendere posizione**, e per la ragione di
# `VERDICT_WORDS`: un valore che in inglese sta in piedi da solo, ricopiato di
# peso, resta una frase e non l'etichetta di un campo.
FITNESS_VERDICT_WORDS = {
    "strong": "this is a strong engine right now",
    "steady": "you are where you were",
    "slipping": "the shape is slipping",
}


def _fitness_verdict(readings: "list[str]") -> str:
    """In che forma e' il corpo, da come stanno i tre punteggi.

    **Qui il conto non e' quante vanno male ma da che parte penda la
    bilancia**, e la differenza con la Health e con la Recovery e' il senso
    delle misure. Una frequenza a riposo sopra la sua fascia e' una cattiva
    notizia e una dentro non e' una notizia: si contano le cattive, e il
    meglio che una mattina possa fare e' non averne. Un punteggio sopra la sua
    fascia invece e' una **buona notizia vera** — e' al suo massimo del mese —
    e un verdetto che la ignorasse direbbe *sei dove eri* di una giornata in
    cui il motore e' il piu' forte da settimane.

    Quindi si pesano le due parti: piu' punteggi che salgono che non ne
    scendono fa *strong*, il contrario fa *slipping*, e la parita' — tutti
    dentro la fascia, o uno su e uno giu' — fa *steady*, che e' la verita' di
    quel giorno e non un modo di non prendere posizione.

    Tre gradini su tre punteggi, come alla Recovery e per lo stesso motivo:
    una scala piu' fine avrebbe gradini che nessuna combinazione raggiunge."""
    up = readings.count("better than usual") + readings.count("much better than usual")
    down = readings.count("worse than usual") + readings.count("much worse than usual")
    if down > up:
        return "slipping"
    if up > down:
        return "strong"
    return "steady"


def _fitness_opening_facts(split: "Split", part: Part, facts: dict) -> dict:
    """Quello che tocca al quinto della Fitness: **come stanno i tre punteggi,
    e nient'altro.**

    Gli stessi attrezzi dei paragrafi di apertura delle altre due sezioni, e
    per le stesse ragioni, che in `_health_opening_facts` sono scritte per
    intero: il verdetto gia' deciso, le sole misure che puo' nominare e come
    si leggono — non i valori e non le fasce, che sono il mestiere dei
    paragrafi sotto.

    **La soglia e gli acclimatamenti non ci sono**, e non per dimenticanza.
    Una fascia non ce l'hanno, quindi una direzione non ce l'hanno
    (`_readings_of` filtra su `bad_when`), e il verdetto e' una frase su che
    forma ha il motore: un numero di soglia non la sposta, e una quota a cui
    il corpo si trova non e' una capacita'. I loro paragrafi se li scrivono
    da se', sotto."""
    seen = _readings_of(split, facts)
    rests_on, leaning, good_news = _carried_by(seen)
    return {
        "verdict": FITNESS_VERDICT_WORDS[_fitness_verdict([m["reading"] for m in seen])],
        "about": _rests_on(rests_on, leaning, good_news),
        "how_they_read": _spoken_of(seen, rests_on, leaning, good_news),
    }


def _fitness_opening_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio del quinto della Fitness. Il recinto e il perche' stanno in
    `_fitness_opening_facts`."""
    return (
        f"Write the opening paragraph of the {split.title} section of the daily report "
        f"for {day:%A %-d %B %Y}. "
        "It goes at the top of the section, above the paragraphs that are already "
        "written — one for each score, one for the threshold, and one for each "
        "acclimatisation that is not zero — and it answers one question: what shape is "
        "this body in?\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "`verdict` is the verdict and you do not reopen it. `how_they_read` names the "
        "only measures you may name anywhere in the paragraph, worst first, and says "
        "which way each of them points — it is the same truth the paragraphs below "
        "were written from, so that yours does not contradict them, and **at the "
        "strength they use**: no reading is put more strongly than it puts itself. "
        "The second "
        "sentence names them and says what they come to, and the third says what that "
        "shape lets you do; **an empty list is no measure to name and no second "
        "sentence at all**, so write the first and the third. **Name a score in the "
        "second sentence only**, and never say twice how one reads. **This is about "
        "today and not about the month**, and it is not about a morning either: these "
        "scores are months of work, so no story of the last four weeks and no *this "
        "morning*. You are writing to the person whose body it is, about what that body "
        "can do, not a report on how it was assembled: **no field is named in "
        "it, and no sentence of it is "
        "about the card**. Write it to the person whose body it is. "
        "Answer with the paragraph and nothing else: no number in it, no band in it, "
        "no heading, no list, no quotes around it."
    )


# I nove file della Fitness spezzata, nella loro cartella come quelli delle
# altre tre.
FITNESS_SPLIT_DIR = "04_fitness_split"

# I pezzi sotto l'apertura, nell'ordine in cui la card li legge: i tre
# punteggi come li disegna (`FITNESS_SCORES`), poi la soglia, poi i due
# acclimatamenti.
#
# **`bad_when` ce l'hanno solo i tre punteggi**, ed e' `below` per tutti e tre:
# e' l'eccezione delle regole di casa, dove sopra la fascia e' la buona
# notizia. La soglia e gli acclimatamenti non ce l'hanno — una fascia non ce
# l'hanno — quindi `_measure_facts` non li riguarda e il verdetto non li
# conta.
FITNESS_PARTS = (
    Part(
        key="vo2max",
        label=FITNESS_LABELS["vo2max"],
        agent=(f"{FITNESS_SPLIT_DIR}/vo2max.md", f"{FITNESS_SPLIT_DIR}/_score.md"),
        cut=_measure_facts,
        asks=_score_prompt,
        bad_when="below",
    ),
    Part(
        key="endurance",
        label=FITNESS_LABELS["endurance"],
        agent=(f"{FITNESS_SPLIT_DIR}/endurance.md", f"{FITNESS_SPLIT_DIR}/_score.md"),
        cut=_measure_facts,
        asks=_score_prompt,
        bad_when="below",
    ),
    Part(
        key="hill",
        label=FITNESS_LABELS["hill"],
        agent=(f"{FITNESS_SPLIT_DIR}/hill.md", f"{FITNESS_SPLIT_DIR}/_score.md"),
        cut=_measure_facts,
        asks=_score_prompt,
        bad_when="below",
    ),
    Part(
        key="threshold",
        label="the threshold",
        agent=(f"{FITNESS_SPLIT_DIR}/_threshold.md",),
        cut=_threshold_piece_facts,
        asks=_threshold_prompt,
    ),
    Part(
        key="altitude_acclimation",
        label="the altitude acclimatisation",
        agent=(f"{FITNESS_SPLIT_DIR}/_altitude.md",),
        cut=_altitude_facts,
        asks=_acclimation_prompt,
    ),
    Part(
        key="heat_acclimation",
        label="the heat acclimatisation",
        agent=(f"{FITNESS_SPLIT_DIR}/_heat.md",),
        cut=_heat_facts,
        asks=_acclimation_prompt,
    ),
)

FITNESS_SPLIT = Split(
    key="fitness_split",
    title="Fitness",
    facts=fitness_facts,
    opening=Part(
        key="verdict",
        label="the opening",
        agent=(f"{FITNESS_SPLIT_DIR}/_verdict.md",),
        cut=_fitness_opening_facts,
        asks=_fitness_opening_prompt,
    ),
    parts=FITNESS_PARTS,
    # I punteggi stanno sotto `scores` e non sotto `morning`: non sono numeri
    # di stamattina, sono di mesi.
    measures_in="scores",
)


# ===========================================================================
# **La settimana spezzata** (todo 101)
# ===========================================================================
#
# Le quattro card del corpo della Week negli stessi pezzi di quelle del
# giorno: un paragrafo per misura, uno in cima, e la cucitura di
# `_split_text` che di che sezione abbia in mano non guarda niente.
#
# **Quello che si riusa e' quasi tutto.** `Part`, `Split`, `_split_text`,
# `_where`, `_sits`, `_reading`, `_measure_facts` e l'apertura generica di
# `_health_opening_facts` non sanno niente ne' di giorno ne' di settimana:
# leggono `split.measures_in` e i `bad_when` dei pezzi. La Fitness riusa
# perfino il ritaglio intero, che il blocco `fitness` dei fatti della
# settimana ha la stessa forma di quello del giorno, campo per campo.
#
# **Quello che cambia sta in tre punti**, e sono i tre che i file dei prompt
# devono dire a parole — per questo sono scritti e non tradotti:
#
# - un valore e' la **media dei sette giorni**, non la lettura di una
#   mattina;
# - una fascia e' di **dodici settimane**, non di ventotto giorni, e `weeks`
#   dice quante erano misurate;
# - la settimana non ha ne' `alerts` ne' `missing` come li ha il giorno: ha
#   `coverage`, che dice **quante mattine stanno sotto ogni media**, e una
#   media sottile va detta sottile invece di spacciarla per una settimana.

# I tre tempi per zona, nell'ordine della card. Sono la risposta settimanale
# alla composizione del carico (todo 54, secondo tempo): i tre carichi del
# giorno — `load_aerobic_low` e compagni — sono finestre di **ventotto
# giorni**, e nella settimana non entrano per richiesta del 23 ottobre 2026.
# I giorni di una settimana. Serve a decidere se una media e' sottile: sette
# su sette non lo e', e un campo che dice "sette" lo faceva scrivere.
WEEK_DAYS = 7

WEEK_ZONES = ("low_aerobic", "high_aerobic", "anaerobic")


def _week_ends(facts: dict) -> str:
    """La settimana come la nomina chi scrive: i suoi due estremi.

    `sections.Report.period` fa la stessa cosa per il prompt dell'agente di
    Claude, e non si importa da la': `ollama` lo carica anche il CLI del
    backfill, e tirarsi dietro il registro delle sezioni per una riga di
    testo no."""
    week = facts.get("week") or {}
    start, end = week.get("start"), week.get("end")
    if not start or not end:
        return "the week"
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return f"the week from Monday {first:%-d %B} to Sunday {last:%-d %B %Y}"


def _week_span(payload: dict) -> dict:
    """I due estremi della settimana, piu' `partial` se e' in corso.

    Compatto di proposito: nei fatti la settimana ha anche `last_day`, che su
    una settimana finita ripete `end`. Ogni campo in piu' nel JSON di un
    modello da otto miliardi e' una cosa in piu' che puo' ricopiare, e questo
    non gli serviva."""
    week = payload.get("week") or {}
    span = {"start": week.get("start"), "end": week.get("end")}
    if week.get("partial"):
        span["partial"] = True
        span["last_day"] = week.get("last_day")
    return span


def _week_measures(payload: dict, card: str) -> dict:
    """Le misure della settimana di una card, con `where` attaccato.

    Il recinto si **ricava da `card`** invece di elencare le chiavi: la lista
    esiste gia' in `weekly_data.WEEK_MEASURES`, che e' anche quella che
    disegna le barre della pagina, e una seconda copia qui sarebbero due
    recinti da tenere d'accordo a mano. E' la lezione di `RECOVERY_MEASURES`
    del giorno, che quella lista ce l'ha."""
    measures = payload.get("measures") or {}
    return {
        key: {**measure, "where": _where(measure)}
        for key, measure in measures.items()
        if measure.get("card") == card
    }


def _week_body_facts(payload: dict, card: str) -> dict:
    """I fatti di una delle due sezioni della settimana che sono fatte di
    medie: Health e Recovery. Le altre due hanno il loro, che i loro numeri
    non stanno sotto `measures`.

    `missing` resta col nome del giorno perche' `_measure_facts` lo legge con
    quel nome e `_style.md` ci conta: una misura elencata li' non si commenta
    come se ci fosse. `alerts` e' vuota e non assente, per la stessa ragione —
    e la settimana di allarmi non ne ha.

    `days` e' `coverage`, cioe' quante delle sette mattine stanno sotto ogni
    media. Non ce l'hanno tutte: `coverage` conta le metriche che Garmin non
    calcola senza orologio al polso, e per le altre il campo semplicemente
    non c'e' — un buco e' una domanda, e a una domanda il modello risponde da
    se'."""
    measures = _week_measures(payload, card)
    coverage = payload.get("coverage") or {}
    return {
        "week": _week_span(payload),
        "measures": measures,
        "days": {key: coverage[key] for key in measures if key in coverage},
        "health_days": payload.get("health_days"),
        "alerts": [],
        "missing": [key for key, m in measures.items() if m.get("value") is None],
    }


def week_health_facts(payload: dict, week: dict | None = None) -> dict:
    """La parte della Health dei fatti della settimana: le quattro medie con
    le loro fasce di dodici settimane.

    Il piano della settimana non le serve e lo ignora, come nel giorno: se il
    corpo ha tenuto per sette giorni non dipende da che cosa c'era scritto sul
    foglio."""
    return _week_body_facts(payload, "health")


def week_recovery_facts(payload: dict, week: dict | None = None) -> dict:
    """La parte della Recovery dei fatti della settimana: le quattro medie del
    recupero.

    **La batteria al risveglio e' `body_battery_wake`** e non il massimo del
    giorno: dal todo 100 la colonna giusta e' quella, e la riga della Week che
    la nomina «Body battery, wake-up» adesso la legge davvero."""
    return _week_body_facts(payload, "recovery")


def week_load_facts(payload: dict, week: dict | None = None) -> dict:
    """La parte della Load dei fatti della settimana: **i tre tempi per zona**,
    il carico acuto contro la sua fascia, e le due frasi di Garmin.

    I tempi arrivano normalizzati come i punteggi della Fitness: nei fatti si
    chiamano `minutes` e `_where` legge `value`, quindi si rinomina qui e
    tutta la macchina delle misure funziona. Che siano minuti e non carico lo
    dicono i file dei tre pezzi, ed e' la cosa su cui un paragrafo puo'
    mentire senza sbagliare un numero.

    Il carico acuto resta: letto alla domenica e' la somma di lunedi-domenica,
    cioe' esattamente la settimana, e questo e' il punto che il todo 54 ha
    salvato.

    Le due frasi — lo stato di allenamento e l'equilibrio — sono **giudizi di
    Garmin e non misure**, e per questo stanno in `state` e non fra le
    misure: non hanno fascia, e un paragrafo che le confrontasse con qualcosa
    confronterebbe due parole."""
    zones = payload.get("zones") or {}
    load = payload.get("load") or {}
    measures: dict = {}
    for key in WEEK_ZONES:
        zone = zones.get(key) or {}
        if zone.get("minutes") is None:
            continue
        measure = {
            "value": zone["minutes"],
            "band": zone.get("band"),
            "weeks": zone.get("weeks"),
        }
        measures[key] = {**measure, "where": _where(measure)}
    if load.get("load_acute") is not None:
        measure = {
            "value": load["load_acute"],
            "band": load.get("band"),
            "weeks": load.get("weeks"),
        }
        measures["carrying"] = {**measure, "where": _where(measure)}
    return {
        "week": _week_span(payload),
        "measures": measures,
        "state": {
            "training_status": load.get("training_status_phrase"),
            "balance": load.get("load_balance_phrase"),
        },
        "measured_min": zones.get("measured_min"),
        "sessions_without_hr": zones.get("sessions_without_hr"),
        "alerts": [],
        "missing": [],
    }


def week_fitness_facts(payload: dict, week: dict | None = None) -> dict:
    """La parte della Fitness dei fatti della settimana.

    **E' `fitness_facts` con la settimana al posto del giorno**, e non e' una
    scorciatoia: il blocco `fitness` dei fatti della settimana ha la stessa
    forma di quello del giorno — `now`, `band`, `change`, `days_ago_28`, i due
    acclimatamenti, la soglia — campo per campo. Riscrivere il ritaglio
    vorrebbe dire due funzioni identiche che divergono da sole.

    Quello che cambia e' che la forma di fine settimana e' **lo stato di quel
    momento** e non una media: i punteggi sono il frutto di mesi, e la
    domenica sera dicono dove si e' arrivati. Lo dicono i file dei pezzi."""
    facts = fitness_facts(payload, week)
    facts.pop("day", None)
    return {"week": _week_span(payload), **facts}


def _week_measure_facts(split: "Split", part: Part, facts: dict) -> dict:
    """Quello che tocca a una misura della settimana: la sua misura, e quante
    delle sette mattine ci stanno sotto.

    Il cuore e' `_measure_facts`, che di giorno o di settimana non sa niente.
    Qui si cambiano tre cose e si dice perche':

    - **via `day`, dentro `week`**: un campo che si chiama giorno in una
      sezione che parla di sette e' il genere di parola che un modello
      piccolo ricopia — ed e' quello che e' successo al sonno il 23 novembre
      2026, con un esempio invece di un campo;
    - **via `alert`**: la settimana non ne ha, e un campo sempre nullo e' una
      domanda in mano a chi scrive;
    - **dentro `days_measured` e `weeks`**: quante mattine sotto la media, e
      quante settimane sotto la fascia. Sono le due sottigliezze che la
      settimana ha e il giorno no.
    """
    base = _measure_facts(split, part, facts)
    base.pop("day", None)
    base.pop("alert", None)
    measure = (facts.get(split.measures_in) or {}).get(part.key) or {}
    days = (facts.get("days") or {}).get(part.key)
    return {
        "week": facts.get("week"),
        **base,
        # **I due campi ci sono solo quando c'e' qualcosa da dirne**, e questa
        # e' la regola di `fitness_facts` imparata un'altra volta: darglieli e
        # poi chiedergli di non guardarli e' il modo piu' sicuro di vederli
        # comparire. Col `days_measured` a sette, llama ha scritto *"this is a
        # thin average built on 7 days"* — sette su sette, cioe' la settimana
        # intera chiamata sottile — e *"built on seven full days of data"*,
        # che e' una frase sul funzionamento della card. A fascia piena
        # scriveva *"with twelve weeks of data to compare against"*.
        #
        # Adesso un campo presente **e'** la cosa da dire: `days_measured` c'e'
        # solo se le mattine sono meno delle sette, e `weeks` solo se la
        # fascia non si e' potuta fare.
        **({"days_measured": days} if days is not None and days < WEEK_DAYS else {}),
        **(
            {"weeks": measure.get("weeks")}
            if measure.get("band") is None and measure.get("weeks") is not None
            else {}
        ),
    }


# Come si legge una misura della settimana. Le righe che il giorno non ha — la
# media dei sette giorni, le mattine che ci stanno sotto — e che sono la
# ragione per cui questi prompt sono scritti e non tradotti.
#
# **La finestra della fascia non si nomina**, ne' qui ne' nelle altre righe
# condivise: al modello non serve sapere di quante settimane e' fatta per dire
# da che parte sta il valore, e nominandola ha scritto *"the band itself is
# based on the past twelve weeks"*, che e' una frase sul funzionamento della
# card. Il giorno fa lo stesso — `MEASURE_READS` la finestra non la dice — e i
# ventotto giorni stanno nel file del punteggio, dove sono una frase da
# allenatore.
WEEK_MEASURE_READS = (
    "`where` says where the week's figure falls against its band, and `reading` says "
    "what that means for this measure: say what you make of them, and never contradict "
    "them. **`value` is the average of the seven days, and `band` is where this measure "
    "has sat in the weeks before** — so a figure here is a week's figure, and a "
    "comparison is with other weeks and never with a single morning. `days_measured`, "
    "when it is there, is how few of the seven mornings the average is built on: say so, "
    "a thin average is not a week. **Never a word about how the band was built** — how "
    "many weeks it holds is not the reader's business. **Not the story day by day** — "
    "which morning was the high one belongs to the Day page, and yours is the seven days as "
    "one thing. "
    "**`week` is there so that you know which week you are writing about, and its dates are never written**: the card is headed by the week already, and a date in the paragraph is a figure spent on nothing. "
)

# I tre tempi per zona: come sopra, piu' la riga dell'unita'. **E' minuti,
# non carico**, ed e' la cosa su cui questo paragrafo puo' mentire senza
# sbagliare un numero — il carico di Garmin e' un'altra misura, sta nel
# pezzo del carico acuto, e nella settimana e' l'unica che ci sia.
WEEK_ZONE_READS = (
    "`where` says where this week's minutes fall against their band, and `reading` what "
    "that means: say what you make of them and contradict neither. **The figure is "
    "minutes spent in the zone this week**, and the band is the same count in the weeks "
    "before — not a training load, not a score, and never called one. **Never a word "
    "about how the band was built.** `weeks`, when it is there, is how few weeks there "
    "were; too few and the comparison is left alone. **No story day by day**, and "
    "nothing about what to train: the week as one thing, and stop. "
    "**`week` is there so that you know which week you are writing about, and its dates are never written**: the card is headed by the week already, and a date in the paragraph is a figure spent on nothing. "
)


def _week_measure_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio di una misura della settimana: la cornice, piu' le righe
    che dicono che si legge una media e non una mattina."""
    return _one_week_measure_prompt(split, part, day, facts, WEEK_MEASURE_READS)


def _week_recovery_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Come sopra, piu' la coda della persona: alla Recovery serve anche nella
    settimana, e per la ragione per cui serve nel giorno — readiness e sonno
    sono cose che uno *ha*, e in bocca vengono *mie*."""
    return _one_week_measure_prompt(
        split, part, day, facts, WEEK_MEASURE_READS + RECOVERY_TAIL
    )


def _week_zone_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    return _one_week_measure_prompt(split, part, day, facts, WEEK_ZONE_READS)


# Il carico acuto: come le zone, **meno la riga dei minuti**. Con quella —
# "the figure is minutes spent in the zone this week" — llama ha scritto
# *"this week's load was 374 minutes"*, e il file del pezzo che diceva il
# contrario non e' bastato: la riga della cornice vince, perche' arriva col
# messaggio e non col prompt di sistema.
WEEK_LOAD_READS = (
    "`where` says where this week's load falls against its band: say what you make of "
    "it, and do not contradict it. **The figure is a training load, a plain number of "
    "Garmin's own — never minutes, never hours, never a time, and never a zone.** "
    "`weeks`, when it is there, is how few weeks the band could be built from; with no "
    "band, give the figure and leave the comparison alone. **No story day by day**, and "
    "nothing about what to train: the week as one thing, and stop. "
    "**`week` is there so that you know which week you are writing about, and its dates are never written**: the card is headed by the week already, and a date in the paragraph is a figure spent on nothing. "
)


def _week_carrying_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    return _one_week_measure_prompt(split, part, day, facts, WEEK_LOAD_READS)


# I punteggi della Fitness **non sono medie**, e questa e' la differenza che
# vale piu' di tutte in questo file: VO2max, endurance e hill sono il frutto
# di mesi, e la domenica sera dicono dove la settimana ti ha lasciato. Dare
# loro le righe di `WEEK_MEASURE_READS` — "il valore e' la media dei sette
# giorni" — sarebbe scrivere una cosa falsa nel prompt, cioe' il modo piu'
# sicuro di vederla comparire nella card.
WEEK_SCORE_READS = (
    "`where` says which side of its own band the score ended the week on, and `reading` "
    "says what that means for this score — it is what decides whether your paragraph is "
    "good news or bad news, and you never work it out again from the band yourself. Say "
    "what you make of them and contradict neither. **The band moves on its own and is "
    "not a target**, and **never a word about how it was built.** **This is where the "
    "score stood at the end of the week and not an average of the seven days**: these "
    "scores are the work of months, and on Sunday evening they say where the week has "
    "left the body. "
    "**`week` is there so that you know which week you are writing about, and its dates are never written**: the card is headed by the week already, and a date in the paragraph is a figure spent on nothing. "
) + FITNESS_TAIL


def _week_score_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    return _one_week_measure_prompt(split, part, day, facts, WEEK_SCORE_READS)


def _week_threshold_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio della soglia della settimana. Vale piu' parole degli altri
    per la ragione del giorno: e' la sola di queste misure che cambi quello
    che si fa in allenamento."""
    return (
        f"Write the paragraph about {part.label} for the {split.title} section of the "
        f"weekly report for {_week_ends(facts)}. "
        "The facts are here, below, and they are all there is: the scores of the "
        "section are not yours and are not in them.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        f"{THRESHOLD_READS}"
        "Answer with the one paragraph and nothing else: no heading, no preamble, "
        "no sign-off, no quotes around it."
    )


def _week_acclimation_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    return (
        f"Write the paragraph about {part.label} for the {split.title} section of the "
        f"weekly report for {_week_ends(facts)}. "
        "The facts are here, below, and they are all there is: the scores, the "
        "threshold and the other acclimatisation are not yours and are not in them."
        "\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        f"{ACCLIMATION_READS}"
        "One sentence, two at the most. "
        "Answer with the one paragraph and nothing else: no heading, no preamble, "
        "no sign-off, no quotes around it."
    )


def _w_score(key: str, label: str, **extra) -> Part:
    """Un punteggio della Fitness della settimana: il file condiviso e'
    `_score.md` e non `_measure.md`, come nel giorno — un punteggio si legge
    al contrario di una misura del corpo, e quella riga sta li'."""
    return Part(
        key=key,
        label=label,
        agent=(f"{W_FITNESS_SPLIT_DIR}/{key}.md", f"{W_FITNESS_SPLIT_DIR}/_score.md"),
        cut=_week_measure_facts,
        asks=_week_score_prompt,
        **extra,
    )


def _one_week_measure_prompt(
    split: "Split", part: Part, day: date, facts: dict, reads: str
) -> str:
    """La cornice del messaggio di un paragrafo della settimana.

    La stessa di `_one_measure_prompt` con due differenze, e sono due perche'
    quella del giorno non si tocca: **il periodo** sono i due estremi della
    settimana invece di una data, e le altre misure non si contano. Il giorno
    dice "le altre tre" perche' sono sempre tre; la settimana ne ha tre, quattro
    o cinque a seconda della sezione, e un numero sbagliato nel prompt e' un
    numero che il modello puo' ricopiare — la lezione del 23 novembre 2026,
    quando l'esempio della riga e' finito nella card al posto del dato."""
    return (
        f"Write the paragraph about {part.label} for the {split.title} section of the "
        f"weekly report for {_week_ends(facts)}. "
        "The facts are here, below, and they are all there is: the other measures of "
        "the section are not yours and are not in them.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        f"{reads}"
        "Answer with the one paragraph and nothing else: no heading, "
        "no preamble, no sign-off, no quotes around it."
    )


def _week_piece(inner):
    """Un ritaglio del giorno riusato nella settimana, col periodo attaccato.

    La soglia e i due acclimatamenti leggono il blocco `fitness`, che nella
    settimana ha la stessa forma: il ritaglio e' buono com'e'. Quello che non
    ha e' `week`, e senza quello la cornice del messaggio direbbe "the week"
    e non quale."""

    def cut(split: "Split", part: Part, facts: dict) -> dict | None:
        piece = inner(split, part, facts)
        if piece is None:
            return None
        return {"week": facts.get("week"), **piece}

    return cut


def _week_opening_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    """Il messaggio di chi apre una sezione della settimana.

    Il recinto e' quello del giorno — `_health_opening_facts`, che e'
    generico: legge `split.measures_in` e i `bad_when` dei pezzi, e di che
    periodo si tratti non sa niente. Qui cambia la domanda: sette giorni
    invece di una mattina, e la frase che chiude non e' *come stai stamattina*
    ma **come il corpo ha preso questa settimana**."""
    return (
        f"Write the opening paragraph of the {split.title} section of the weekly report "
        f"for {_week_ends(facts)}. "
        "It goes at the top of the section, above the paragraphs of the single measures, "
        "which are already written, and it says what they add up to over the seven "
        "days.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "`verdict` is the verdict and you do not reopen it. `measures` names the only "
        "measures you may name anywhere in the paragraph, worst first, and `about` is "
        "what the second sentence makes of them: put both in your own words and not in "
        "these. **An empty `measures` is no measure to name and no second sentence at "
        "all** — write the first sentence and the third, and leave the missing one "
        "unmentioned. `how_they_read` is how each of those measures reads, so that your "
        "paragraph does not contradict the section it opens: say each one as its reading "
        "says it and no further. **The subject is the week and not a morning**: how the "
        "body took these seven days, not how it is right now. No number, no band, no "
        "day of the week named, and nothing about what to train.\n\n"
        "Answer with the paragraph and nothing else: no heading, no preamble, no list, "
        "no quotes around it. Two sentences or three, and short."
    )


def _week_load_opening_facts(split: "Split", part: Part, facts: dict) -> dict | None:
    """Quello che tocca a chi apre la Load della settimana: **le due frasi di
    Garmin, e nient'altro.**

    Non si usa il recinto generico delle altre tre, e la ragione e' la stessa
    per cui il giorno non lo usa: i pezzi della Load non hanno `bad_when` —
    un tempo per zona sopra la sua fascia non e' una notizia buona ne'
    cattiva finche' non si sa che settimana era, e in una di scarico e'
    perfino il piano che funziona. Senza `bad_when` il recinto generico
    renderebbe una lista vuota, cioe' un'apertura senza niente da aprire.

    Al loro posto ci sono i due giudizi che Garmin da' sulla settimana: lo
    stato di allenamento e l'equilibrio fra facile e duro. Sono parole e non
    numeri, quindi non si contraddicono con una fascia.

    `None` quando non c'e' nessuna delle due: un'apertura senza verdetto non
    e' un'apertura, e la sezione comincia dal primo tempo per zona con un
    paragrafo in meno."""
    state = facts.get("state") or {}
    if not state.get("training_status") and not state.get("balance"):
        return None
    return {"week": facts.get("week"), "state": state}


def _week_load_opening_prompt(split: "Split", part: Part, day: date, facts: dict) -> str:
    return (
        f"Write the opening paragraph of the Load section of the weekly report for "
        f"{_week_ends(facts)}. "
        "It goes at the top, above the paragraphs about the time spent in each zone and "
        "about how much the week carried, which are already written.\n\n"
        f"{json.dumps(facts, indent=2, default=str)}\n\n"
        "`training_status` and `balance` are Garmin's two words on the week, in its own "
        "shorthand: say them the way a coach says them out loud, never read out as "
        "labels and never quoted in capitals. They are judgements and not measures, so "
        "there is no band to put them against and no figure to give. One short sentence "
        "on what the week's work amounted to, and one on what it was short of or long "
        "on, if the two words say so. **No number, no zone named, nothing about what to "
        "train next.**\n\n"
        "Answer with the paragraph and nothing else: no heading, no preamble, no quotes "
        "around it. Two sentences, and short."
    )


# --- I quattro splits della settimana --------------------------------------

W_HEALTH_SPLIT_DIR = "w1_health_split"
W_LOAD_SPLIT_DIR = "w2_load_split"
W_RECOVERY_SPLIT_DIR = "w3_recovery_split"
W_FITNESS_SPLIT_DIR = "w4_fitness_split"


def _w_measure(directory: str, asks, key: str, label: str, **extra) -> Part:
    """Una misura della settimana: il file si chiama come la chiave, e
    `_measure.md` della sua cartella viene dopo — dal piu' stretto al piu'
    largo, come nel giorno."""
    return Part(
        key=key,
        label=label,
        agent=(f"{directory}/{key}.md", f"{directory}/_measure.md"),
        cut=_week_measure_facts,
        asks=asks,
        **extra,
    )


W_HEALTH_PARTS = (
    _w_measure(W_HEALTH_SPLIT_DIR, _week_measure_prompt,
               "resting_hr", "the week's resting heart rate", bad_when="above"),
    _w_measure(W_HEALTH_SPLIT_DIR, _week_measure_prompt,
               "hrv_last_night", "the week's HRV", bad_when="below"),
    _w_measure(W_HEALTH_SPLIT_DIR, _week_measure_prompt,
               "resp_sleep_avg", "the week's breathing rate in sleep", bad_when="above"),
    _w_measure(W_HEALTH_SPLIT_DIR, _week_measure_prompt,
               "stress_avg", "the week's stress", bad_when="above"),
)

W_HEALTH_SPLIT = Split(
    key="w_health_split",
    title="Health",
    facts=week_health_facts,
    opening=Part(
        key="verdict",
        label="the opening",
        agent=(f"{W_HEALTH_SPLIT_DIR}/_verdict.md",),
        cut=_week_piece(_health_opening_facts),
        asks=_week_opening_prompt,
    ),
    parts=W_HEALTH_PARTS,
    measures_in="measures",
)

W_RECOVERY_PARTS = (
    _w_measure(W_RECOVERY_SPLIT_DIR, _week_recovery_prompt,
               "readiness", "the week's readiness", bad_when="below"),
    _w_measure(W_RECOVERY_SPLIT_DIR, _week_recovery_prompt,
               "sleep_hours", "the week's sleep", bad_when="below"),
    _w_measure(W_RECOVERY_SPLIT_DIR, _week_recovery_prompt,
               "body_battery_wake", "the week's body battery at wake-up", bad_when="below"),
    # Senza `bad_when`, come il minimo di ieri nel giorno: un minimo piu'
    # basso del solito e' quanto e' costata la settimana, non un difetto del
    # recupero, e non deve poter spostare il verdetto sul corpo.
    _w_measure(W_RECOVERY_SPLIT_DIR, _week_recovery_prompt,
               "body_battery_low", "the week's body battery low"),
)

W_RECOVERY_SPLIT = Split(
    key="w_recovery_split",
    title="Recovery",
    facts=week_recovery_facts,
    opening=Part(
        key="verdict",
        label="the opening",
        agent=(f"{W_RECOVERY_SPLIT_DIR}/_verdict.md",),
        cut=_week_piece(_health_opening_facts),
        asks=_week_opening_prompt,
    ),
    parts=W_RECOVERY_PARTS,
    measures_in="measures",
)

W_LOAD_PARTS = (
    _w_measure(W_LOAD_SPLIT_DIR, _week_zone_prompt,
               "low_aerobic", "the time spent in easy aerobic work"),
    _w_measure(W_LOAD_SPLIT_DIR, _week_zone_prompt,
               "high_aerobic", "the time spent in harder aerobic work"),
    _w_measure(W_LOAD_SPLIT_DIR, _week_zone_prompt,
               "anaerobic", "the time spent in anaerobic work"),
    # **Su un file suo e non su quello condiviso**, come nel giorno: gli
    # altri tre pezzi di questa sezione sono minuti, e il file che lo dice
    # per tre volte in mano al carico acuto ha fatto scrivere a llama *"374
    # minutes in the zone"* — il carico di Garmin chiamato tempo, e
    # attribuito a una zona che non esiste.
    Part(
        key="carrying",
        label="how much the week carried",
        agent=(f"{W_LOAD_SPLIT_DIR}/_carrying.md",),
        cut=_week_measure_facts,
        asks=_week_carrying_prompt,
    ),
)

W_LOAD_SPLIT = Split(
    key="w_load_split",
    title="Load",
    facts=week_load_facts,
    opening=Part(
        key="verdict",
        label="the opening",
        agent=(f"{W_LOAD_SPLIT_DIR}/_verdict.md",),
        cut=_week_load_opening_facts,
        asks=_week_load_opening_prompt,
    ),
    parts=W_LOAD_PARTS,
    measures_in="measures",
)

# La Fitness della settimana riusa i pezzi del giorno che non sono misure —
# la soglia e i due acclimatamenti — perche' i loro fatti sono gli stessi:
# `_threshold_facts` e i due `_..._facts` leggono il blocco `fitness`, che
# nella settimana ha la stessa forma. Cambia la cornice del messaggio, che e'
# la settimana, e cambiano i file dei prompt.
W_FITNESS_PARTS = (
    _w_score("vo2max", "the VO2max score", bad_when="below"),
    _w_score("endurance", "the endurance score", bad_when="below"),
    _w_score("hill", "the hill score", bad_when="below"),
    Part(
        key="threshold",
        label="the lactate threshold",
        agent=(f"{W_FITNESS_SPLIT_DIR}/_threshold.md",),
        cut=_week_piece(_threshold_piece_facts),
        asks=_week_threshold_prompt,
    ),
    Part(
        key="altitude_acclimation",
        label="the altitude acclimation",
        agent=(f"{W_FITNESS_SPLIT_DIR}/_altitude.md",),
        cut=_week_piece(_altitude_facts),
        asks=_week_acclimation_prompt,
    ),
    Part(
        key="heat_acclimation",
        label="the heat acclimation",
        agent=(f"{W_FITNESS_SPLIT_DIR}/_heat.md",),
        cut=_week_piece(_heat_facts),
        asks=_week_acclimation_prompt,
    ),
)

W_FITNESS_SPLIT = Split(
    key="w_fitness_split",
    title="Fitness",
    facts=week_fitness_facts,
    opening=Part(
        key="verdict",
        label="the opening",
        agent=(f"{W_FITNESS_SPLIT_DIR}/_verdict.md",),
        cut=_week_piece(_health_opening_facts),
        asks=_week_opening_prompt,
    ),
    parts=W_FITNESS_PARTS,
    measures_in="scores",
)


SECTIONS: "dict[str, Split]" = {
    section.key: section
    for section in (
        HEALTH_SPLIT,
        LOAD_SPLIT,
        RECOVERY_SPLIT,
        FITNESS_SPLIT,
        W_HEALTH_SPLIT,
        W_LOAD_SPLIT,
        W_RECOVERY_SPLIT,
        W_FITNESS_SPLIT,
    )
}
"""Le sezioni che la pagina Test sa chiedere. Le altre quattro del giorno non
ci sono: si aggiungono quando servono, una alla volta, che ognuna vuole il
suo ritaglio dei fatti e la sua prova.

**Sono tutte spezzate, e per un po' non lo erano.** Accanto a ognuna stava la
stessa sezione chiesta in un modo solo — un prompt, una domanda, un file in
`.ollama/agents/` — e le due si guardavano affiancate sulla pagina per
decidere quale delle due strade restava. La spezzata e' quella che e' restata:
e' quella che la pagina mostra, l'unica che il ciclo di taratura sappia tarare
(`bench_tune.DEFAULT_SECTIONS`), e dopo quattro giri sta a 0.092 sulla Health
e a 0.000 sulla Load contro gli 0.546 e 0.586 delle intere.

**Il confronto, pero', non e' stato vinto: e' stato chiuso.** Alla pari — il
giro `2026-11-20-1638`, prima che il ciclo tarasse qualcosa — le intere
avevano zero errori gravi contro 1 e 9, stavano piu' vicine ai testi di Claude
(0.900 contro 0.957) e ci arrivavano in 76 parole contro 153, che e' la
lunghezza di Claude e non quella della spezzata. Su `recovery` e `fitness`
l'intera non e' mai salita sul banco. Chi volesse riaprire la questione trova
le 50 righe misurate nel quaderno, sotto le chiavi `health` e `load`: sono
l'unica traccia che resta, perche' i quattro prompt non ci sono piu'."""


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
            # ricadeva sull'esempio in fondo a `.claude/agents/01_health.md` invece di
            # guardare i numeri. A zero, zero su otto, due volte (con
            # l'esempio e senza). Un verdetto sbagliato su una card non e'
            # varieta', e la stessa mattina con gli stessi numeri puo' avere
            # la stessa risposta.
            "options": {"temperature": 0, "num_ctx": CONTEXT_TOKENS},
            # **Il modello resta in memoria**, e non e' un'ottimizzazione: e'
            # l'unico modo di avere due risposte confrontabili. Ollama di suo
            # lo scarica dopo cinque minuti di quiete, e un modello ricaricato
            # non rende lo stesso testo nemmeno a temperatura zero — provato:
            # la stessa domanda prima e dopo uno scarico da' due paragrafi
            # diversi su cinque, perche' il riparto fra scheda e processore
            # cambia l'ordine delle somme e un argmax quasi in parita' si
            # ribalta. A modello caldo, tre risposte su tre identiche.
            #
            # Conta per il ciclo di taratura (`bench_tune`), che fra un giro e
            # l'altro aspetta l'editor per minuti: senza questo, una pausa
            # lunga fa scaricare il modello e la misura del giro dopo non e'
            # piu' confrontabile con quella del giro prima. Un quarto d'ora
            # copre il tempo massimo dell'editor (dieci minuti) e lascia
            # liberare i cinque giga poco dopo.
            "keep_alive": KEEP_ALIVE,
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
    section: Split,
    day: date,
    payload: dict,
    repo_root: Path,
    week: dict | None = None,
) -> tuple[str, str]:
    """Il testo di una sezione scritto dal modello locale, e il nome del
    modello che l'ha scritto. Alza `OllamaError` se la macchina non
    risponde.

    Una porta sola, che per un po' ne smistava due: finche' la pagina Test
    teneva accanto la sezione intera — un prompt, una domanda — qui c'era un
    `isinstance` e due strade. Resta la firma, che all'endpoint non e' mai
    interessato quale fosse: chiede il testo di una chiave e lo mette nella
    card."""
    return _split_text(section, day, payload, repo_root, week)


def asked(split: Split, facts: dict) -> "list[tuple[Part, dict]]":
    """I pezzi di una sezione spezzata **che si chiedono davvero**, nell'ordine
    in cui il testo finito li legge: l'apertura in cima e poi gli altri, col
    ritaglio di ognuno.

    **L'ordine e' qui e non nel prompt**, che e' il punto di tutta questa
    strada, e un pezzo il cui `cut` rende `None` non c'e': la settimana senza
    piano, il rapporto che Garmin non ha, un acclimatamento a zero.

    Sta in una funzione sua perche' la leggono in due. `_split_text` ci chiede
    le domande da fare; `bench_score` ci chiede **a quale paragrafo del testo
    finito corrisponde quale pezzo**, che e' il solo modo di controllare un
    paragrafo contro i fatti che quel paragrafo aveva in mano. Due copie di
    questa riga sarebbero due allineamenti che divergono, e il secondo
    darebbe la colpa al paragrafo sbagliato."""
    mine = [(piece, piece.cut(split, piece, facts)) for piece in (split.opening, *split.parts)]
    return [(piece, owned) for piece, owned in mine if owned is not None]


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
    asks = [
        (
            lambda piece=piece, owned=owned: _ask(
                _system_prompt(repo_root, *piece.agent),
                piece.asks(split, piece, day, owned),
            )
        )
        for piece, owned in asked(split, facts)
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
