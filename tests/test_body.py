"""La bilancia (todo 97): cosa diventa una pesata, e quale pesata risponde per
un giorno.

Il metro di questi test sono le tre regole che la card promette: **zero non e'
un valore**, **una pesata sola e non il meglio di tante**, e **mai una pesata
successiva al giorno che si guarda**.
"""

import json
from datetime import date, datetime

import pytest

from training.interface.body_data import body_on
from training.renpho.sync import measurement, write_days

# Una riga di Renpho, ridotta ai campi che contano. Quella vera ne ha 122, e
# le altre cento sono zeri, fasce della bilancia e impedenze degli elettrodi.
FULL = {
    "id": 6114246994923356032,
    "timeStamp": 1794301591,  # 2026-11-10 10:06:31 locale
    "resistance": True,
    "weight": 102.6,
    "bmi": 28.4,
    "bodyfat": 28.2,
    "water": 52.7,
    "muscle": 41.4,
    "smmMass": 42.48,
    "sinew": 68.74,
    "fatFreeWeight": 73.67,
    "bone": 4.9,
    "protein": 14.4,
    "subfat": 20.1,
    "visfat": 11.0,
    "bmr": 1961,
    "bodyage": 60,
    "measureAge": 58,
    "height": 189.5,
    "laBodyFatMass": 1.98,
    "laMuscleMass": 4.11,
    "trunkBodyFatMass": 0,
    "tBodyFatMass": 15.33,
    "tMuscleMass": 32.14,
}

# La pesata coi calzini: la cella di carico ha pesato, gli elettrodi no.
NO_IMPEDANCE = {
    "id": 6112934731285757824,
    "timeStamp": 1794145156,  # 2026-11-08 14:39:16
    "resistance": False,
    "weight": 102.0,
    "bmi": 28.3,
    "bodyfat": 0.0,
    "water": 0.0,
    "muscle": 0.0,
    "bmr": 0,
    "bodyage": 0,
    "measureAge": 58,
    "height": 189.5,
}


def at(stamp: int) -> str:
    return datetime.fromtimestamp(stamp).isoformat(timespec="seconds")


class TestMeasurement:
    def test_a_full_weigh_in_keeps_its_numbers(self):
        m = measurement(FULL)
        assert m["weight_kg"] == 102.6
        assert m["body_fat_pct"] == 28.2
        assert m["skeletal_muscle_kg"] == 42.48
        assert m["muscle_mass_kg"] == 68.74
        assert m["bmr_kcal"] == 1961
        assert m["impedance"] is True
        assert m["measured_at"] == at(1794301591)

    def test_without_impedance_only_weight_and_bmi_survive(self):
        """Zero non e' un valore: nessuno ha lo 0% di acqua, e una card che
        disegnasse quegli zeri direbbe una bugia precisa. Il peso e il BMI
        restano, che quelli non vengono dagli elettrodi."""
        m = measurement(NO_IMPEDANCE)
        assert m["impedance"] is False
        assert m["weight_kg"] == 102.0 and m["bmi"] == 28.3
        assert m["body_fat_pct"] is None
        assert m["water_pct"] is None
        assert m["bmr_kcal"] is None
        assert m["body_age"] is None
        assert m["segments"] is None

    def test_the_segments_come_through(self):
        """I segmenti non si mostrano ancora, ma si scrivono: il file e' il
        registro, e un dato buttato oggi non torna."""
        segments = measurement(FULL)["segments"]
        assert segments["trunk"] == {"fat_mass_kg": 15.33, "muscle_mass_kg": 32.14}
        assert segments["left_arm"]["muscle_mass_kg"] == 4.11


@pytest.fixture
def data_dir(tmp_path):
    """Due giorni di pesate, come quelli veri: l'8 novembre due (la prima senza
    impedenza), il 10 una."""
    second = {**FULL, "id": 1, "timeStamp": 1794145334}  # 2026-11-08 14:42:14
    write_days([measurement(r) for r in (NO_IMPEDANCE, second, FULL)], tmp_path)
    return tmp_path


class TestBodyOn:
    def test_the_day_of_the_weigh_in_answers_with_it(self, data_dir):
        body = body_on(data_dir, date(2026, 11, 10))
        assert body["days_ago"] == 0
        assert body["measured_day"] == date(2026, 11, 10)
        assert [m["value"] for m in body["measures"]][:2] == [102.6, 28.4]

    def test_a_day_without_one_gets_the_last_before_it(self, data_dir):
        """E' la regola che la card chiede: su una bilancia ci si sale quando
        si vuole, quindi un giorno senza pesata e' il caso normale."""
        body = body_on(data_dir, date(2026, 11, 13))
        assert body["measured_day"] == date(2026, 11, 10)
        assert body["days_ago"] == 3

    def test_a_past_day_never_sees_a_later_weigh_in(self, data_dir):
        """Aprendo il 9 novembre non si deve vedere la pesata del 10: un giorno
        passato non racconta il futuro."""
        body = body_on(data_dir, date(2026, 11, 9))
        assert body["measured_day"] == date(2026, 11, 8)
        assert body["days_ago"] == 1

    def test_before_the_first_weigh_in_there_is_nothing(self, data_dir):
        assert body_on(data_dir, date(2026, 11, 7)) is None

    def test_no_folder_is_not_an_error(self, tmp_path):
        """Chi non ha una bilancia non ha la cartella, e la card non c'e'."""
        assert body_on(tmp_path, date(2026, 11, 10)) is None

    def test_of_a_day_with_two_the_complete_one_wins(self, data_dir):
        """L'8 novembre ci sono due pesate a tre minuti di distanza, la prima
        senza impedenza: quella che dice qualcosa e' la seconda. E non si
        cuciono insieme — il peso di una e il grasso dell'altra sarebbero un
        corpo mai esistito."""
        body = body_on(data_dir, date(2026, 11, 8))
        assert body["impedance"] is True
        assert body["measured_at"] == at(1794145334)
        assert all(m["value"] is not None for m in body["measures"])

    def test_the_bands_wait_for_eight_weigh_ins(self, data_dir):
        """Tre pesate non fanno una fascia: lo scarto tipo sarebbe rumore, e la
        barra prometterebbe un "di solito" che non esiste."""
        body = body_on(data_dir, date(2026, 11, 10))
        assert all(m["band"] is None for m in body["measures"])
        assert body["weighings"] == 2  # il 10 novembre piu' l'8


class TestWriteDays:
    def test_one_file_per_day_with_every_weigh_in(self, data_dir):
        found = json.loads((data_dir / "health" / "body_composition" / "2026-11-08.json").read_text())
        assert [m["measured_at"] for m in found] == [at(1794145156), at(1794145334)]

    def test_a_second_run_does_not_lose_what_is_on_disk(self, data_dir):
        """Si fonde per id invece di sovrascrivere: il giorno in cui l'API
        rendesse una finestra piu' corta, una scrittura secca cancellerebbe
        dal disco delle pesate vere."""
        write_days([measurement(FULL)], data_dir)
        path = data_dir / "health" / "body_composition" / "2026-11-08.json"
        assert len(json.loads(path.read_text())) == 2
