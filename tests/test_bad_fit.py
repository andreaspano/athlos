"""Un file che non si legge non deve portare giu' l'API.

`sync()` e `rebuild()` leggono i FIT dentro una somma: un file illeggibile
alzava, e con lui `list_activities()` e **ogni** endpoint dietro
`api/cache.py` — 500 a ogni richiesta, per sempre, perche' il file non viene
consumato e la riga della versione non avanza.
"""

import shutil

import pytest

from training.garmin.config import DATA_DIR
from training.interface.db import list_activities, rebuild

ARCHIVE = (DATA_DIR / "db" / "activities.db").exists()


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / "db").mkdir()
    (tmp_path / "fit").mkdir()
    (tmp_path / "json").mkdir()
    return tmp_path


@pytest.fixture(scope="module")
def a_real_fit():
    """Un FIT vero dall'archivio: quello che si legge serve a provare che
    quello che non si legge e' l'unico scartato."""
    if not ARCHIVE:
        pytest.skip("serve l'archivio vero")
    files = sorted((DATA_DIR / "fit").glob("*_ACTIVITY.fit"), key=lambda p: p.stat().st_size)
    if not files:
        pytest.skip("nessun FIT nell'archivio")
    # Il piu' piccolo: leggerne uno costa, e questi test provano il percorso,
    # non i numeri.
    return files[0]


@pytest.fixture(scope="module")
def a_running_fit():
    """Una corsa: solo per gli sport a piedi si calcola la velocita'
    equivalente, quindi solo li' si puo' provare che un suo guasto non si
    porta via l'attivita'."""
    if not ARCHIVE:
        pytest.skip("serve l'archivio vero")
    from training.interface.db import list_activities as live

    activities = live(DATA_DIR)
    running = activities[activities["sport"] == "running"]
    if running.empty:
        pytest.skip("nessuna corsa nell'archivio")
    # La corsa col FIT piu' piccolo, per la stessa ragione.
    paths = [
        path
        for aid in running["activity_id"]
        if (path := DATA_DIR / "fit" / f"{int(aid)}_ACTIVITY.fit").exists()
    ]
    if not paths:
        pytest.skip("nessun FIT delle corse")
    return min(paths, key=lambda p: p.stat().st_size)


class TestAJunkFileIsSkipped:
    """La cache la costruisce `rebuild()`, che dal todo 93 e' un comando e non
    un effetto della lettura."""

    def test_a_file_that_is_not_a_fit_does_not_raise(self, data_dir, capsys):
        (data_dir / "fit" / "999999_ACTIVITY.fit").write_bytes(b"non sono un file FIT")

        assert rebuild(data_dir, say=lambda _: None) == 0
        assert list_activities(data_dir).empty
        assert "non si legge" in capsys.readouterr().out

    def test_it_is_skipped_on_every_call_and_never_wedges(self, data_dir):
        (data_dir / "fit" / "999999_ACTIVITY.fit").write_bytes(b"non sono un file FIT")

        for _ in range(3):
            rebuild(data_dir, say=lambda _: None)
            assert list_activities(data_dir).empty, "nessuna eccezione, nessun blocco"

    def test_the_good_ones_still_get_in(self, data_dir, a_real_fit):
        shutil.copy(a_real_fit, data_dir / "fit" / a_real_fit.name)
        (data_dir / "fit" / "999999_ACTIVITY.fit").write_bytes(b"spazzatura")

        rebuild(data_dir, say=lambda _: None)
        activities = list_activities(data_dir)

        assert len(activities) == 1, "l'attivita' buona c'e', quella rotta no"
        assert 999999 not in set(activities["activity_id"])


class TestEquivalentSpeedCannotKillAnActivity:
    """La velocita' equivalente e' una colonna in piu': se il modello di
    costo non si applica — un'attivita' che attraversa il cambio d'ora, dove
    l'indice locale torna indietro — resta vuota, come per gli sport che non
    la prevedono."""

    def test_a_failure_leaves_the_column_empty_and_the_activity_in(
        self, data_dir, a_running_fit, monkeypatch, capsys
    ):
        from training.interface import db

        shutil.copy(a_running_fit, data_dir / "fit" / a_running_fit.name)

        def boom(*args, **kwargs):
            raise ValueError("index values must be monotonic")

        monkeypatch.setattr(db, "equivalent_speed_kmh", boom)
        monkeypatch.setattr(db, "equivalent_speed_series", boom)

        db.rebuild(data_dir, say=lambda _: None)
        activities = list_activities(data_dir)

        assert len(activities) == 1, "l'attivita' c'e' comunque"
        assert activities["equiv_speed_kmh"].isna().all()
        assert "non calcolata" in capsys.readouterr().out
