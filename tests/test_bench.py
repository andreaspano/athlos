"""Il registro del banco e il ciclo che tara i prompt.

Niente qui lancia `claude` ne' parla con ollama: e' la regola di casa
(`tests/conftest.py`, `tests/test_local_text.py`) e il modo e' quello di
`tests/test_refresh.py`, cioe' sostituire la funzione che fa la chiamata. Il
data root e' sempre un `tmp_path`.
"""

import json
import shutil
import threading
from datetime import date
from pathlib import Path

import pytest

from training.api import bench, bench_tune, ollama
from training.api.context import REPO_ROOT


def a_row(day="2026-10-26", section="health_split", iteration=0, text="un testo", **extra):
    return {
        **bench.row(
            run="prova",
            iteration=iteration,
            day=date.fromisoformat(day),
            section_key=section,
            model="finto:1b",
            prompts="aaaa",
            seconds=1.0,
            ollama_text=text,
            claude="il bersaglio",
            held_out=False,
        ),
        **extra,
    }


# --- Il registro ---


def test_a_row_goes_and_comes_back(tmp_path):
    bench.store(tmp_path, [a_row()])
    (back,) = bench.load(tmp_path)
    assert back["day"] == "2026-10-26"
    assert back["section"] == "health_split"
    assert back["ollama"] == "un testo"
    assert back["claude"] == "il bersaglio"


def test_the_same_day_and_section_is_replaced(tmp_path):
    """**La regola**: dentro un giro c'e' una riga per card per giorno.
    Rifare lo stesso giorno sostituisce invece di aggiungere, ed e' il test che
    la fissa."""
    bench.store(tmp_path, [a_row(text="il primo")])
    bench.store(tmp_path, [a_row(text="il secondo")])
    rows = bench.load(tmp_path)
    assert len(rows) == 1
    assert rows[0]["ollama"] == "il secondo"


def test_another_iteration_is_another_row(tmp_path):
    """Il giro e' l'asse in piu', e serve: per dire che una modifica ai prompt
    ha migliorato le cose devono esistere il prima e il dopo."""
    bench.store(tmp_path, [a_row(iteration=0), a_row(iteration=1)])
    assert len(bench.load(tmp_path)) == 2


def test_two_sections_of_a_day_live_side_by_side(tmp_path):
    bench.store(tmp_path, [a_row(section="health_split"), a_row(section="load_split")])
    assert len(bench.load(tmp_path)) == 2


def test_the_rows_are_sorted(tmp_path):
    """Asserito **sul testo del file** e non attraverso il lettore: un ordine
    sbagliato che il lettore rimette a posto resterebbe invisibile."""
    bench.store(tmp_path, [a_row(day="2026-10-28"), a_row(day="2026-10-27")])
    lines = (tmp_path / "bench" / "local_text.jsonl").read_text().strip().splitlines()
    assert [json.loads(line)["day"] for line in lines] == ["2026-10-27", "2026-10-28"]


def test_a_record_is_one_physical_line(tmp_path):
    """Il testo di una sezione spezzata ha le righe vuote fra i paragrafi, e
    deve restare su una riga sola. **E' il test che prende chi passasse a
    `files.write_json`**, che ha `indent=2` fisso."""
    bench.store(tmp_path, [a_row(text="primo paragrafo\n\nsecondo paragrafo")])
    lines = (tmp_path / "bench" / "local_text.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["ollama"] == "primo paragrafo\n\nsecondo paragrafo"


def test_the_accents_stay_readable(tmp_path):
    """Il file si legge a occhio, quindi gli accenti non diventano sequenze di
    escape: `ensure_ascii=False`, come in `files.write_json`."""
    bench.store(tmp_path, [a_row(text="perche' si però")])
    assert "però" in (tmp_path / "bench" / "local_text.jsonl").read_text()


def test_a_missing_file_reads_as_nothing(tmp_path):
    assert bench.load(tmp_path) == []


def test_a_corrupt_line_is_skipped_and_said(tmp_path, capsys):
    bench.store(tmp_path, [a_row()])
    path = tmp_path / "bench" / "local_text.jsonl"
    path.write_text("{non e' json\n" + path.read_text())
    assert len(bench.load(tmp_path)) == 1
    assert "non si legge" in capsys.readouterr().out


def test_the_next_write_drops_the_corrupt_line(tmp_path):
    """La tolleranza qui **cancella**, perche' chi scrive riscrive tutto il
    file da quello che ha letto. Per un quaderno va bene, ma e' una differenza
    da `files.read_json` e va fissata in un test invece di sorprendere."""
    bench.store(tmp_path, [a_row()])
    path = tmp_path / "bench" / "local_text.jsonl"
    path.write_text("{rotta\n" + path.read_text())
    bench.store(tmp_path, [a_row(day="2026-10-27")])
    assert "rotta" not in path.read_text()


def test_the_folder_is_created(tmp_path):
    """`files.write_text` non fa `mkdir`: lo fa chi scrive."""
    bench.store(tmp_path, [a_row()])
    assert (tmp_path / "bench").is_dir()


def test_no_tmp_file_is_left(tmp_path):
    bench.store(tmp_path, [a_row()])
    assert not list((tmp_path / "bench").glob("*.tmp"))


def test_an_unwritable_bench_does_not_raise(tmp_path, capsys):
    """**La card deve vedersi anche se il quaderno non si scrive**, e un ciclo
    di una notte non muore per il suo taccuino. Il modo portabile di rendere
    una cartella impossibile e' metterci un file al suo posto: `mkdir` alza
    `FileExistsError`, che e' un `OSError`. Niente `chmod`, che da root non fa
    niente."""
    (tmp_path / "bench").write_text("sono un file, non una cartella")
    bench.store(tmp_path, [a_row()])
    assert "non registra" in capsys.readouterr().out


def test_the_writes_do_not_lose_each_other(tmp_path):
    """Sedici thread su sedici chiavi diverse, e in fondo sedici righe.

    L'asserzione e' sul conto finale, quindi deterministica. Senza il lucchetto
    il ciclo leggi-modifica-riscrivi ne perde quasi sempre qualcuna — e col
    temporaneo dal nome fisso di `write_text` arriverebbe a pubblicare un file
    impastato. **Fra processi non vede niente**, per costruzione: quello
    vorrebbe un `flock`."""
    threads = [
        threading.Thread(target=bench.store, args=(tmp_path, [a_row(section=f"s{n}")]))
        for n in range(16)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(bench.load(tmp_path)) == 16


# --- L'impronta dei prompt ---


def test_the_fingerprint_follows_the_prompt_files(tmp_path):
    """**E' quello che rende il ciclo un'ora invece di tre**: se l'impronta non
    cambia il testo non puo' essere cambiato, e la riga si riusa."""
    section = ollama.SECTIONS["recovery_split"]
    before = bench.fingerprint(REPO_ROOT, section)
    assert before == bench.fingerprint(REPO_ROOT, section)
    assert before != bench.fingerprint(REPO_ROOT, ollama.SECTIONS["health_split"])


def test_the_fingerprint_ignores_the_front_matter(tmp_path):
    """Il front matter non arriva al modello — `_system_prompt` lo toglie —
    quindi una descrizione cambiata non deve far rigenerare niente."""
    (tmp_path / ".ollama" / "agents").mkdir(parents=True)
    style = tmp_path / ".ollama" / "agents" / "_style.md"
    style.write_text("House rules")
    agent = tmp_path / ".ollama" / "agents" / "01_health.md"
    agent.write_text("---\nname: uno\n---\n\nIl compito.")
    first = bench.fingerprint(tmp_path, ollama.SECTIONS["health"])
    agent.write_text("---\nname: due\ndescription: altro\n---\n\nIl compito.")
    assert bench.fingerprint(tmp_path, ollama.SECTIONS["health"]) == first
    agent.write_text("---\nname: uno\n---\n\nIl compito, cambiato.")
    assert bench.fingerprint(tmp_path, ollama.SECTIONS["health"]) != first


def test_a_row_is_reused_only_when_everything_matches():
    rows = [a_row()]
    day = date(2026, 10, 26)
    assert bench.reusable(rows, day, "health_split", "aaaa", "finto:1b")
    assert not bench.reusable(rows, day, "health_split", "bbbb", "finto:1b")
    assert not bench.reusable(rows, day, "health_split", "aaaa", "altro:1b")
    assert not bench.reusable(rows, day, "load_split", "aaaa", "finto:1b")
    assert not bench.reusable(rows, date(2026, 10, 27), "health_split", "aaaa", "finto:1b")


def test_the_claude_fragment_comes_from_the_section_title(tmp_path):
    """`health` e `health_split` sono la stessa sezione chiesta in due modi, e
    il frammento di Claude e' uno: il nome del file viene dal titolo."""
    folder = tmp_path / "01.daily" / "2026-10-26"
    folder.mkdir(parents=True)
    (folder / "health.md").write_text("il bersaglio della Health")
    for key in ("health", "health_split"):
        got = bench.claude_text(tmp_path, date(2026, 10, 26), ollama.SECTIONS[key])
        assert got == "il bersaglio della Health"


def test_an_empty_fragment_is_no_fragment(tmp_path):
    """Lo zero byte conta come assente, come in `app._fragment_path`."""
    folder = tmp_path / "01.daily" / "2026-10-26"
    folder.mkdir(parents=True)
    (folder / "health.md").write_text("   \n")
    assert bench.claude_text(tmp_path, date(2026, 10, 26), ollama.SECTIONS["health"]) is None


# --- Il corpus e i giorni tenuti da parte ---


def test_the_corpus_starts_where_the_target_stopped_moving():
    """L'ultimo cambio a un prompt di Claude e' del 26 ottobre, e un bersaglio
    che si muove non e' un bersaglio."""
    assert bench_tune.CORPUS_FROM == date(2026, 10, 26)


def test_one_day_in_three_is_held_out():
    days = bench_tune.corpus(date(2026, 10, 26), date(2026, 11, 20))
    held = bench_tune.held_out(days)
    assert len(days) == 26
    assert len(held) == 9
    # Sparsi e non in coda: in coda ci sarebbe dentro l'andamento del tempo.
    assert date(2026, 11, 20) not in held
    assert bench_tune.held_out(days) == held


# --- Gli scatti dei prompt, e il respingere una modifica ---


@pytest.fixture
def agents(tmp_path):
    """Una finta `.ollama/agents/` da fare a pezzi."""
    folder = tmp_path / ".ollama" / "agents"
    (folder / "01_health_split").mkdir(parents=True)
    (folder / "_style.md").write_text("le regole di casa")
    (folder / "01_health.md").write_text("il compito della Health")
    (folder / "01_health_split" / "_verdict.md").write_text("il verdetto")
    return tmp_path


def test_a_snapshot_and_a_restore_put_everything_back(agents, tmp_path):
    where = tmp_path / "scatto"
    bench_tune.snapshot(agents, where)
    live = agents / ".ollama" / "agents"
    (live / "01_health.md").write_text("ROVINATO dall'editor")
    assert bench_tune.changed_since(agents, where) == ["01_health.md"]
    bench_tune.restore(where, agents)
    assert (live / "01_health.md").read_text() == "il compito della Health"
    assert bench_tune.changed_since(agents, where) == []


def test_a_restore_removes_what_the_editor_added(agents, tmp_path):
    """Una modifica respinta non deve lasciarne un pezzo in giro."""
    where = tmp_path / "scatto"
    bench_tune.snapshot(agents, where)
    live = agents / ".ollama" / "agents"
    (live / "01_health_split" / "_nuovo.md").write_text("un file che l'editor ha aggiunto")
    bench_tune.restore(where, agents)
    assert not (live / "01_health_split" / "_nuovo.md").exists()


def test_a_restore_never_leaves_a_prompt_missing(agents, tmp_path):
    """Si scrive file per file e non con un `rmtree`: cosi' la cartella non e'
    mai in uno stato in cui un prompt manca, e un processo che muore in mezzo
    non lascia il repo rotto."""
    where = tmp_path / "scatto"
    bench_tune.snapshot(agents, where)
    live = agents / ".ollama" / "agents"
    before = {p.name for p in live.rglob("*.md")}
    (live / "_style.md").write_text("cambiato")
    bench_tune.restore(where, agents)
    assert {p.name for p in live.rglob("*.md")} == before


# --- La misura ---


def test_the_measure_separates_the_held_out_days():
    rows = [
        {**a_row(day="2026-10-26"), "score": 2.0, "faults": ["uno", "due"], "soft": [], "distance": 0.8, "held_out": False},
        {**a_row(day="2026-10-27"), "score": 0.0, "faults": [], "soft": [], "distance": 0.9, "held_out": True},
    ]
    got = bench_tune.measure(rows)
    assert got["train"]["score"] == 2.0
    assert got["held"]["score"] == 0.0
    assert got["train"]["hard"] == 2


def test_the_measure_is_a_mean_and_not_a_sum():
    """Un giro in cui una sezione non ha risposto genera meno righe, e con la
    somma sembrerebbe migliore."""
    one = [{**a_row(), "score": 1.0, "faults": [], "soft": [], "distance": 0.5, "held_out": False}]
    two = one + [{**a_row(section="load_split"), "score": 1.0, "faults": [], "soft": [], "distance": 0.5, "held_out": False}]
    assert bench_tune.measure(one)["train"]["score"] == bench_tune.measure(two)["train"]["score"]


def test_the_editor_never_sees_a_held_out_day():
    """I giorni tenuti da parte servono a misurare, e un editor che li vede li
    impara."""
    rows = [
        {**a_row(day="2026-10-26"), "score": 9.0, "faults": ["grave"], "soft": [], "distance": 0.5, "held_out": True},
        {**a_row(day="2026-10-27"), "score": 1.0, "faults": ["piccolo"], "soft": [], "distance": 0.5, "held_out": False},
    ]
    summary = bench_tune.measure(rows)
    floor = {"score": 0.3, "hard": 32, "texts": 104}
    message = bench_tune.editor_prompt(summary, floor, rows)
    assert "2026-10-27" in message
    assert "2026-10-26" not in message


def test_the_editor_is_told_the_floor_and_asked_for_one_change():
    rows = [{**a_row(), "score": 1.0, "faults": ["grave"], "soft": [], "distance": 0.5, "held_out": False}]
    message = bench_tune.editor_prompt(
        bench_tune.measure(rows), {"score": 0.3, "hard": 32, "texts": 104}, rows
    )
    assert "exactly one change" in message
    assert "0.3" in message
    assert ".ollama/agents/" in message
    assert "`.claude/agents/` are the target" in message


def test_the_editor_is_fenced_to_the_ollama_prompts(monkeypatch, tmp_path):
    """**La guardia e' la regola dei permessi**, non la buona volonta': si
    controlla che la riga `Edit(...)` nomini solo `.ollama/agents/` e col
    doppio slash iniziale, che senza quello non combacia con niente."""
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs

        class Result:
            returncode = 0
            stdout = "ho cambiato un file"
            stderr = ""

        return Result()

    monkeypatch.setattr(bench_tune.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(bench_tune.subprocess, "run", fake_run)
    import contextlib

    monkeypatch.setattr(
        bench_tune.refresh, "_claim", lambda data_dir: contextlib.nullcontext(True)
    )
    done, said = bench_tune.edit(tmp_path, tmp_path, "il messaggio", say=lambda m: None)
    assert done and said == "ho cambiato un file"
    edits = [a for a in seen["command"] if a.startswith("Edit(")]
    assert len(edits) == 1
    assert edits[0].startswith("Edit(//")
    assert ".ollama/agents" in edits[0]
    assert ".claude" not in edits[0]
    assert seen["kwargs"]["stdin"] is bench_tune.subprocess.DEVNULL


def test_without_claude_on_the_path_the_editor_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(bench_tune.shutil, "which", lambda name: None)
    done, said = bench_tune.edit(tmp_path, tmp_path, "x", say=lambda m: None)
    assert not done and "PATH" in said


# --- Il ciclo, con l'editor e ollama finti ---


@pytest.fixture
def bench_world(tmp_path, monkeypatch):
    """Un repo finto coi prompt veri, un data root e un frammento di Claude.

    I prompt sono quelli veri perche' il ciclo ne calcola l'impronta e ne fa
    gli scatti: una finta cartella con due file non proverebbe il
    ripristino."""
    repo = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / ".ollama" / "agents", repo / ".ollama" / "agents")
    data, summary = tmp_path / "data", tmp_path / "summary"
    (summary / "01.daily" / "2026-10-26").mkdir(parents=True)
    (summary / "01.daily" / "2026-10-26" / "health.md").write_text("Resting heart rate ordinary.")
    return repo, data, summary


def _run(bench_world, monkeypatch, *, text_after: str, text_before: str, iterations=1):
    repo, data, summary = bench_world
    state = {"edited": False}

    def fake_ollama(section, day, payload, repo_root, week=None):
        return (text_after if state["edited"] else text_before), "finto:1b"

    def fake_editor(repo_root, data_dir, prompt, say=print):
        state["edited"] = True
        (repo / ".ollama" / "agents" / "01_health.md").write_text("IL PROMPT NUOVO")
        return True, "ho cambiato 01_health.md"

    monkeypatch.setattr(ollama, "section_text", fake_ollama)
    monkeypatch.setattr(bench_tune, "edit", fake_editor)
    tally = bench_tune.tune(
        days=[date(2026, 10, 26)],
        sections=("health",),
        iterations=iterations,
        repo_root=repo,
        data_dir=data,
        summary_dir=summary,
        model="finto:1b",
        say=lambda message: None,
    )
    return tally, (repo / ".ollama" / "agents" / "01_health.md").read_text()


def test_an_improvement_survives_to_the_end(bench_world, monkeypatch):
    """**Il test che ha trovato un bug vero.** Il ripristino finale rimetteva
    lo scatto del giro migliore, che e' lo stato *prima* della sua modifica:
    buttava via proprio la modifica che aveva vinto. Un ciclo provato solo coi
    peggioramenti sembrava giusto."""
    tally, prompt = _run(
        bench_world,
        monkeypatch,
        text_before="my body came back and yesterday cost him 999",
        text_after="Resting heart rate ordinary.",
    )
    assert tally["best"] == 1
    assert prompt == "IL PROMPT NUOVO"


def test_a_regression_is_rejected_and_the_prompts_go_back(bench_world, monkeypatch):
    """Tarando a mano ho provato una modifica che ha fatto scrivere il
    contrario dei fatti, e l'ho ripristinata io. Il ciclo lo deve fare da
    se'."""
    repo, _, _ = bench_world
    before = (repo / ".ollama" / "agents" / "01_health.md").read_text()
    tally, prompt = _run(
        bench_world,
        monkeypatch,
        text_before="Resting heart rate ordinary.",
        text_after="my body came back and yesterday cost him 999",
    )
    assert tally["best"] == 0
    assert [h["kept"] for h in tally["history"]] == [True, False]
    assert prompt == before


def test_the_loop_stops_when_nothing_improves(bench_world, monkeypatch):
    """Tre giri a vuoto e si smette, invece di consumare gettoni per niente."""
    tally, _ = _run(
        bench_world,
        monkeypatch,
        text_before="Resting heart rate ordinary.",
        text_after="my body came back and yesterday cost him 999",
        iterations=9,
    )
    assert len(tally["history"]) == 1 + bench_tune.PATIENCE
    assert "nessun miglioramento" in tally["stopped"]


def test_an_editor_that_changes_nothing_stops_the_loop(bench_world, monkeypatch):
    """Se l'editor non tocca un file non c'e' niente da rimisurare, e
    rigenerare sarebbe venti minuti per lo stesso risultato."""
    repo, data, summary = bench_world
    monkeypatch.setattr(
        ollama, "section_text", lambda *a, **k: ("Resting heart rate ordinary.", "finto:1b")
    )
    monkeypatch.setattr(bench_tune, "edit", lambda *a, **k: (True, "non ho toccato niente"))
    tally = bench_tune.tune(
        days=[date(2026, 10, 26)], sections=("health",), iterations=3, repo_root=repo,
        data_dir=data, summary_dir=summary, model="finto:1b", say=lambda m: None,
    )
    assert tally["stopped"] == "l'editor non ha cambiato niente"


# --- Le tre decisioni prese guardando i numeri del primo giro ---


def test_the_loop_tunes_the_split_sections():
    """Le sezioni intere restano fuori di suo: il loro guasto — cinque
    paragrafi chiesti e uno scritto — e' **il guasto per cui le spezzate
    esistono**, e l'editor ci spenderebbe i primi giri a rifare una battaglia
    gia' aggirata. Restano chiedibili con `--sections`."""
    assert all(key.endswith("_split") for key in bench_tune.DEFAULT_SECTIONS)
    assert set(bench_tune.DEFAULT_SECTIONS) <= set(ollama.SECTIONS)


def test_the_measure_reports_the_distance_beside_the_score():
    """La distanza si guarda e non si somma: se scende mentre il punteggio sta
    fermo, l'editor sta facendo imitare la voce di Claude."""
    rows = [
        {**a_row(), "score": 1.0, "faults": ["grave"], "soft": [], "distance": 0.8, "held_out": False}
    ]
    got = bench_tune.measure(rows)
    assert got["train"]["score"] == 1.0
    assert got["train"]["distance"] == 0.8


def test_the_loop_stops_when_it_beats_claude(tmp_path, monkeypatch):
    """**La condizione d'arresto e' raggiungibile**, che col primo peso non lo
    era: da tutti e due i lati il punteggio sono i soli errori, e la distanza —
    che il bersaglio contro se stesso non ha — sta fuori."""
    repo = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / ".ollama" / "agents", repo / ".ollama" / "agents")
    data, summary = tmp_path / "data", tmp_path / "summary"
    (summary / "01.daily" / "2026-10-26").mkdir(parents=True)
    # Il bersaglio ha un numero che nessuno gli ha dato: il pavimento sale.
    (summary / "01.daily" / "2026-10-26" / "health.md").write_text("You woke at 999 today.")
    monkeypatch.setattr(
        ollama, "section_text", lambda *a, **k: ("Resting heart rate ordinary.", "finto:1b")
    )
    monkeypatch.setattr(bench_tune, "edit", lambda *a, **k: (True, "non dovrebbe servire"))
    tally = bench_tune.tune(
        days=[date(2026, 10, 26)], sections=("health",), iterations=5, repo_root=repo,
        data_dir=data, summary_dir=summary, model="finto:1b", say=lambda m: None,
    )
    assert tally["floor"]["score"] > 0
    assert "sotto quello di Claude" in tally["stopped"]
    # Si e' fermato subito: nessun giro dopo lo zero.
    assert [h["iteration"] for h in tally["history"]] == [0]


def test_the_first_iteration_does_not_reuse_another_runs_rows(tmp_path, monkeypatch):
    """**La misura di partenza si rigenera, e la "correzione" che la faceva
    riusare era sbagliata.**

    Sembrava uno spreco: a prompt fermi il testo non puo' cambiare, quindi
    perche' rifare venti minuti di domande? Perche' non e' vero. Due giri a
    cinquanta minuti di distanza, stessa impronta e stesso modello, avevano 75
    testi su 100 diversi: in mezzo Ollama aveva scaricato il modello, e un
    modello ricaricato non rende lo stesso testo.

    Una riga di un altro giro e' quindi di un'altra istanza del modello, e
    prenderla come punto di partenza vorrebbe dire misurare i giri che seguono
    contro un regime numerico diverso dal loro — e dare alla prima modifica il
    merito di qualcosa che si era mosso da solo."""
    repo = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / ".ollama" / "agents", repo / ".ollama" / "agents")
    data, summary = tmp_path / "data", tmp_path / "summary"
    (summary / "01.daily" / "2026-10-26").mkdir(parents=True)
    (summary / "01.daily" / "2026-10-26" / "health.md").write_text("Il bersaglio.")
    section = ollama.SECTIONS["health"]
    # Una riga gia' nel quaderno, con l'impronta dei prompt di adesso.
    bench.store(
        data,
        [
            bench.row(
                run="prima", iteration=0, day=date(2026, 10, 26), section_key="health",
                model="finto:1b", prompts=bench.fingerprint(repo, section),
                seconds=9.9, ollama_text="il testo di prima", claude="Il bersaglio.",
                held_out=False,
            )
        ],
    )
    chiamate = []
    monkeypatch.setattr(
        ollama, "section_text",
        lambda *a, **k: (chiamate.append(1), ("testo nuovo", "finto:1b"))[1],
    )
    monkeypatch.setattr(bench_tune, "edit", lambda *a, **k: (True, "non serve"))
    bench_tune.tune(
        days=[date(2026, 10, 26)], sections=("health",), iterations=0, repo_root=repo,
        data_dir=data, summary_dir=summary, model="finto:1b", say=lambda m: None,
    )
    assert chiamate, "il giro 0 ha riusato la riga di un altro giro"


def test_the_editor_does_not_inherit_the_api_key(monkeypatch, tmp_path):
    """**L'editor paga dal login, non da una chiave a consumo.**

    `claude` preferisce `ANTHROPIC_API_KEY` al login di claude.ai e lo dice su
    stderr. Da cron la chiave non c'e' e gli agenti del report girano sul
    login; una sessione di Claude Code invece la mette, e il ciclo andava a
    pescare da un credito esaurito — due chiamate e poi «Credit balance is too
    low». Togliendola, il ciclo si comporta uguale da dovunque lo si lanci."""
    import contextlib

    seen = {}

    def fake_run(command, **kwargs):
        seen["env"] = kwargs.get("env")

        class Result:
            returncode = 0
            stdout = "fatto"
            stderr = ""

        return Result()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "una-chiave-finta")
    monkeypatch.setattr(bench_tune.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(bench_tune.subprocess, "run", fake_run)
    monkeypatch.setattr(
        bench_tune.refresh, "_claim", lambda data_dir: contextlib.nullcontext(True)
    )
    bench_tune.edit(tmp_path, tmp_path, "il messaggio", say=lambda m: None)
    assert "ANTHROPIC_API_KEY" not in seen["env"]
    assert "PATH" in seen["env"], "il resto dell'ambiente deve restare"


def test_the_real_error_is_read_from_stdout(monkeypatch, tmp_path):
    """`claude` mette gli avvisi su stderr e l'errore che conta su stdout, e
    `refresh._tail` guarda stderr per primo: per un giro il «credito esaurito»
    e' sembrato un problema di connettori."""
    import contextlib

    class Result:
        returncode = 1
        stdout = "Credit balance is too low"
        stderr = "⚠ un avviso che non c'entra niente"

    monkeypatch.setattr(bench_tune.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(bench_tune.subprocess, "run", lambda *a, **k: Result())
    monkeypatch.setattr(
        bench_tune.refresh, "_claim", lambda data_dir: contextlib.nullcontext(True)
    )
    done, said = bench_tune.edit(tmp_path, tmp_path, "x", say=lambda m: None)
    assert not done
    assert said == "Credit balance is too low"


def test_the_editor_sees_every_section_that_has_faults():
    """**Il difetto che la prima notte ha fatto vedere.** I casi peggiori erano
    dieci in assoluto, e la Fitness se li e' presi tutti per quattro giri: la
    Recovery, seconda peggiore con dodici errori gravi, non e' mai entrata
    nella stanza. Tre per sezione, e ognuna che ha errori ci entra."""
    rows = []
    # La Fitness ha i cinque casi peggiori in assoluto.
    for n in range(5):
        rows.append({**a_row(day=f"2026-10-2{n}", section="fitness_split"),
                     "score": 9.0 - n, "faults": ["grave"], "soft": [], "distance": 0.5,
                     "held_out": False})
    # La Recovery e' cattiva, ma sotto tutte quelle.
    rows.append({**a_row(day="2026-11-01", section="recovery_split"),
                 "score": 1.0, "faults": ["grave"], "soft": [], "distance": 0.5,
                 "held_out": False})
    message = bench_tune.editor_prompt(
        bench_tune.measure(rows), {"score": 0.3, "hard": 32, "texts": 104}, rows
    )
    assert "recovery_split" in message, "la sezione sotto non entra mai"
    # E della Fitness ne entrano tre, non cinque.
    assert message.count("fitness_split (punteggio") == bench_tune.WORST_PER_SECTION


def test_a_clean_section_does_not_take_a_slot():
    """Una sezione senza errori non ha niente da far vedere: il posto va a chi
    ne ha."""
    rows = [
        {**a_row(section="load_split"), "score": 0.0, "faults": [], "soft": [],
         "distance": 0.5, "held_out": False},
        {**a_row(section="recovery_split"), "score": 1.0, "faults": ["grave"], "soft": [],
         "distance": 0.5, "held_out": False},
    ]
    message = bench_tune.editor_prompt(
        bench_tune.measure(rows), {"score": 0.3, "hard": 1, "texts": 4}, rows
    )
    assert "recovery_split (punteggio" in message
    assert "load_split (punteggio" not in message


def test_the_stopping_threshold_can_be_asked_for(tmp_path, monkeypatch):
    """**Il pavimento di Claude e' 0,32 perche' Claude sbaglia**: 28 dei suoi
    32 errori sono un passo di soglia inventato e portato avanti per
    diciassette giorni. Quindi «non peggio di Claude» si raggiunge avendo
    ancora addosso errori veri — ed e' quello che e' successo la prima notte,
    col ciclo fermo al giro 3 e la Recovery intatta. Con `--target` si chiede
    di andare oltre."""
    repo = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / ".ollama" / "agents", repo / ".ollama" / "agents")
    data, summary = tmp_path / "data", tmp_path / "summary"
    (summary / "01.daily" / "2026-10-26").mkdir(parents=True)
    (summary / "01.daily" / "2026-10-26" / "health.md").write_text("You woke at 999 today.")
    monkeypatch.setattr(
        ollama, "section_text", lambda *a, **k: ("Resting heart rate ordinary.", "finto:1b")
    )
    # L'editor finto deve cambiare un file davvero, o il ciclo si ferma per
    # l'altro motivo giusto: niente cambiato, niente da rimisurare.
    tocchi = iter(range(99))
    def editor(*a, **k):
        (repo / ".ollama" / "agents" / "01_health.md").write_text(f"versione {next(tocchi)}")
        return True, "cambiato"
    monkeypatch.setattr(bench_tune, "edit", editor)
    comune = dict(
        days=[date(2026, 10, 26)], sections=("health",), repo_root=repo, data_dir=data,
        summary_dir=summary, model="finto:1b", say=lambda m: None,
    )
    # Col pavimento si ferma subito: il testo e' pulito e Claude no.
    senza = bench_tune.tune(iterations=3, **comune)
    assert "quello di Claude" in senza["stopped"]
    assert [h["iteration"] for h in senza["history"]] == [0]
    # Con una soglia impossibile tira avanti e consuma i giri.
    con = bench_tune.tune(iterations=2, target=-1.0, **comune)
    assert len(con["history"]) > 1
