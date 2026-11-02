"""Le due passate sole di `build_weekly_data`.

Le misure e le zone si leggono su tredici settimane — le dodici della fascia
piu' quella corrente — e prima ognuna rifiltrava o reindicizzava il frame
intero: 104 reindex per le misure, 13 filtri per le zone.
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from training.interface import weekly_data as W

MONDAY = date(2026, 10, 26)


def health_frame(values: dict[date, float]) -> pd.DataFrame:
    days = pd.date_range(MONDAY - timedelta(weeks=13), MONDAY + timedelta(days=6), freq="D")
    frame = pd.DataFrame(index=days, columns=["resting_hr"], dtype="float64")
    for day, value in values.items():
        frame.loc[pd.Timestamp(day), "resting_hr"] = value
    return frame


def naive_mean(health: pd.DataFrame, column: str, monday: date) -> float | None:
    """Come si faceva prima: una settimana alla volta."""
    week = health.reindex(pd.date_range(monday, periods=7, freq="D"))[column].dropna()
    return float(week.mean()) if len(week) else None


class TestWeekMeans:
    def test_it_agrees_with_one_week_at_a_time(self):
        values = {MONDAY - timedelta(days=n): 50 + (n % 7) for n in range(0, 60, 3)}
        health = health_frame(values)

        means = W._week_means(health, ["resting_hr"], MONDAY - timedelta(weeks=12), 13)

        for k in range(13):
            monday = MONDAY - timedelta(weeks=12 - k)
            got = means["resting_hr"].iloc[k]
            expected = naive_mean(health, "resting_hr", monday)
            if expected is None:
                assert pd.isna(got), monday
            else:
                assert got == pytest.approx(expected), monday

    def test_a_week_without_values_stays_a_hole(self):
        health = health_frame({MONDAY: 48.0})
        means = W._week_means(health, ["resting_hr"], MONDAY - timedelta(weeks=12), 13)

        assert means["resting_hr"].iloc[-1] == 48.0
        assert means["resting_hr"].iloc[:-1].isna().all(), "le dodici prima sono vuote"
        assert len(means) == 13, "le settimane vuote restano nella serie"


class TestWeeksByMonday:
    def frame(self, days: list[date]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "start_time": pd.to_datetime([f"{d} 10:00" for d in days]),
                "sport": ["running"] * len(days),
                "min_low_aerobic": [30.0] * len(days),
                "min_high_aerobic": [5.0] * len(days),
                "min_anaerobic": [1.0] * len(days),
            }
        )

    def test_an_activity_lands_in_the_week_of_its_start_day(self):
        acts = self.frame([MONDAY, MONDAY + timedelta(days=6), MONDAY - timedelta(days=1)])
        weeks = W._weeks_by_monday(acts, MONDAY - timedelta(weeks=1), 2)

        assert len(weeks[MONDAY]) == 2, "il lunedi e la domenica della stessa settimana"
        assert len(weeks[MONDAY - timedelta(weeks=1)]) == 1

    def test_weeks_without_sessions_are_empty_frames(self):
        weeks = W._weeks_by_monday(self.frame([MONDAY]), MONDAY - timedelta(weeks=12), 13)

        assert len(weeks) == 13
        assert len(weeks[MONDAY]) == 1
        assert all(weeks[MONDAY - timedelta(weeks=k)].empty for k in range(1, 13))

    def test_activities_outside_the_span_are_left_out(self):
        acts = self.frame([MONDAY, MONDAY - timedelta(weeks=20)])
        weeks = W._weeks_by_monday(acts, MONDAY - timedelta(weeks=2), 3)

        assert sum(len(f) for f in weeks.values()) == 1

    def test_no_activities_at_all(self):
        weeks = W._weeks_by_monday(pd.DataFrame(), MONDAY - timedelta(weeks=2), 3)
        assert len(weeks) == 3
        assert all(f.empty for f in weeks.values())

    def test_the_totals_agree_with_the_one_week_version(self):
        acts = self.frame([MONDAY, MONDAY + timedelta(days=2)])
        weeks = W._weeks_by_monday(acts, MONDAY, 1)

        assert W._zone_totals_of(weeks[MONDAY]) == W._zone_totals(acts, MONDAY)
