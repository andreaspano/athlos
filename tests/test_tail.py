"""La coda del review: i rilievi che il limite dei quindici aveva tagliato."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from training.api import refresh as R
from training.api.sections import DAILY, WEEKLY


class TestFactsAreValidJson:
    """Il file dei fatti lo leggono gli agenti: `json.dumps` scrive i NaN
    nudi, che non sono JSON. Su quaranta giorni dell'archivio ce n'erano
    otto."""

    def test_nan_and_infinity_become_null(self):
        assert R._jsonable(float("nan")) is None
        assert R._jsonable(float("inf")) is None
        assert R._jsonable(float("-inf")) is None

    def test_it_walks_dicts_and_lists(self):
        value = {"a": [1.0, float("nan")], "b": {"c": float("inf")}, "d": "testo", "e": 3}
        assert R._jsonable(value) == {"a": [1.0, None], "b": {"c": None}, "d": "testo", "e": 3}

    def test_the_result_is_strict_json(self):
        import json

        text = json.dumps(R._jsonable({"x": float("nan")}))
        assert "NaN" not in text
        json.loads(text, parse_constant=lambda name: (_ for _ in ()).throw(ValueError(name)))


class TestWrittenKnowsOldNames:
    """Il backfill salta le sezioni che hanno gia' un testo. Senza i nomi
    vecchi rifaceva il Summary di 89 giorni e 13 settimane."""

    @pytest.mark.parametrize(
        "kind, legacy",
        [(DAILY, "summary_evening"), (DAILY, "summary_morning"), (WEEKLY, "summary_end")],
    )
    def test_a_legacy_fragment_counts_as_written(self, tmp_path, kind, legacy):
        (tmp_path / f"{legacy}.md").write_text("Il corpo ha tenuto.", encoding="utf-8")
        assert R._written(tmp_path, "summary", kind) is True

    def test_an_empty_legacy_fragment_does_not(self, tmp_path):
        (tmp_path / "summary_evening.md").touch()
        assert R._written(tmp_path, "summary", DAILY) is False

    def test_a_section_without_old_names_is_unaffected(self, tmp_path):
        (tmp_path / "health.md").write_text("testo", encoding="utf-8")
        assert R._written(tmp_path, "health", DAILY) is True
        assert R._written(tmp_path, "load", DAILY) is False


class TestRoutePoints:
    """Chiedendo 2000 punti su 2001 il passo arrotondato ne rendeva 1001."""

    @pytest.mark.parametrize("total, asked", [(2001, 2000), (5000, 2000), (3, 2), (2000, 2000)])
    def test_it_returns_what_it_was_asked(self, total, asked):
        points = np.arange(total)
        keep = np.unique(np.linspace(0, total - 1, asked).round().astype(int))
        assert len(keep) == min(asked, total)
        assert keep[0] == 0
        assert keep[-1] == total - 1


class TestZoneMinutes:
    """`_zone_totals` distingue da sempre i due casi: una settimana senza
    sedute e' uno zero vero, una settimana con sedute ma senza frequenza non
    ha misura. `measured_min` li confondeva, sommando niente e dicendo
    "misurati, e sono zero"."""

    def week(self, minutes):
        import pandas as pd

        return pd.DataFrame(
            {
                "start_time": pd.to_datetime(["2026-10-27 10:00", "2026-10-29 10:00"]),
                "sport": ["running", "running"],
                "min_low_aerobic": [minutes, minutes],
                "min_high_aerobic": [minutes, minutes],
                "min_anaerobic": [minutes, minutes],
            }
        )

    def test_sessions_without_heart_rate_have_no_measure(self):
        from training.interface import weekly_data as W

        zones = W._week_zones(self.week(None), date(2026, 10, 26))
        assert [zones[k]["minutes"] for k in ("low_aerobic", "high_aerobic", "anaerobic")] == [
            None, None, None
        ]
        assert zones["measured_min"] is None
        assert zones["sessions_without_hr"] == 2

    def test_a_week_with_no_sessions_is_a_real_zero(self):
        import pandas as pd

        from training.interface import weekly_data as W

        zones = W._week_zones(pd.DataFrame(), date(2026, 10, 26))
        assert zones["measured_min"] == 0, "il riposo e' un dato"

    def test_measured_minutes_are_summed_when_they_exist(self):
        from training.interface import weekly_data as W

        zones = W._week_zones(self.week(10.0), date(2026, 10, 26))
        assert zones["measured_min"] == 60


class TestBackfillFlags:
    def test_the_subject_flag_is_refused_with_a_range(self):
        """`--day 2026-10-01 --from 2026-09-01` faceva una cosa diversa da
        quella chiesta, in silenzio."""
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--day", type=date.fromisoformat)
        parser.add_argument("--section")
        parser.add_argument("--moment")
        args = parser.parse_args(["--day", "2026-10-01"])
        args.start, args.end = date(2026, 9, 1), None

        with pytest.raises(SystemExit):
            R._backfill_cli(DAILY, args, date(2026, 10, 31), parser)
