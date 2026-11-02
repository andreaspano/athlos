"""La fascia dei minuti per zona, e i due conti delle sedute fuori.

Le dodici settimane prima entrano cosi': una senza sedute vale zero, perche'
il riposo e' un dato della stagione; una con sedute ma senza soglia non vale
niente. Dove nessuna era misurabile restavano solo gli zeri dei riposi e la
fascia veniva 0-0, cioe' diceva che qualunque minuto di allenamento e' un
fuori scala.
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from training.interface.weekly_data import MIN_BAND_WEEKS, _week_zones

MONDAY = date(2026, 10, 26)


def sessions(weeks: dict[int, tuple[int, bool]]) -> pd.DataFrame:
    """Una attivita' per settimana indietro: `{k: (minuti, misurata)}`.

    `misurata` falsa vuol dire seduta senza soglia, cioe' minuti per zona a
    `None` — la frequenza c'e' comunque.
    """
    rows = []
    for back, (minutes, measured) in weeks.items():
        day = MONDAY - timedelta(weeks=back) + timedelta(days=2)
        rows.append(
            {
                "start_time": pd.Timestamp(f"{day} 10:00"),
                "sport": "running",
                "avg_heart_rate": 140,
                "min_low_aerobic": float(minutes) if measured else None,
                "min_high_aerobic": 0.0 if measured else None,
                "min_anaerobic": 0.0 if measured else None,
            }
        )
    return pd.DataFrame(rows)


class TestTheBandNeedsSomethingMeasured:
    def test_rest_weeks_alone_give_no_band(self):
        """Il caso del 3 agosto: quattro settimane con sedute mai misurate e
        otto di riposo. Gli otto zeri passavano il minimo e la fascia usciva
        0-0."""
        weeks = {k: (0, False) for k in (1, 4, 7, 10)}  # con sedute, non misurate
        zones = _week_zones(sessions(weeks), MONDAY)

        assert zones["low_aerobic"]["band"] is None
        assert zones["low_aerobic"]["weeks"] == 8, "le otto di riposo restano contate"

    def test_one_measured_week_is_enough_to_compare(self):
        weeks = {k: (0, False) for k in (1, 4, 7)}
        weeks[2] = (300, True)
        zones = _week_zones(sessions(weeks), MONDAY)

        assert zones["low_aerobic"]["band"] is not None

    def test_a_full_season_has_its_band(self):
        weeks = {k: (300 + k, True) for k in range(1, 13)}
        band = _week_zones(sessions(weeks), MONDAY)["low_aerobic"]["band"]

        assert band is not None
        assert band["low"] < band["high"]

    def test_too_few_values_still_give_no_band(self):
        """Il minimo di `_band` resta, e vale insieme alla regola nuova: una
        settimana misurata c'e', ma i valori sono quattro — le altre otto
        avevano sedute senza soglia, e quelle non contano."""
        weeks = {k: (0, False) for k in range(1, 9)}
        weeks[9] = (300, True)
        zones = _week_zones(sessions(weeks), MONDAY)

        assert zones["low_aerobic"]["weeks"] == 4, "una misurata piu' tre di riposo"
        assert zones["low_aerobic"]["band"] is None

    def test_the_band_floor_stays_at_zero(self):
        weeks = {1: (600, True), 2: (10, True)}
        weeks.update({k: (300, True) for k in range(3, 13)})
        band = _week_zones(sessions(weeks), MONDAY)["low_aerobic"]["band"]
        assert band["low"] >= 0 and band["outer_low"] >= 0


class TestTheTwoCounts:
    def test_a_session_with_a_heart_rate_but_no_threshold(self):
        """Contava queste e le chiamava "senza frequenza": per ogni settimana
        prima di agosto 2026 diceva agli agenti che l'intera settimana era
        stata registrata senza frequenza."""
        week = sessions({0: (0, False)})
        zones = _week_zones(week, MONDAY)

        assert zones["sessions_without_hr"] == 0, "la frequenza c'era"
        assert zones["sessions_without_zones"] == 1, "i minuti per zona no"

    def test_a_session_without_a_heart_rate(self):
        week = sessions({0: (0, False)})
        week.loc[0, "avg_heart_rate"] = None
        zones = _week_zones(week, MONDAY)

        assert zones["sessions_without_hr"] == 1
        assert zones["sessions_without_zones"] == 1

    def test_a_measured_session_is_in_neither(self):
        zones = _week_zones(sessions({0: (120, True)}), MONDAY)
        assert zones["sessions_without_hr"] == 0
        assert zones["sessions_without_zones"] == 0

    def test_an_empty_week(self):
        zones = _week_zones(pd.DataFrame(), MONDAY)
        assert zones["sessions_without_hr"] == 0
        assert zones["sessions_without_zones"] == 0
