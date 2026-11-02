"""Le sezioni dei report, una per card (todo 44 per il giorno, 53 per la
settimana).

Ogni sezione ha il suo agente, che ne scrive il corpo in un file dentro la
cartella del report (`summary/01.daily/<giorno>/`,
`summary/02.weekly/<lunedi>/`). Qui sta l'elenco, in un posto solo: lo legge
l'API per comporre il report e l'orchestratore per sapere chi lanciare e in
che ordine.

Le sezioni che guardano i numeri girano per prime, quelle che leggono i
frammenti delle altre dopo: l'ordine di `run_order` non e' quello in cui le
sezioni si leggono nella pagina.

Giorno e settimana hanno la stessa forma e due registri diversi, tenuti
insieme da `Report`: cambiano le sezioni, la cartella, i due giri e gli
agenti, non il meccanismo."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class Section:
    key: str
    # Il titolo nel report (`## Health`): lo mette chi compone, non l'agente.
    title: str
    # Il nome dell'agente in `.claude/agents/`.
    agent: str
    # Vera per chi legge i frammenti degli altri invece dei numeri.
    reads_fragments: bool
    # Vera per chi deve scrivere la riga `verdict:` in cima al frammento
    # (todo 92). Le due meta' del patto — chiederla nel prompt
    # (`refresh._prompt`) e toglierla quando si compone il report
    # (`app._verdict`) — stanno in due moduli, e prima erano tenute insieme
    # dalla stringa "training" battuta a mano in entrambi.
    writes_verdict: bool = False
    # Vera per chi legge il piano della settimana (todo 14 e 64). Solo la
    # Training del **giorno**: quella della settimana giudica sette giorni,
    # non la seduta di domani — da cui il vecchio `and kind is DAILY`, che
    # serviva solo perche' la bandiera era una stringa condivisa fra i due
    # registri.
    reads_plan: bool = False


# Nell'ordine in cui si leggono nella pagina.
#
# **Sei sezioni dal todo 66**, e due pagine con un giro ciascuna: il Report
# e' il corpo, scritto la mattina (le quattro card piu' il Summary che le
# riassume), la Training e' la seduta, scritta la sera. Prima erano otto: il
# verdetto in due pezzi (il sole del mattino e la luna della sera, todo 49) e
# un `next` che proponeva la seduta successiva. Il Summary e' tornato uno
# perche' adesso ha un soggetto solo e un giro solo; `next` e' stato tolto,
# e quello che si perde e' scritto nel todo 66 — la seduta suggerita non
# c'e' piu', e le regole di deroga del piano non le applica piu' nessuno.
SECTIONS: tuple[Section, ...] = (
    Section("summary", "Summary", "07_summary", True),
    Section("training", "Training", "05_training", False, writes_verdict=True, reads_plan=True),
    Section("recovery", "Recovery", "03_recovery", False),
    Section("health", "Health", "01_health", False),
    Section("load", "Load", "02_load", False),
    Section("fitness", "Fitness", "04_fitness", False),
)

# La settimana (todo 53), sulla linea del giorno dal todo 68: le quattro card
# del corpo con il Summary che le riassume, il Training, e il Next.
#
# **Il Summary e' uno.** Erano due — l'apertura del lunedi e la chiusura
# della domenica — e il secondo leggeva il primo. Adesso e' solo la chiusura,
# scritta quando i sette giorni ci sono: una settimana ha i numeri alla fine,
# non all'inizio. Il prezzo e' che dal lunedi al sabato la settimana non ha
# nessun testo, ed e' scritto nel todo 68.
#
# **Anche il Next e' andato** (todo 69), dopo quello del giorno (todo 66).
# Era la strategia dei sette giorni che vengono, e l'unica cosa che
# adattava la forma del blocco a com'era andata la settimana appena finita.
# Adesso quella forma la dice il piano scritto e nessun agente la rivede: le
# sei sezioni raccontano, nessuna prescrive.
WEEK_SECTIONS: tuple[Section, ...] = (
    Section("summary", "Summary", "w7_summary", True),
    Section("training", "Training", "w5_training", False, writes_verdict=True),
    Section("recovery", "Recovery", "w3_recovery", False),
    Section("health", "Health", "w1_health", False),
    Section("load", "Load", "w2_load", False),
    Section("fitness", "Fitness", "w4_fitness", False),
)

# Nell'ordine in cui si lanciano, che e' quello dei numeri degli agenti e non
# quello di lettura: prima quelle che guardano i numeri, poi quelle che
# leggono i frammenti delle altre. Il primo verdetto prima del secondo,
# perche' quando girano insieme (il tasto della pagina) il secondo deve
# trovare il primo scritto.
# Uno solo: le sei chiavi sono le stesse per il giorno e per la settimana —
# cambiano gli agenti (`01_health` e `w1_health`), non l'ordine — e scriverlo
# due volte voleva dire due liste da tenere d'accordo a mano.
_RUN_KEYS = (
    "health",
    "load",
    "recovery",
    "fitness",
    "training",
    "summary",
)


def _ordered(sections: tuple[Section, ...], keys: tuple[str, ...]) -> tuple[Section, ...]:
    by_key = {section.key: section for section in sections}
    order = tuple(by_key[key] for key in keys)
    assert {s.key for s in order} == {s.key for s in sections}
    # I verdetti stanno in fondo, tutti insieme: chi legge i frammenti degli
    # altri non puo' girare prima di loro.
    first = next(i for i, s in enumerate(order) if s.reads_fragments)
    assert all(s.reads_fragments for s in order[first:]), "i verdetti per ultimi"
    return order


RUN_ORDER: tuple[Section, ...] = _ordered(SECTIONS, _RUN_KEYS)
WEEK_RUN_ORDER: tuple[Section, ...] = _ordered(WEEK_SECTIONS, _RUN_KEYS)


# I due giri dei timer (todo 47, riscritti dal todo 66). Adesso **ogni giro
# scrive una pagina** e ogni sezione gira una volta al giorno: la mattina
# alle otto il corpo, cioe' il Report; la sera alle nove la seduta, cioe' la
# Training.
#
# Prima i due giri si sovrapponevano — `load` e `fitness` scritti due volte,
# `next` due volte, e un Summary con mezzo verdetto per giro. Il prezzo del
# taglio e' che `load` e `fitness` raccontano lo stato **prima** della seduta
# di oggi: il Report dice come stai stamattina, e il carico di oggi si legge
# domani.
MOMENT_SECTIONS: dict[str, tuple[str, ...]] = {
    "morning": ("health", "recovery", "load", "fitness", "summary"),
    "evening": ("training",),
}

# **Un giro solo** (todo 68): la domenica sera, in coda a quello del giorno
# (todo 66: le 21), nella stessa riga di cron.
#
# Erano due. Il lunedi scriveva una sezione sola — l'apertura, che guardava
# la settimana prima — perche' una settimana al suo primo giorno non ha
# numeri da commentare: le medie starebbero su un giorno e le sedute su
# nessuna. Quel ragionamento vale ancora, e la conclusione e' cambiata: se
# l'unica cosa che il lunedi puo' dire e' come ci arrivi, e il verdetto e'
# uno, allora il verdetto e' quello della fine. **Un momento che scrive una
# sezione sola non e' un momento.**
#
WEEK_MOMENT_SECTIONS: dict[str, tuple[str, ...]] = {
    "end": ("health", "recovery", "load", "fitness", "training", "summary"),
}

assert all(
    set(keys) <= {s.key for s in SECTIONS} for keys in MOMENT_SECTIONS.values()
)
assert all(
    set(keys) <= {s.key for s in WEEK_SECTIONS} for keys in WEEK_MOMENT_SECTIONS.values()
)

# Come si dice all'agente a che punto siamo. Non e' un fatto del periodo ma
# del giro (todo 47). Dal todo 66 ogni giro del giorno ha una sezione sola a
# cui la riga serve: la mattina il Summary, che parla del corpo di stanotte;
# la sera il Training, che parla della seduta appena fatta. Le due righe
# restano anche perche' il tasto della pagina rifa' **tutte** le sezioni a
# qualunque ora, e allora il momento decide con che voce.
_DAY_MOMENT_LINES = {
    "morning": "This is the morning run: the day is ahead of him.",
    "evening": "This is the evening run: the day is behind him.",
}
_WEEK_MOMENT_LINES = {
    "end": "This is the Sunday evening run: the week is finished, and the next one starts "
    "tomorrow.",
}


# I giri del backfill (todo 50): non sono quelli dei timer, perche' li' si
# scrive il presente e qui un periodo finito.
#
# Dal todo 66 il giorno ne vuole due, uno per pagina: prima la seduta con la
# voce della sera, poi il corpo con quella del mattino. Erano tre, perche' il
# verdetto era in due pezzi e il secondo leggeva il primo. Il Summary resta
# in coda al suo giro — lo mette `run_order`, che i verdetti li tiene per
# ultimi — cosi' trova scritte le quattro sezioni che deve riassumere.
_DAY_BACKFILL = (
    ("evening", ("training",)),
    ("morning", ("health", "recovery", "load", "fitness", "summary")),
)
# La settimana ne vuole uno dal todo 68, che di momenti ne ha uno: tutto
# nella chiusura. Erano due, e il secondo era l'apertura, che del report
# della settimana **precedente** aveva bisogno — da cui il ciclo dalla piu'
# vecchia alla piu' recente, che resta giusto comunque.
# Un momento solo, quindi il giro del backfill **e'** quello dei momenti: si
# deriva, invece di ripetere le sei chiavi in un terzo posto.
_WEEK_BACKFILL = tuple(WEEK_MOMENT_SECTIONS.items())


@dataclass(frozen=True)
class Report:
    """Un tipo di report: quello del giorno o quello della settimana.

    Tiene insieme le cose che l'orchestratore deve sapere per scriverlo —
    dove vanno i frammenti, chi gira, in che ordine e con che voce — cosi'
    il ciclo e' uno solo per tutti e due (todo 53)."""

    name: str
    # Come si chiama nel prompt dell'agente.
    what: str
    # Vera per il giro che prima di scrivere richiama Garmin. **La settimana
    # non scarica mai** (todo 53): gira in coda al giro del giorno, che ha
    # appena chiamato, e un secondo scaricamento sarebbe solo un'altra
    # occasione di fallire.
    downloads: bool
    # Quanto dura un periodo: un giorno, o una settimana.
    step: timedelta
    # La cartella sotto `summary/`.
    folder: str
    # Nell'ordine in cui si leggono nella pagina.
    sections: tuple[Section, ...]
    # Nell'ordine in cui si lanciano.
    run_order: tuple[Section, ...]
    # I giri: quali sezioni scrive ognuno.
    moments: dict[str, tuple[str, ...]]
    # La riga che dice all'agente a che punto del periodo siamo.
    moment_lines: dict[str, str]
    # I giri con cui si riscrive un periodo passato, nell'ordine.
    backfill: tuple[tuple[str, tuple[str, ...]], ...]
    # I nomi che una sezione aveva prima, per i frammenti scritti allora
    # (todo 66 per il giorno, 68 per la settimana). Il verdetto era in due
    # pezzi e adesso e' uno: senza questo, i giorni e le settimane gia'
    # scritti mostrerebbero un Summary vuoto, che non e' "il testo non c'e'"
    # ma "il file si chiama come si chiamava allora". L'ordine conta: il
    # pezzo della fine prima di quello dell'inizio, che su un periodo
    # concluso e' lui il verdetto.
    old_fragments: dict[str, tuple[str, ...]]

    @property
    def by_key(self) -> dict[str, Section]:
        return {section.key: section for section in self.sections}

    def start_of(self, day: date) -> date:
        """Il periodo che contiene `day`: il giorno stesso, o il suo
        lunedi'. Era riderivato in cinque punti di `refresh.py`, ognuno col
        suo `if kind is WEEKLY`."""
        if self.step == timedelta(weeks=1):
            return day - timedelta(days=day.weekday())
        return day

    def period(self, subject: date) -> str:
        """Il periodo come lo legge l'agente: un giorno, o una settimana con
        i suoi due estremi."""
        if self.name == "weekly":
            return f"the week from Monday {subject} to Sunday {subject + timedelta(days=6)}"
        return subject.isoformat()


DAILY = Report(
    name="daily",
    what="daily report",
    downloads=True,
    step=timedelta(days=1),
    folder="01.daily",
    sections=SECTIONS,
    run_order=RUN_ORDER,
    moments=MOMENT_SECTIONS,
    moment_lines=_DAY_MOMENT_LINES,
    backfill=_DAY_BACKFILL,
    old_fragments={"summary": ("summary_evening", "summary_morning")},
)
WEEKLY = Report(
    name="weekly",
    what="weekly report",
    downloads=False,
    step=timedelta(weeks=1),
    folder="02.weekly",
    sections=WEEK_SECTIONS,
    run_order=WEEK_RUN_ORDER,
    moments=WEEK_MOMENT_SECTIONS,
    moment_lines=_WEEK_MOMENT_LINES,
    backfill=_WEEK_BACKFILL,
    old_fragments={"summary": ("summary_end", "summary_start")},
)
KINDS = {report.name: report for report in (DAILY, WEEKLY)}


for _report in (DAILY, WEEKLY):
    _keys = [k for _moment, keys in _report.backfill for k in keys]
    assert len(_keys) == len(set(_keys)), f"{_report.name}: una sezione due volte nel backfill"
    assert set(_keys) == {s.key for s in _report.sections}, f"{_report.name}: backfill incompleto"


# L'ora da cui una giornata si considera alle spalle. Serve alla **voce** del
# testo, non a chi gira.
#
# Dal todo 66 i due giri del giorno scrivono sezioni diverse, quindi di suo
# il momento sarebbe deciso dal giro. Serve ancora per il **tasto della
# pagina**, che rifa' tutte le sezioni a qualunque ora: premuto alle 21:30
# riscrive anche il Summary, e quello deve sapere che parla di una giornata
# alle spalle e non di una che comincia.
EVENING_FROM_HOUR = 15


def moment_at(when: datetime) -> str:
    """Il momento della giornata di `when`, per la voce del testo.

    Si ricava sempre dall'orologio, anche quando a lanciare e' il tasto
    della pagina: cosi' un refresh a mano parla come il giro del timer che
    gli e' piu' vicino. Quale sezione gira e' un'altra cosa, e la decidono
    solo i timer (`MOMENT_SECTIONS`)."""
    return "evening" if when.hour >= EVENING_FROM_HOUR else "morning"


def week_moment_at(monday: date, today: date) -> str:
    """Il momento di una settimana, per la voce del testo.

    Dal todo 68 ce n'e' **uno solo**, la chiusura: il verdetto e' uno e si
    scrive quando i sette giorni ci sono. Prima una settimana ancora aperta
    si raccontava dal lunedi, con l'apertura che guardava la settimana prima.

    La funzione resta, con un valore solo, perche' il momento e' un parametro
    del ciclo condiviso col giorno: il tasto della pagina lo chiede per
    sapere con che voce fare scrivere, e togliere il concetto per la sola
    settimana costerebbe piu' di quanto rende. `monday` e `today` non si
    guardano piu'."""
    return "end"
