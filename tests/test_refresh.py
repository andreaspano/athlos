"""La macchina a stati dell'orchestratore: come finisce un giro, e cosa
racconta dopo.

Qui non gira nessun agente: `_write_section` e `_prepare` vengono sostituiti,
perche' il punto non e' cosa scrivono gli agenti ma cosa dice l'orchestratore
quando qualcosa va storto.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from training.api import refresh as R
from training.api.sections import DAILY

DAY = date(2026, 10, 1)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Lo stato e' di modulo: ogni test parte dal suo."""
    monkeypatch.setattr(R, "_state", R._blank_state())


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Sostituisce la preparazione dei dati e la scrittura delle sezioni.

    `prepare` decide se i fatti si preparano; `write` decide, sezione per
    sezione, se l'agente ha scritto.
    """

    def build(prepare=lambda *a, **k: (True, None, {"ok": True, "message": None}), write=None):
        def default_write(
            kind, section, subject, moment, repo_root, facts, folder, began,
            summary_dir, data_dir,
        ):
            (Path(folder) / f"{section.key}.md").write_text("testo", encoding="utf-8")
            return True, None

        monkeypatch.setattr(R, "_prepare", prepare)
        monkeypatch.setattr(R, "_write_section", write or default_write)
        return dict(
            kind=DAILY, subject=DAY, started=datetime.now(), repo_root=tmp_path,
            summary_dir=tmp_path / "summary", data_dir=tmp_path,
        )

    return build


def run(args, sections=None, **kwargs):
    chosen = sections if sections is not None else DAILY.run_order[:2]
    return R._run(
        args["kind"], args["subject"], args["started"], args["repo_root"],
        args["summary_dir"], args["data_dir"], tuple(chosen), update=False, **kwargs
    )


class TestTerminalState:
    def test_a_clean_run_ends_done(self, harness):
        args = harness()
        outcome = run(args)
        assert [row["status"] for row in outcome["sections"].values()] == ["done", "done"]
        assert R.status()["status"] == "done"

    def test_a_crash_still_leaves_a_terminal_state(self, harness):
        """Era il difetto: senza `finally` il thread moriva, lo stato restava
        'running' per sempre e il guardiano di `start()` rifiutava ogni
        Refresh successivo fino al riavvio dell'API."""
        def boom(*args, **kwargs):
            raise OSError("mount in sola lettura")

        args = harness(prepare=boom)
        with pytest.raises(OSError):
            run(args)

        state = R.status()
        assert state["status"] == "failed"
        assert state["finished"] is not None
        assert "OSError" in state["message"]

    def test_a_failed_section_is_reported(self, harness):
        def write(
            kind, section, subject, moment, repo_root, facts, folder, began,
            summary_dir, data_dir,
        ):
            if section.key == DAILY.run_order[0].key:
                return False, "02_load exited with 1."
            (Path(folder) / f"{section.key}.md").write_text("testo", encoding="utf-8")
            return True, None

        args = harness(write=write)
        outcome = run(args)
        assert outcome["sections"][DAILY.run_order[0].key]["status"] == "failed"
        assert "kept their previous text" in outcome["message"]
        assert R.status()["status"] == "failed"


class TestLockCollision:
    def test_a_collision_keeps_the_previous_record(self, harness, monkeypatch):
        """`start()` azzerava le sezioni **prima** di provare il lock: una
        collisione con il timer cancellava il motivo del guasto precedente e
        mostrava sei card 'idle' senza che nessun agente avesse girato."""
        key = DAILY.run_order[0].key
        R._set(key, status="failed", message="02_load exited with 1.")

        import contextlib

        @contextlib.contextmanager
        def busy(data_dir):
            yield False

        monkeypatch.setattr(R, "_claim", busy)
        args = harness()
        assert run(args) is None

        state = R.status()
        assert state["status"] == "failed"
        assert state["message"] == "Another refresh is already running."
        assert state["sections"][key]["message"] == "02_load exited with 1.", "il motivo resta"


def test_write_section_refuses_an_empty_file(tmp_path, monkeypatch):
    """Il controllo vero, preso da solo: `claude` esce 0 e lascia un file
    vuoto."""
    import subprocess

    section = DAILY.run_order[0]
    folder = tmp_path / "day"
    folder.mkdir()

    def fake_run(command, **kwargs):
        (folder / f"{section.key}.md").touch()
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(R.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setattr(R, "_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(R, "_allowed_tools", lambda *a, **k: ["Read"])

    # `began` e' un secondo prima, come nella realta': fra la partenza e il
    # frammento passa il tempo dell'agente. (E serve: l'`mtime` di un file
    # appena creato puo' essere un millesimo *indietro* rispetto a
    # `datetime.now()`, perche' i due orologi hanno grana diversa.)
    good, problem = R._write_section(
        DAILY, section, DAY, "morning", tmp_path, tmp_path / "facts.json",
        folder, datetime.now() - timedelta(seconds=1), tmp_path, tmp_path,
    )
    assert good is False
    assert "empty" in problem


class TestBackfill:
    def test_a_period_that_wrote_nothing_is_not_counted(self, tmp_path, monkeypatch):
        """Il conto veniva dallo stato globale: un periodo in cui `_prepare`
        era fallito si contava con gli stati 'done' del periodo prima."""
        calls = {"n": 0}

        def prepare(kind, subject, repo_root, data_dir, facts, update):
            calls["n"] += 1
            if subject == date(2026, 10, 2):
                return False, "i fatti non si preparano", None
            return True, None, None

        def write(
            kind, section, subject, moment, repo_root, facts, folder, began,
            summary_dir, data_dir,
        ):
            (Path(folder) / f"{section.key}.md").write_text("testo", encoding="utf-8")
            return True, None

        monkeypatch.setattr(R, "_prepare", prepare)
        monkeypatch.setattr(R, "_write_section", write)
        monkeypatch.setattr(R, "_last_complete", lambda kind, today: date(2026, 10, 31))

        tally = R.backfill(
            DAILY, date(2026, 10, 1), date(2026, 10, 2), tmp_path, tmp_path / "summary", tmp_path
        )

        day_one = tmp_path / "summary" / DAILY.folder / "2026-10-01"
        day_two = tmp_path / "summary" / DAILY.folder / "2026-10-02"
        assert day_one.is_dir(), "il primo giorno si scrive"
        assert not day_two.exists(), "il secondo no"
        assert tally["written"] == len(list(day_one.glob("*.md")))
        assert tally["failed"], "le sezioni del secondo giorno sono fra le fallite"
        assert any("2026-10-02" in row for row in tally["failed"])


class TestFragmentReaders:
    """I tre posti che dicevano "scritto" in tre modi diversi (app.py)."""

    def test_an_empty_new_name_does_not_shadow_the_legacy_one(self, tmp_path):
        from training.api.app import _fragment_path

        folder = tmp_path / "2026-10-01"
        folder.mkdir()
        legacy = DAILY.old_fragments.get("summary", ())
        assert legacy, "il registro conosce i nomi vecchi del Summary"
        (folder / f"{legacy[0]}.md").write_text("The body held up well today.", encoding="utf-8")
        (folder / "summary.md").touch()

        chosen = _fragment_path(folder, "summary", DAILY)
        assert chosen.name == f"{legacy[0]}.md"
        assert chosen.read_text(encoding="utf-8").startswith("The body")

    def test_a_fragment_with_only_a_verdict_is_not_written(self, tmp_path):
        from training.api.app import _fragment_sections

        folder = tmp_path / "2026-10-01"
        folder.mkdir()
        (folder / "training.md").write_text("verdict: high\n", encoding="utf-8")

        rows = {title: (body, written, verdict) for title, body, written, verdict in _fragment_sections(folder, DAILY)}
        body, written, verdict = next(v for k, v in rows.items() if k and "rain" in k)
        assert body == ""
        assert written is None, "nessuna ora su una sezione senza testo"
        assert verdict == "high"


class TestSummaryGate:
    """Il Summary legge i frammenti degli altri (`Section.reads_fragments`):
    se in questo giro qualcuno e' fallito, dei suoi leggerebbe il testo del
    giro prima."""

    def test_the_summary_does_not_run_after_a_failure(self, harness, tmp_path):
        ran: list[str] = []

        def write(
            kind, section, subject, moment, repo_root, facts, folder, began,
            summary_dir, data_dir,
        ):
            ran.append(section.key)
            if section.key == "health":
                return False, "01_health exited with 1."
            (Path(folder) / f"{section.key}.md").write_text("testo", encoding="utf-8")
            return True, None

        args = harness(write=write)
        order = [s for s in DAILY.run_order if s.key in ("health", "summary")]
        outcome = run(args, sections=order)

        assert "health" in ran
        assert "summary" not in ran, "non si chiama l'agente del Summary"
        assert outcome["sections"]["summary"]["status"] == "failed"
        assert "not run" in outcome["sections"]["summary"]["message"]
        assert "health" in outcome["sections"]["summary"]["message"]

    def test_the_summary_runs_when_the_others_are_fine(self, harness):
        ran: list[str] = []

        def write(
            kind, section, subject, moment, repo_root, facts, folder, began,
            summary_dir, data_dir,
        ):
            ran.append(section.key)
            (Path(folder) / f"{section.key}.md").write_text("testo", encoding="utf-8")
            return True, None

        args = harness(write=write)
        order = [s for s in DAILY.run_order if s.key in ("health", "summary")]
        outcome = run(args, sections=order)

        assert "summary" in ran
        assert outcome["sections"]["summary"]["status"] == "done"


class TestCollisionExitCode:
    def test_a_report_that_could_not_run_exits_non_zero(self, monkeypatch, tmp_path):
        """Il timer ha `OnFailure=athlos-alert@`: uscendo 0, systemd
        registrava un successo per un giro che non ha scritto niente."""
        import contextlib

        import pytest as _pytest

        @contextlib.contextmanager
        def busy(data_dir):
            yield False

        monkeypatch.setattr(R, "_claim", busy)
        monkeypatch.setattr(R, "_prepare", lambda *a, **k: (True, None, None))
        args = dict(
            kind=DAILY, subject=DAY, started=datetime.now(), repo_root=tmp_path,
            summary_dir=tmp_path, data_dir=tmp_path,
        )
        assert run(args) is None, "il giro non parte"
        # e il comando, davanti a None, esce 1: vedi `_cli`.
        source = (R.__file__,)
        assert "raise SystemExit(1)" in open(source[0], encoding="utf-8").read()


class TestCliExitCode:
    """Il codice d'uscita del comando: e' quello che systemd guarda, e con
    `OnFailure=athlos-alert@` e' anche l'unico modo in cui un giro andato
    male si fa sentire. Non era coperto, ed e' il buco da cui e' passato un
    `NameError` nel ramo finale."""

    def outcome(self, message=None, download=None, failed=()):
        rows = {
            s.key: {"status": "failed" if s.key in failed else "done", "message": None}
            for s in DAILY.run_order
        }
        return {"message": message, "download": download, "sections": rows}

    def run_cli(self, monkeypatch, outcome, argv=("--moment", "morning")):
        import sys

        monkeypatch.setattr(sys, "argv", ["training-daily-report", *argv])
        monkeypatch.setattr(R, "_run", lambda *a, **k: outcome)
        with pytest.raises(SystemExit) as caught:
            R._cli(DAILY)
        return caught.value.code

    def test_a_clean_run_exits_zero(self, monkeypatch):
        code = self.run_cli(monkeypatch, self.outcome(download={"ok": True, "message": None}))
        assert code == 0

    def test_a_failed_section_exits_one(self, monkeypatch):
        code = self.run_cli(
            monkeypatch,
            self.outcome(message="These sections kept their previous text: load", failed=("load",)),
        )
        assert code == 1

    def test_a_failed_download_exits_one(self, monkeypatch):
        """Todo 81: il report c'e' lo stesso, ma e' scritto su dati vecchi."""
        code = self.run_cli(
            monkeypatch,
            self.outcome(download={"ok": False, "message": "uv: not found"}),
        )
        assert code == 1

    def test_a_run_that_never_started_exits_one(self, monkeypatch):
        code = self.run_cli(monkeypatch, None)
        assert code == 1


# --- Chi scrive le quattro card del corpo (dal 21 novembre 2026) ---
#
# Dal giorno di `LOCAL_FROM` Health, Load, Recovery e Fitness le scrive il
# modello di casa, in pezzi, e Claude per quelle quattro non gira piu'. Il
# confronto fra i due, durato dal 26 ottobre sui 104 testi del banco, finisce
# li': `bench_tune.CORPUS_TO` lo dice dall'altra parte.
#
# Qui non si parla con ollama: si sostituisce `ollama.section_text`, come fa
# `tests/test_bench.py`. Quello che questi test difendono non e' il testo —
# quello si legge sul banco — ma **chi** lo scrive e **in che giorni**.


class TestWhoWrites:
    def test_the_four_body_cards_are_local_and_the_rest_is_not(self):
        """Le quattro del corpo del giorno portano la chiave della spezzata;
        il Training e il Summary no, e la settimana nemmeno una."""
        from training.api.sections import SECTIONS, WEEK_SECTIONS

        local = {s.key: s.local for s in SECTIONS if s.local}
        assert local == {
            "health": "health_split",
            "load": "load_split",
            "recovery": "recovery_split",
            "fitness": "fitness_split",
        }
        assert all(s.local is None for s in SECTIONS if s.key in ("training", "summary"))
        assert all(s.local is None for s in WEEK_SECTIONS)

    def test_every_local_key_exists(self):
        """**Il campo e' scritto a mano, quindi si controlla.** Una chiave che
        in `ollama.SECTIONS` non c'e' alzerebbe un `KeyError` alle 8:15; una
        che c'e' ma e' di un'altra sezione metterebbe nella card il testo di
        un'altra misura senza che niente lo dica."""
        from training.api import ollama
        from training.api.sections import SECTIONS

        for section in SECTIONS:
            if not section.local:
                continue
            assert section.local in ollama.SECTIONS
            # E la spezzata e' della sua sezione, non di un'altra.
            assert ollama.SECTIONS[section.local].title == section.title

    def test_a_local_section_runs_no_subprocess(self, tmp_path, monkeypatch):
        """**Il cuore del cambio**: la card si scrive senza lanciare
        `claude`. Se un giorno il bivio si rompesse, il giro continuerebbe a
        funzionare pagando gettoni e scrivendo il testo dell'altro."""
        from training.api import ollama

        section = next(s for s in DAILY.run_order if s.key == "health")
        folder = tmp_path / "day"
        folder.mkdir()
        chiesto = {}

        def fake_ollama(wanted, day, payload, repo_root, week=None):
            chiesto["key"] = wanted.key
            chiesto["day"] = day
            return "Il verdetto.\n\nLa prima misura.\n\nLa seconda.", "finto:1b"

        def no_subprocess(*args, **kwargs):
            raise AssertionError("ha lanciato un sottoprocesso")

        monkeypatch.setattr(ollama, "section_text", fake_ollama)
        monkeypatch.setattr(R.subprocess, "run", no_subprocess)
        monkeypatch.setattr(R, "_prepare", lambda *a, **k: (True, None, None))

        good, problem = R._write_section(
            DAILY, section, date(2026, 11, 21), "morning", tmp_path,
            tmp_path / "facts.json", folder, datetime.now() - timedelta(seconds=1),
            tmp_path, tmp_path,
        )
        assert good is True
        assert problem == "written by finto:1b"
        assert chiesto == {"key": "health_split", "day": date(2026, 11, 21)}
        assert (folder / "health.md").read_text(encoding="utf-8").startswith("Il verdetto.")

    def test_the_fragment_keeps_its_paragraphs(self, tmp_path, monkeypatch):
        """La forma e' quella della spezzata: un paragrafo per misura, e non
        un blocco cucito. **L'ordine e il numero li decide Python**, ed e' il
        punto di tutta questa strada — attaccarli in uno butterebbe via la
        cosa per cui la sezione e' stata spezzata."""
        from training.api import ollama

        section = next(s for s in DAILY.run_order if s.key == "recovery")
        folder = tmp_path / "day"
        folder.mkdir()
        cinque = "\n\n".join(f"Il paragrafo numero {n}." for n in range(1, 6))
        monkeypatch.setattr(ollama, "section_text", lambda *a, **k: (cinque, "finto:1b"))

        R._write_section(
            DAILY, section, date(2026, 11, 21), "morning", tmp_path,
            tmp_path / "facts.json", folder, datetime.now(), tmp_path, tmp_path,
        )
        written = (folder / "recovery.md").read_text(encoding="utf-8")
        assert len([p for p in written.strip().split("\n\n") if p.strip()]) == 5

    def test_a_day_before_the_switch_still_goes_to_claude(self, tmp_path, monkeypatch):
        """**Il test che difende i frammenti di ottobre.**
        `make backfill_reports` rifa' giorni passati: senza il confronto con
        `LOCAL_FROM` riscriverebbe con llama le card che Claude ha scritto,
        cambiando il report a posteriori e cancellando dal disco i 104
        frammenti che sono il bersaglio del banco."""
        from training.api import ollama

        section = next(s for s in DAILY.run_order if s.key == "health")
        folder = tmp_path / "day"
        folder.mkdir()
        lanciati = []

        def fake_run(command, **kwargs):
            lanciati.append(command[0])
            (folder / f"{section.key}.md").write_text("di Claude", encoding="utf-8")
            return R.subprocess.CompletedProcess(command, 0, "", "")

        def no_ollama(*args, **kwargs):
            raise AssertionError("ha chiesto al modello di casa un giorno di Claude")

        monkeypatch.setattr(ollama, "section_text", no_ollama)
        monkeypatch.setattr(R.shutil, "which", lambda name: "/usr/bin/claude")
        monkeypatch.setattr(R.subprocess, "run", fake_run)
        monkeypatch.setattr(R, "_prompt", lambda *a, **k: "prompt")
        monkeypatch.setattr(R, "_allowed_tools", lambda *a, **k: ["Read"])

        good, _ = R._write_section(
            DAILY, section, date(2026, 10, 26), "morning", tmp_path,
            tmp_path / "facts.json", folder, datetime.now() - timedelta(seconds=1),
            tmp_path, tmp_path,
        )
        assert good is True
        assert lanciati == ["/usr/bin/claude"]
        assert (folder / "health.md").read_text(encoding="utf-8") == "di Claude"

    def test_a_silent_ollama_fails_the_section(self, tmp_path, monkeypatch):
        """**Nessuna ricaduta su Claude.** La sezione fallisce, il motivo
        finisce nello stato della pagina, `_cli` esce 1 e il timer manda la
        notifica. La card di quel giorno resta vuota, che e' meglio di un
        report completo in cui non si sa chi ha scritto cosa."""
        from training.api import ollama

        section = next(s for s in DAILY.run_order if s.key == "fitness")
        folder = tmp_path / "day"
        folder.mkdir()

        def muto(*args, **kwargs):
            raise ollama.OllamaError("Cannot reach Ollama at 127.0.0.1:11434")

        monkeypatch.setattr(ollama, "section_text", muto)
        monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: 1 / 0)

        good, problem = R._write_section(
            DAILY, section, date(2026, 11, 21), "morning", tmp_path,
            tmp_path / "facts.json", folder, datetime.now(), tmp_path, tmp_path,
        )
        assert good is False
        assert "fitness" in problem and "Cannot reach Ollama" in problem
        assert not (folder / "fitness.md").exists()

    def test_an_empty_answer_does_not_cover_the_old_text(self, tmp_path, monkeypatch):
        """Un frammento vuoto passava per scritto, contava come sezione fatta
        e copriva quello col nome vecchio, lasciando la card bianca e il testo
        di prima irraggiungibile (`_write_section`, e `_written`). Scrivere da
        Python invece che da un sottoprocesso lo rende improbabile, non
        impossibile."""
        from training.api import ollama

        section = next(s for s in DAILY.run_order if s.key == "load")
        folder = tmp_path / "day"
        folder.mkdir()
        monkeypatch.setattr(ollama, "section_text", lambda *a, **k: ("   \n\n  ", "finto:1b"))

        good, problem = R._write_section(
            DAILY, section, date(2026, 11, 21), "morning", tmp_path,
            tmp_path / "facts.json", folder, datetime.now(), tmp_path, tmp_path,
        )
        assert good is False
        assert "empty" in problem
        assert not (folder / "load.md").exists()
