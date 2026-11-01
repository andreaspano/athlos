"""Sintesi dello stato di forma recente: attivita' + metriche di benessere.

Usa una cache locale su disco (data/) e la aggiorna solo dove serve: le
attivita' gia' scaricate e i giorni di salute passati non vengono
richiesti di nuovo, mentre le metriche di oggi vengono sempre riscaricate
perche' possono cambiare nel corso della giornata (es. training readiness
dopo un allenamento mattutino).
"""

import contextlib
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from .activities import download_activities_between
from .auth import init_api
from .config import DATA_DIR, FITNESS_STATUS_WINDOW_DAYS
from .files import read_json
from .health import export_daily_health, today_local


# I nove endpoint di prima del todo 38: endurance, hill score e soglia del
# lattato sono solo per la Day in React, e questo snapshot resta com'era.
# L'agente del report non lo usa piu' (prende i fatti da `make daily_data`,
# todo 31), ma `make fitness_status` resta.
REPORT_ENDPOINTS = (
    "stats",
    "sleep",
    "stress",
    "hrv",
    "spo2",
    "respiration",
    "resting_heart_rate",
    "training_readiness",
    "training_status",
)


def _load_cached_health(data_dir: Path, start_date: date, end_date: date) -> dict[str, dict[str, Any]]:
    health_dir = data_dir / "health"
    result: dict[str, dict[str, Any]] = {name: {} for name in REPORT_ENDPOINTS}

    d = start_date
    while d <= end_date:
        date_str = d.strftime("%Y-%m-%d")
        for name in REPORT_ENDPOINTS:
            path = health_dir / name / f"{date_str}.json"
            # Un file troncato non deve far morire lo snapshot dopo che ha
            # speso tutte le chiamate: si salta quel giorno, come fa
            # `interface/health.py` con gli stessi file.
            data = read_json(path, default=None, label=f"{name}/{date_str}.json")
            if data is not None:
                result[name][date_str] = data
        d += timedelta(days=1)

    return result


def build_fitness_status(
    data_dir: Path = DATA_DIR, days: int = FITNESS_STATUS_WINDOW_DAYS
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    today = today_local()
    start_date = today - timedelta(days=days - 1)

    api = init_api()

    print(f"Aggiorno i dati recenti ({start_date} -> {today})...")
    _, activities = download_activities_between(
        api, start_date.isoformat(), today.isoformat(), data_dir
    )
    export_daily_health(api, data_dir, start_date, today, force_dates={today})

    health = _load_cached_health(data_dir, start_date, today)

    return {
        "window": {"start": start_date.isoformat(), "end": today.isoformat(), "days": days},
        "activities": activities,
        "health": health,
    }


def main() -> None:
    """Stampa lo snapshot come JSON su stdout; ogni messaggio di
    avanzamento (proprio o delle funzioni chiamate) va su stderr, per
    lasciare stdout pulito a chi consuma l'output come JSON."""
    with contextlib.redirect_stdout(sys.stderr):
        status = build_fitness_status()
    print(json.dumps(status, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
