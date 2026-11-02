"""Quando una seduta e' fatta di pezzi da leggere riga per riga.

`is_structured` guardava i passi distinti su **tutti** i giri: un
allenamento con riscaldamento e defaticamento ne ha tre anche con un solo
pezzo di lavoro, e il lungo di 115 minuti del 31 ottobre veniva presentato
come quattordici ripetute — i suoi auto-lap al chilometro.
"""

import pandas as pd
import pytest

from training.interface.laps import is_structured, session_laps


def laps(rows: list[tuple]) -> pd.DataFrame:
    """Giri come li tiene il database: passo, intensita', trigger."""
    return pd.DataFrame(
        [
            {
                "lap_index": index,
                "workout_step": step,
                "intensity": intensity,
                "trigger": trigger,
                "time_s": time_s,
                "distance_m": 1000.0,
                "speed_kmh": 10.0,
                "avg_hr": 140,
                "max_hr": 150,
                "cadence": 80,
                "ascent_m": 0,
            }
            for index, (step, intensity, trigger, time_s) in enumerate(rows)
        ]
    )


LONG_RUN = laps(
    # Il lungo: riscaldamento, quattordici chilometri dentro un passo solo,
    # defaticamento. I chilometri li chiude l'auto-lap.
    [(0.0, "warmup", "distance", 449.0)]
    + [(1.0, "active", "distance", 440.0)] * 14
    + [(2.0, "cooldown", "manual", 9.0)]
)
REPEAT_BLOCK = laps(
    # Rip_5min4T: le quattro ripetute sono un passo dentro un `repeat`, e le
    # chiude la durata del passo.
    [(0.0, "warmup", "distance", 600.0)]
    + [(1.0, "active", "time", 300.0), (2.0, "rest", "time", 120.0)] * 4
)
DISTINCT_STEPS = laps(
    # Rip_4x5: ogni ripetuta e' un passo suo.
    [(0.0, "warmup", "distance", 600.0)]
    + [(1.0, "active", "time", 300.0), (2.0, "rest", "time", 120.0)]
    + [(3.0, "active", "time", 300.0), (4.0, "rest", "time", 120.0)]
)
FREE_RUN = laps([(0.0, "active", "distance", 440.0)] * 8)


class TestIsStructured:
    def test_a_continuous_long_run_is_not(self):
        assert is_structured(LONG_RUN) is False

    def test_reps_written_as_a_repeat_block_are(self):
        """Un passo di lavoro solo, ma chiuso a tempo: sono ripetute."""
        assert is_structured(REPEAT_BLOCK) is True

    def test_reps_written_as_distinct_steps_are(self):
        assert is_structured(DISTINCT_STEPS) is True

    def test_a_free_run_is_not(self):
        """`workout_step` a zero su giri che sono l'auto-lap: lo scrivono
        anche certe corse libere."""
        assert is_structured(FREE_RUN) is False

    def test_without_work_laps_it_is_not(self):
        only_warmup = laps([(0.0, "warmup", "distance", 400.0), (1.0, "cooldown", "manual", 60.0)])
        assert is_structured(only_warmup) is False

    @pytest.mark.parametrize(
        "frame", [pd.DataFrame(), pd.DataFrame({"intensity": ["active"]})]
    )
    def test_nothing_to_read_is_not(self, frame):
        assert is_structured(frame) is False


class TestWhatTheCardShows:
    def test_the_long_run_has_no_table(self):
        payload = session_laps(LONG_RUN, "running")
        assert payload["structured"] is False
        assert payload["laps"] == [], "nessuna riga: la tabella sarebbe quattordici finte ripetute"

    def test_the_reps_are_numbered(self):
        payload = session_laps(REPEAT_BLOCK, "running")
        labels = [lap["label"] for lap in payload["laps"]]
        assert payload["structured"] is True
        assert labels.count("Rep 1") == 1
        assert "Rep 4" in labels
        assert labels.count("Recovery") >= 3
