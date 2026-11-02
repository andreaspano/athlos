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
        def default_write(kind, section, subject, moment, repo_root, facts, folder, began, summary_dir):
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
        def write(kind, section, subject, moment, repo_root, facts, folder, began, summary_dir):
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
        folder, datetime.now() - timedelta(seconds=1), tmp_path,
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

        def write(kind, section, subject, moment, repo_root, facts, folder, began, summary_dir):
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
