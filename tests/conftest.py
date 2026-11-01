"""Attrezzi comuni ai test del pacchetto `garmin`.

Nessun test parla con Garmin ne' tocca il data root vero: le chiamate passano
tutte da `safe_call`, che qui viene sostituito, e i file stanno in `tmp_path`.
"""

import io
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from training.garmin import activities as A


def zip_bytes(name: str = "123_ACTIVITY.fit", body: bytes = b"fit-bytes") -> bytes:
    """Uno zip in memoria, come quelli che Garmin manda."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, body)
    return buf.getvalue()


def activity(activity_id: int, days_ago: int = 0, name: str = "corsa") -> dict:
    """Una riga dell'elenco attivita', con la data di inizio che serve alla
    finestra di scansione."""
    stamp = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "activityId": activity_id,
        "startTimeLocal": stamp,
        "activityName": name,
        "activityType": {"typeKey": "running"},
    }


class FakeApi:
    """Sta solo a dare i nomi dei metodi: le risposte le decide il doppio di
    `safe_call`, che smista sul nome della funzione che gli arriva."""

    class ActivityDownloadFormat:
        ORIGINAL = "ORIGINAL"

    def get_activities(self, start, limit): ...
    def get_activities_by_date(self, start, end, **kwargs): ...
    def download_activity(self, activity_id, dl_fmt=None): ...


@pytest.fixture
def run_update(tmp_path, monkeypatch):
    """Lancia `update_activity` su una cartella temporanea con Garmin finto.

    Restituisce `(scaricate, tracce)`, dove `tracce` conta le pagine chieste,
    gli id di cui si e' tentato lo scaricamento e quante volte e' partito il
    rinfresco della salute.
    """

    def run(batches: list[list[dict]], downloads: dict, existing=()) -> tuple[list, dict]:
        fit = tmp_path / "fit"
        fit.mkdir(parents=True, exist_ok=True)
        for activity_id in existing:
            (fit / f"{activity_id}_ACTIVITY.fit").write_bytes(b"x")

        trace = {"pages": 0, "downloaded_ids": [], "health": 0}

        def fake_safe_call(func, *args, **kwargs):
            name = getattr(func, "__name__", "")
            if name == "get_activities":
                trace["pages"] += 1
                page = args[0] // 100
                return batches[page] if page < len(batches) else []
            if name == "download_activity":
                trace["downloaded_ids"].append(args[0])
                body = downloads.get(args[0])
                if isinstance(body, Exception):
                    raise body
                return body
            raise AssertionError(f"chiamata non prevista: {name}")

        monkeypatch.setattr(A, "safe_call", fake_safe_call)
        monkeypatch.setattr(A, "init_api", FakeApi)
        monkeypatch.setattr(A, "REQUEST_DELAY", 0)
        monkeypatch.setattr(
            A, "refresh_recent_health", lambda api, data_dir: trace.__setitem__("health", trace["health"] + 1)
        )
        return A.update_activity(tmp_path), trace

    return run


@pytest.fixture
def config_file(tmp_path) -> Path:
    """Un `config.yaml` minimo e valido, da storpiare una chiave per volta."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "token_store: ~/token\n"
        "local_tz: Europe/Rome\n"
        "history_start: 2025-01-01\n"
        "request_delay: 0.3\n"
        "health_refresh_days: 3\n"
        "fitness_status_window_days: 14\n",
        encoding="utf-8",
    )
    return path
