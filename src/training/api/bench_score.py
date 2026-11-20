"""Quanto un testo del modello di casa e' sbagliato, contato senza chiedere
niente a nessuno.

**Perche' non basta la distanza dal testo di Claude.** I guasti che il banco ha
trovato nei primi giorni erano tutti di un tipo che nessuna distanza fra
stringhe vede: un verdetto che due righe sotto si contraddice, un numero che la
card mostra gia', i due body battery impastati in una frase, la settimana
recitata invece di essere giudicata, *my body* al posto di *your body*, e la
mia stessa spiegazione di un campo ricopiata di peso dentro la card. Due testi
possono dire la stessa cosa con parole diverse, e due testi che si somigliano
possono dire cose opposte.

E il bersaglio non e' infallibile: il 19 novembre il frammento di Claude dice
che la readiness stava *«inside its usual range and near the top of it»* con un
88 contro una fascia che chiude a 79,3. Ottimizzare verso Claude su quel giorno
vuol dire insegnare a sbagliare come lui. Percio' **i controlli si passano
anche a Claude**: quello che lui prende e' il pavimento realistico, e un giorno
in cui lui fallisce esce dal termine di distanza invece di diventare il
bersaglio.

**Quello che rende i controlli possibili e' che Python sa la risposta.** Per
ogni paragrafo di una sezione spezzata si sa esattamente quali fatti quel
paragrafo aveva in mano — `ollama.asked` da' l'allineamento fra pezzi e
paragrafi, ed e' la stessa funzione con cui il testo viene cucito — quindi
«questo numero non gliel'ha dato nessuno» e «questa lettura e' il contrario di
quella che aveva» sono conti, non opinioni.

**I controlli sono una lista, non una teoria.** Prendono i guasti che sono
stati visti. Uno nuovo passa inosservato finche' qualcuno non lo guarda e
aggiunge la riga, e per quello la pagina Test resta il posto dove si guarda.
"""

import difflib
import json
import re
from pathlib import Path
from typing import Any

from training.api import ollama

# I pesi. Stanno qui in cima perche' sono la cosa che si ritocca, e perche' un
# peso sparso in mezzo al codice e' un peso che nessuno trova.
#
# Gli errori gravi pesano tre volte i leggeri. **E la distanza non pesa: non
# entra nel punteggio**, si misura e si guarda.
#
# Il primo giro la contava con peso 0,3, e i numeri del corpus hanno mostrato
# perche' non va. Il punteggio di llama era 0,646 sui giorni tenuti da parte e
# quello di Claude 0,32, ma i due numeri **non sono fatti degli stessi pezzi**:
# dentro il primo c'erano 0,246 di distanza che Claude, essendo il bersaglio,
# per costruzione non ha. Confrontarli voleva dire chiedere a llama di azzerare
# ogni errore *e* dimezzare la distanza per pareggiare — un traguardo che non
# si raggiunge, e un ciclo che gira finche' finiscono i giri.
#
# Togliendola, il confronto e' fra cose confrontabili e dice una cosa che non
# mi aspettavo: **sugli errori llama sta 0,400 contro 0,320 di Claude**, cioe'
# vicino, e sui soli errori gravi sta meglio (0,222 contro 0,320, perche' il
# frammento della Fitness di Claude si porta avanti un passo di soglia
# inventato per diciassette giorni).
#
# E c'e' la ragione di sostanza: la distanza e' lessicale, non semantica. Il
# modo piu' corto di farla scendere e' far imitare la voce di Claude — *«that
# is not a quibble»* — che e' il contrario di quello che serve. Resta nel file
# e nella pagella perche' va guardata: se scende senza che scendano gli
# errori, l'editor sta imitando.
HARD = 1.0
SOFT = 0.3

# Numeri che si possono scrivere senza averli nei fatti: la finestra della
# fascia, che tutti i prompt nominano, e gli estremi della scala di Garmin.
# Piu' i numeri piccoli, che in prosa sono conteggi e non cifre ("due o tre
# frasi", "uno dei tre"): il bersaglio di questo controllo sono le cifre
# specifiche — 42.9, 5156, 906.88, 151 — e sono tutte sopra la dozzina.
FREE_NUMBERS = {28.0, 100.0}
SMALL_ENOUGH = 12

# Le parole in codice di Garmin, che `_style.md` vieta in due righe. Invece di
# elencarle si riconosce la forma: tutto maiuscolo con un trattino basso, o una
# parola lunga tutta maiuscola. Cosi' un codice nuovo si prende da se'.
GARMIN_CODE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b|\b[A-Z]{6,}\b")
# Le maiuscole che sono nomi e non codici.
NOT_A_CODE = {"VO2MAX", "HRV", "RPE", "ATTENZIONE"}

# La persona, e qui la regola e' piu' fine di quanto sembri.
#
# **La prima persona dell'allenatore e' autorizzata**, e il controllo l'ha
# imparato a sue spese: la prima versione prendeva ogni `I` e dava 38 errori
# sui 104 testi di Claude — tutti del tipo *«I would not shrug it away»*,
# *«breathing in sleep is the one I like least»*, che e' la voce che
# `01_health.md` chiede espressamente («in a coach's voice: *I do not like
# that one*»). E i tre `we` del corpus sono *«what we do have is stark»*, che
# e' inglese normale.
#
# Quello che le regole di casa vietano e' **la prima persona dell'atleta**: il
# suo corpo e la sua notte raccontati come se fossero di chi scrive. Sono i
# guasti veri che ho visto in llama — *«my body came back further than
# usual»*, *«we're doing about as much of this kind of work as usual»*, *«we
# usually do»*, *«I'm feeling better than normal»* — e si distinguono dal
# possessivo e dal verbo che segue, non dal pronome da solo.
#
# La terza persona invece si vieta per intero: **Claude non la usa mai** in
# tutto il corpus, e llama ci scivola (*«yesterday cost him»*, *«took more out
# of him»*).
#
# **E il nome proprio e' terza persona**, che e' il buco che questo controllo
# ha avuto per due giorni. Cercavo i pronomi e non il nome, quindi *«Andrea's
# nervous system spent the night under load»* passava liscio: dieci testi su
# centocinquanta lo dicevano e il punteggio non ne sapeva niente. Lo diceva
# perche' lo dicevano i miei prompt — «one paragraph of **Andrea's** daily
# report» nella riga del compito, dieci file su tredici — e un nome nella
# frase piu' letta del prompt e' un nome che ricompare nella card. I prompt di
# Claude quella riga non ce l'hanno, e Claude il nome non lo scrive mai.
FIRST_PERSON = re.compile(
    r"\bmy\b|\bour\b"
    r"|\bwe(?:'re|'ve| are| were| have)?\s+(?:doing|getting|seeing|running|sleeping|"
    r"training|carrying|recovering|coming|asking)\b"
    r"|\bwe\s+(?:usually|normally|typically|expect)\b"
    r"|\bI(?:'m| am)\s+\w+ing\b"
    r"|\bI\s+(?:slept|woke|ran|feel|felt|trained)\b",
    re.IGNORECASE,
)
THIRD_PERSON = re.compile(
    r"\b(?:he|he's|his|him|the athlete|Andrea|Andrea's)\b", re.IGNORECASE
)

# I nomi dei campi letti ad alta voce. Solo le forme distintive: `about` e
# `where` sono inglese normale e vietarle farebbe solo falsi positivi.
FIELD_NAMES = re.compile(
    r"\b(?:how_they_read|what_it_rests_on|still_to_come|verdict_word|asks_for|"
    r"what_yesterday_cost|load_aerobic_\w+|load_anaerobic|body_battery_\w+|"
    r"sleep_hours|resting_hr|hrv_last_night|resp_sleep|stress_avg_yesterday)\b"
)

# Le frasi con cui un paragrafo parla della propria impalcatura invece che del
# corpo. Lista cresciuta sui guasti visti, e cresce ancora.
# `nothing to say about it` **non c'e' dentro**, e la ragione e' il corpus:
# Claude la usa nove volte, sempre per liquidare una misura normale
# («breathing in sleep plain middle of the range, nothing to say about it»),
# che e' prosa d'allenatore e non una frase sui campi.
SCAFFOLD = (
    "no measures",
    "that's all we have",
    "there is nothing for it to rest on",
    "nothing for it to rest on",
    "the only measure that",
    "was measured",
    "this verdict",
    "the verdict is",
    "the verdict was",
)

# Quanto si puo' sbagliare la lunghezza che il prompt chiede, in piu' o in
# meno, prima che sia un errore leggero. Meta' e il doppio: i prompt dicono
# "circa novanta parole", non novanta.
#
# **Di suo questo controllo non morde**, perche' vale solo per le sezioni
# intere (`wanted_words` rende `None` per le spezzate) e il ciclo le lascia
# fuori — la ragione sta in `bench_tune.DEFAULT_SECTIONS`. Resta perche' e'
# giusto, e chiedendo `--sections health,load` torna a contare: sui testi
# interi di llama spara 48 volte su 50, che e' la forma non rispettata.
LENGTH_SLACK = 0.5

# Quante parole chiede un prompt, letto dal prompt. **Non una tabella scritta a
# mano**: ne avevo scritta una e aveva i numeri delle sezioni spezzate sulle
# intere, che dava otto errori di lunghezza sui testi di Claude per colpa mia.
# La frase e' uniforme in tutti e otto i file, e leggerla vuol dire che se
# qualcuno cambia il conto nel prompt il controllo lo segue.
WANTED_WORDS = re.compile(r"[Aa]bout (\d+) words")


def wanted_words(repo_root, section, *, claude: bool) -> int | None:
    """Quante parole chiede il prompt che ha scritto quel testo.

    Due file diversi per la stessa sezione: la copia di llama e quella di
    Claude chiedono lunghezze diverse — la Load di Claude ottanta parole, la
    copia di llama centottanta, perche' una e' un paragrafo e l'altra sono sei
    — e misurare un testo contro il conto dell'altro e' un errore inventato.

    **Per una sezione spezzata non si controlla**, e `None` vuol dire proprio
    questo. Il conto non sta scritto in nessun file: i pezzi parlano di frasi
    («due o tre», «quarantacinque parole» per l'apertura) e il totale non lo
    dice nessuno. Prendere quello dell'intera e' sbagliato di suo — la Recovery
    di Claude chiede ottanta parole per un paragrafo, la spezzata ne fa cinque
    — e la prima versione dava un errore di lunghezza su ogni testo della
    Recovery spezzata per quel motivo. Un controllo che non ha un numero vero
    da confrontare non si inventa il numero: si tace."""
    if isinstance(section, ollama.Split):
        return None
    whole = next(
        (s for s in ollama.SECTIONS.values()
         if not isinstance(s, ollama.Split) and s.title == section.title),
        None,
    )
    if whole is None:
        return None
    path = Path(repo_root) / (".claude/agents" if claude else ".ollama/agents") / whole.agent
    if not path.exists():
        return None
    found = WANTED_WORDS.search(path.read_text(encoding="utf-8"))
    return int(found.group(1)) if found else None


# Un passo o un'ora scritti coi due punti: `5:53`, `8:09`. Vanno riconosciuti
# interi, o si leggono come due numeri e nessuno dei due sta nei fatti — che e'
# l'altro falso positivo che ha fatto sembrare sbagliati i frammenti della
# Fitness di Claude: «about 5:53 per kilometre» diventava «53 inventato».
CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def _numbers(text: str) -> "list[str]":
    """I numeri scritti in cifre, coi passi `mm:ss` tolti di mezzo perche' li
    guarda `_clocks`. Quelli in parole non si prendono: *eight hours nine* non
    si vede, e non e' un problema — le cifre inventate sono il bersaglio."""
    return re.findall(r"\d+(?:\.\d+)?", CLOCK.sub(" ", text))


def _clocks(text: str) -> "list[tuple[str, float]]":
    """I passi e le durate scritti coi due punti, come sono scritti e in
    secondi: `5:53` fa 353. Nei fatti il passo di soglia e' in secondi al
    chilometro, e il sonno in minuti."""
    return [
        (m.group(), int(m.group(1)) * 60 + int(m.group(2))) for m in CLOCK.finditer(text)
    ]


def _fact_numbers(facts: Any) -> "set[float]":
    """Tutti i numeri che stanno nei fatti, a qualunque profondita', piu'
    quelli che se ne ricavano leggendoli come si leggono.

    I minuti del sonno entrano anche come ore e minuti, che e' la scrittura
    della card: 489 vale anche 8 e 9."""
    found: set[float] = set()

    def walk(node: Any) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            found.add(float(node))
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(value)
                if key == "sleep_minutes" and isinstance(value, (int, float)):
                    found.add(float(value // 60))
                    found.add(float(value % 60))
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
        else:
            # Tutto il resto si guarda come lo si scriverebbe. **Le date
            # arrivano come oggetti `date`**, e un paragrafo che nomina il
            # giorno di una lettura ne usa un pezzo: senza questo ramo «read on
            # 22 October» era un numero inventato, ed e' il falso positivo che
            # ha fatto sembrare sbagliati sette frammenti di Claude di fila.
            for part in re.findall(r"\d+(?:\.\d+)?", str(node)):
                found.add(float(part))

    walk(facts)
    return found


def _covers(value: float, written: str) -> bool:
    """Se un numero dei fatti puo' essere stato scritto cosi'. Tollera
    l'arrotondamento alla precisione con cui e' scritto: 906.88 copre 907, e
    42.9 copre 42.9 e 43."""
    decimals = len(written.split(".")[1]) if "." in written else 0
    try:
        asked = float(written)
    except ValueError:
        return False
    return round(value, decimals) == asked or float(int(value)) == asked


def invented_numbers(text: str, facts: Any) -> "list[str]":
    """I numeri che nessuno gli ha dato."""
    allowed = _fact_numbers(facts)
    # I fatti come li legge chi scrive: serve per i passi, che nei fatti
    # possono stare **gia' scritti coi due punti** — `_threshold_facts` rende
    # `pace` come "5:43 per kilometre", perche' il conto lo fa Python. Cercare
    # 343 secondi in quel caso non trova niente, e il passo giusto diventava un
    # numero inventato.
    rendered = json.dumps(facts, ensure_ascii=False, default=str)
    out = []
    for written, seconds in _clocks(text):
        # Un passo scritto come sta nei fatti va bene; se no si confronta in
        # secondi, che e' come i fatti lo tengono quando non l'hanno tradotto.
        if written in rendered:
            continue
        if not any(abs(known - seconds) < 1 for known in allowed):
            out.append(written)
    for written in _numbers(text):
        value = float(written)
        if value in FREE_NUMBERS or (value <= SMALL_ENOUGH and "." not in written):
            continue
        if not any(_covers(known, written) for known in allowed):
            out.append(written)
    return out


def _paragraphs(section: "ollama.Section | ollama.Split", text: str, facts: dict):
    """I paragrafi del testo accoppiati ai fatti che ognuno aveva in mano.

    Per una sezione spezzata l'accoppiamento e' esatto, e non per fortuna:
    `ollama.asked` e' la stessa funzione con cui `_split_text` decide quali
    pezzi chiedere e in che ordine, quindi il paragrafo *i* e' del pezzo *i*.
    Se i conti non tornano — una risposta con dentro una riga vuota che
    `_one_paragraph` non ha appiattito — si lascia perdere invece di dare la
    colpa al paragrafo sbagliato.

    Per una sezione intera non c'e' nessun accoppiamento da fare: il testo e'
    uno e i fatti sono quelli della sezione. I controlli che hanno bisogno di
    sapere *di chi* e' un paragrafo valgono quindi solo per le spezzate, ed e'
    una differenza da dire, non da nascondere."""
    if not isinstance(section, ollama.Split):
        return [(None, facts, text)]
    pieces = ollama.asked(section, facts)
    written = text.split("\n\n")
    if len(written) != len(pieces):
        return []
    return [(piece, owned, paragraph) for (piece, owned), paragraph in zip(pieces, written)]


def contradicted_readings(section, text: str, facts: dict) -> "list[str]":
    """I paragrafi che dicono il contrario del `reading` che avevano in mano.

    Le letture sono un insieme chiuso e il modello le ricopia, quindi il
    controllo e' una ricerca di sottostringa e non un giudizio. Prende il caso
    vero che ho visto: una mattina con due buone notizie in cui il paragrafo
    della frequenza a riposo ha scritto *much worse than usual* su un
    `reading` che diceva *much better*."""
    out = []
    for piece, owned, paragraph in _paragraphs(section, text, facts):
        reading = (owned or {}).get("reading")
        if not reading or piece is None:
            continue
        said_worse = "worse than usual" in paragraph
        said_better = "better than usual" in paragraph
        if "better" in reading and said_worse:
            out.append(f"{piece.key}: dice *worse* su un reading *{reading}*")
        elif "worse" in reading and said_better:
            out.append(f"{piece.key}: dice *better* su un reading *{reading}*")
        elif reading.startswith(("normal", "comfortably")) and (said_worse or said_better):
            out.append(f"{piece.key}: dice fuori fascia su un reading *{reading}*")
    return out


# Le etichette che in inglese sono parole comuni, e che percio' **non si
# cercano**: «your morning readiness» e «a good place for recovery after last
# night's sleep» sono prosa, non riferimenti alla misura di un'altra sezione.
#
# Cercandole come sottostringa davano undici errori su centoquattro testi, e
# per due di quelli ho ritoccato i prompt prima di accorgermi che il difetto
# era nel metro. E' la stessa classe dei falsi positivi che mi aveva insegnato
# il corpus di Claude — il passo `5:53` letto come due numeri, l'`I`
# dell'allenatore — e si chiude allo stesso modo: il controllo tiene solo i
# nomi che in una frase non ci capitano per caso.
#
# Il prezzo, detto: un riferimento vero alla readiness dentro il paragrafo di
# un'altra misura non si prende piu'. Un falso positivo pero' costa di piu' —
# manda a cambiare i prompt per niente, e l'ho appena fatto.
COMMON_WORDS = {"readiness", "last night's sleep", "sleep"}


def _label_of(piece) -> str:
    return re.sub(r"^the ", "", piece.label.lower())


def _other_labels(section) -> "set[str]":
    """Come si chiamano le misure delle altre sezioni. Sono quelle che un
    paragrafo non puo' nominare: il reader le ha sulla sua card, giudicate da
    chi le possiede."""
    out = set()
    for other in ollama.SECTIONS.values():
        if not isinstance(other, ollama.Split) or other.title == section.title:
            continue
        out.update(_label_of(piece) for piece in other.parts)
    return out - COMMON_WORDS


def foreign_measures(section, text: str, facts: dict) -> "list[str]":
    """I paragrafi che nominano una misura che non era loro.

    Vale per le spezzate, dove si sa di chi e' ogni paragrafo. Un'etichetta che
    e' pezzo dell'altra — *body battery* dentro *body battery at wake-up* —
    si lascia fuori, che prenderebbe il paragrafo giusto per il motivo
    sbagliato."""
    if not isinstance(section, ollama.Split):
        return []
    foreign = _other_labels(section) - COMMON_WORDS
    mine = {_label_of(piece) for piece in section.parts} - COMMON_WORDS
    out = []
    for piece, owned, paragraph in _paragraphs(section, text, facts):
        if piece is None:
            continue
        own = _label_of(piece)
        if piece is section.opening:
            # L'apertura puo' nominare le misure che le sono state date.
            allowed = {
                m["measure"].lower() for m in (owned or {}).get("how_they_read", [])
            }
            candidates = foreign | {lab for lab in mine if lab not in " ".join(allowed)}
        else:
            candidates = foreign | (mine - {own})
        low = paragraph.lower()
        for label in sorted(candidates):
            if label in own or own in label:
                continue
            if label in low:
                out.append(f"{piece.key}: nomina *{label}*")
    return out


def garmin_codes(text: str) -> "list[str]":
    return [w for w in GARMIN_CODE.findall(text) if w not in NOT_A_CODE]


def wrong_person(text: str) -> "list[str]":
    out = []
    if found := FIRST_PERSON.findall(text):
        out.append(f"prima persona: {sorted(set(w.lower() for w in found))}")
    if found := THIRD_PERSON.findall(text):
        out.append(f"terza persona: {sorted(set(w.lower() for w in found))}")
    return out


def hard_faults(section, text: str, facts: dict) -> "list[str]":
    """Gli errori gravi: quelli che fanno dire al testo una cosa falsa, o una
    cosa che non e' sua."""
    out = []
    out += [f"numero inventato: {n}" for n in invented_numbers(text, facts)]
    out += [f"lettura contraddetta: {m}" for m in contradicted_readings(section, text, facts)]
    out += [f"persona sbagliata: {m}" for m in wrong_person(text)]
    out += [f"misura non sua: {m}" for m in foreign_measures(section, text, facts)]
    out += [f"codice di Garmin: {c}" for c in garmin_codes(text)]
    return out


def soft_faults(section, text: str, facts: dict, wanted: int | None = None) -> "list[str]":
    """Gli errori leggeri: quelli che fanno dire al testo una cosa vera in un
    modo che non va."""
    out = []
    out += [f"nome di campo: {m}" for m in sorted(set(FIELD_NAMES.findall(text)))]
    low = text.lower()
    out += [f"parla di se': {p}" for p in SCAFFOLD if p in low]
    if wanted:
        words = len(text.split())
        if not (wanted * (1 - LENGTH_SLACK) <= words <= wanted * (1 + LENGTH_SLACK)):
            out.append(f"lunghezza: {words} parole invece di circa {wanted}")
    # Il numero del paragrafo scritto piu' di una volta: i prompt dicono "al
    # massimo un numero per paragrafo, e solo se porta il punto".
    #
    # **Solo per le spezzate**, dove un paragrafo e' una misura. In una sezione
    # intera un paragrafo copre quattro misure e due o tre numeri ci stanno di
    # diritto: contarli li' dava ventisette errori sui testi di Claude, che e'
    # la regola di un prompt applicata al prompt sbagliato.
    if isinstance(section, ollama.Split):
        for piece, owned, paragraph in _paragraphs(section, text, facts):
            if len(_numbers(paragraph)) > 1:
                out.append(f"numeri nello stesso paragrafo: {piece.key}")
    return out


def distance(a: str | None, b: str | None) -> float:
    """Quanto due testi si somigliano, al contrario: zero se sono uguali, uno
    se non hanno niente in comune.

    `difflib` e non un coseno fra embedding: libreria standard, nessuna
    dipendenza, deterministico. Un modello di embedding darebbe un segnale
    semantico invece che lessicale, ma su questa macchina non ce n'e' uno
    scaricato.

    **Non entra nel punteggio**, e il perche' sta in cima al modulo: si
    guarda, e serve a riconoscere l'editor che imita invece di correggere."""
    if not a or not b:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()


def score(
    section,
    facts: dict,
    text: str,
    claude: str | None = None,
    *,
    wanted: int | None = None,
    claude_wanted: int | None = None,
) -> "dict[str, Any]":
    """La pagella di un testo: gli errori, la distanza dal bersaglio, e il
    punteggio — che e' **la somma dei soli errori**.

    **La distanza si conta solo se il bersaglio regge i controlli.** Se il
    frammento di Claude ha un errore grave, su quella sezione e quel giorno
    Claude non e' un bersaglio: il termine va a zero e il punteggio resta
    quello degli errori. E' la riga che impedisce al ciclo di imparare gli
    sbagli del 19 novembre."""
    hard = hard_faults(section, text, facts)
    soft = soft_faults(section, text, facts, wanted)
    target_faults = hard_faults(section, claude, facts) if claude else []
    gap = distance(text, claude) if claude and not target_faults else 0.0
    return {
        "faults": hard,
        "soft": soft,
        "distance": round(gap, 3),
        "target_faults": target_faults,
        # **Solo gli errori.** La distanza sta nella riga sopra e non qui: il
        # perche' e' in cima al modulo, accanto ai pesi.
        "score": round(len(hard) * HARD + len(soft) * SOFT, 3),
    }
