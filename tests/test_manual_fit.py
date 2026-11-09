"""Un FIT che non viene da Garmin Connect entra nell'archivio come gli altri.

Lo scaricamento di Garmin estrae file che si chiamano `<id>_ACTIVITY.fit`, e
per anni l'archivio ha guardato solo quelli: l'esportazione di MyWhoosh di una
pedalata al rullo — che si chiama come il gettone con cui l'hai scaricata — era
un allenamento vero in una cartella letta ogni giorno, e restava fuori per il
nome che porta.

Due cose vanno provate, e la seconda e' quella che si rompe in silenzio: che il
file entri, e che **non venga riletto a ogni sync**, perche' il suo id non sta
nel nome e la chiave con cui si riconosce e' il percorso.
"""

import shutil
from datetime import datetime

import pandas as pd
import pytest

from training.garmin.config import DATA_DIR
from training.interface import db
from training.interface.db import list_activities, rebuild, sync
from training.interface.fit import MANUAL_ID_BASE, load_activity_summary

ARCHIVE = (DATA_DIR / "db" / "activities.db").exists()


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / "db").mkdir()
    (tmp_path / "fit").mkdir()
    (tmp_path / "json").mkdir()
    return tmp_path


@pytest.fixture(scope="module")
def a_real_fit():
    """Un FIT vero dall'archivio, il piu' piccolo: questi test provano la
    strada che fa un file, non i numeri che ci sono dentro."""
    if not ARCHIVE:
        pytest.skip("serve l'archivio vero")
    files = sorted((DATA_DIR / "fit").glob("*_ACTIVITY.fit"), key=lambda p: p.stat().st_size)
    if not files:
        pytest.skip("nessun FIT nell'archivio")
    return files[0]


class TestAFitWithoutAnIdInTheName:
    def test_it_gets_in_with_an_id_taken_from_its_start_time(self, data_dir, a_real_fit):
        # Lo stesso file, due volte: una col nome di Garmin e una col nome di
        # un'esportazione. Devono diventare due righe con due id, perche' per
        # l'archivio sono due file diversi — e' il modo di avere un FIT vero
        # senza id nel nome senza dipendere da un'esportazione di MyWhoosh.
        shutil.copy(a_real_fit, data_dir / "fit" / a_real_fit.name)
        manual = data_dir / "fit" / "9xhBLisD1yrpjp0BGOC2JAOajk6OiLqYCkI717pw.fit"
        shutil.copy(a_real_fit, manual)

        rebuild(data_dir, say=lambda _: None)
        activities = list_activities(data_dir)

        assert len(activities) == 2, "ci sono entrambi"
        theirs = activities[activities["path"] == str(manual)].iloc[0]
        start = load_activity_summary(manual)["start_time"]
        assert theirs.activity_id > MANUAL_ID_BASE, "l'id non puo' confondersi con quelli di Garmin"
        assert theirs.start_time == pd.Timestamp(start), "e' la stessa seduta del file di Garmin"
        assert theirs.sport == activities.iloc[0].sport

    def test_the_id_does_not_change_between_two_rebuilds(self, data_dir, a_real_fit):
        """L'id viene dall'istante di partenza e non dal nome del file, quindi
        va provato che sia lo stesso ogni volta: se cambiasse, ogni rebuild
        lascerebbe una riga in piu' per la stessa seduta."""
        shutil.copy(a_real_fit, data_dir / "fit" / "qualunque-nome.fit")

        rebuild(data_dir, say=lambda _: None)
        first = set(list_activities(data_dir)["activity_id"])
        rebuild(data_dir, say=lambda _: None)

        assert set(list_activities(data_dir)["activity_id"]) == first

    def test_a_second_sync_does_not_read_it_again(self, data_dir, a_real_fit, monkeypatch):
        shutil.copy(a_real_fit, data_dir / "fit" / "qualunque-nome.fit")
        rebuild(data_dir, say=lambda _: None)

        reads = []
        real = db.load_activity_summary
        monkeypatch.setattr(
            db, "load_activity_summary", lambda path: (reads.append(path), real(path))[1]
        )

        assert sync(data_dir) == 0, "niente di nuovo da leggere"
        assert reads == [], "il file c'e' gia': aprirlo e' un secondo buttato"
        assert len(list_activities(data_dir)) == 1


class TestTheNameOfTheActivity:
    """`activity_names.json` ha solo le attivita' di Garmin Connect. Di una
    pedalata esportata da MyWhoosh il nome del percorso sta in un campo dello
    sviluppatore del FIT, ed e' meglio di una cella vuota — ma vale solo dove
    Connect non dice niente, perche' quello di Connect e' il nome che Andrea
    puo' correggere."""

    @pytest.fixture
    def fake_fit(self, data_dir, monkeypatch):
        """Un file finto e un riepilogo inventato: qui si prova la precedenza
        fra i due nomi, e un FIT vero con il campo `Title` non si puo'
        fabbricare in un test."""
        path = data_dir / "fit" / "gettone.fit"
        path.write_bytes(b"non viene mai aperto")

        summary = {
            "activity_id": MANUAL_ID_BASE + 1762622166,
            "path": str(path),
            "fit_name": "Al Qudra",
            "sport": "cycling",
            "sub_sport": "virtual_activity",
            "start_time": datetime(2026, 11, 8, 18, 16, 6),
            "total_distance_km": 15.3,
            "total_time_min": 32.1,
            "avg_heart_rate": 122,
            "max_heart_rate": 144,
            "avg_speed_kmh": 28.6,
            "total_calories": 323,
            "total_ascent_m": 30,
            "total_descent_m": None,
            "vo2max": None,
            "aerobic_te": None,
            "anaerobic_te": None,
            "hr_zone_bounds": None,
            "threshold_hr": None,
            "workout_name": None,
            "workout_active_steps": None,
            "workout_active_max_s": None,
        }
        monkeypatch.setattr(db, "load_activity_summary", lambda _: dict(summary))
        monkeypatch.setattr(db, "_parse_fit_records", lambda _: pd.DataFrame())
        monkeypatch.setattr(db, "_parse_fit_laps", lambda _: pd.DataFrame())
        return summary

    def test_the_fit_title_is_used_when_connect_has_nothing(self, data_dir, fake_fit):
        rebuild(data_dir, say=lambda _: None)

        assert list_activities(data_dir).iloc[0].activity_name == "Al Qudra"

    def test_connect_wins_when_it_has_a_name(self, data_dir, fake_fit):
        (data_dir / "json" / "activity_names.json").write_text(
            '{"%d": "Rullo serale"}' % fake_fit["activity_id"], encoding="utf-8"
        )

        rebuild(data_dir, say=lambda _: None)

        assert list_activities(data_dir).iloc[0].activity_name == "Rullo serale"
