"""Il registro del banco di prova: i testi che il modello di casa ha scritto,
accanto a quelli che l'agente di Claude ha scritto davvero.

La pagina Test fa scrivere a ollama le stesse sezioni del report e le mette
accanto a quelle di Claude, ma **il confronto si guardava a occhio e moriva col
ricarico**: niente di quello che il modello scriveva veniva salvato, quindi non
si potevano rileggere due giorni, non si potevano confrontare due modelli, e di
una taratura dei prompt non restava il «prima». Questo modulo e' il quaderno
che mancava, e `bench_tune.py` e' il ciclo che lo usa per tarare i prompt da
se'.

**Una riga per (giro, giorno, sezione)**, su un file solo. Il giorno e' quello
dei dati — non quello in cui il testo e' nato — e dentro un giro c'e'
esattamente una riga per card per giorno. Il giro e' l'asse in piu', e serve
perche' per dire che una modifica ai prompt ha migliorato le cose devono
esistere il prima e il dopo.

**Il file sta fuori da `summary/`**, e questa e' la riga che non si tocca: i
frammenti del report li scrivono gli agenti di Claude, la Day legge quelli, e
il modello di casa non deve poter mettere niente dove il report va a leggere.
`bench/` e' sorella di `summary/` e non figlia.

**L'impronta dei prompt e' quello che rende il ciclo economico.** A modello
caldo e temperatura zero, con gli stessi fatti e gli stessi prompt, ollama
rende lo stesso testo: quindi se l'impronta non e' cambiata il testo non puo'
essere cambiato, e la riga che c'e' si riusa invece di rifare la domanda.
Rigenerare tutti i giorni per tutte le sezioni sono venti minuti; rigenerare la
sola sezione il cui prompt e' stato ritoccato sono tre.

«A modello caldo» non e' un dettaglio: fra due giri distanti Ollama scarica il
modello, e un modello ricaricato non rende lo stesso testo. La storia sta in
`reusable`, ed e' il motivo per cui il riuso vale dentro un giro e non fra
giri diversi.
"""

import hashlib
import json
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

from training.api import ollama
from training.garmin.files import write_text

# La cartella del quaderno dentro il data root, e il file. Il percorso se lo
# compone chi lo usa, come fanno `_terrain_path` e `_db_path`: una costante in
# `config.py` che nessuno legge sarebbe una seconda verita' da tenere
# d'accordo con la prima.
_FOLDER = "bench"
_FILENAME = "local_text.jsonl"

# Una riscrittura per volta. Il ciclo e' un processo solo e sequenziale, ma
# l'endpoint della pagina Test chiede sei sezioni insieme e ognuna girerebbe
# in un thread del pool di Starlette: senza lucchetto due cicli
# leggi-modifica-riscrivi si perdono le righe a vicenda.
#
# E fa piu' che evitare righe perse: `write_text` usa un temporaneo dal nome
# fisso (`<file>.tmp`, non un `mkstemp` come `save_json_map`), quindi due
# scrittori insieme si pesterebbero lo stesso temporaneo e `os.replace`
# pubblicherebbe un file impastato.
#
# **Se un secondo processo comparira'** — due `make api` su due porte con due
# `ATHLOS_OLLAMA_MODEL`, che e' il solo modo di confrontare due modelli alla
# volta — qui va un `flock` come `interface.db.write_lock`. Un lucchetto di
# thread fra due processi non vede niente.
_write_lock = threading.Lock()

# Quanti caratteri dell'impronta si tengono. Dodici su un sha256 bastano per
# qualche decina di versioni di prompt, e in una riga da leggere a occhio
# sessantaquattro sarebbero rumore.
_FINGERPRINT_CHARS = 12


def _path(data_dir: Path) -> Path:
    return Path(data_dir) / _FOLDER / _FILENAME


def prompt_files(section: "ollama.Split") -> "tuple[str, ...]":
    """I file di prompt che compongono una sezione, nell'ordine in cui il
    modello li legge.

    Sono quelli di ogni pezzo, l'apertura compresa — nove o dieci, perche' le
    misure portano anche le regole condivise. `_style.md` non c'e' dentro: lo
    attacca `_system_prompt` a tutti, e `impronta` lo include passando da li'."""
    return tuple(name for piece in (section.opening, *section.parts) for name in piece.agent)


def fingerprint(repo_root: Path, section: "ollama.Split") -> str:
    """L'impronta dei prompt di una sezione: lo hash di **quello che il modello
    legge davvero**, non dei file su disco.

    Passa da `ollama._system_prompt`, quindi dentro ci sono le regole di casa e
    **non** c'e' il front matter, che quel modulo toglie prima di spedire. Una
    descrizione cambiata in testa a un file non fa rigenerare niente, ed e'
    giusto: al modello non arriva.

    **Quello che l'impronta non vede** sono i messaggi, che li compone il
    Python (`_user_prompt`, `_measure_prompt`, e gli altri). Per il ciclo va
    bene — l'editor ha il permesso di scrivere solo in `.ollama/agents/` e il
    Python non lo tocca — ma chi ritocca un messaggio a mano deve sapere che le
    righe vecchie non si marcano da se'."""
    pieces = [
        ollama._system_prompt(repo_root, *piece.agent)
        for piece in (section.opening, *section.parts)
    ]
    digest = hashlib.sha256("\n".join(pieces).encode("utf-8")).hexdigest()
    return digest[:_FINGERPRINT_CHARS]


def claude_text(summary_dir: Path, day: date, section: "ollama.Split") -> str | None:
    """Il frammento che l'agente di Claude ha scritto per quel giorno e quella
    sezione, cioe' **il bersaglio**.

    Il nome del file viene dal titolo della sezione e non dalla chiave, perche'
    `health` e `health_split` sono la stessa sezione chiesta in due modi e il
    frammento di Claude e' uno: `summary/01.daily/<giorno>/health.md`.

    `None` quando non c'e' o e' vuoto — un giorno senza report non e' un
    guasto, e` _fragment_path` in `app.py` tratta lo zero byte come assente per
    la stessa ragione."""
    path = Path(summary_dir) / "01.daily" / day.isoformat() / f"{section.title.lower()}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def load(data_dir: Path) -> "list[dict[str, Any]]":
    """Le righe del quaderno, in ordine di file.

    Tollerante come `files.read_json`, e per lo stesso motivo: un file assente
    rende la lista vuota, e una riga che non si legge si dice e si salta invece
    di fermare un ciclo che dura una notte.

    **Attenzione: la tolleranza qui cancella.** Chi scrive riscrive tutto il
    file da queste righe, quindi una riga rovinata non viene solo saltata —
    alla prossima scrittura non c'e' piu'. Per un quaderno va bene, ma e' una
    differenza da `read_json`, che e' in sola lettura."""
    path = _path(data_dir)
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"ATTENZIONE: {path}:{number} non si legge ({exc}): la salto.", flush=True)
    return rows


def _key(row: "dict[str, Any]") -> "tuple[str, int, str, str]":
    """Cosa identifica una riga: il giro, e dentro il giro una card per
    giorno."""
    return (row.get("run", ""), row.get("iteration", 0), row.get("day", ""), row.get("section", ""))


def store(data_dir: Path, rows: "list[dict[str, Any]]") -> None:
    """Mette queste righe nel quaderno: quelle con la stessa chiave le
    sostituisce, le altre le aggiunge, e riscrive il file ordinato.

    **Non e' in sola aggiunta, ed e' voluto.** Tenere una riga sola per chiave
    vuol dire rileggere, sostituire e riscrivere — che e' quello che fanno
    `save_terrain_override` e `save_run_type_override`, un lucchetto di modulo
    e la scrittura atomica di `files.write_text`. Nel progetto non esiste un
    file in sola aggiunta: si riscrive sempre tutto.

    L'ordine e' per (giro, iterazione, giorno, sezione): dentro un giro il file
    si legge come una tabella, e le due card di una sezione — intera e spezzata
    — finiscono vicine perche' le chiavi si somigliano. Non e' l'ordine della
    pagina, ed e' meglio cosi': e' quello del confronto.

    **Un errore di scrittura non alza.** Il quaderno e' una faccenda di
    contorno: se il disco e' pieno o la cartella non e' scrivibile lo si dice e
    si tira avanti, che un ciclo di una notte non deve morire per il suo
    taccuino, e la card della pagina Test deve vedersi comunque. Si prende solo
    `OSError`: un campo non serializzabile e' un bug e deve farsi sentire."""
    if not rows:
        return
    path = _path(data_dir)
    with _write_lock:
        keys = {_key(row) for row in rows}
        kept = [row for row in load(data_dir) if _key(row) not in keys]
        merged = sorted([*kept, *rows], key=_key)
        lines = [json.dumps(row, ensure_ascii=False, default=str) for row in merged]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text(path, "\n".join(lines) + "\n")
        except OSError as exc:
            print(f"ATTENZIONE: il banco non registra ({exc}): vado avanti.", flush=True)


def latest(data_dir: Path, start: date | None = None, end: date | None = None):
    """La riga piu' recente per ogni (giorno, sezione), cioe' **lo stato di
    adesso** del quaderno.

    Il file tiene la storia — un giro per ogni taratura, e dentro un giro un
    giro per ogni modifica ai prompt — ma chi guarda la pagina vuole l'ultima
    versione di ogni card, non l'archivio.

    **Il piu' recente e' quello scritto per ultimo** (`written_at`), e non
    quello col nome del giro piu' alto. Il nome e' l'ora in cui il ciclo e'
    partito e di suo si ordinerebbe da se', ma e' una stringa che chi lancia
    il ciclo decide: una volta ho scritto quattro righe a mano chiamando il
    giro `2026-11-20-leaning`, e in ordine di stringa `l` sta sopra ogni
    cifra. Quelle righe avrebbero vinto contro ogni giro successivo e la
    pagina si sarebbe fermata li' senza dirlo a nessuno. L'ora della
    scrittura, invece, non dipende da come qualcuno chiama le cose; il nome
    del giro resta a parita', che due righe scritte nello stesso secondo
    vanno comunque ordinate.

    E' la funzione che la pagina Test legge. **Niente qui genera testo**: i due
    testi — quello del modello di casa e quello di Claude — sono nella stessa
    riga da quando il ciclo l'ha scritta, e la pagina li mostra affiancati
    senza chiedere niente a nessuno."""

    def quando(row: "dict[str, Any]"):
        return (row.get("written_at", ""), row.get("run", ""), row.get("iteration", 0))

    newest: "dict[tuple[str, str], dict[str, Any]]" = {}
    for row in load(data_dir):
        day = row.get("day", "")
        if (start and day < start.isoformat()) or (end and day > end.isoformat()):
            continue
        key = (day, row.get("section", ""))
        seen = newest.get(key)
        if seen is None or quando(row) >= quando(seen):
            newest[key] = row
    return [newest[key] for key in sorted(newest)]


def reusable(
    known: "list[dict[str, Any]]", day: date, section_key: str, prompts: str, model: str
) -> "dict[str, Any] | None":
    """Una riga gia' scritta che vale ancora: stesso giorno, stessa sezione,
    stessa impronta dei prompt, stesso modello.

    **E' la riga che rende un giro tre minuti invece di venti.** A modello
    caldo e temperatura zero gli stessi prompt sui fatti dello stesso giorno
    rendono lo stesso testo, quindi rifare la domanda non puo' dare niente di
    nuovo: un giro che ha ritoccato il prompt di una sezione sola non ha motivo
    di rigenerare le altre tre.

    **«A modello caldo» e' la clausola che conta, e l'ho imparata sbagliando.**
    Avevo scritto che a temperatura zero il testo e' sempre lo stesso, e non e'
    vero: due giri a cinquanta minuti di distanza avevano 75 testi su 100
    diversi, con la stessa impronta e lo stesso modello. In mezzo Ollama aveva
    scaricato il modello e ricaricato, e un modello ricaricato non rende lo
    stesso testo. Dentro un giro invece tre risposte su tre sono identiche, e
    `ollama.KEEP_ALIVE` lo tiene in memoria anche durante le pause dell'editor.

    Per questo **chi chiama deve passare solo le righe del suo giro**: una riga
    di un giro di ieri l'ha scritta un'altra istanza del modello, e riusarla
    vuol dire mescolare due regimi numerici e misurare una differenza che non
    viene dai prompt."""
    for row in reversed(known):
        if (
            row.get("day") == day.isoformat()
            and row.get("section") == section_key
            and row.get("prompts") == prompts
            and row.get("model") == model
            and row.get("ollama")
        ):
            return row
    return None


def row(
    *,
    run: str,
    iteration: int,
    day: date,
    section_key: str,
    model: str,
    prompts: str,
    seconds: float,
    ollama_text: str,
    claude: str | None,
    held_out: bool,
) -> "dict[str, Any]":
    """Una riga del quaderno, coi due testi affiancati.

    I due testi stanno nella stessa riga — e quello di Claude si ripete in ogni
    giro — perche' una riga che si legge da sola e' quello che conta in un
    registro di esperimenti: sessanta kilobyte per giro non sono un problema,
    una riga che per capirsi ha bisogno di un'altra riga lo e'.

    `written_at` va memorizzato e non derivato dall'`mtime` come altrove nel
    progetto: qui si riscrive tutto il file, quindi la data del file dice
    «l'ultima scrittura di qualunque riga» e non serve a niente. Formato di
    casa: ora locale, `isoformat(sep=" ")`."""
    return {
        "run": run,
        "iteration": iteration,
        "day": day.isoformat(),
        "section": section_key,
        "model": model,
        "prompts": prompts,
        "seconds": seconds,
        "held_out": held_out,
        "written_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "ollama": ollama_text,
        "claude": claude,
    }
