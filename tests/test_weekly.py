"""La settimana: la finestra delle fasce di forma, e il patto fra il payload e
il modello."""

from datetime import date, timedelta

import pandas as pd
import pytest

from training.api.models import DailyData, WeeklyData
from training.interface import weekly_data as W


class TestFitnessBandWindow:
    """`_fitness_bands` campiona la domenica che **chiude** ognuna delle
    dodici settimane precedenti."""

    def test_the_first_sample_is_the_sunday_just_gone(self, monkeypatch):
        """Era il difetto: con `weeks=k, days=1` il primo campione cadeva una
        settimana troppo indietro, e la domenica appena passata non veniva
        guardata mai."""
        asked: list[date] = []
        monkeypatch.setattr(
            W, "_at_end_of", lambda health, column, day: asked.append(day) or None
        )
        monkeypatch.setattr(W, "FITNESS_SCORES", (("vo2max", 1),))
        monkeypatch.setattr(W, "FITNESS_KEYS", {"vo2max": "vo2max"})

        monday = date(2026, 10, 26)
        W._fitness_bands(pd.DataFrame(), monday)

        assert asked[0] == date(2026, 10, 25), "la domenica che chiude la settimana prima"
        assert asked[-1] == monday - timedelta(weeks=W.BAND_WEEKS) + timedelta(days=6)
        assert len(asked) == W.BAND_WEEKS

    def test_it_samples_the_same_sundays_as_the_load_band(self, monkeypatch):
        """I due fratelli nello stesso file devono guardare le stesse
        settimane: `_week_load` prende `start + 6 giorni`."""
        monday = date(2026, 10, 26)
        asked: list[date] = []
        monkeypatch.setattr(
            W, "_at_end_of", lambda health, column, day: asked.append(day) or None
        )
        monkeypatch.setattr(W, "FITNESS_SCORES", (("vo2max", 1),))
        monkeypatch.setattr(W, "FITNESS_KEYS", {"vo2max": "vo2max"})
        W._fitness_bands(pd.DataFrame(), monday)

        like_load = [
            monday - timedelta(weeks=k) + timedelta(days=6)
            for k in range(1, W.BAND_WEEKS + 1)
        ]
        assert asked == like_load


# I due test qui sotto hanno bisogno dell'archivio vero: il payload si
# costruisce dai dati, e su una cartella vuota si fermerebbe per un'altra
# ragione (vedi il rilievo aperto su `app.py:163`). Dove l'archivio non c'e'
# si salta, invece di fallire.
def _archive() -> bool:
    from training.garmin.config import DATA_DIR

    return (DATA_DIR / "db" / "activities.db").exists()


@pytest.mark.skipif(not _archive(), reason="serve l'archivio vero")
class TestPayloadMatchesModel:
    """`api/weekly.py` lo dichiara come il suo invariante: la pagina e gli
    agenti devono vedere le stesse cose. L'endpoint filtra il payload sui
    campi del modello, quindi un campo non dichiarato spariva in silenzio —
    cosi' sono andati persi `four_weeks`, `health_days` e `vo2max`, che sono
    i tre blocchi che gli agenti settimanali citano per nome nei loro
    prompt."""

    def test_the_weekly_payload_has_no_key_the_model_drops(self):
        from training.api.weekly import weekly_payload
        from training.garmin.config import DATA_DIR

        payload = weekly_payload(date(2026, 10, 19), DATA_DIR)
        assert set(payload) == set(WeeklyData.model_fields)

    def test_the_daily_payload_has_no_key_the_model_drops(self):
        from training.api.daily import daily_payload
        from training.garmin.config import DATA_DIR

        payload = daily_payload(date(2026, 11, 1), DATA_DIR)
        assert set(payload) == set(DailyData.model_fields)
