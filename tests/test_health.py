"""Un file di salute si salta solo se e' completo, e completo vuol dire
"salvato dopo la fine del suo giorno **e** leggibile", nel fuso dell'account."""

import os
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from garminconnect import GarminConnectConnectionError

from training.garmin import health as H
from training.garmin.config import LOCAL_TZ
from training.garmin.files import write_json

DAY = date(2026, 10, 20)
ROME = ZoneInfo("Europe/Rome")


def touch(path, moment: datetime):
    stamp = moment.timestamp()
    os.utime(path, (stamp, stamp))


def test_saved_after_the_day_ended_is_complete(tmp_path):
    path = tmp_path / "x.json"
    write_json(path, {"ok": 1})
    touch(path, datetime(2026, 10, 21, 0, 30, tzinfo=ROME))
    assert H._is_complete(path, DAY) is True


def test_saved_during_the_day_is_not(tmp_path):
    """E' la fotografia a meta' del todo 39: alle 13:20 manca la corsa delle
    19:50, e con lei il VO2max e il carico che Garmin ne ricava."""
    path = tmp_path / "x.json"
    write_json(path, {"ok": 1})
    touch(path, datetime(2026, 10, 20, 13, 20, tzinfo=ROME))
    assert H._is_complete(path, DAY) is False


@pytest.mark.parametrize("content", ['{"x": 1', "", "non json"])
def test_an_unreadable_file_is_never_complete(tmp_path, content):
    """Anche un file troncato ha un mtime dopo la fine del giorno: senza la
    lettura di controllo restava "completo" per sempre."""
    path = tmp_path / "x.json"
    path.write_text(content, encoding="utf-8")
    touch(path, datetime(2026, 10, 21, 0, 30, tzinfo=ROME))
    assert H._is_complete(path, DAY) is False


def test_a_missing_file_is_not_complete(tmp_path):
    assert H._is_complete(tmp_path / "nope.json", DAY) is False


def test_the_verdict_does_not_depend_on_the_machine_clock(tmp_path, monkeypatch):
    """Su un portatile in viaggio, alle 23 di Roma l'orologio di sistema puo'
    dire che e' già l'una del giorno dopo: il file non deve per questo
    diventare completo."""
    path = tmp_path / "x.json"
    write_json(path, {"ok": 1})
    touch(path, datetime(2026, 10, 20, 23, 0, tzinfo=ROME))
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    time.tzset()
    try:
        assert H._is_complete(path, DAY) is False
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()


def test_today_local_follows_the_account_timezone():
    assert H.today_local() == datetime.now(LOCAL_TZ).date()


def test_a_broken_metric_is_counted_and_raised_at_the_end(tmp_path, monkeypatch):
    """Un anno di storico non si butta per una chiamata, ma la mancata non
    passa in silenzio: prima `make update_activity` usciva 0 e la pagina
    scriveva "scaricamento ok"."""
    def good(api, day):
        return {"giorno": day}

    def broken(api, day):
        raise GarminConnectConnectionError("500 su questo endpoint")

    monkeypatch.setattr(H, "DAILY_ENDPOINTS", {"buono": good, "rotto": broken})
    monkeypatch.setattr(H, "REQUEST_DELAY", 0)
    monkeypatch.setattr(H, "safe_call", lambda func, *a, **k: func(*a, **k))
    day = H.today_local() - timedelta(days=3)

    with pytest.raises(RuntimeError, match="non scaricate"):
        H.export_daily_health(object(), tmp_path, day, day)

    written = tmp_path / "health" / "buono" / f"{day}.json"
    assert written.exists(), "le metriche buone si scrivono comunque"
