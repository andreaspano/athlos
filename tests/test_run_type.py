"""Il tipo delle corse: ripetute, lunga, tempo, facile.

Due regole erano scritte male, e insieme spiegano due delle sette correzioni
a mano in `activity_run_type.json`: la lunga non poteva essere lunga se
l'orologio aveva fatto girare un allenamento, e le ripetute scritte come
blocco `repeat` contavano come una.
"""

import pytest

from training.interface.run_type import LONG_MIN, TEMPO_STEP_MIN_S, guess_run_type


def guess(minutes=None, name=None, steps=None, longest=None, sport="running"):
    return guess_run_type(sport, minutes, name, steps, longest)


class TestLong:
    def test_a_long_run_with_a_workout_is_long(self):
        """Il caso vero del 31 ottobre: `w01_long`, 115 minuti, un passo
        attivo. La regola della lunga stava su un `elif` del ramo
        dell'allenamento, quindi non la raggiungeva mai."""
        assert guess(minutes=115, name="w01_long", steps=1) == "long"

    def test_a_long_run_without_a_workout_is_long(self):
        assert guess(minutes=115) == "long"

    def test_just_under_the_threshold_is_easy(self):
        assert guess(minutes=LONG_MIN - 1) == "easy"

    def test_exactly_the_threshold_is_long(self):
        assert guess(minutes=LONG_MIN) == "long"

    def test_intervals_win_over_long(self):
        """Una seduta a ripetute di due ore e' una seduta a ripetute."""
        assert guess(minutes=130, name="Rip_4x5", steps=5, longest=240) == "intervals"

    def test_tempo_wins_over_long(self):
        assert guess(minutes=130, name="x", steps=1, longest=TEMPO_STEP_MIN_S) == "tempo"


class TestIntervals:
    def test_two_active_steps_are_intervals(self):
        assert guess(minutes=50, name="Rip_4x5", steps=5, longest=240) == "intervals"

    def test_one_long_active_step_is_tempo(self):
        assert guess(minutes=50, name="x", steps=1, longest=TEMPO_STEP_MIN_S) == "tempo"

    def test_one_short_active_step_is_easy(self):
        """Sotto i dieci minuti e' un allungo, non un tempo."""
        assert guess(minutes=50, name="x", steps=1, longest=120) == "easy"


class TestNotRunning:
    @pytest.mark.parametrize("sport", ["cycling", "hiking", "treadmill", None])
    def test_only_runs_have_a_type(self, sport):
        assert guess(minutes=115, sport=sport) is None


class TestTheWorkoutStepsAreCounted:
    """`fit._workout` espande i blocchi `repeat`: un passo attivo dentro un
    giro da quattro sono quattro passi."""

    def steps(self, messages: list[dict]) -> dict:
        from training.interface.fit import _workout

        class FakeMessage:
            def __init__(self, values):
                self._values = values

            def get_values(self):
                return self._values

            def get_value(self, key):
                return self._values.get(key)

        class FakeFit:
            def get_messages(self, kind):
                if kind == "workout":
                    return iter([FakeMessage({"wkt_name": "prova"})])
                return iter(FakeMessage(m) for m in messages)

        return _workout(FakeFit())

    def test_distinct_steps_are_counted_one_each(self):
        out = self.steps(
            [
                {"intensity": "warmup", "duration_type": "distance"},
                {"intensity": "active", "duration_type": "time", "duration_time": 300.0},
                {"intensity": "rest", "duration_type": "time", "duration_time": 120.0},
                {"intensity": "active", "duration_type": "time", "duration_time": 300.0},
                {"intensity": "cooldown", "duration_type": "distance"},
            ]
        )
        assert out["workout_active_steps"] == 2
        assert out["workout_active_max_s"] == 300.0

    def test_a_repeat_block_counts_its_repetitions(self):
        """Il caso vero di `Rip_5min4T`: un passo attivo, un recupero, e un
        passo di ripetizione che dice di tornare al passo 1 quattro volte."""
        out = self.steps(
            [
                {"intensity": "warmup", "duration_type": "distance"},
                {"intensity": "active", "duration_type": "time", "duration_time": 300.0},
                {"intensity": 4, "duration_type": "time", "duration_time": 120.0},
                {
                    "intensity": None,
                    "duration_type": "repeat_until_steps_cmplt",
                    "duration_step": 1,
                    "repeat_steps": 4,
                },
                {"intensity": "cooldown", "duration_type": "distance"},
            ]
        )
        assert out["workout_active_steps"] == 4
        assert out["workout_active_max_s"] == 300.0, "il piu' lungo resta quello di un giro"

    def test_a_block_inside_a_block(self):
        """Due `repeat` annidati si moltiplicano: 2 x 3 giri su un passo
        attivo sono sei."""
        out = self.steps(
            [
                {"intensity": "active", "duration_type": "time", "duration_time": 60.0},
                {
                    "intensity": None,
                    "duration_type": "repeat_until_steps_cmplt",
                    "duration_step": 0,
                    "repeat_steps": 3,
                },
                {
                    "intensity": None,
                    "duration_type": "repeat_until_steps_cmplt",
                    "duration_step": 0,
                    "repeat_steps": 2,
                },
            ]
        )
        assert out["workout_active_steps"] == 6

    def test_a_repeat_of_one_changes_nothing(self):
        out = self.steps(
            [
                {"intensity": "active", "duration_type": "time", "duration_time": 60.0},
                {
                    "intensity": None,
                    "duration_type": "repeat_until_steps_cmplt",
                    "duration_step": 0,
                    "repeat_steps": 1,
                },
            ]
        )
        assert out["workout_active_steps"] == 1

    def test_without_a_workout_message_everything_is_none(self):
        from training.interface.fit import _workout

        class Empty:
            def get_messages(self, kind):
                return iter([])

        assert _workout(Empty()) == {
            "workout_name": None,
            "workout_active_steps": None,
            "workout_active_max_s": None,
        }
