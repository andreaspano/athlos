"""Chi scrive i report: il tasto Refresh della Day (todo 41, riscritto dal 44
e dal 47), i due giri di cron e, dal todo 53, anche il report della
settimana.

Dal todo 44 il report non lo scrive piu' un agente solo: ogni sezione ha il
suo (`api/sections.py`) e scrive il proprio frammento nella cartella del
periodo — `summary/01.daily/<giorno>/`, `summary/02.weekly/<lunedi>/`. Qui
c'e' chi li lancia e chi ne tiene lo stato.

**Un ciclo solo per il giorno e per la settimana** (todo 53): cambiano le
sezioni, la cartella, i fatti e la voce, e sono tutte cose che stanno in
`sections.Report`. Due cicli quasi uguali che divergono nel tempo sono il
modo sicuro di avere due difetti diversi.

Dal todo 94 una sezione e' **una chiamata al modello**, non un processo
`claude -p`: il prompt e i documenti li mette insieme questo modulo
(`_prompt` e `_documents`), la chiamata la fa `api/agents.py`, e il frammento
lo scrive `_write_section`. Prima a scriverlo era l'agente, e bisognava
guardare dopo se l'aveva fatto davvero.

Gli agenti girano **in fila**, non insieme: a parita' di lavoro i gettoni
sono gli stessi, ma un giro che va storto si ferma invece di bruciare quello
che resta, e non si rischiano i limiti di frequenza.

Dal todo 47 a lanciare non e' piu' solo il tasto: le righe di cron
(`deploy/crontab`) fanno il giro del mattino e quello della sera, che non
sono uguali, e il lunedi e la domenica ci si attacca la settimana. Da li'
vengono tre cose che il tasto da solo non chiedeva:

- il **momento**, che e' la voce con cui Next e Summary parlano;
- il lock **su file**, perche' il guardiano in memoria vale dentro un solo
  processo e il giro di cron e' un processo diverso dall'API;
- l'esito dello **scaricamento** nello stato, perche' senza nessuno a
  guardare un login scaduto scriverebbe report su dati vecchi in silenzio.

I fatti si preparano **una volta sola** per giro e vanno nel messaggio di
ogni sezione: calcolarli per ognuna vorrebbe dire sei sincronizzazioni del
database e della salute.

Lo stato resta in memoria: se il server si riavvia torna `idle`. Lo stdin e'
chiuso, cosi' un login Garmin scaduto non si ferma ad aspettare una
password."""

import argparse
import contextlib
import fcntl
import math
import subprocess
import threading
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from training.api import agents
from training.api.cache import invalidate
from training.api.plans import week_plan_path
from training.api.sections import (
    DAILY,
    WEEKLY,
    Report,
    Section,
    moment_at,
    week_moment_at,
)
from training.garmin.files import json_text, write_text

# Il tempo per scaricare i dati nuovi da Garmin, prima degli agenti.
UPDATE_TIMEOUT_SECONDS = 15 * 60
# Le righe finali dell'output tenute quando qualcosa fallisce.
MESSAGE_LINES = 5

_lock = threading.Lock()

# Il guardiano "un lavoro alla volta" di `_state` vale dentro **un processo
# solo**: l'API e il comando da terminale (quello che lanciano i timer del
# todo 47) sono processi diversi, e senza questo file partirebbero due
# `make update_activity` e due serie di agenti sugli stessi frammenti. Il
# lock sta nella cartella dei dati, accanto ad `activities.db`, e non si
# aspetta mai: chi lo trova occupato se ne va. Vale anche fra giorno e
# settimana: il giro del lunedi li fa uno dopo l'altro, non insieme.
LOCK_FILENAME = ".refresh.lock"


@contextlib.contextmanager
def _claim(data_dir: Path) -> Iterator[bool]:
    """Prende il lock dei lavori, se e' libero. Rende vero a chi l'ha preso e
    falso a chi l'ha trovato occupato; il file resta, e' il lock a sparire."""
    path = Path(data_dir) / LOCK_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        handle.close()


def _blank_section() -> dict:
    return {"status": "idle", "started": None, "finished": None, "message": None}


def _blank_state() -> dict:
    return {
        "status": "idle",
        "kind": DAILY.name,
        "day": None,
        "moment": None,
        "started": None,
        "finished": None,
        "message": None,
        "download": None,
        "sections": {section.key: _blank_section() for section in DAILY.run_order},
    }


_state: dict = _blank_state()


def status() -> dict:
    """Lo stato del lavoro, una copia: quello d'insieme e quello di ogni
    sezione."""
    with _lock:
        copy = dict(_state)
        copy["sections"] = {key: dict(value) for key, value in _state["sections"].items()}
        return copy


def start(
    subject: date,
    repo_root: Path,
    summary_dir: Path,
    data_dir: Path,
    keys: tuple[str, ...] | None = None,
    kind: Report = DAILY,
) -> dict:
    """Lancia il lavoro per `subject` — un giorno, o il lunedi di una
    settimana — se non ce n'e' gia' uno in corso. Rende lo stato: quello
    nuovo, o quello del lavoro che sta gia' girando.

    `keys` sono le sezioni da rifare, nell'ordine di `kind.run_order`; senza,
    si rifanno tutte: il tasto della pagina vuol dire "rifai tutto" a
    qualunque ora, e i sottoinsiemi dei giri li scelgono i timer."""
    sections = [s for s in kind.run_order if keys is None or s.key in keys]
    with _lock:
        if _state["status"] == "running":
            copy = dict(_state)
            copy["sections"] = {k: dict(v) for k, v in _state["sections"].items()}
            return copy
        now = datetime.now()
        # Prima di sovrascriverlo: serve a sapere se le sezioni che ci sono
        # gia' parlano dello stesso tipo di report.
        was = _state["kind"]
        _state.update(
            status="running",
            kind=kind.name,
            day=subject,
            moment=_moment_of(kind, subject, now),
            started=now,
            finished=None,
            message=None,
            download=None,
        )
        # Le sezioni sono quelle del report che si sta scrivendo: dopo un
        # giro settimanale lo stato non deve raccontare le chiavi del
        # giorno. Quelle che non si rifanno restano com'erano: lo stato dice
        # quello che e' successo l'ultima volta, non una bugia.
        #
        # **Qui non si azzera niente.** Le sezioni che si rifanno le azzera
        # `_run`, dopo aver preso il lock: azzerarle adesso vuol dire perdere
        # il resoconto del giro precedente anche quando questo giro non parte
        # affatto, perche' il lock e' di un altro processo. Un 'load' fallito
        # col suo messaggio diventava sei sezioni 'idle' senza che nessun
        # agente avesse girato.
        known = _state["sections"] if was == kind.name else {}
        _state["sections"] = {
            s.key: known.get(s.key, _blank_section()) for s in kind.run_order
        }
        started = _state["started"]
    thread = threading.Thread(
        target=_run,
        args=(kind, subject, started, repo_root, summary_dir, data_dir, tuple(sections)),
        daemon=True,
    )
    thread.start()
    return status()


def _moment_of(kind: Report, subject: date, when: datetime) -> str:
    """Il momento di default: per il giorno lo da' l'orologio, per la
    settimana il fatto che sia finita o no."""
    if kind is WEEKLY:
        return week_moment_at(subject, when.date())
    return moment_at(when)


def _set(key: str, **fields) -> None:
    with _lock:
        _state["sections"][key].update(**fields)


def _run(
    kind: Report,
    subject: date,
    started: datetime,
    repo_root: Path,
    summary_dir: Path,
    data_dir: Path,
    sections: tuple[Section, ...],
    update: bool = True,
    moment: str | None = None,
) -> dict | None:
    """Il lavoro vero: i dati, i fatti del periodo, gli agenti in fila.

    Rende `None` senza fare niente se un altro lavoro sta gia' girando, qui o
    in un altro processo. Altrimenti rende il **resoconto di questo giro**:
    `message`, `download` e com'e' finita ogni sezione che ha girato.

    Il resoconto e' il valore di ritorno e non lo stato globale, perche' lo
    stato globale ne tiene uno solo — l'ultimo — mentre `backfill` ne legge
    uno per periodo: le sezioni del periodo prima venivano contate come
    scritte in quello dopo.

    Qualunque guasto lascia comunque uno stato terminale (vedi il `finally`):
    lo stato e' l'unico modo che ha la pagina di sapere com'e' andata, e un
    `OSError` da `subprocess`, dalla scrittura dei fatti o da `mkdir` lo
    lasciava a 'running' per sempre, con ogni Refresh successivo rifiutato
    dal guardiano di `start()` fino al riavvio dell'API.

    Il momento e' la voce con cui Next e Summary parlano, non chi gira: di
    suo lo decide `_moment_of`, e lo si puo' imporre per riscrivere una
    sezione con la voce dell'altro giro.

    **La settimana non scarica mai** (todo 53): gira in coda al giro del
    giorno, che ha appena chiamato Garmin, e un secondo scaricamento sarebbe
    solo un'altra occasione di fallire."""
    moment = moment or _moment_of(kind, subject, started)
    update = update and kind.downloads
    # Lo stato deve avere le voci di **questo** report: `start()` le ha gia'
    # messe, ma il comando da terminale chiama `_run` direttamente e senza
    # questo troverebbe le chiavi dell'altro tipo (il primo giro settimanale
    # e' morto cosi', su `KeyError: 'summary_end'`).
    with _lock:
        if _state["kind"] != kind.name:
            _state["kind"] = kind.name
            _state["sections"] = {s.key: _blank_section() for s in kind.run_order}
        else:
            for section in kind.run_order:
                _state["sections"].setdefault(section.key, _blank_section())
    failed: list[str] = []
    message = None
    download = None
    results: dict[str, dict] = {}
    # Se si muore prima di decidere, e' un guasto.
    outcome = "failed"
    claimed = False
    try:
        with _claim(data_dir) as mine:
            if not mine:
                message = "Another refresh is already running."
                return None
            claimed = True
            # Il lock e' nostro: da qui le sezioni che si rifanno ripartono
            # da zero (vedi `start()`).
            with _lock:
                for section in sections:
                    _state["sections"][section.key] = _blank_section()
            ok, problem, download, facts = _prepare(
                kind, subject, repo_root, data_dir, update
            )
            with _lock:
                _state["download"] = download
            if not ok:
                message = problem
            else:
                folder = Path(summary_dir) / kind.folder / subject.isoformat()
                folder.mkdir(parents=True, exist_ok=True)
                # Il piano della settimana (todo 14) lo leggono **due**
                # sezioni, e per due date diverse: Next, che prescrive la
                # seduta del giorno dopo, e Training del giorno (todo
                # 64), che giudica quella di oggi. Il percorso lo sceglie
                # `_prompt` sezione per sezione: la stessa data per
                # entrambe sarebbe sbagliata per una delle due, e la sera
                # i due giorni cadono perfino in settimane diverse.
                # Niente file, nessuna frase nel prompt: un piano che non
                # c'e' non deve diventare un'istruzione da inventare.
                for section in sections:
                    # Chi legge i frammenti degli altri (il Summary) non
                    # gira se in questo giro qualcuno e' fallito: dei
                    # suoi leggerebbe il testo del giro prima e
                    # mescolerebbe due giorni in un verdetto, dichiarando
                    # 'done'. Meglio nessun Summary nuovo che uno falso.
                    if section.reads_fragments and failed:
                        problem = (
                            "not run: " + ", ".join(failed) + " failed in this run"
                        )
                        _set(
                            section.key, status="failed", started=None,
                            finished=datetime.now(), message=problem,
                        )
                        results[section.key] = {"status": "failed", "message": problem}
                        failed.append(section.key)
                        continue
                    began = datetime.now()
                    _set(
                        section.key, status="running", started=began,
                        finished=None, message=None,
                    )
                    good, problem = _write_section(
                        kind, section, subject, moment, repo_root, facts, folder,
                        Path(summary_dir),
                    )
                    _set(
                        section.key,
                        status="done" if good else "failed",
                        finished=datetime.now(),
                        message=problem,
                    )
                    results[section.key] = {
                        "status": "done" if good else "failed",
                        "message": problem,
                    }
                    if not good:
                        failed.append(section.key)
        if failed and not message:
            message = "These sections kept their previous text: " + ", ".join(failed)
        outcome = "failed" if (failed or message) else "done"
        return {"message": message, "download": download, "sections": results}
    except BaseException as exc:
        message = f"The run stopped: {type(exc).__name__}: {exc}"
        raise
    finally:
        # Anche il giro che non e' partito ha il suo stato terminale: lo dice
        # il messaggio, non il silenzio.
        if claimed or message:
            with _lock:
                _state.update(status=outcome, finished=datetime.now(), message=message)


def _jsonable(value):
    """Lo stesso valore con i `NaN` e gli infiniti al posto giusto, cioe'
    `null`.

    `json.dumps` li scrive nudi (`NaN`), che non e' JSON: un parser severo si
    ferma li', e questo file lo leggono gli agenti. Su quaranta giorni e
    dieci settimane dell'archivio ce n'erano otto e sei."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _facts(kind: Report, subject: date, data_dir: Path) -> dict:
    """I fatti del periodo, gli stessi che riceve la pagina."""
    if kind is WEEKLY:
        from training.api.weekly import weekly_payload

        return weekly_payload(subject, data_dir)
    from training.api.daily import daily_payload

    return daily_payload(subject, data_dir)


def _prepare(
    kind: Report,
    subject: date,
    repo_root: Path,
    data_dir: Path,
    update: bool = True,
) -> tuple[bool, str | None, dict | None, dict | None]:
    """Scarica i dati nuovi e rende i fatti del periodo. Rende se si puo'
    andare avanti, l'eventuale motivo per cui no, com'e' andato lo
    scaricamento e i fatti.

    Dal todo 94 i fatti non passano piu' da un file temporaneo: li legge
    `_documents`, che li mette nel messaggio della sezione. Il file c'era
    perche' a leggerlo era un sottoprocesso.

    `update_activity` chiama Garmin: se fallisce (niente rete, login scaduto)
    non ci si ferma, si va avanti con i dati locali. **Ma lo si dice**: da
    quando a lanciare sono i timer (todo 47) non c'e' nessuno a guardare, e
    un login scaduto farebbe scrivere report su dati di tre giorni fa senza
    che niente lo segnali. L'esito finisce in `download`, e da li' nello
    stato che la pagina mostra. Con `update` falso non si chiama affatto: si
    riscrive il testo sui dati che ci sono gia'.

    I fatti sono quelli di `api/daily.daily_payload` e
    `api/weekly.weekly_payload`, cioe' **gli stessi che riceve la pagina**,
    non quelli di `make daily_data`: quel JSON non ha il blocco `fitness`, e
    l'agente di Fitness scriveva che i punteggi non c'erano mentre la card
    accanto li mostrava."""
    download = None
    if update:
        try:
            done = subprocess.run(
                ["make", "update_activity"],
                cwd=repo_root, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=UPDATE_TIMEOUT_SECONDS, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            download = {"ok": False, "message": f"The download could not run: {exc}"}
        else:
            download = {"ok": done.returncode == 0, "message": None}
            if done.returncode != 0:
                download["message"] = (
                    _tail(done) or f"make update_activity exited with {done.returncode}."
                )
        # I file sono cambiati sotto la cache: senza questo i fatti sarebbero
        # quelli di prima dello scaricamento.
        invalidate(data_dir)
    try:
        payload = _facts(kind, subject, data_dir)
    except Exception as exc:  # noqa: BLE001 - qualunque cosa, il lavoro si ferma qui
        return False, f"The facts could not be built: {exc}", download, None
    return True, None, download, _jsonable(payload)


def _plan_text(
    kind: Report,
    section: Section,
    subject: date,
    summary_dir: Path | None,
) -> str | None:
    """Il piano della settimana per chi lo legge, o `None`.

    **Lo legge una sezione sola: il Training del giorno** (todo 64). Giudica
    la seduta di oggi, e senza il piano giudicava solo contro le sedute
    passate — da cui verdetti come «nothing was planned» (vero del file
    dell'orologio) su un giorno che un piano ce l'aveva, e nove chilometri
    lodati dove ne erano previsti cinque.

    Era Next a leggerlo per secondo, per una data diversa — la sera, il
    giorno dopo — e da li' viene il calcolo sezione per sezione invece di uno
    per tutte in `_run`. Next non c'e' piu', ne' nel giorno (todo 66) ne'
    nella settimana (todo 69), e **nessuno prescrive piu' niente**: il piano
    si segue come e' scritto.

    Le altre sezioni il piano non lo vedono: Health, Recovery, Load e Fitness
    raccontano dei numeri, e quello che era previsto non li cambia. Il
    Training della settimana resta fuori: li' il confronto e' con la forma
    dei sette giorni, un'altra domanda.

    Un piano che non c'e' rende `None`, e il prompt torna quello di sempre:
    all'agente non si dice ne' che un piano esiste ne' che non esiste. Dirgli
    "per questo giorno non c'era un piano" sarebbe peggio di tacere — e' la
    frase che sul 27 ottobre ha sviato il verdetto.

    Dal todo 94 si rende il **testo** e non il percorso: il file lo leggeva
    l'agente con un giro di tool, adesso glielo si mette sotto gli occhi. Un
    file che non si legge e' come un piano che non c'e': meglio una sezione
    scritta senza che una sezione non scritta."""
    if summary_dir is None or not section.reads_plan:
        return None
    plan = week_plan_path(summary_dir, subject)
    if plan is None:
        return None
    try:
        return plan.read_text(encoding="utf-8")
    except OSError:
        return None


def _documents(
    kind: Report,
    section: Section,
    subject: date,
    facts: dict,
    folder: Path,
    summary_dir: Path | None,
) -> dict[str, str]:
    """Quello che la sezione ha sotto gli occhi, in blocchi col nome che il
    suo prompt usa: `facts` sempre, `plan` a chi legge il piano, e i
    frammenti accanto a chi scrive un verdetto sugli altri.

    E' esattamente quello che gli agenti andavano a leggere da se'. Misurato
    sui transcript dei giri col sottoprocesso (todo 94), per giro: 1,73
    letture di frammenti dello stesso periodo, 0,74 del file dei fatti e 0,09
    di un periodo passato — cioe' niente che non sia qui.

    I frammenti sono **quelli che in quel momento ci sono**, come la cartella
    li dava a chi la leggeva: uno che manca manca, e uno rimasto dal giro
    prima arriva com'era. Il Summary non gira affatto se in questo giro
    qualcuno e' fallito (vedi `_run`), che e' dove quel caso si decide."""
    documents = {"facts": json_text(facts)}
    plan = _plan_text(kind, section, subject, summary_dir)
    if plan is not None:
        documents["plan"] = plan
    if section.reads_fragments:
        for other in kind.run_order:
            if other.key == section.key:
                continue
            path = folder / f"{other.key}.md"
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if text.strip():
                documents[other.key] = text
    return documents


# La riga del voto, che la Training scrive in cima al suo frammento (todo
# 92): da li' la toglie `_verdict` in `api/app.py`, e diventa la faccia nella
# cornice della card.
#
# **Sta nel prompt e non solo nel file dell'agente** perche' `_style.md` —
# che `agents.system_prompt` attacca *dopo* il file dell'agente — dice "solo
# il corpo, nessun preambolo", e quella riga sembra un preambolo. Provato:
# col solo file dell'agente il frammento tornava senza. Il prompt e' l'ultima
# cosa che l'agente legge ed e' la piu' specifica, e chiedere qui una cosa
# che qui si toglie tiene le due meta' nello stesso posto.
VERDICT_LINE = (
    "Begin your answer with one line, `verdict: ` and one of terrible, low, medium, high, "
    "perfect, then a blank line, then your text. That line is not part of the body: it is "
    "taken off when the report is composed, and becomes the face on your card. Your agent "
    "file says how to choose the word. "
)

# Come si chiede il testo: niente file da scrivere, niente intestazione,
# niente preambolo. Dal todo 94 la risposta **e'** il frammento, e chi
# scrive e' `_write_section`.
ANSWER_LINE = (
    "Answer with the body of the section and nothing else: no `## ` heading, no preamble, "
    "no closing remark."
)


def _prompt(
    kind: Report,
    section: Section,
    subject: date,
    moment: str,
    documents: dict[str, str],
) -> str:
    """Il lavoro della sezione, in coda ai documenti.

    Dal todo 94 nessuna frase nomina un percorso: i fatti, il piano e i
    frammenti sono blocchi del messaggio, e il prompt li chiama per nome. Chi
    legge non ha modo di andare a prendere altro, quindi dirgli dove sta un
    file sarebbe mandarlo contro un muro."""
    answer = f"{VERDICT_LINE}{ANSWER_LINE}" if section.writes_verdict else ANSWER_LINE
    when = kind.moment_lines[moment]
    period = kind.period(subject)
    plan = (
        "The plan for the week is in the `plan` block: the session it lists for "
        f"{subject.isoformat()} is what this one was meant to be. Judge the session "
        "against it as well as against the past ones. "
        if "plan" in documents
        else ""
    )
    if section.reads_fragments:
        others = ", ".join(f"`{name}`" for name in documents if name not in ("facts", "plan"))
        written = (
            f"The other sections are already written, in the {others} blocks: they are your "
            "input. "
            if others
            else ""
        )
        return (
            f"Write the {section.title} part of the {kind.what} for {period}. "
            f"{when} {written}{plan}The facts, if you need them, are in the `facts` block. "
            f"{answer}"
        )
    return (
        f"Write the {section.title} section of the {kind.what} for {period}. "
        f"{when} {plan}The facts are in the `facts` block. {answer}"
    )


def _write_section(
    kind: Report,
    section: Section,
    subject: date,
    moment: str,
    repo_root: Path,
    facts: dict,
    folder: Path,
    summary_dir: Path,
) -> tuple[bool, str | None]:
    """Chiede la sezione al modello e scrive il frammento. Rende se e'
    andata e, se no, perche'.

    **Il file lo scrive chi controlla**, e questa e' la semplificazione del
    todo 94. Col sottoprocesso a scrivere era l'agente, l'esito 0 non
    bastava, e servivano tre controlli dopo — il file c'e', e' di adesso, non
    e' vuoto — perche' un agente poteva finire bene senza aver scritto
    niente. Adesso o c'e' un testo o c'e' un motivo."""
    documents = _documents(kind, section, subject, facts, folder, summary_dir)
    prompt = _prompt(kind, section, subject, moment, documents)
    try:
        text = agents.write(repo_root, section.agent, prompt, documents)
    except agents.AgentError as exc:
        return False, str(exc)
    fragment = folder / f"{section.key}.md"
    try:
        write_text(fragment, text.strip() + "\n")
    except OSError as exc:
        return False, f"{fragment.name} could not be written: {exc}"
    return True, None


def _tail(result: subprocess.CompletedProcess) -> str:
    lines = (result.stderr.strip() or result.stdout.strip()).splitlines()
    return "\n".join(lines[-MESSAGE_LINES:])


def section_keys(
    name: str | None, moment: str | None = None, kind: Report = DAILY
) -> tuple[str, ...] | None:
    """Le chiavi da rifare: una sola col nome di una sezione, quelle del giro
    con un momento, tutte senza niente. Alza `KeyError` su un nome che non
    esiste.

    Il nome di una sezione vince sul momento: chiedere una sezione sola e'
    piu' preciso di chiedere un giro."""
    if name is not None:
        return (kind.by_key[name].key,)
    if moment is not None:
        return kind.moments[moment]
    return None


def _written(folder: Path, key: str, kind: Report = DAILY) -> bool:
    """Vero se la sezione ha gia' un testo, **anche sotto un nome vecchio**.

    I nomi vecchi stanno nel registro (`Report.old_fragments`) e li conosce
    anche chi compone il report (`app._fragment_path`). Qui non li guardava
    nessuno, e il backfill rifaceva il Summary di ogni periodo che l'aveva
    solo come `summary_evening.md` o `summary_end.md`: sul disco sono 89
    giorni e 13 settimane, cioe' un centinaio di sessioni di agente spese per
    riscrivere un testo che c'era."""
    names = (key, *kind.old_fragments.get(key, ()))
    return any(
        (path := folder / f"{name}.md").exists() and path.stat().st_size > 0
        for name in names
    )


def _subjects(kind: Report, start: date, end: date) -> list[date]:
    """I periodi dell'intervallo, dal piu' vecchio: i giorni, o i lunedi."""
    step = kind.step
    current = start
    out = []
    while current <= end:
        out.append(current)
        current += step
    return out


def _last_complete(kind: Report, today: date) -> date:
    """L'ultimo periodo **concluso** prima di `today`: ieri, o il lunedi'
    della settimana prima di quella in corso.

    E' il confine del backfill. I giri del registro (`Report.backfill`)
    aprono con il momento di chiusura — `end` per la settimana, `evening`
    per il giorno — che dice all'agente che il periodo e' finito. Su un
    periodo ancora aperto quella riga e' falsa, e il testo esce come un
    verdetto su qualcosa che deve ancora succedere (todo 56).

    Il confine della settimana e' il lunedi', non le 22 della domenica: a
    chiudere la settimana e' il giro delle 22, e un backfill lanciato dopo
    non deve rifare quello che il timer ha appena scritto."""
    return kind.start_of(today) - kind.step


def backfill(
    kind: Report,
    start: date,
    end: date,
    repo_root: Path,
    summary_dir: Path,
    data_dir: Path,
) -> dict[str, Any]:
    """Riscrive i report di un intervallo nella forma di oggi (todo 50).

    **Salta le sezioni che esistono gia'**, non i periodi: un backfill
    interrotto riprende da dove si era fermato, e rilanciarlo su un periodo
    gia' fatto non costa niente. Per rifare un periodo da capo restano
    `--day`/`--week` e `--section`.

    **Non scarica mai**: i dati storici sono gia' su disco, e una chiamata a
    Garmin per ognuno degli ottanta giorni sarebbe sbagliata.

    **Se il lock e' occupato si ferma**: il giro dei timer ha la precedenza,
    e il backfill si rilancia dopo. Rende il riepilogo — periodi toccati,
    sezioni scritte, saltate e fallite — e dice se si e' fermato."""
    subjects = _subjects(kind, start, end)
    # I periodi non ancora conclusi si lasciano fuori, e si contano: un
    # backfill che annuncia otto settimane e ne riscrive sette deve dirlo.
    limite = _last_complete(kind, date.today())
    left_out = [s for s in subjects if s > limite]
    subjects = [s for s in subjects if s <= limite]
    tally: dict[str, Any] = {
        "subjects": len(subjects), "written": 0, "skipped": 0,
        "failed": [], "stopped": None, "touched": 0,
        "left_out": len(left_out),
    }
    for index, subject in enumerate(subjects):
        folder = Path(summary_dir) / kind.folder / subject.isoformat()
        worked = False
        for moment, keys in kind.backfill:
            missing = [k for k in keys if not _written(folder, k, kind)]
            tally["skipped"] += len(keys) - len(missing)
            if not missing:
                continue
            sections = tuple(s for s in kind.run_order if s.key in missing)
            started = datetime.now()
            outcome = _run(
                kind, subject, started, repo_root, summary_dir, data_dir,
                sections, update=False, moment=moment,
            )
            if outcome is None:
                tally["stopped"] = subject
                return tally
            worked = True
            # Il resoconto e' quello di **questo** periodo. Leggendolo dallo
            # stato globale, un periodo in cui `_prepare` era fallito — e
            # quindi nessuna sezione aveva girato — si contava con gli stati
            # 'done' del periodo prima: sei sezioni scritte, cartella mai
            # creata, e il comando usciva 0 annunciando il successo.
            for section in sections:
                row = outcome["sections"].get(section.key)
                if row and row["status"] == "done":
                    tally["written"] += 1
                else:
                    reason = (row or {}).get("message") or outcome["message"] or "non scritta"
                    tally["failed"].append(f"{subject} {section.key}: {reason}")
        tally["touched"] += int(worked)
    return tally


def _day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"data non valida: {text!r} (serve YYYY-MM-DD)")


def _backfill_cli(kind: Report, args, last: date, parser: argparse.ArgumentParser) -> None:
    """Il ramo `--from` del comando: cicla l'intervallo e esce.

    Non convive con `--section` ne' con `--moment`: quelli scelgono cosa
    rifare di un periodo solo, qui i giri li decide il registro
    (`Report.backfill`)."""
    from training.api.context import REPO_ROOT, SUMMARY_DIR
    from training.garmin.config import DATA_DIR

    if args.section or args.moment:
        parser.error("--from non si usa insieme a --section o --moment")
    # Il soggetto di un periodo solo non si usa con un intervallo: prima
    # veniva ignorato in silenzio, cioe' `--day 2026-10-01 --from 2026-09-01`
    # faceva una cosa diversa da quella che si era chiesta senza dirlo.
    subject_flag = "--week" if kind is WEEKLY else "--day"
    if getattr(args, subject_flag.lstrip("-")) is not None:
        parser.error(f"{subject_flag} non si usa insieme a --from")
    # Il backfill riscrive periodi **conclusi**: il presente lo scrive gia'
    # il comando senza `--from`, che e' quello che lanciano i timer.
    ultimo = _last_complete(kind, date.today())
    start, end = args.start, args.end or ultimo
    if kind is WEEKLY:
        if start.weekday() != 0 or end.weekday() != 0:
            parser.error("con --from e --to servono due lunedi'")
    if end < start:
        parser.error(f"l'intervallo e' al contrario: {start} ... {end}")
    if end > ultimo:
        quello = "la settimana" if kind is WEEKLY else "il giorno"
        comando = "training-weekly-report" if kind is WEEKLY else "training-daily-report"
        parser.error(
            f"il backfill arriva al {ultimo}, l'ultimo periodo finito: {quello} dopo e'"
            f" ancora in corso, e chiuderla adesso vorrebbe dire giudicarla prima del"
            f" tempo. Per il presente c'e' {comando} senza --from."
        )

    quanti = len(_subjects(kind, start, end))
    quale, tocchi = ("settimane", "toccate") if kind is WEEKLY else ("giorni", "toccati")
    print(f"Riscrivo {quanti} {quale}, dal {start} al {end}. Le sezioni gia' scritte si saltano.")
    tally = backfill(kind, start, end, REPO_ROOT, SUMMARY_DIR, DATA_DIR)
    print(
        f"  {tally['touched']} {quale} {tocchi}, {tally['written']} sezioni scritte, "
        f"{tally['skipped']} gia' c'erano"
    )
    if tally["left_out"]:
        print(
            f"  {tally['left_out']} {quale} lasciate fuori: non sono ancora finite."
            if kind is WEEKLY
            else f"  {tally['left_out']} giorni lasciati fuori: non sono ancora finiti."
        )
    if tally["failed"]:
        print(f"  {len(tally['failed'])} fallite: " + ", ".join(tally["failed"][:10]))
    if tally["stopped"]:
        print(
            f"  Fermato al {tally['stopped']}: un altro lavoro ha il lock. "
            "Rilancia lo stesso comando quando ha finito, riprende da li'."
        )
    raise SystemExit(1 if (tally["failed"] or tally["stopped"]) else 0)


def _cli(kind: Report) -> None:
    """Rifa' un report da terminale, senza passare dall'API.

    Lo stesso lavoro del tasto Refresh, ma in primo piano e senza server:
    serve per rifare un report a mano, per provare l'impianto, ed e' quello
    che lanciano i timer (`--moment`, todo 47 e 53). Stampa come e' andata
    sezione per sezione, ed esce 1 se qualcuna e' fallita **o se i dati non
    si sono scaricati** (todo 81).

    Se un altro lavoro sta gia' girando — il tasto della pagina, o il giro
    di cron dell'altro momento — non si mette in coda: lo dice ed esce 0,
    cosi' nel registro un accavallamento non si legge come un guasto."""
    from training.api.context import REPO_ROOT, SUMMARY_DIR
    from training.garmin.config import DATA_DIR

    weekly = kind is WEEKLY
    parser = argparse.ArgumentParser(
        description=f"Rifa' il report {'settimanale' if weekly else 'giornaliero'}, "
        "una sezione o tutte."
    )
    parser.add_argument(
        "--week" if weekly else "--day",
        type=_day,
        help="il lunedi della settimana (YYYY-MM-DD); di default quella di oggi"
        if weekly
        else "il giorno (YYYY-MM-DD); di default oggi",
    )
    parser.add_argument("--section", help="una sola sezione: " + ", ".join(kind.by_key))
    parser.add_argument(
        "--moment",
        choices=tuple(kind.moments),
        help="il giro di un timer invece di tutte le sezioni ("
        + "; ".join(f"{name} = {', '.join(keys)}" for name, keys in kind.moments.items())
        + "). Da' anche la voce a Next e Summary, che senza la prendono "
        "dal periodo: con --section riscrive quella sezione sola con la "
        "voce del giro scelto.",
    )
    if not weekly:
        parser.add_argument(
            "--no-update",
            action="store_true",
            help="non richiamare Garmin: riscrive il testo sui dati che ci sono gia'",
        )
    quale = "il lunedi" if weekly else "il giorno"
    parser.add_argument(
        "--from",
        dest="start",
        type=_day,
        help=f"riscrive tutto l'intervallo invece di un periodo solo: {quale} da cui "
        "partire (todo 50). Salta le sezioni che esistono gia' e non scarica niente.",
    )
    parser.add_argument(
        "--to",
        dest="end",
        type=_day,
        help="l'ultimo dell'intervallo di --from; di default l'ultimo possibile",
    )
    args = parser.parse_args()
    today = date.today()
    if weekly:
        # Di default la settimana di oggi: il giro del lunedi apre quella
        # che comincia, quello della domenica chiude quella che finisce in
        # giornata, e sono la stessa. Per una settimana vecchia, `--week`.
        subject = args.week or (today - timedelta(days=today.weekday()))
        if subject.weekday() != 0:
            parser.error(f"il {subject} non e' un lunedi'")
        if subject > today:
            parser.error(f"la settimana del {subject} non e' ancora cominciata")
    else:
        subject = args.day or today
        if subject > today:
            parser.error(f"il {subject} non e' ancora arrivato")
    if args.start:
        _backfill_cli(kind, args, subject, parser)
    try:
        keys = section_keys(args.section, args.moment, kind)
    except KeyError:
        parser.error(
            f"sezione sconosciuta: {args.section!r} (ce ne sono {', '.join(kind.by_key)})"
        )
    sections = tuple(s for s in kind.run_order if keys is None or s.key in keys)

    what = f"della settimana del {subject}" if weekly else f"del {subject}"
    print(f"Report {what}: {len(sections)} sezioni, una alla volta.")
    outcome = _run(
        kind,
        subject,
        datetime.now(),
        REPO_ROOT,
        SUMMARY_DIR,
        DATA_DIR,
        sections,
        not getattr(args, "no_update", False),
        args.moment,
    )
    if outcome is None:
        # Esce 1, non 0: il report di questo periodo **non e' stato scritto**,
        # e chi lancia e' un timer con `OnFailure=mygarmin-alert@`. Uscendo 0
        # systemd registrava un successo per un giro che non ha fatto niente,
        # che e' lo stesso silenzio sui dati vecchi che il docstring di
        # `_prepare` dice di non voler permettere.
        print("Ce n'e' gia' uno in corso: non faccio niente.")
        raise SystemExit(1)
    if outcome["download"] and not outcome["download"]["ok"]:
        print(f"  dati     non scaricati  {outcome['download']['message']}")
    for section in sections:
        row = outcome["sections"].get(section.key) or {"status": "non girata", "message": None}
        note = f"  {row['message']}" if row["message"] else ""
        print(f"  {section.key:15} {row['status']}{note}")
    print(outcome["message"] or "Fatto.")
    # Esce 1 anche quando lo scaricamento e' fallito, non solo quando e'
    # fallita una sezione (todo 81). Il report c'e' lo stesso — `_prepare`
    # va avanti con i dati locali apposta — ma e' scritto su dati che non
    # sono quelli di oggi, e chi lancia deve poterlo sapere senza leggere
    # il registro: il 21 ottobre due giri hanno scritto su dati vecchi
    # (`uv: not found`) uscendo 0, e non se n'e' accorto nessuno.
    download = outcome["download"]
    stale = bool(download) and not download["ok"]
    broken = bool(outcome["message"]) or any(
        row["status"] != "done" for row in outcome["sections"].values()
    )
    raise SystemExit(1 if broken or stale else 0)


def main() -> None:
    """Il report del giorno da terminale (`training-daily-report`)."""
    _cli(DAILY)


def week_main() -> None:
    """Il report della settimana da terminale (`training-weekly-report`)."""
    _cli(WEEKLY)
