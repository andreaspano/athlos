"""I minuti per zona: **una regola sola**.

Il database li scrive (`db._zone_minutes`) e il grafico li ricalcola
(`run_chart.effects`); avevano due conti diversi — un tetto di 30 secondi per
buco contro la regola delle pause — e su 8 delle 12 sedute recenti non
andavano d'accordo, con la Day che leggeva uno e la Week l'altro.
"""

import json

import pandas as pd
import pytest

from training.interface.grade import sample_seconds
from training.interface.run_chart import EFFECTS, durations_s, effects

BOUNDS = [110, 130, 150, 165, 180]
THRESHOLD = 160


def index_of(*seconds: int) -> pd.DatetimeIndex:
    return pd.to_datetime(list(seconds), unit="s")


class TestSampleSeconds:
    def test_one_second_per_sample_when_the_watch_records_every_second(self):
        assert list(sample_seconds(index_of(0, 1, 2, 3))) == [1, 1, 1, 1]

    def test_a_sparse_file_charges_the_gap(self):
        """I file vecchi hanno un record ogni cinque secondi."""
        assert list(sample_seconds(index_of(0, 5, 10))) == [5, 5, 1]

    def test_a_pause_costs_one_second(self):
        """Il tempo in cui l'orologio era fermo non e' tempo allenato: il
        semaforo non si conta."""
        assert list(sample_seconds(index_of(0, 1, 2, 300, 301))) == [1, 1, 1, 1, 1]

    def test_the_last_sample_is_worth_one(self):
        assert sample_seconds(index_of(0, 1))[-1] == 1

    def test_an_empty_index(self):
        assert len(sample_seconds(pd.to_datetime([], unit="s"))) == 0

    def test_durations_s_is_the_same_rule(self):
        frame = pd.DataFrame({"heart_rate": [100, 100, 100]}, index=index_of(0, 1, 240))
        assert list(durations_s(frame)) == list(sample_seconds(frame.index))


class TestTheDatabaseAgreesWithTheChart:
    def build(self, tmp_path, samples: list[tuple[int, int]]):
        """Una seduta finta: la riga dell'attivita' e i suoi campioni."""
        from training.interface.db import _connect

        (tmp_path / "db").mkdir(exist_ok=True)
        conn = _connect(tmp_path)
        conn.execute(
            "INSERT INTO activities (activity_id, path, sport, start_time, hr_zone_bounds, "
            "threshold_hr, parsed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                "x.fit",
                "running",
                "2026-10-20 10:00:00",
                json.dumps(BOUNDS),
                THRESHOLD,
                "2026-10-20 11:00:00",
            ),
        )
        conn.executemany(
            "INSERT INTO records (activity_id, ts_epoch, heart_rate) VALUES (1, ?, ?)", samples
        )
        conn.commit()
        return conn

    def frame(self, samples: list[tuple[int, int]]) -> pd.DataFrame:
        return pd.DataFrame(
            {"heart_rate": [hr for _, hr in samples]},
            index=pd.to_datetime([ts for ts, _ in samples], unit="s"),
        )

    @pytest.mark.parametrize(
        "samples, why",
        [
            ([(t, 120) for t in range(0, 600)], "dieci minuti in basso aerobico"),
            ([(t, 155) for t in range(0, 300)], "cinque minuti in alto aerobico"),
            ([(t, 170) for t in range(0, 120)], "due minuti in anaerobico"),
            (
                [(t, 120) for t in range(0, 300)] + [(t, 155) for t in range(300, 600)],
                "due fasce di fila",
            ),
            (
                [(t, 120) for t in range(0, 300)] + [(t, 120) for t in range(900, 1200)],
                "con una pausa di dieci minuti in mezzo",
            ),
            ([(t * 5, 140) for t in range(0, 60)], "un file rado, un record ogni 5 s"),
        ],
    )
    def test_the_two_give_the_same_minutes(self, tmp_path, samples, why):
        from training.interface.db import _zone_minutes

        conn = self.build(tmp_path, samples)
        try:
            stored = _zone_minutes(conn, 1)
        finally:
            conn.close()

        computed = effects(self.frame(samples), BOUNDS, THRESHOLD)
        expected = tuple(round(computed[key] / 60, 1) for key in EFFECTS)

        assert stored == pytest.approx(expected, abs=0.1), why

    def test_the_pause_is_not_counted_as_training(self, tmp_path):
        """Il caso che i due conti vedevano diverso: con un tetto di 30 s per
        buco, dieci minuti di sosta ne regalavano mezzo alla fascia."""
        from training.interface.db import _zone_minutes

        samples = [(t, 120) for t in range(0, 300)] + [(t, 120) for t in range(900, 1200)]
        conn = self.build(tmp_path, samples)
        try:
            low, _, _ = _zone_minutes(conn, 1)
        finally:
            conn.close()

        assert low == pytest.approx(10.0, abs=0.1), "600 campioni, un secondo l'uno"

    def test_no_heart_rate_is_none(self, tmp_path):
        from training.interface.db import _zone_minutes

        conn = self.build(tmp_path, [(t, None) for t in range(0, 100)])
        try:
            assert _zone_minutes(conn, 1) is None
        finally:
            conn.close()
