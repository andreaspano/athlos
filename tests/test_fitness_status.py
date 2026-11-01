"""Lo snapshot non deve morire per un file di salute rovinato: a quel punto ha
già speso tutte le chiamate, e morirebbe di nuovo a ogni tentativo."""

from datetime import date

from training.garmin import fitness_status as F
from training.garmin.files import write_json

DAY = date(2026, 10, 20)


def test_a_truncated_day_is_skipped_not_fatal(tmp_path, capsys):
    for name in ("stats", "sleep"):
        (tmp_path / "health" / name).mkdir(parents=True)
    write_json(tmp_path / "health" / "stats" / f"{DAY}.json", {"passi": 1000})
    (tmp_path / "health" / "sleep" / f"{DAY}.json").write_text('{"a":', encoding="utf-8")

    out = F._load_cached_health(tmp_path, DAY, DAY)

    assert out["stats"][str(DAY)] == {"passi": 1000}
    assert out["sleep"] == {}
    assert "non si legge" in capsys.readouterr().out
