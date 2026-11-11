"""La forma del blocco: i chilometri e la velocita' di ogni settimana.

E' quello che la Training della Week disegna, in fondo alla vista, per il
blocco a cui quella settimana appartiene. Il metro di questi test e' che i
numeri dicano la verita' sulle tre cose che il grafico mostra: **la velocita'
si pesa sul tempo**, **la settimana in corso non e' una settimana finita** e
**il disegno e' il blocco com'era alla fine della settimana che si guarda**.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from training.interface.block_data import (
    SPEED_FLOOR_KMH,
    block_shape_payload,
    speed_samples,
    weighted_quantiles,
)

MONDAY = date(2026, 10, 26)

GOAL = """---
race: 2027-02-28
race_name: mezza maratona
target_time: "2:20:00"
distance_km: 21.0975
block_weeks: 18
current: true
---

# Half marathon in 2h20

Il testo del goal.
"""

WEEK = """---
week: {monday}
plan: half_marathon_2.20
block_week: {number}
block_weeks: 3
phase: {phase}
sessions:
  - {{date: {monday}, sport: rest}}
  - {{date: {tuesday}, sport: running, kind: easy, distance_km: 5}}
  - {{date: {sunday}, sport: running, kind: long, distance_km: 14}}
---

# Week {number}
"""


@pytest.fixture
def block(tmp_path):
    """Tre settimane scritte che dichiarano lo stesso goal."""
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / "half_marathon_2.20.md").write_text(GOAL)
    weeks = tmp_path / "summary" / "05.plan"
    weeks.mkdir(parents=True)
    for number in (1, 2, 3):
        monday = MONDAY + timedelta(weeks=number - 1)
        (weeks / f"{monday.isoformat()}.md").write_text(
            WEEK.format(
                monday=monday.isoformat(),
                tuesday=(monday + timedelta(days=1)).isoformat(),
                sunday=(monday + timedelta(days=6)).isoformat(),
                number=number,
                phase="base" if number < 3 else "build",
            )
        )
    return tmp_path / "summary", plan_dir


def runs(*days_and_km) -> pd.DataFrame:
    """Le attivita' come le vede `block_data`: una riga per corsa."""
    return pd.DataFrame(
        [
            {
                "activity_id": 100 + i,
                "sport": "running",
                "start_time": pd.Timestamp(day) + pd.Timedelta(hours=9),
                "total_distance_km": km,
            }
            for i, (day, km) in enumerate(days_and_km)
        ]
    )


def no_samples(_activity_id):
    return np.empty(0, dtype="float32"), np.empty(0, dtype="float32")


class TestWeightedQuantiles:
    def test_the_weights_decide_the_median(self):
        """Il mediano e' il punto in cui meta' del **tempo** sta sotto, non
        meta' dei campioni: e' tutta la ragione per cui i pesi viaggiano
        accanto ai valori."""
        values = np.array([6.0, 10.0], dtype="float32")
        lento = weighted_quantiles(values, np.array([9.0, 1.0], dtype="float32"), (0.5,))
        veloce = weighted_quantiles(values, np.array([1.0, 9.0], dtype="float32"), (0.5,))
        assert lento[0] < 7.0 < veloce[0]

    def test_nothing_to_summarise_is_none(self):
        """Una settimana senza campioni non ha un mediano, e `None` non e'
        zero: a zero il grafico disegnerebbe una scatola sul fondo."""
        assert weighted_quantiles(np.empty(0), np.empty(0)) is None


class TestSpeedSamples:
    def test_walking_pace_is_dropped(self):
        """Sotto i tre km/h c'e' il semaforo, non l'andatura: resta fuori,
        altrimenti tira giu' il mediano della settimana per una ragione che
        non e' come hai corso."""
        index = pd.date_range("2026-10-27 09:00", periods=60, freq="1s")
        records = pd.DataFrame(
            {"equiv_speed_kmh": [0.5] * 30 + [10.0] * 30}, index=index
        )
        speeds, seconds = speed_samples(records)
        assert speeds.size == seconds.size
        assert speeds.min() >= SPEED_FLOOR_KMH

    def test_no_column_no_samples(self):
        index = pd.date_range("2026-10-27 09:00", periods=3, freq="1s")
        speeds, _ = speed_samples(pd.DataFrame({"hr": [120, 121, 122]}, index=index))
        assert speeds.size == 0


class TestBlockShapePayload:
    def test_the_week_in_progress_is_partial(self, block):
        """La settimana in corso porta i chilometri di fin qui: sono marcati
        `partial`, e il grafico lascia fuori il loro punto invece di
        disegnare un crollo ogni volta che si apre la pagina."""
        summary_dir, plan_dir = block
        today = MONDAY + timedelta(weeks=2, days=2)  # mercoledi' della terza
        data = block_shape_payload(
            summary_dir,
            plan_dir,
            runs((MONDAY + timedelta(days=1), 10.0), (today, 6.0)),
            "half_marathon_2.20",
            no_samples,
            today=today,
        )
        prima, ultima = data["weeks"][0], data["weeks"][2]
        assert data["block_week"] == 3
        assert prima["partial"] is False and prima["done_km"] == 10.0
        assert ultima["partial"] is True and ultima["done_km"] == 6.0

    def test_a_week_not_begun_has_no_kilometres(self, block):
        """Una settimana che non e' cominciata non vale zero: non esiste
        ancora, e una barra assente non e' una barra a zero."""
        summary_dir, plan_dir = block
        data = block_shape_payload(
            summary_dir, plan_dir, runs(), "half_marathon_2.20", no_samples, today=MONDAY
        )
        assert data["weeks"][0]["plan_km"] == 19.0  # 5 + 14, il riposo non conta
        assert [w["done_km"] for w in data["weeks"][1:]] == [None, None]

    def test_the_block_is_what_the_weeks_declare(self, block):
        """Le tre settimane dicono `block_weeks: 3`, il goal ne promette 18:
        vince il registro dei file, che e' quello che era previsto allora
        (todo 86)."""
        summary_dir, plan_dir = block
        data = block_shape_payload(
            summary_dir, plan_dir, runs(), "half_marathon_2.20", no_samples, today=MONDAY
        )
        assert data["block_weeks"] == 3 and len(data["weeks"]) == 3

    def test_a_goal_without_weeks_is_none(self, block):
        """Nessuna settimana lo dichiara: non e' un errore, e' un goal che non
        si sta seguendo. La card lo dice in una riga."""
        summary_dir, plan_dir = block
        (plan_dir / "half_marathon_2.30.md").write_text(GOAL)
        assert (
            block_shape_payload(
                summary_dir, plan_dir, runs(), "half_marathon_2.30", no_samples, today=MONDAY
            )
            is None
        )

    def test_a_past_week_is_the_block_as_it_was_then(self, block):
        """Guardando una settimana passata il grafico e' il blocco **com'era
        alla fine di quella settimana**: i chilometri delle settimane dopo
        non ci sono, anche se sono stati corsi. E' il taglio che fa battere il
        disegno una volta a settimana, come il report."""
        summary_dir, plan_dir = block
        data = block_shape_payload(
            summary_dir,
            plan_dir,
            runs(
                (MONDAY + timedelta(days=1), 10.0),
                (MONDAY + timedelta(weeks=1, days=1), 12.0),
            ),
            "half_marathon_2.20",
            no_samples,
            until=MONDAY,
            today=MONDAY + timedelta(weeks=2, days=2),
        )
        assert [w["done_km"] for w in data["weeks"]] == [10.0, None, None]
        # Nessuna settimana e' incompleta: quella in corso sta oltre il
        # confine, quindi non ha chilometri da marcare `partial`.
        assert [w["partial"] for w in data["weeks"]] == [False, False, False]
        # Il piano resta tutto: le settimane che vengono tengono la loro barra
        # del previsto, che e' il resto del blocco.
        assert [w["plan_km"] for w in data["weeks"]] == [19.0, 19.0, 19.0]

    def test_a_week_ahead_does_not_measure_the_future(self, block):
        """Un lunedi' oltre oggi non allarga la misura: `until` puo' solo
        tirare il confine indietro. Guardando una settimana prevista si vede
        il blocco di adesso, e quella in corso resta `partial`."""
        summary_dir, plan_dir = block
        today = MONDAY + timedelta(weeks=2, days=2)  # mercoledi' della terza
        data = block_shape_payload(
            summary_dir,
            plan_dir,
            runs((MONDAY + timedelta(days=1), 10.0), (today, 6.0)),
            "half_marathon_2.20",
            no_samples,
            until=MONDAY + timedelta(weeks=9),
            today=today,
        )
        assert [w["done_km"] for w in data["weeks"]] == [10.0, None, 6.0]
        assert data["weeks"][2]["partial"] is True

    def test_the_speed_of_a_week_stacks_its_runs(self, block):
        """I campioni delle corse si impilano e **poi** si riassumono: una
        corsa lenta e una veloce nella stessa settimana danno un mediano in
        mezzo, non la media di due mediani."""
        summary_dir, plan_dir = block
        samples = {
            100: (np.full(600, 7.0, dtype="float32"), np.ones(600, dtype="float32")),
            101: (np.full(200, 11.0, dtype="float32"), np.ones(200, dtype="float32")),
        }
        data = block_shape_payload(
            summary_dir,
            plan_dir,
            runs((MONDAY + timedelta(days=1), 8.0), (MONDAY + timedelta(days=6), 4.0)),
            "half_marathon_2.20",
            lambda activity_id: samples[activity_id],
            today=MONDAY + timedelta(days=6),
        )
        week = data["weeks"][0]
        assert week["median"] == 7.0  # i tre quarti del tempo sono a 7
        assert week["p95"] == pytest.approx(11.0)
        assert week["minutes"] == pytest.approx(800 / 60, abs=0.1)
