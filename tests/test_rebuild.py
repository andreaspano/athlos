"""La ricostruzione della cache: fuori dalle richieste, accanto, a pezzi.

Il 2 novembre 2026 due correzioni da poche righe sono costate 37 minuti di
API ferma ciascuna, perche' `sync()` chiamava `rebuild()` e `rebuild()`
cancellava il database vivo — e `sync()` la chiama chi legge, cioe' qualunque
richiesta HTTP (todo 93).
"""

import shutil

import pytest

from training.garmin.config import DATA_DIR
from training.interface import db

ARCHIVE = (DATA_DIR / "db" / "activities.db").exists()


@pytest.fixture
def data_dir(tmp_path):
    for folder in ("db", "fit", "json"):
        (tmp_path / folder).mkdir()
    return tmp_path


@pytest.fixture(scope="module")
def two_fits():
    if not ARCHIVE:
        pytest.skip("serve l'archivio vero")
    files = sorted((DATA_DIR / "fit").glob("*_ACTIVITY.fit"), key=lambda p: p.stat().st_size)
    if len(files) < 2:
        pytest.skip("servono due FIT")
    return files[:2]


def quiet(_message: str) -> None:
    pass


class TestSyncDoesNotRebuild:
    def test_an_empty_cache_is_reported_not_built(self, data_dir, two_fits):
        shutil.copy(two_fits[0], data_dir / "fit" / two_fits[0].name)

        assert db.sync(data_dir) == 0, "non ha letto niente"
        assert db.list_activities(data_dir).empty, "e non ha costruito niente"

        state = db.cache_state(data_dir)
        assert state["ok"] is False
        assert "make rebuild" in state["message"]

    def test_an_older_version_serves_what_it_has(self, data_dir, two_fits):
        shutil.copy(two_fits[0], data_dir / "fit" / two_fits[0].name)
        db.rebuild(data_dir, say=quiet)
        assert len(db.list_activities(data_dir)) == 1

        conn = db._connect(data_dir)
        db._write_version(conn, db._LOGIC_KEY, "una_versione_vecchia")
        conn.commit()
        conn.close()

        # Il secondo file non entra: le righe che ci sono vengono da un altro
        # codice, e mescolarle sarebbe peggio.
        shutil.copy(two_fits[1], data_dir / "fit" / two_fits[1].name)
        assert db.sync(data_dir) == 0
        assert len(db.list_activities(data_dir)) == 1, "i dati vecchi si servono"

        state = db.cache_state(data_dir)
        assert state["ok"] is False
        assert "una_versione_vecchia" in state["message"]
        assert db.LOGIC_VERSION in state["message"]
        assert "make rebuild" in state["message"]

    def test_a_current_cache_is_quiet(self, data_dir, two_fits):
        shutil.copy(two_fits[0], data_dir / "fit" / two_fits[0].name)
        db.rebuild(data_dir, say=quiet)

        assert db.sync(data_dir) == 0, "niente di nuovo da leggere"
        assert db.cache_state(data_dir) == {"ok": True, "message": None}

    def test_a_new_file_still_gets_in(self, data_dir, two_fits):
        shutil.copy(two_fits[0], data_dir / "fit" / two_fits[0].name)
        db.rebuild(data_dir, say=quiet)
        shutil.copy(two_fits[1], data_dir / "fit" / two_fits[1].name)

        assert db.sync(data_dir) == 1
        assert len(db.list_activities(data_dir)) == 2


class TestRebuildBuildsBeside:
    def test_the_live_database_survives_a_failed_rebuild(self, data_dir, two_fits, monkeypatch):
        """Prima si cancellava il vivo e si ricominciava: un'interruzione
        lasciava l'archivio a meta' e ogni richiesta senza niente da
        leggere."""
        shutil.copy(two_fits[0], data_dir / "fit" / two_fits[0].name)
        db.rebuild(data_dir, say=quiet)
        before = db._db_path(data_dir).stat().st_size

        # Un'eccezione qualunque: per il codice e' lo stesso percorso di un
        # Ctrl+C, che `pytest` non lascia catturare.
        def boom(*args, **kwargs):
            raise RuntimeError("interrotta")

        monkeypatch.setattr(db, "_parse_and_store_or_warn", boom)
        with pytest.raises(RuntimeError):
            db.rebuild(data_dir, say=quiet)

        assert db._db_path(data_dir).stat().st_size == before, "il vivo e' intatto"

        monkeypatch.undo()
        assert len(db.list_activities(data_dir)) == 1, "e si legge ancora"

    def test_an_interrupted_rebuild_is_resumed(self, data_dir, two_fits, monkeypatch):
        for path in two_fits:
            shutil.copy(path, data_dir / "fit" / path.name)
        real = db._parse_and_store_or_warn
        calls = {"n": 0}

        def once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("interrotta")
            return real(*args, **kwargs)

        monkeypatch.setattr(db, "_parse_and_store_or_warn", once)
        monkeypatch.setattr(db, "REBUILD_BATCH", 1)
        with pytest.raises(RuntimeError):
            db.rebuild(data_dir, say=quiet)

        beside = db._db_path(data_dir).with_name(db._db_path(data_dir).name + ".new")
        assert beside.exists(), "il lavoro fatto resta accanto"

        monkeypatch.setattr(db, "_parse_and_store_or_warn", real)
        said: list[str] = []
        db.rebuild(data_dir, say=said.append)

        assert any("riprendo" in line for line in said)
        assert len(db.list_activities(data_dir)) == 2
        assert not beside.exists(), "a posto, il file accanto non c'e' piu'"


@pytest.mark.skipif(not ARCHIVE, reason="serve l'archivio vero")
class TestDerivedVersion:
    def test_a_derived_bump_does_not_reread_the_files(self, data_dir, two_fits, monkeypatch):
        """E' la scorciatoia che non c'era: due delle tre correzioni del 2
        novembre cambiavano solo conti derivati, e sono costate mezz'ora."""
        shutil.copy(two_fits[0], data_dir / "fit" / two_fits[0].name)
        db.rebuild(data_dir, say=quiet)

        conn = db._connect(data_dir)
        db._write_version(conn, db._DERIVED_KEY, "0")
        conn.commit()
        conn.close()

        def boom(*args, **kwargs):
            raise AssertionError("nessun file va riletto")

        monkeypatch.setattr(db, "_parse_and_store_or_warn", boom)
        db.sync(data_dir)

        conn = db._connect(data_dir)
        try:
            assert db._stored_version(conn, db._DERIVED_KEY) == db.DERIVED_VERSION
        finally:
            conn.close()
        assert db.cache_state(data_dir)["ok"] is True


class TestRefreshDerivedRemovesToo:
    """Un giro derivato che non sa togliere non e' un giro derivato:
    `_store_zone_minutes` non scrive mai un NULL, quindi un valore che non si
    puo' piu' calcolare resterebbe in tabella per sempre."""

    def test_a_value_that_can_no_longer_be_computed_goes_away(self, data_dir):
        import json

        conn = db._connect(data_dir)
        try:
            conn.execute(
                "INSERT INTO activities (activity_id, path, sport, start_time, "
                "hr_zone_bounds, threshold_hr, min_low_aerobic, min_high_aerobic, "
                "min_anaerobic, parsed_at) VALUES (1, 'x.fit', 'running', "
                "'2026-09-20 10:00:00', ?, NULL, 10.0, 2.0, 0.0, 'x')",
                (json.dumps([110, 130, 150, 165, 180]),),
            )
            conn.commit()

            db.refresh_derived(conn)

            row = conn.execute(
                "SELECT min_low_aerobic, min_high_aerobic, min_anaerobic "
                "FROM activities WHERE activity_id = 1"
            ).fetchone()
            assert row == (None, None, None), "senza soglia non si puo' calcolare, e non resta"
        finally:
            conn.close()

    def test_it_is_idempotent(self, data_dir, two_fits):
        import shutil

        shutil.copy(two_fits[0], data_dir / "fit" / two_fits[0].name)
        db.rebuild(data_dir, say=quiet)

        conn = db._connect(data_dir)
        try:
            def snapshot():
                return conn.execute(
                    "SELECT activity_id, min_low_aerobic, min_high_aerobic, min_anaerobic, "
                    "threshold_hr, threshold_hr_borrowed FROM activities ORDER BY activity_id"
                ).fetchall()

            before = snapshot()
            db.refresh_derived(conn)
            once = snapshot()
            db.refresh_derived(conn)
            assert once == snapshot()
            assert once == before, "il rebuild lascia la tabella gia' in pari"
        finally:
            conn.close()
