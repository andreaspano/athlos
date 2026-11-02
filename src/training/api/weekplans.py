"""Chi genera i piani settimanali di `summary/05.plan/` (todo 86).

`plans.py` e' chi legge: il blocco scritto a mano in `plan/<slug>.md`, e le
settimane che da quel blocco sono nate. Qui c'e' chi le fa nascere, che fino
al todo 86 non esisteva — i diciannove file di `summary/05.plan/` li ha
scritti un giro a mano il 26 ottobre 2026, e cambiare goal non ne riscriveva
nessuno perche' non c'era niente da chiamare. Il flag `current` del todo 84
segnava un'intenzione e non muoveva niente; da qui muove le settimane.

**Le scrive un agente, non questo modulo.** Il blocco e' prosa: la tabella
delle diciotto settimane da' km, lungo e qualita' riga per riga, tre tabelle
di fase danno la forma dei sette giorni, un'altra i ritmi e le frequenze, e
in fondo ci sono le deroghe. Un parser di quelle tabelle sarebbe il parser
del markdown di una persona: si romperebbe sul primo blocco scritto
diversamente — un trail, una gara in salita, un periodo senza gara — e si
romperebbe in silenzio, perche' una tabella che non si trova diventa una
settimana senza sedute. Quindi un agente (`.claude/agents/p_week.md`),
lanciato come `refresh._write_section` lancia le sezioni dei report.

**Lo stile dei report non si attacca.** `_style.md` dice *il corpo di una
sezione, nessun titolo, un paragrafo, niente tabelle*, che qui sono tutte
istruzioni sbagliate: una settimana e' un documento con front matter, titoli
e tabelle. Quel che vale di quelle regole sta nel file dell'agente.

**Le date le decide questo modulo.** Il lunedi' (che e' il nome del file),
`block_week`, `block_weeks`, `plan`, `race` e `target_time` escono dal front
matter del blocco e da un conto, e all'agente si danno nel prompt. Un agente
che scrive diciassette front matter a mano ne sbaglia uno, e l'errore e'
muto: `load_day_plan` cerca la seduta **per data**, quindi una data sbagliata
non da' un errore, da' un giorno senza piano, e si scopre a dicembre
guardando una card vuota.

**Il file nasce in `.staging/` e arriva al suo posto solo se passa i
controlli** (`check`). Un file rotto e' peggio di un file che non c'e':
quello che manca lo gestiscono apposta tutti e tre i lettori — `None`,
nessuna frase nel prompt, nessuna card — mentre quello rotto gira, e il
Training del giorno giudica una corsa contro una seduta sbagliata e ne
scrive il verdetto. In una sottocartella della cartella dei piani e non in
`/tmp`, cosi' una settimana scartata si puo' leggere; `glob("*.md")` non
scende nelle sottocartelle, quindi da li' non si vede ne' nell'elenco ne'
nel conto di `ahead`.

**Dal lunedi' prossimo in avanti.** Il passato non si tocca (todo 85): le
settimane finite sono il registro di quello che era previsto allora, e i
report di allora le hanno giudicate. La settimana **in corso** sta col
passato, ed e' la decisione nuova: i suoi giorni passati sono stati corsi e
giudicati, la card Plan della Day legge il file dal vivo, e una settimana che
cambia sotto i piedi a meta' e' peggio di una settimana che finisce sul
piano vecchio. Il prezzo e' che `ahead`, che conta da questo lunedi', resta a
una settimana fino al lunedi' dopo.

**Quello che c'e' gia' va in `.trash/`, non si sovrascrive.** Il README dice
che una settimana si puo' riscrivere a mano avvicinandosi alla data, sullo
stato di forma del momento: uno di quei file puo' essere mezz'ora di lavoro
di una persona. Stessa scelta del todo 85 per i goal, e lo stesso fatto da
dire ad alta voce: **generare e' un gesto distruttivo**, il primo che tocca
file dentro `summary/`."""

import argparse
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

# I pezzi di `plans.py`: leggere il front matter, il titolo, i valori, e
# soprattutto `_day_row`, che e' chi cerca la riga di un giorno nella tabella.
# Il controllo deve usare **lui** e non una regola scritta qui: quello che
# conta non e' che la tabella sia bella, e' che il lettore la trovi.
from training.api.plans import (
    WEEK_PLAN_FOLDER,
    _as_date,
    _as_number,
    _as_text,
    _day_row,
    _distance_label,
    _front_matter,
    _MONTHS,
    _title,
    load_plans,
    week_plan_path,
)

# Il lock dei lavori e il timeout di un agente sono quelli dei report: due
# serie di `claude` sugli stessi file non si fanno, e fra processi diversi il
# file e' l'unica cosa che lo impedisce.
from training.api.refresh import TIMEOUT_SECONDS, _claim, _tail

# L'agente che scrive una settimana.
AGENT = "p_week"
# Dove il file nasce, e dove restano le settimane scartate.
STAGING_FOLDER = ".staging"
# Dove va la settimana che questa sostituisce.
TRASH_FOLDER = ".trash"
# I tipi di seduta del formato (`summary/05.plan/README.md`). Insieme chiuso:
# un `kind: tempo` non lo mostra nessuno.
KINDS = ("easy", "quality", "long", "race")
# Il giorno senza allenamento. Non e' uno sport e non ha `kind`.
REST = "rest"


class BlockProblem(Exception):
    """Un blocco da cui non si puo' generare: non c'e', non e' quello, o gli
    manca una chiave senza la quale non si sa nemmeno quali settimane
    scrivere."""


@dataclass(frozen=True)
class Week:
    """L'identita' di una settimana: tutto quello che non e' allenamento.

    La calcola questo modulo e l'agente la riceve gia' fatta; `check` la
    rilegge nel file per verificare che sia arrivata intera."""

    monday: date
    block_week: int
    block_weeks: int
    plan: str
    race: date | None
    target_time: str | None

    @property
    def days(self) -> list[date]:
        """I sette giorni, da lunedi' a domenica."""
        return [self.monday + timedelta(days=offset) for offset in range(7)]

    @property
    def file(self) -> str:
        return f"{self.monday.isoformat()}.md"


def next_monday(today: date) -> date:
    """Il primo lunedi' che non e' ancora cominciato.

    E' da qui che si genera: vedi il docstring del modulo."""
    return today - timedelta(days=today.weekday()) + timedelta(weeks=1)


def block(plan_dir: Path, slug: str | None = None) -> dict:
    """Il goal da cui generare: quello chiesto, o **quello attuale**.

    Senza slug vince `current: true`, che e' la prima volta che quel flag
    serve a qualcosa fuori dalla pagina Goal. Nessun goal attuale non si
    indovina: generare dal primo dell'elenco vorrebbe dire scrivere
    diciassette settimane su un bersaglio che nessuno ha scelto."""
    plans = load_plans(plan_dir)
    if not plans:
        raise BlockProblem(f"nessun goal in {plan_dir}")
    if slug is not None:
        for plan in plans:
            if plan["slug"] == slug:
                return plan
        raise BlockProblem(
            f"nessun goal si chiama {slug!r} in {plan_dir} "
            f"(ci sono: {', '.join(plan['slug'] for plan in plans)})"
        )
    for plan in plans:
        if plan["current"]:
            return plan
    raise BlockProblem(
        "nessun goal e' quello attuale: serve `current: true` nel front matter di uno dei "
        f"file di {plan_dir}, o il nome del goal da cui generare"
    )


def weeks(goal: dict, first_monday: date) -> list[Week]:
    """Le settimane del blocco da `first_monday` in poi, in ordine.

    `block_start` si riporta al suo lunedi': i file portano il nome di un
    lunedi' per definizione, quindi un blocco che comincia di mercoledi' non
    puo' voler dire altro.

    Senza `block_start` o `block_weeks` non si genera, e per la pagina
    invece quelle chiavi non sono obbligatorie — un goal senza niente si
    vede comunque, coi riquadri vuoti. Qui l'errore dice **quale chiave
    manca e in quale file**, che e' l'unica cosa utile da sapere."""
    start, total = goal["block_start"], goal["weeks"]
    missing = [
        name for name, value in (("block_start", start), ("block_weeks", total)) if value is None
    ]
    if missing:
        raise BlockProblem(
            f"al goal {goal['slug']} manca {' e '.join(missing)}: va nel front matter di "
            f"{goal['file']}, e senza non si sa quali settimane scrivere"
        )
    monday = start - timedelta(days=start.weekday())
    return [
        Week(day, index + 1, total, goal["slug"], goal["race"], goal["target_time"])
        for index in range(total)
        if (day := monday + timedelta(weeks=index)) >= first_monday
    ]


def _bad_distance(value: object) -> str | None:
    """La distanza che `_distance_label` non sa leggere, come la si scrive in
    un messaggio; `None` quando va bene (assente, un numero, o due)."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None
    if isinstance(value, (list, tuple)):
        ends = [v for v in value if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(ends) == len(value) == 2:
            return None
    return repr(value)


def check(path: Path, week: Week) -> list[str]:
    """I problemi del file, lista vuota se va bene.

    Sono controlli **strutturali**: dicono che ci sono sette sedute con un
    `kind` noto e una riga nella tabella per ognuna, non che quelle sedute
    siano sensate. Quello lo dice il blocco, e lo guarda una persona sulle
    righe che il comando stampa."""
    meta, body = _front_matter(path.read_text(encoding="utf-8"))
    if not meta:
        return ["il front matter non c'e' o non si legge: senza, il file e' solo prosa"]
    _, text = _title(body)
    problems: list[str] = []

    def shown(value: object) -> str:
        # Una data si scrive come la scrive il file, non come la stampa
        # Python: il messaggio lo legge chi guarda il file.
        return value.isoformat() if isinstance(value, date) else repr(value)

    def same(key: str, wanted: object, found: object) -> None:
        if found != wanted:
            problems.append(f"`{key}` e' {shown(found)}, non {shown(wanted)}")

    same("week", week.monday, _as_date(meta.get("week")))
    same("plan", week.plan, _as_text(meta.get("plan")))
    same(
        "block_week",
        week.block_week,
        int(n) if (n := _as_number(meta.get("block_week"))) is not None else None,
    )
    same(
        "block_weeks",
        week.block_weeks,
        int(n) if (n := _as_number(meta.get("block_weeks"))) is not None else None,
    )
    # Gara e bersaglio si controllano solo se il blocco ce li ha: un blocco
    # senza gara e' un blocco, non un errore.
    if week.race is not None:
        same("race", week.race, _as_date(meta.get("race")))
    if week.target_time is not None:
        same("target_time", week.target_time, _as_text(meta.get("target_time")))

    sessions = meta.get("sessions")
    if not isinstance(sessions, list):
        problems.append("`sessions` non c'e': le sedute a macchina sono la meta' del formato")
        return problems
    dated: dict[date, dict] = {}
    for entry in sessions:
        if not isinstance(entry, dict):
            problems.append(f"una voce di `sessions` non e' una seduta: {entry!r}")
            continue
        day = _as_date(entry.get("date"))
        if day is None:
            problems.append(f"una seduta non ha `date`: {entry!r}")
            continue
        if day in dated:
            problems.append(f"due sedute per il {day}")
        dated[day] = entry
    if absent := [day for day in week.days if day not in dated]:
        problems.append("manca la seduta del " + ", ".join(day.isoformat() for day in absent))
    if extra := [day for day in sorted(dated) if day not in week.days]:
        problems.append(
            "sedute fuori dalla settimana: " + ", ".join(day.isoformat() for day in extra)
        )
    for day in week.days:
        entry = dated.get(day)
        if entry is None:
            continue
        sport = _as_text(entry.get("sport"))
        if not sport:
            problems.append(f"la seduta del {day} non dice `sport`")
        elif sport != REST and (kind := _as_text(entry.get("kind"))) not in KINDS:
            problems.append(
                f"il {day} ha `kind: {kind}`, che non e' uno di {', '.join(KINDS)}"
            )
        if (bad := _bad_distance(entry.get("distance_km"))) is not None:
            problems.append(f"il {day} ha `distance_km: {bad}`, che non e' un numero ne' due")
        if _day_row(text, day) is None:
            problems.append(
                f"la tabella non ha una riga per il {day.day} {_MONTHS[day.month - 1]}: "
                "e' quella che la card del giorno legge, nella forma dei file"
            )
    return problems


def _km(entry: dict) -> float:
    """I chilometri di una seduta, il centro quando il piano da' un
    intervallo: serve a sommarli, non a mostrarli."""
    value = entry.get("distance_km")
    if isinstance(value, (list, tuple)):
        ends = [float(v) for v in value if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return sum(ends) / len(ends) if ends else 0.0
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def line(path: Path, week: Week) -> str:
    """La riga che il comando stampa per una settimana scritta.

    **Questa e' la verifica vera.** I controlli di `check` sono strutturali;
    queste righe si leggono accanto alla tabella «Le 18 settimane» del
    blocco, e un lungo di 21 km alla settimana 3 si vede a occhio."""
    meta, _ = _front_matter(path.read_text(encoding="utf-8"))
    sessions = [entry for entry in (meta.get("sessions") or []) if isinstance(entry, dict)]
    phase = _as_text(meta.get("phase")) or "?"
    km = sum(_km(entry) for entry in sessions)
    long_run = next(
        (_distance_label(entry.get("distance_km")) for entry in sessions
         if _as_text(entry.get("kind")) == "long"),
        None,
    )
    quality = sum(1 for entry in sessions if _as_text(entry.get("kind")) == "quality")
    return (
        f"  {week.monday}  {week.block_week:>2}/{week.block_weeks}  {phase:<9}"
        f"{km:>5.0f} km  lungo {long_run or '-':<9}{quality} qualita'"
    )


def _previous_of_goal(summary_dir: Path, week: Week, say) -> Path | None:
    """Il file della settimana prima, ma solo se e' di questo blocco.

    La continuita' e' la sostanza di questi piani (vedi `_prompt`): un file
    di un altro goal e' peggio di nessun file, perche' l'agente non ha modo
    di sapere che non e' il suo."""
    previous = week_plan_path(summary_dir, week.monday - timedelta(days=1))
    if previous is None:
        if week.block_week > 1:
            say(f"              la settimana prima non c'e': questa riparte dal blocco")
        return None
    from training.api.plans import _front_matter, _read

    meta, _ = _front_matter(_read(previous))
    belongs = _as_text(meta.get("plan"))
    if belongs is not None and belongs != week.plan:
        say(
            f"              {previous.name} e' del goal {belongs}, non di {week.plan}: "
            f"questa riparte dal blocco"
        )
        return None
    return previous


def _prompt(goal: dict, plan_dir: Path, week: Week, summary_dir: Path, target: Path,
            previous: Path | None) -> str:
    """Il lavoro dell'agente: la sua settimana, il blocco, il formato e la
    settimana prima.

    **La settimana prima e' la sostanza del piano**: il lungo che va da 15 a
    16, il rifornimento che entra alla settimana 7, gli ultimi chilometri a
    ritmo gara dalla 10. Senza quel file ogni settimana ripartirebbe dal
    blocco e la continuita' sarebbe una coincidenza."""
    readme = Path(summary_dir) / WEEK_PLAN_FOLDER / "README.md"
    identity = [
        f"week: {week.monday.isoformat()}",
        f"plan: {week.plan}",
        f"block_week: {week.block_week}",
        f"block_weeks: {week.block_weeks}",
    ]
    if week.race is not None:
        identity.append(f"race: {week.race.isoformat()}")
    if week.target_time is not None:
        identity.append(f'target_time: "{week.target_time}"')
    before = (
        f"The week before it is written in {previous}: read it, this one carries on from there. "
        if previous is not None
        else "There is no week before this one to read. "
    )
    return (
        f"Write the plan of the week of {week.monday.isoformat()} — week {week.block_week} of "
        f"{week.block_weeks} of the block in {plan_dir / goal['file']}. Read that block: it is "
        f"the authority on the paces, the volumes and the shape of the week, and the row of your "
        f"week in its table of the whole block says what this week is for. "
        f"{before}"
        f"The format of the file is described in {readme}: read it and follow it, front matter "
        f"and table. "
        f"The front matter must carry exactly these values, which are not yours to decide: "
        + "; ".join(identity)
        + ". The seven `sessions` are the seven days from "
        f"{week.monday.isoformat()} to {week.days[-1].isoformat()}, one per day, and the table "
        f"has a row for each of them. "
        f"Write the file to {target}."
    )


def _write_week(repo_root: Path, prompt: str, target: Path, began: datetime) -> str | None:
    """Lancia l'agente su una settimana. Rende il motivo per cui non ha
    scritto, o `None`.

    Come `refresh._write_section`: stdin chiuso, il timeout di un agente
    solo, i permessi di scrittura ristretti alla cartella dove il file deve
    nascere — e il controllo che il file sia stato scritto **adesso**, che
    uscire 0 non basta."""
    claude = shutil.which("claude")
    if claude is None:
        return "il comando claude non e' nel PATH"
    command = [
        claude, "-p", "--agent", AGENT,
        # Il doppio slash non e' un refuso: in una regola di permesso un
        # percorso che comincia con `/` si intende relativo alla cartella del
        # progetto, e per dire "assoluto" se ne mettono due.
        "--allowedTools", "Read", f"Edit(/{target.parent.resolve()}/**)",
        "--", prompt,
    ]
    try:
        done = subprocess.run(
            command, cwd=repo_root, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return f"{AGENT} non ha finito in {TIMEOUT_SECONDS // 60} minuti"
    if done.returncode != 0:
        return _tail(done) or f"{AGENT} e' uscito con {done.returncode}"
    if not (target.exists() and target.stat().st_mtime >= began.timestamp()):
        return f"{AGENT} ha finito senza scrivere {target.name}"
    return None


def generate(
    repo_root: Path,
    plan_dir: Path,
    summary_dir: Path,
    data_dir: Path,
    goal: dict,
    wanted: list[Week],
    say=print,
) -> dict:
    """Scrive le settimane di `wanted`, una alla volta, e dice come e' andata.

    In fila e non insieme, per i motivi dell'orchestratore dei report: a
    parita' di lavoro i gettoni sono gli stessi, un giro che va storto si
    ferma invece di bruciare le sessioni rimaste, e non si rischiano i limiti
    di frequenza.

    Stampa mentre va: diciassette agenti sono mezz'ora, e una riga a settimana
    e' l'unico modo di guardare un comando cosi' lungo mentre gira."""
    tally: dict = {"written": [], "failed": [], "trashed": 0, "stopped": False}
    folder = Path(summary_dir) / WEEK_PLAN_FOLDER
    staging = folder / STAGING_FOLDER
    staging.mkdir(parents=True, exist_ok=True)
    # Il lock si prende e si lascia **una settimana per volta**, non per tutto
    # il giro: diciotto settimane sono tre ore, e tenendolo dall'inizio alla
    # fine ogni report che cadeva in quella finestra — le 8 e le 21 — trovava
    # il lock occupato e non si scriveva. Fra una settimana e l'altra adesso
    # c'e' il suo spazio. Le settimane sono indipendenti: ognuna vede il file
    # di quella prima, che per allora e' gia' al suo posto.
    for week in wanted:
        with _claim(data_dir) as mine:
            if not mine:
                tally["stopped"] = True
                return tally
            target = folder / week.file
            staged = staging / week.file
            # Il lunedi' prima, che e' la settimana prima: se c'e' un file, e'
            # quello appena scritto o quello che c'era gia'.
            #
            # **Ma deve venire da questo goal.** Quando la settimana prima e'
            # stata scartata, qui restava il file vecchio di quel lunedi', che
            # puo' essere di un altro blocco: l'agente leggeva la continuita'
            # sbagliata senza che nessuno lo dicesse. Se non e' di questo
            # goal non si passa, e si dice che la catena e' rotta.
            previous = _previous_of_goal(summary_dir, week, say)
            began = datetime.now()
            problem = _write_week(
                repo_root,
                _prompt(goal, plan_dir, week, summary_dir, staged, previous),
                staged,
                began,
            )
            problems = [problem] if problem else check(staged, week)
            if problems:
                tally["failed"].append((week.monday, problems))
                say(f"  {week.monday}  scartata: " + "; ".join(problems))
                if staged.exists():
                    say(f"              resta in {staged}")
                continue
            if target.exists():
                trash = folder / TRASH_FOLDER
                trash.mkdir(exist_ok=True)
                target.rename(trash / f"{week.monday.isoformat()}-{datetime.now():%Y%m%d-%H%M%S}.md")
                tally["trashed"] += 1
            staged.rename(target)
            tally["written"].append(week.monday)
            say(line(target, week))
    return tally


def _monday(text: str) -> date:
    try:
        day = date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"data non valida: {text!r} (serve YYYY-MM-DD)")
    if day.weekday() != 0:
        raise argparse.ArgumentTypeError(f"il {day} non e' un lunedi'")
    return day


def main() -> None:
    """Il generatore da terminale (`training-week-plans`, `make week_plans`).

    Non e' una cosa da mettere in un timer: sono diciassette sessioni di
    `claude`, e un piano nuovo non e' una cosa che succede ogni notte alle
    otto. Il lock lo prende una settimana per volta (vedi `write_weeks`),
    cosi' un report che casca in mezzo al giro trova il suo spazio."""
    from training.api.context import REPO_ROOT
    from training.garmin.config import DATA_DIR, PLAN_DIR, SUMMARY_DIR

    parser = argparse.ArgumentParser(
        description="Genera i piani settimanali di summary/05.plan/ dal blocco di un goal."
    )
    parser.add_argument(
        "--goal", help="lo slug del goal (il nome del file senza .md); di default quello attuale"
    )
    parser.add_argument(
        "--from", dest="start", type=_monday,
        help="il primo lunedi' da scrivere; di default il lunedi' prossimo. Il passato e la "
        "settimana in corso non si riscrivono.",
    )
    parser.add_argument(
        "--to", dest="end", type=_monday,
        help="l'ultimo lunedi' da scrivere; di default la settimana di gara",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="dice quali settimane scriverebbe, e quali manderebbe nel cestino, senza lanciare "
        "nessun agente",
    )
    args = parser.parse_args()
    try:
        goal = block(PLAN_DIR, args.goal)
        first = next_monday(date.today())
        if args.start is not None and args.start < first:
            parser.error(
                f"il {args.start} e' passato o e' la settimana in corso: si genera dal {first}. "
                "Le settimane finite sono il registro di quello che era previsto allora, e i "
                "report di allora le hanno giudicate."
            )
        wanted = weeks(goal, args.start or first)
    except BlockProblem as problem:
        raise SystemExit(f"Non posso generare: {problem}")
    if args.end is not None:
        wanted = [week for week in wanted if week.monday <= args.end]
    if not wanted:
        print(f"Niente da scrivere: il blocco di {goal['slug']} non ha settimane da qui in poi.")
        raise SystemExit(0)
    folder = SUMMARY_DIR / WEEK_PLAN_FOLDER
    quante = len(wanted)
    print(
        f"{quante} settiman{'a' if quante == 1 else 'e'} dal {wanted[0].monday} al "
        f"{wanted[-1].monday}, dal goal {goal['slug']} ({goal['file']})."
    )
    if args.dry_run:
        for week in wanted:
            target = folder / week.file
            print(
                f"  {week.monday}  {week.block_week:>2}/{week.block_weeks}  -> {target.name}"
                + ("  (c'e' gia': andrebbe nel cestino)" if target.exists() else "")
            )
        print("Niente scritto: --dry-run.")
        raise SystemExit(0)
    existing = sum(1 for week in wanted if (folder / week.file).exists())
    if existing:
        print(
            f"  {existing} di queste ci sono gia' e vanno in {TRASH_FOLDER}/: una settimana si "
            "puo' essere riscritta a mano."
        )
    tally = generate(REPO_ROOT, PLAN_DIR, SUMMARY_DIR, DATA_DIR, goal, wanted)
    if tally["stopped"]:
        print("Un altro lavoro ha il lock (un giro dei report): non faccio niente, rilancia dopo.")
        raise SystemExit(1)
    print(
        f"{len(tally['written'])} scritte, {len(tally['failed'])} scartate, "
        f"{tally['trashed']} nel cestino."
    )
    if tally["failed"]:
        print(
            "Le scartate restano in " + str(folder / STAGING_FOLDER) + ", e al loro posto resta "
            "quello che c'era: una settimana rotta non va in giro."
        )
    print("Adesso leggi le righe qui sopra accanto alla tabella del blocco: i controlli sono "
          "strutturali, l'allenamento lo giudichi tu.")
    raise SystemExit(1 if tally["failed"] else 0)
