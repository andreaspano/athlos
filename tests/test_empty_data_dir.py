"""Una cartella dati vuota: il primo avvio di una installazione nuova, o
quello prima del primo `make update_activity`.

Deve rispondere "niente", non "guasto": e' l'unico momento in cui chi arriva
non ha modo di distinguere un'installazione rotta da una vuota."""

from datetime import date

import pytest

from training.interface.db import list_activities


@pytest.fixture
def empty(tmp_path):
    (tmp_path / "db").mkdir()
    (tmp_path / "fit").mkdir()
    (tmp_path / "health").mkdir()
    return tmp_path


def test_the_activity_frame_has_its_types_at_zero_rows(empty):
    """Era la radice: a zero righe `start_time` restava di tipo `object`, e i
    dodici posti che fanno `start_time.dt.date` alzavano `AttributeError`."""
    activities = list_activities(empty)

    assert activities.empty
    assert str(activities["start_time"].dtype).startswith("datetime64")
    assert list(activities["start_time"].dt.date) == []


def test_the_daily_payload_does_not_raise(empty):
    from training.api.daily import daily_payload

    payload = daily_payload(date(2026, 10, 30), empty)
    assert str(payload["day"]) == "2026-10-30"
    assert payload["sessions"]["today"] == []
    assert payload["health_data_up_to"] is None


def test_the_weekly_payload_does_not_raise(empty):
    from training.api.weekly import weekly_payload

    payload = weekly_payload(date(2026, 10, 26), empty)
    assert payload["activities"] == []


def test_nothing_is_read_from_the_real_data_root(empty):
    """`fitness_on` leggeva gli acclimatamenti dal data root globale
    qualunque cartella si fosse chiesta: su una cartella vuota tornavano
    popolati, il che e' il modo in cui il difetto si vede."""
    from training.api.daily import daily_payload

    payload = daily_payload(date(2026, 10, 30), empty)
    fitness = payload["fitness"]
    assert fitness["altitude_acclimation"] is None
    assert fitness["heat_acclimation"] is None
    assert payload["morning"]["hrv_baseline"] is None
