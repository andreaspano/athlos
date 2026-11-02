"""I battiti in salita contro quelli in piano.

`activity_numbers` calcolava la pendenza come rapporto fra due campioni
consecutivi: un metro di quota sbagliato su cinque di distanza fa un 20%, e
il barometro sbaglia piu' di un metro. I due secchi — sopra il 3% e fra -1 e
+1 — si riempivano col rumore, e il grafico della stessa pagina disegnava
un'altra pendenza.
"""

import numpy as np
import pandas as pd
import pytest

from training.interface.activity_report import activity_numbers
from training.interface.grade import slope_pct


def records(altitudes: list[float], heart_rates: list[int], step_m: float = 5.0) -> pd.DataFrame:
    """Una seduta: un campione al secondo, `step_m` metri l'uno."""
    n = len(altitudes)
    return pd.DataFrame(
        {
            "altitude_m": altitudes,
            "heart_rate": heart_rates,
            "distance_km": np.arange(n) * step_m / 1000,
            "speed_kmh": [step_m * 3.6] * n,
            "cadence": [80] * n,
            "equiv_speed_kmh": [None] * n,
        },
        index=pd.to_datetime(range(n), unit="s"),
    )


class TestTheSlopeIsSmoothed:
    def test_a_flat_stretch_with_a_noisy_altimeter_stays_flat(self):
        """Quota che oscilla di mezzo metro su un terreno piano: il rapporto
        fra due campioni la legge come il 10%, la pendenza vera come zero."""
        noise = [100.0 + (0.5 if index % 2 else 0.0) for index in range(200)]
        frame = records(noise, [130] * 200)

        raw = (frame["altitude_m"].diff() / (frame["distance_km"].diff() * 1000) * 100).clip(-30, 30)
        smoothed = slope_pct(frame)

        assert (raw.abs() > 3).sum() > 50, "il conto grezzo vede salite che non ci sono"
        assert (smoothed.abs() > 3).sum() == 0, "la pendenza lisciata no"

    def test_a_real_climb_is_still_a_climb(self):
        climb = [100.0 + index * 0.5 for index in range(200)]  # 10% su 5 m per campione
        assert (slope_pct(records(climb, [150] * 200)) > 3).sum() > 100


class TestTheTwoBuckets:
    def test_the_heart_rate_follows_the_ground(self):
        """Cento campioni in salita a 150 battiti e cento in piano a 120:
        i due secchi devono separarli."""
        climb = [100.0 + index * 0.5 for index in range(100)]
        flat = [climb[-1]] * 100
        frame = records(climb + flat, [150] * 100 + [120] * 100)

        out = activity_numbers(frame)

        assert out["uphill_hr"] == pytest.approx(150, abs=2)
        assert out["flat_hr"] == pytest.approx(120, abs=2)

    def test_noise_does_not_move_the_flat_heart_rate(self):
        """Il caso che il conto grezzo sbagliava: terreno piano con un
        altimetro rumoroso, e i battiti che salgono verso la fine."""
        noise = [100.0 + (0.5 if index % 2 else 0.0) for index in range(200)]
        frame = records(noise, [120] * 100 + [150] * 100)

        out = activity_numbers(frame)

        assert out["uphill_hr"] is None, "non c'e' nessuna salita"
        assert out["flat_hr"] == pytest.approx(135, abs=2), "tutti i campioni sono piani"

    def test_without_altitude_there_are_no_buckets(self):
        frame = records([None] * 100, [130] * 100)
        out = activity_numbers(frame)
        assert out["uphill_hr"] is None
        assert out["flat_hr"] is None
