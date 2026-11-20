"""Il ciclo che tara i prompt del modello di casa contro i testi di Claude.

Per tre giorni ho fatto a mano quello che fa questo modulo: generare una
sezione, leggerla, capire cosa non torna, cambiare una riga di prompt,
rigenerare, e tenere la versione buona. Ha funzionato — la notte scritta nella
scrittura giusta, i due body battery separati, la persona raddrizzata — ma
guardava un giorno alla volta, e il «prima» di ogni modifica l'ho tenuto in uno
scratchpad che poi ho buttato.

```
giro 0   genera i giorni del corpus coi prompt di adesso e misura
         misura anche i frammenti di Claude -> il pavimento realistico
giro N   mostra a un agente Claude i casi peggiori dei giorni di taratura
         quello cambia UNA cosa in `.ollama/agents/`
         si rigenera solo quello che quel file tocca
         si rimisura
         se peggiora -> si rimettono i prompt di prima, modifica respinta
         se migliora -> si tiene, e diventa il migliore
fine     quando il punteggio dei giorni tenuti da parte scende sotto quello di
         Claude, o non migliora per tre giri, o finiscono i giri
         e **si ripristina il migliore, non l'ultimo**
```

**Respingere i peggioramenti non e' un lusso.** Tarando a mano ho provato a
togliere un campo dai fatti dell'apertura, e una mattina con due buone notizie
e' diventata *«resting heart rate is much worse than usual»*: il contrario dei
fatti. L'ho ripristinato io. Un ciclo che non lo sa fare arriva al decimo giro
peggiore del primo.

**Una modifica per giro**, non una riscrittura: se un giro cambia tre file non
si sa quale ha spostato il punteggio. Ed e' anche quello che lo rende
economico, perche' rigenerare la sola sezione toccata sono tre minuti invece di
venti (`bench.reusable`).

**L'editor puo' scrivere solo in `.ollama/agents/`**, e la guardia non e' una
raccomandazione: e' la regola dei permessi di `claude -p`, la stessa con cui
`refresh` lascia a un agente del report la sua sola cartella. I prompt di
Claude sono il bersaglio e restano intoccabili; il Python nemmeno si discute.

## La prima notte

Quattro giri, tutti tenuti, e si e' fermato da se' quando il punteggio dei
giorni tenuti da parte e' passato sotto quello di Claude:

```
giro 0   0,419            errori gravi 24
giro 1   0,378   _score.md       i numeri dei punteggi via
giro 2   0,353   _threshold.md   la data della lettura a parole
giro 3   0,269   _verdict.md     la persona, spostata in fondo al file
                 (pavimento di Claude: 0,320)
```

**Ma il titolo onesto non e' «llama ha raggiunto Claude».** Tutte e quattro le
modifiche sono in `04_fitness_split/`, e il guadagno e' tutto di una sezione:
Fitness da 0,796 a 0,336 con gli errori gravi a zero, mentre Health, Load e
Recovery non si sono mosse di un millesimo perche' i loro file non sono stati
toccati. La Fitness era rotta e il ciclo l'ha riparata; il traguardo e' caduto
perche' quella sezione pesava per meta' del punteggio. La Recovery ha ancora i
suoi dodici errori gravi e aspetta un giro suo (`--sections recovery_split`).

**E il punteggio sopravvaluta il guadagno.** Letti i due testi dello stesso
giorno, un paragrafo e' migliorato e uno e' peggiorato. La soglia prima diceva
*«it's worth noting that this measure doesn't have a corresponding pace»* — una
frase su un campo mancante — e dopo *«it sets the pace for harder efforts in
training»*, che e' un giudizio. Il VO2max invece diceva *«your engine is bigger
than it has been in the last month»* e adesso dice *«which means it's better
than usual»*, che e' il campo `reading` riletto ad alta voce: la cifra e'
andata via e con lei la frase che valeva. Le parole medie sono ferme (165,7 ->
168,7), quindi non e' un impoverimento generale — ma su quel paragrafo la
perdita e' reale, e **nessuna delle due misure la vede**. E' il motivo per cui
l'ultimo passo della verifica e' leggere i testi e non la curva.

Due cose invece hanno tenuto. **Niente adattamento al corpus**: il punteggio
dei giorni tenuti da parte (0,269) e' migliore di quello di taratura (0,297), e
se il ciclo avesse imparato i sedici giorni sarebbe il contrario. **E la
distanza e' ferma a 0,77** per tutti e quattro i giri: era la guardia contro un
editor che fa imitare la voce di Claude invece di correggere, e non e'
scattata.

**Tre delle quattro modifiche hanno tolto una regola che avevo scritto io**, e
due hanno applicato lezioni che stanno nei commenti di questo stesso progetto:
le regole attaccano in fondo al messaggio e non in mezzo a un prompt lungo
(`MEASURE_READS`), e una regola che cita la frase sbagliata la insegna
(`RECOVERY_TAIL`). Il ciclo non ha scoperto come si scrive un report: ha
trovato i punti in cui i miei prompt contraddicevano quello che il progetto
aveva gia' imparato.
"""

import argparse
import os
import shutil
import subprocess
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from training.api import bench, bench_score, ollama, refresh
from training.garmin.files import write_text

# Le sezioni che il ciclo tara di suo: **le quattro spezzate**.
#
# Le quattro intere restano fuori, e la ragione e' nei numeri del primo giro.
# Il controllo della lunghezza spara 48 volte su 50 testi interi, perche' i
# prompt interi di llama chiedono cinque o sei paragrafi e llama ne scrive uno.
# E' un guasto vero e non un falso positivo — ma e' **il guasto per cui le
# sezioni spezzate esistono**: la forma che un prompt non riesce a far
# rispettare la impone Python, cucendo una risposta per paragrafo. Lasciarle
# dentro vorrebbe dire far spendere all'editor i suoi giri a rifare una
# battaglia che era gia' stata persa e aggirata, e con meta' degli errori
# leggeri che vengono da li' ci spenderebbe i primi.
#
# Restano chiedibili con `--sections health,load`: sono il termine di
# paragone, e sulla pagina la Health e la Load intere si vedono ancora accanto
# alle loro spezzate.
DEFAULT_SECTIONS = ("health_split", "load_split", "recovery_split", "fitness_split")

# Il primo giorno in cui i prompt di Claude sono quelli di adesso: l'ultimo
# cambio e' del 26 ottobre alle 18:03 e il frammento della Load di quel giorno
# e' nato alle 22:00. Prima di questa data il bersaglio e' un altro prompt, e
# un bersaglio che si muove non e' un bersaglio.
CORPUS_FROM = date(2026, 10, 26)

# **E l'ultimo.** Dal 21 novembre le quattro card del corpo le scrive il
# modello di casa (`sections.LOCAL_FROM`), quindi da quel giorno il file
# `summary/01.daily/<giorno>/health.md` — che `bench.claude_text` legge come
# bersaglio — non e' piu' di Claude: e' di llama.
#
# Senza questa riga il primo giro di domani prenderebbe il 21 novembre e
# metterebbe come bersaglio il testo del modello stesso: distanza zero, nessun
# errore nel bersaglio, e un pavimento che non vuol dire niente. Il ciclo
# starebbe tarando ollama contro ollama e il punteggio migliorerebbe da solo.
#
# Il confronto, quindi, e' chiuso e il corpus e' quello che e': 26 giorni e
# 104 testi bersaglio, che restano sul disco e dentro ogni riga del quaderno.
# Il ciclo ci gira sopra quanto si vuole; di giorni nuovi non ne arrivano.
CORPUS_TO = date(2026, 11, 20)

# Un giorno su tre sta fuori dalla taratura. Deterministico e non gli ultimi
# otto: in coda ci sarebbe dentro l'andamento del tempo, e il ciclo imparerebbe
# il novembre invece del mestiere.
HELD_OUT_EVERY = 3

# Quanti casi si mostrano all'editor, **per sezione**.
#
# Era dieci in assoluto, e la prima notte ha fatto vedere perche' non va: la
# Fitness era la peggiore e si e' presa tutti e dieci i posti per quattro giri
# di fila. Le sue quattro modifiche l'hanno portata da 0,796 a 0,336, e nel
# frattempo la Recovery — dodici errori gravi, la seconda peggiore — non e'
# mai entrata nella stanza, perche' i suoi casi non arrivavano mai fra i dieci
# peggiori del mucchio.
#
# **Una sezione cattiva-ma-non-peggiore non si guarda mai**, finche' la prima
# non e' a posto. Tre per sezione invece di dieci in tutto: con quattro sezioni
# fanno dodici casi, il messaggio passa da 19 a 23 kilobyte, e ognuna che ha
# errori entra. Cosi' la Recovery non ha bisogno di un giro dedicato.
WORST_PER_SECTION = 3

# Quanti giri senza miglioramento prima di smettere.
PATIENCE = 3

# L'editor e' un agente Claude e ha dieci minuti, come quelli del report
# (`refresh.TIMEOUT_SECONDS`).
EDITOR_TIMEOUT = 10 * 60

# Quanti minuti si aspetta che il lucchetto dei report si liberi. Mezz'ora:
# un giro di report ne dura di meno, e se dopo mezz'ora e' ancora occupato c'e'
# qualcosa che non va e non e' il caso di insistere in silenzio.
WAIT_FOR_LOCK = 30

# La cartella dei prompt che l'editor puo' toccare, e la sola.
AGENT_DIR = ".ollama/agents"


def _say(message: str) -> None:
    """Stampa l'avanzamento, **spingendolo fuori subito**.

    `weekplans.generate` si accontenta di `say=print` perche' gira in primo
    piano, dove lo stdout e' un terminale e va a righe. Questo ciclo gira
    rediretto su un file o nel journal, dove Python bufferizza a blocchi da
    otto kilobyte: la prima volta che l'ho lanciato per venti minuti il log e'
    rimasto vuoto fino alla fine, che su un lavoro da notte vuol dire non
    sapere se sta girando o se e' morto."""
    print(message, flush=True)


def bounded(end: date, say=_say) -> date:
    """L'ultimo giorno che si puo' misurare, che non e' sempre quello chiesto.

    Il bersaglio finisce dove Claude ha smesso di scrivere quelle quattro
    sezioni (`CORPUS_TO`). Chiedendo un giorno dopo, il ciclo leggerebbe come
    bersaglio il testo del modello di casa e starebbe misurando ollama contro
    se stesso: distanza zero, nessun errore nel bersaglio, e un punteggio che
    scende da solo.

    **E quando taglia lo dice.** Un corpus che si accorcia in silenzio sembra
    il corpus che hai chiesto, e tutti i numeri che ne escono sembrano di
    venticinque giorni quando sono di venti."""
    if end <= CORPUS_TO:
        return end
    say(
        f"il bersaglio finisce il {CORPUS_TO}: da li' in poi quei frammenti "
        f"li scrive il modello di casa, non Claude. Mi fermo a {CORPUS_TO}."
    )
    return CORPUS_TO


def corpus(start: date, end: date) -> "list[date]":
    return [start + timedelta(n) for n in range((end - start).days + 1)]


def held_out(days: "list[date]") -> "set[date]":
    """I giorni che la taratura non vede. Uno su tre per indice, quindi sparsi
    in tutto il periodo e sempre gli stessi fra un giro e l'altro: un insieme
    di prova che cambia non misura niente."""
    return {day for n, day in enumerate(days) if n % HELD_OUT_EVERY == 0}


def _facts_of(day: date, data_dir: Path, summary_dir: Path):
    """I fatti del giorno e il piano della sua settimana, una volta per
    giorno: le sei sezioni li ritagliano dallo stesso payload, e rileggerlo sei
    volte sarebbe sei volte lo stesso lavoro."""
    from training.api.daily import daily_payload
    from training.api.plans import load_week_plan

    return daily_payload(day, data_dir), load_week_plan(summary_dir, day)


def generate(
    *,
    run: str,
    iteration: int,
    days: "list[date]",
    sections: "tuple[str, ...]",
    repo_root: Path,
    data_dir: Path,
    summary_dir: Path,
    known: "list[dict[str, Any]]",
    model: str,
    say=_say,
) -> "list[dict[str, Any]]":
    """Un giro di generazione: una riga per (giorno, sezione), col punteggio
    dentro.

    **Quello che non e' cambiato non si rigenera.** A temperatura zero gli
    stessi prompt sugli stessi fatti rendono lo stesso testo, quindi se
    l'impronta dei prompt di quella sezione e' la stessa di una riga che c'e'
    gia' si riusa il testo e si salta la domanda. Dopo una modifica a un file
    solo, cinque sezioni su sei passano da qui senza chiamare niente — ed e' il
    motivo per cui un giro costa tre minuti e non venti.

    Una riga riusata tiene i suoi `seconds`: sono il tempo della volta in cui
    e' stata scritta davvero, che e' l'unico che vuol dire qualcosa."""
    out = []
    prompts = {key: bench.fingerprint(repo_root, ollama.SECTIONS[key]) for key in sections}
    reused = 0
    for day in days:
        payload, week = _facts_of(day, data_dir, summary_dir)
        for key in sections:
            section = ollama.SECTIONS[key]
            facts = section.facts(payload, week)
            claude = bench.claude_text(summary_dir, day, section)
            old = bench.reusable(known, day, key, prompts[key], model)
            if old:
                text, seconds = old["ollama"], old["seconds"]
                reused += 1
            else:
                began = time.monotonic()
                try:
                    text, _ = ollama.section_text(section, day, payload, repo_root, week)
                except ollama.OllamaError as exc:
                    say(f"  {day} {key:16} non risponde: {exc}")
                    continue
                seconds = round(time.monotonic() - began, 1)
                say(f"  {day} {key:16} {seconds}s")
            marks = bench_score.score(section, facts, text, claude)
            out.append(
                {
                    **bench.row(
                        run=run,
                        iteration=iteration,
                        day=day,
                        section_key=key,
                        model=model,
                        prompts=prompts[key],
                        seconds=seconds,
                        ollama_text=text,
                        claude=claude,
                        held_out=day in held_out(days),
                    ),
                    **marks,
                }
            )
    if reused:
        say(f"  ({reused} righe riusate, l'impronta dei prompt non era cambiata)")
    return out


def measure(rows: "list[dict[str, Any]]") -> "dict[str, Any]":
    """Il punteggio di un giro, diviso fra i giorni di taratura e quelli tenuti
    da parte.

    **La media per testo e non la somma**, o un giro che genera meno righe —
    una sezione che non ha risposto — sembrerebbe migliore.

    `score` sono i soli errori; la distanza dal bersaglio sta accanto e non
    dentro (`bench_score`, in cima)."""

    def over(chosen):
        if not chosen:
            return {"score": 0.0, "hard": 0, "soft": 0, "distance": 0.0, "texts": 0}
        return {
            "score": round(sum(r["score"] for r in chosen) / len(chosen), 3),
            "hard": sum(len(r["faults"]) for r in chosen),
            "soft": sum(len(r["soft"]) for r in chosen),
            # **Fuori dal punteggio, dentro la pagella.** Se questa scende
            # mentre `score` non si muove, l'editor sta facendo imitare la voce
            # di Claude invece di correggere quello che non torna.
            "distance": round(sum(r["distance"] for r in chosen) / len(chosen), 3),
            "texts": len(chosen),
        }

    return {
        "train": over([r for r in rows if not r["held_out"]]),
        "held": over([r for r in rows if r["held_out"]]),
        "by_section": {
            key: round(
                sum(r["score"] for r in rows if r["section"] == key)
                / max(1, sum(1 for r in rows if r["section"] == key)),
                3,
            )
            for key in sorted({r["section"] for r in rows})
        },
        "by_fault": dict(
            Counter(f.split(":")[0] for r in rows for f in (*r["faults"], *r["soft"])).most_common()
        ),
    }


def claude_floor(
    days: "list[date]", repo_root: Path, data_dir: Path, summary_dir: Path
) -> "dict[str, Any]":
    """Il pavimento: quanto prendono i frammenti di Claude agli stessi
    controlli.

    **E' la soglia d'arrivo, e non e' un numero inventato.** «Simili» vuol dire
    *gli errori di ollama non sono piu' di quelli di Claude*, e quel numero lo
    dicono i dati.

    E il confronto e' fra cose confrontabili perche' da tutti e due i lati il
    punteggio sono i soli errori: la distanza, che Claude contro se stesso non
    ha, sta fuori (`bench_score`, in cima). Col primo peso che le avevo dato la
    soglia era irraggiungibile per costruzione. Misurato sul corpus di ottobre
    e novembre: 32 errori gravi su 104 testi, tutti numeri che nei fatti non
    c'erano — un passo di soglia portato avanti per diciassette giorni quando
    il lattato non era stato rilevato, e quattro body battery sbagliati.
    Nessun errore leggero.

    **I controlli sono quelli delle sezioni spezzate**, e per un po' erano
    quelli delle intere: finche' il banco le teneva, un frammento di Claude —
    che e' un blocco solo, come lo chiedeva l'intera — si misurava con quelle.
    Non e' una perdita di rigore: i controlli che hanno bisogno di sapere di
    chi e' un paragrafo (la misura non sua, la lettura contraddetta) su un
    testo che di paragrafi ne ha uno si fermano da se', ed e' esattamente
    quello che `score` fa da sempre quando misura lo stesso frammento come
    bersaglio di una riga del quaderno. Quelli che mordono — i numeri
    inventati, i codici di Garmin, la persona sbagliata — guardano il testo
    intero e non cambiano."""
    totals = []
    for day in days:
        payload, week = _facts_of(day, data_dir, summary_dir)
        for key in DEFAULT_SECTIONS:
            section = ollama.SECTIONS[key]
            text = bench.claude_text(summary_dir, day, section)
            if not text:
                continue
            facts = section.facts(payload, week)
            totals.append(bench_score.score(section, facts, text))
    hard = sum(len(t["faults"]) for t in totals)
    soft = sum(len(t["soft"]) for t in totals)
    return {
        "texts": len(totals),
        "hard": hard,
        "soft": soft,
        "score": round(sum(t["score"] for t in totals) / max(1, len(totals)), 3),
    }


def _snapshot_dir(data_dir: Path, run: str, iteration: int) -> Path:
    """Lo scatto preso **prima** che l'editor tocchi niente, a ogni giro: e'
    quello che si rimette quando una modifica va respinta."""
    return Path(data_dir) / "bench" / "tuning" / run / f"{iteration:02d}" / "agents"


def _best_dir(data_dir: Path, run: str) -> Path:
    """Lo scatto del migliore, e **serve una cartella sua**.

    Il primo giro sbagliava qui: ripristinava alla fine lo scatto del giro
    migliore, che e' lo stato *prima* della modifica di quel giro — cioe'
    buttava via proprio la modifica che l'aveva fatto vincere. Gli scatti per
    giro servono a respingere, che guarda indietro; tenere il migliore vuole
    uno scatto preso *dopo* una modifica accettata, e quindi un posto suo."""
    return Path(data_dir) / "bench" / "tuning" / run / "best" / "agents"


def snapshot(repo_root: Path, where: Path) -> None:
    """Una copia dei prompt prima di toccarli. E' il meccanismo con cui una
    modifica si respinge e con cui alla fine si ripristina il migliore."""
    where.parent.mkdir(parents=True, exist_ok=True)
    if where.exists():
        shutil.rmtree(where)
    shutil.copytree(Path(repo_root) / AGENT_DIR, where)


def restore(where: Path, repo_root: Path) -> "list[str]":
    """Rimette i prompt come stavano nello scatto, e dice quali file ha
    toccato.

    **File per file e non con un `rmtree`.** Cancellare la cartella e
    ricopiarla lascerebbe, per un istante, un `.ollama/agents/` senza i prompt:
    se il processo muore li' in mezzo il repo resta rotto. Scrivendo un file
    per volta con `write_text` — che passa da un temporaneo e da `os.replace` —
    la cartella non e' mai in uno stato in cui un prompt manca. I file che
    l'editor ha aggiunto si levano, che se no una modifica respinta ne
    lascerebbe un pezzo."""
    live = Path(repo_root) / AGENT_DIR
    touched = []
    saved = {p.relative_to(where): p for p in where.rglob("*.md")}
    for name, source in saved.items():
        target = live / name
        text = source.read_text(encoding="utf-8")
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text(target, text)
            touched.append(str(name))
    for path in live.rglob("*.md"):
        if path.relative_to(live) not in saved:
            path.unlink()
            touched.append(f"{path.relative_to(live)} (aggiunto, levato)")
    return touched


def changed_since(repo_root: Path, where: Path) -> "list[str]":
    """Quali file di prompt l'editor ha cambiato rispetto allo scatto."""
    live = Path(repo_root) / AGENT_DIR
    saved = {p.relative_to(where): p.read_text(encoding="utf-8") for p in where.rglob("*.md")}
    now = {p.relative_to(live): p.read_text(encoding="utf-8") for p in live.rglob("*.md")}
    return sorted(
        str(name) for name in set(saved) | set(now) if saved.get(name) != now.get(name)
    )


def _case(row: "dict[str, Any]") -> str:
    """Un caso come lo legge l'editor: i due testi e cosa non torna."""
    faults = "\n".join(f"  - {f}" for f in (*row["faults"], *row["soft"])) or "  - (nessuno)"
    target = row["claude"] or "(non c'e')"
    return (
        f"### {row['day']} — {row['section']} (punteggio {row['score']})\n"
        f"Errori trovati:\n{faults}\n\n"
        f"**Quello che ha scritto il modello di casa:**\n{row['ollama']}\n\n"
        f"**Quello che ha scritto Claude (il bersaglio):**\n{target}\n"
    )


def editor_prompt(
    summary: "dict[str, Any]", floor: "dict[str, Any]", rows: "list[dict[str, Any]]"
) -> str:
    """Il messaggio per l'agente che cambia i prompt.

    I casi sono **solo dei giorni di taratura**: quelli tenuti da parte servono
    a misurare, e un editor che li vede li impara."""
    # I peggiori **di ogni sezione**, e non del mucchio: il perche' sta accanto
    # a `WORST_PER_SECTION`. Ordinati per punteggio alla fine, cosi' l'editor
    # legge comunque il peggiore per primo.
    scelti = []
    for key in sorted({r["section"] for r in rows}):
        suoi = [r for r in rows if r["section"] == key and not r["held_out"] and r["score"] > 0]
        scelti += sorted(suoi, key=lambda r: -r["score"])[:WORST_PER_SECTION]
    worst = sorted(scelti, key=lambda r: -r["score"])
    sections = "\n".join(f"  {k:16} {v}" for k, v in summary["by_section"].items())
    faults = "\n".join(f"  {k:30} {v}" for k, v in summary["by_fault"].items())
    cases = "\n".join(_case(r) for r in worst)
    return (
        "You are tuning the prompts of a local model so that it writes the sections of "
        "a daily training report as well as the Claude agent does.\n\n"
        "The prompts live in `.ollama/agents/`. **That directory is the only thing you "
        "may edit**, and the permission rules enforce it: the prompts in "
        "`.claude/agents/` are the target and must not change, and neither must any "
        "Python.\n\n"
        f"## Where it stands\n\n"
        f"Score per text, tuning days: {summary['train']['score']} — **the faults, and "
        f"only the faults**: {summary['train']['hard']} hard and "
        f"{summary['train']['soft']} soft over {summary['train']['texts']} texts.\n"
        f"The Claude fragments, measured the same way, score "
        f"{floor['score']} ({floor['hard']} hard faults over {floor['texts']} texts). "
        "**That is the floor, not zero**: the target is not perfect either.\n\n"
        f"By section:\n{sections}\n\nBy kind of fault:\n{faults}\n\n"
        f"The texts also sit {summary['train']['distance']} away from the Claude ones by "
        "a plain string distance. **That number is not the target and it is not in the "
        "score**: two writers can say the same thing in different words, and the "
        "shortest way to shrink it is to make the local model impersonate Claude's "
        "voice, which is not what any of this is for. It is here so you can see it; "
        "if it falls while the faults do not, the change was imitation.\n\n"
        f"## The worst cases, a few from each section\n\n{cases}\n"
        "## What to do\n\n"
        "**Make exactly one change**, to one file, and make it the change that the "
        "evidence above argues for. Not a rewrite: one rule added, moved or reworded. "
        "A change to several files at once cannot be told apart by the next "
        "measurement, and a change the evidence does not support is a guess.\n\n"
        "Things this project has already learned the hard way, so you do not pay for "
        "them again:\n"
        "- **An explanation in a prompt is an example.** Rules that explain *why* get "
        "copied into the card word for word. State the constraint, not the reasoning.\n"
        "- **Naming the mistake teaches it.** A rule that quotes the bad phrase tends "
        "to produce the bad phrase. Say what to write, not what not to.\n"
        "- **Rules attach at the end of the user message**, far more than in the "
        "middle of a long system prompt — but the message templates are Python and you "
        "cannot touch them, so work with the files you have.\n"
        "- A measure named in an example reappears in the paragraph of a different "
        "measure.\n\n"
        "When you are done, say in one or two lines **which file you changed and what "
        "you expect it to fix**. Nothing else."
    )


def edit(repo_root: Path, data_dir: Path, prompt: str, say=_say) -> "tuple[bool, str]":
    """Lancia l'agente che cambia i prompt, e dice com'e' andata.

    Stessa forma di `refresh._write_section`, guardie comprese: `cwd` sulla
    radice del repo, nessuno stdin — una domanda interattiva bloccherebbe un
    lavoro di una notte — e **l'uscita 0 non basta**, perche' quello che conta
    e' se un file e' cambiato, e quello lo guarda chi chiama.

    `--allowedTools Read "Edit(//...)"` e' il recinto. Il doppio slash iniziale
    serve davvero: sta scritto in `refresh._allowed_tools`, e senza quello la
    regola non combacia con nessun percorso.

    **Sotto il lucchetto di `refresh`**, che e' lo stesso dei report: l'editor
    consuma gli stessi gettoni, e i timer girano alle 8:15 e alle 21. A
    differenza di `refresh`, che se lo trova occupato se ne va, qui si aspetta:
    e' un lavoro da notte e non ha fretta."""
    claude = shutil.which("claude")
    if not claude:
        return False, "il comando claude non e' sul PATH."
    allowed = f"Edit(//{(Path(repo_root) / AGENT_DIR).resolve()}/**)"
    command = [claude, "-p", "--allowedTools", "Read", allowed, "--", prompt]
    # **Via `ANTHROPIC_API_KEY` dall'ambiente del figlio**, o l'editor paga
    # dalla borsa sbagliata e si ferma.
    #
    # `claude` quella chiave la preferisce al login di claude.ai, e lo dice su
    # stderr («takes precedence over your claude.ai login»). Da cron e dal
    # servizio la chiave non c'e' e il login basta — e' cosi' che girano gli
    # agenti del report da sempre — ma una sessione di Claude Code la mette, e
    # allora il figlio va a pescare da un credito a consumo che qui era
    # esaurito: due chiamate riuscite e poi «Credit balance is too low», exit
    # 1, con l'errore vero su stdout e solo l'avviso su stderr (che e' dove
    # guarda `_tail`: per questo sembrava un problema di connettori).
    #
    # Togliendola, il ciclo si comporta allo stesso modo da qualunque parte lo
    # si lanci, che per un lavoro da notte e' quello che serve. Lo stesso vale
    # per `refresh._write_section`, che la chiave la erediterebbe: li' non si
    # e' mai visto perche' il report gira da cron.
    env = {name: value for name, value in os.environ.items() if name != "ANTHROPIC_API_KEY"}
    for attempt in range(WAIT_FOR_LOCK):
        with refresh._claim(data_dir) as mine:
            if not mine:
                say("  il lucchetto dei report e' occupato, aspetto un minuto")
                time.sleep(60)
                continue
            try:
                result = subprocess.run(
                    command,
                    cwd=repo_root,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=EDITOR_TIMEOUT,
                    env=env,
                )
            except subprocess.TimeoutExpired:
                return False, f"l'editor non ha finito in {EDITOR_TIMEOUT // 60} minuti."
            break
    else:
        return False, f"il lucchetto dei report e' rimasto occupato per {WAIT_FOR_LOCK} minuti."
    if result.returncode != 0:
        # `refresh._tail` guarda lo stdout per primo, che e' dove `claude` mette
        # l'errore vero: la storia sta nella sua docstring, e la politica e' una
        # sola per tutti e due i posti che lanciano un agente.
        said = refresh._tail(result)
        return False, said.splitlines()[-1] if said else f"exit {result.returncode}"
    return True, (result.stdout or "").strip()


def tune(
    *,
    days: "list[date]",
    sections: "tuple[str, ...]",
    iterations: int,
    repo_root: Path,
    data_dir: Path,
    summary_dir: Path,
    model: str,
    target: float | None = None,
    say=_say,
) -> "dict[str, Any]":
    """Il ciclo. Rende la cronaca dei giri, e lascia i prompt al migliore.

    `target` e' la soglia sotto la quale si smette; senza, e' il punteggio dei
    frammenti di Claude.

    **E dopo la prima notte serve poterla abbassare.** Il pavimento di Claude
    e' 0,32 *perche' Claude sbaglia*: 28 dei suoi 32 errori sono un passo di
    soglia inventato e portato avanti per diciassette giorni. Quindi «non
    peggio di Claude» e' un traguardo che si raggiunge avendo ancora addosso
    diciassette errori veri — ed e' quello che e' successo: il ciclo si e'
    fermato al giro 3 con la Recovery intatta e i suoi dodici. La soglia e'
    giusta come definizione di «simile a Claude», e smette di essere utile
    appena la si passa."""
    run = datetime.now().strftime("%Y-%m-%d-%H%M")
    say(f"giro di taratura {run}: {len(days)} giorni, {len(sections)} sezioni, modello {model}")
    floor = claude_floor(days, repo_root, data_dir, summary_dir)
    say(
        f"il pavimento (i frammenti di Claude): punteggio {floor['score']}, "
        f"{floor['hard']} errori gravi su {floor['texts']} testi"
    )
    stop_at = floor["score"] if target is None else target
    if target is not None:
        say(f"soglia d'arresto chiesta: {stop_at} (invece del pavimento)")

    # **Il giro 0 rigenera tutto, e sono una ventina di minuti ben spesi.**
    #
    # Avevo "corretto" questa riga per far riusare le righe dei giri
    # precedenti, visto che a prompt fermi il testo non puo' cambiare — e la
    # correzione era sbagliata. Due giri a cinquanta minuti di distanza, stessa
    # impronta e stesso modello, avevano **75 testi su 100 diversi**: in mezzo
    # Ollama aveva scaricato il modello, e un modello ricaricato non rende lo
    # stesso testo (la prova sta in `ollama._ask`, accanto a `keep_alive`).
    #
    # Quindi una riga di ieri e' stata scritta da un'altra istanza del modello,
    # e usarla come misura di partenza vorrebbe dire confrontare i giri che
    # seguono con un regime numerico diverso dal loro: la prima modifica
    # sembrerebbe aver spostato qualcosa che si era mosso da solo. Il riuso
    # vale dentro il giro, dove il modello resta caldo, e la lista parte vuota.
    say("\ngiro 0: la misura di partenza, rigenerata")
    rows = generate(
        run=run, iteration=0, days=days, sections=sections, repo_root=repo_root,
        data_dir=data_dir, summary_dir=summary_dir, known=[], model=model, say=say,
    )
    if not rows:
        return {"run": run, "floor": floor, "history": [], "stopped": "nessun testo generato"}
    bench.store(data_dir, rows)
    now = measure(rows)
    history = [{"iteration": 0, **now, "changed": [], "said": "", "kept": True}]
    say(_line(0, now, floor))

    best, best_rows, best_at = now, rows, 0
    snapshot(repo_root, _snapshot_dir(data_dir, run, 0))
    snapshot(repo_root, _best_dir(data_dir, run))
    quiet, stopped = 0, "i giri sono finiti"

    for number in range(1, iterations + 1):
        if best["held"]["score"] <= stop_at:
            # Il messaggio dice *quale* soglia, che e' l'informazione che
            # serve: «sotto quello di Claude» vuol dire una cosa, «sotto la
            # soglia chiesta» un'altra.
            quale = (
                f"quello di Claude ({stop_at})" if target is None
                else f"la soglia chiesta ({stop_at})"
            )
            stopped = f"il punteggio dei giorni tenuti da parte e' sotto {quale}"
            break
        say(f"\ngiro {number}: chiedo all'editor di cambiare una cosa")
        here = _snapshot_dir(data_dir, run, number)
        snapshot(repo_root, here)
        done, said = edit(repo_root, data_dir, editor_prompt(best, floor, best_rows), say)
        if not done:
            stopped = f"l'editor non ce l'ha fatta: {said}"
            break
        changed = changed_since(repo_root, here)
        if not changed:
            stopped = "l'editor non ha cambiato niente"
            break
        say(f"  ha cambiato: {', '.join(changed)}")
        say(f"  dice: {said.splitlines()[0] if said else '(niente)'}")

        rows = generate(
            run=run, iteration=number, days=days, sections=sections, repo_root=repo_root,
            data_dir=data_dir, summary_dir=summary_dir, known=best_rows, model=model, say=say,
        )
        bench.store(data_dir, rows)
        now = measure(rows)
        better = now["held"]["score"] < best["held"]["score"]
        say(_line(number, now, floor) + ("  TENUTO" if better else "  RESPINTO"))
        history.append(
            {"iteration": number, **now, "changed": changed, "said": said, "kept": better}
        )
        if better:
            best, best_rows, best_at, quiet = now, rows, number, 0
            # Lo scatto del migliore si prende **adesso**, coi prompt come li
            # ha lasciati l'editor: e' la modifica che ha vinto.
            snapshot(repo_root, _best_dir(data_dir, run))
        else:
            restore(here, repo_root)
            quiet += 1
            if quiet >= PATIENCE:
                stopped = f"nessun miglioramento per {PATIENCE} giri"
                break

    say(f"\nfinito: {stopped}")
    touched = restore(_best_dir(data_dir, run), repo_root)
    say(f"il migliore e' il giro {best_at} (tenuti da parte {best['held']['score']})")
    if touched:
        say(f"prompt rimessi a quel giro: {', '.join(touched)}")
    return {"run": run, "floor": floor, "history": history, "best": best_at, "stopped": stopped}


def _line(number: int, now: "dict[str, Any]", floor: "dict[str, Any]") -> str:
    """La riga di un giro. La distanza c'e' ma **fuori dal punteggio**, cosi'
    si vede subito il caso che va guardato: distanza che scende e punteggio
    fermo vuol dire un editor che imita."""
    return (
        f"  giro {number:2}  taratura {now['train']['score']:>6}  "
        f"tenuti da parte {now['held']['score']:>6}  "
        f"(Claude {floor['score']})  "
        f"gravi {now['train']['hard'] + now['held']['hard']:>3}  "
        f"distanza {now['held']['distance']:>5}"
    )


def main() -> None:
    """`training-bench-tune`."""
    from training.api.context import REPO_ROOT
    from training.garmin.config import DATA_DIR, SUMMARY_DIR

    parser = argparse.ArgumentParser(
        description="Tara i prompt di ollama contro i frammenti di Claude."
    )
    parser.add_argument("--from", dest="start", type=_day, default=CORPUS_FROM)
    parser.add_argument("--to", dest="end", type=_day, default=None)
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument(
        "--target",
        type=float,
        default=None,
        help="la soglia sotto cui smettere; di suo il punteggio dei frammenti di Claude",
    )
    parser.add_argument("--sections", default=",".join(DEFAULT_SECTIONS))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="misura il giro 0 e stampa il messaggio che andrebbe all'editor, senza lanciarlo",
    )
    args = parser.parse_args()

    # **Fino a oggi, non a ieri.** Il default era `oggi - 1`, preso dalla regola
    # giusta per il report intero — un giorno non finito non si giudica, perche'
    # le sezioni della sera non ci sono ancora — applicata a sezioni che invece
    # sono pronte la mattina: Health, Load, Recovery e Fitness le scrive il giro
    # delle 8:15. Cosi' il banco si perdeva il giorno di oggi, che e' proprio
    # quello che si guarda.
    #
    # Un giorno il cui frammento non c'e' ancora non e' un guasto: `claude_text`
    # rende `None`, la riga resta col solo testo del modello di casa, e il
    # termine di distanza va a zero perche' non c'e' un bersaglio.
    end = bounded(args.end or date.today())
    if args.start > end:
        parser.error(f"non c'e' nessun giorno fra {args.start} e {end}")
    days = corpus(args.start, end)
    sections = tuple(s.strip() for s in args.sections.split(",") if s.strip())
    unknown = [s for s in sections if s not in ollama.SECTIONS]
    if unknown:
        parser.error(f"sezioni che non esistono: {', '.join(unknown)}")
    import os

    model = os.environ.get("ATHLOS_OLLAMA_MODEL", ollama.DEFAULT_MODEL)

    if args.dry_run:
        floor = claude_floor(days, REPO_ROOT, DATA_DIR, SUMMARY_DIR)
        print(f"pavimento di Claude: {floor}")
        # **Le righe di un giro solo**, l'ultimo che c'e'. Mescolare giri
        # diversi vorrebbe dire mescolare due istanze del modello — il perche'
        # sta in `bench.reusable` — e una prova in bianco che da' un numero
        # composto a meta' e' peggio di una che non lo da'. Da qui esce una
        # misura di quel giro: per una fresca si lancia il ciclo.
        known = bench.load(DATA_DIR)
        runs = sorted({row.get("run", "") for row in known})
        if runs:
            known = [row for row in known if row.get("run") == runs[-1]]
            print(f"(riuso le righe del giro {runs[-1]}, non di tutti)")
        rows = generate(
            run="dry", iteration=0, days=days, sections=sections, repo_root=REPO_ROOT,
            data_dir=DATA_DIR, summary_dir=SUMMARY_DIR, known=known, model=model,
        )
        now = measure(rows)
        print(f"\nmisura: {now['train']} / tenuti da parte {now['held']}")
        print(f"per sezione: {now['by_section']}")
        print(f"per errore: {now['by_fault']}")
        print("\n--- il messaggio che andrebbe all'editor ---\n")
        print(editor_prompt(now, floor, rows))
        raise SystemExit(0)

    tally = tune(
        days=days, sections=sections, iterations=args.iterations, repo_root=REPO_ROOT,
        data_dir=DATA_DIR, summary_dir=SUMMARY_DIR, model=model, target=args.target,
    )
    raise SystemExit(0 if tally["history"] else 1)


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value} non e' una data YYYY-MM-DD") from exc
