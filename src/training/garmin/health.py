"""Esportazione delle metriche giornaliere di salute/wellness."""

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from garminconnect import Garmin, GarminConnectAuthenticationError

from .auth import init_api
from .client import safe_call
from .config import DATA_DIR, HEALTH_REFRESH_DAYS, HISTORY_START, LOCAL_TZ, REQUEST_DELAY
from .files import write_json

DAILY_ENDPOINTS = {
    "stats": lambda api, d: api.get_stats(d),
    "sleep": lambda api, d: api.get_sleep_data(d),
    "stress": lambda api, d: api.get_stress_data(d),
    "hrv": lambda api, d: api.get_hrv_data(d),
    "spo2": lambda api, d: api.get_spo2_data(d),
    "respiration": lambda api, d: api.get_respiration_data(d),
    "resting_heart_rate": lambda api, d: api.get_rhr_day(d),
    "training_readiness": lambda api, d: api.get_training_readiness(d),
    "training_status": lambda api, d: api.get_training_status(d),
    # La card Fitness della Day in React (todo 38): rispondono con il
    # dizionario del giorno, `{}` prima che l'orologio li calcolasse.
    "endurance_score": lambda api, d: api.get_endurance_score(d),
    "hill_score": lambda api, d: api.get_hill_score(d),
}

# La soglia del lattato della corsa (todo 38) non e' un endpoint giornaliero:
# chiesta per un giorno, Garmin risponde con liste vuote tranne il giorno in
# cui ne ha rilevata una nuova. Si tiene solo l'ultima (`latest=True`), in un
# file unico riscritto a ogni `update_activity`. Il backfill non la scarica:
# l'ultima soglia di oggi scritta nei file dei giorni passati sarebbe falsa.
LACTATE_THRESHOLD_FILE = "lactate_threshold_latest.json"


def _is_complete(path: Path, day: date) -> bool:
    """Il file del giorno `day` c'e' ed e' stato salvato dopo la fine di quel
    giorno (mezzanotte del giorno dopo, ora locale come le date dei file).

    Un file salvato durante il giorno e' una fotografia a meta' (todo 39): il
    `training_status` del 2026-10-15, salvato alle 13:20, non aveva la corsa
    delle 19:50, ne' il VO2max e il carico che Garmin ne ha ricavato."""
    try:
        saved = datetime.fromtimestamp(path.stat().st_mtime, tz=LOCAL_TZ)
    except OSError:
        return False
    # Il giorno e' quello di Garmin, cioe' del fuso dell'account (`local_tz`),
    # non quello dell'orologio della macchina: su un portatile in viaggio, o in
    # un container con un TZ diverso, le due mezzanotti non sono la stessa e un
    # file scritto alle 23 di Roma risultava salvato il giorno dopo.
    end_of_day = datetime.combine(
        day + timedelta(days=1), datetime.min.time(), tzinfo=LOCAL_TZ
    )
    if saved < end_of_day:
        return False
    # Anche un file troncato ha un mtime dopo la fine del suo giorno: senza
    # questa lettura resterebbe "completo" per sempre e quel giorno non si
    # riscaricherebbe mai piu'. Costa una lettura di pochi kB per file, contro
    # le 11 chiamate a Garmin che fa risparmiare.
    try:
        with open(path, encoding="utf-8") as f:
            json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    return True


def today_local() -> date:
    """Oggi nel fuso dell'account, non in quello della macchina: e' il giorno
    con cui Garmin nomina i suoi dati, e quello con cui li nominiamo noi."""
    return datetime.now(LOCAL_TZ).date()


def export_daily_health(
    api: Garmin,
    out_dir: Path,
    start_date: date,
    end_date: date,
    force_dates: Optional[set[date]] = None,
) -> None:
    """Esporta le metriche giornaliere tra start_date e end_date. Un file gia'
    su disco si salta solo se e' completo (`_is_complete`: salvato dopo la
    fine del suo giorno); se manca o e' stato salvato durante il giorno si
    scarica di nuovo. Cosi' oggi si riscarica sempre, ieri si completa al
    primo giro di oggi, e un giorno rimasto a meta' si sistema al primo
    backfill. Le date in force_dates si riscaricano comunque."""
    force_dates = force_dates or set()
    health_dir = out_dir / "health"
    for name in DAILY_ENDPOINTS:
        (health_dir / name).mkdir(parents=True, exist_ok=True)

    total_days = (end_date - start_date).days + 1
    print(f"Scarico le metriche giornaliere di salute per {total_days} giorni "
          f"({start_date} -> {end_date})...")
    print("(puoi interrompere con Ctrl+C e rilanciare piu' tardi: riprendera' da dove eri arrivato)")

    d = start_date
    day_count = 0
    downloaded = 0
    failures: list[str] = []
    while d <= end_date:
        date_str = d.strftime("%Y-%m-%d")
        day_count += 1

        for name, func in DAILY_ENDPOINTS.items():
            target = health_dir / name / f"{date_str}.json"
            if _is_complete(target, d) and d not in force_dates:
                continue
            try:
                data = safe_call(func, api, date_str)
            except GarminConnectAuthenticationError:
                # Inutile provare gli altri 4000: serve un login.
                raise
            except Exception as exc:
                # Un anno di storico non si butta per una chiamata, quindi si
                # tira avanti; ma il conto finisce nell'errore finale, cosi'
                # chi ha lanciato (o `api/refresh.py`) lo sa.
                print(f"  ATTENZIONE: {name} del {date_str} non scaricato: {exc}")
                failures.append(f"{name} {date_str}: {exc}")
            else:
                if data is not None:
                    write_json(target, data)
                    downloaded += 1
            time.sleep(REQUEST_DELAY)

        if day_count % 30 == 0 or d == end_date:
            print(
                f"  ...elaborati {day_count}/{total_days} giorni (ultimo: {date_str}), "
                f"{downloaded} file scaricati"
            )

        d += timedelta(days=1)

    if failures:
        raise RuntimeError(
            f"{len(failures)} metriche non scaricate su {total_days} giorni "
            f"({downloaded} file scritti). La prima: {failures[0]}"
        )


def export_lactate_threshold(api: Garmin, out_dir: Path) -> None:
    """Scarica l'ultima soglia del lattato in `health/LACTATE_THRESHOLD_FILE`,
    sopra quella di prima. Se Garmin non risponde il file vecchio resta."""
    try:
        data = safe_call(lambda: api.get_lactate_threshold(latest=True))
    except GarminConnectAuthenticationError:
        raise
    except Exception as exc:
        # Il docstring promette che il file vecchio resta: qui l'eccezione si
        # ferma, ma a voce alta.
        print(f"  ATTENZIONE: soglia del lattato non aggiornata: {exc}")
        return
    if data is None:
        return
    health_dir = out_dir / "health"
    health_dir.mkdir(parents=True, exist_ok=True)
    write_json(health_dir / LACTATE_THRESHOLD_FILE, data)


def refresh_recent_health(api: Garmin, data_dir: Path = DATA_DIR) -> None:
    """Rinfresca le metriche degli ultimi giorni: oggi sempre, e i giorni prima
    i cui file non sono completi (vedi `export_daily_health`).

    La chiama `update_activity`, che senza di lei terrebbe aggiornate le
    attivita' e non la salute. Oggi cambia nel corso della giornata (la
    readiness dopo un allenamento, il body battery che si consuma); ieri, se
    l'ultimo giro e' stato ieri di giorno, e' rimasto a meta' e si completa
    adesso. In piu' riscarica l'ultima soglia del lattato."""
    today = today_local()
    export_daily_health(
        api,
        Path(data_dir),
        today - timedelta(days=HEALTH_REFRESH_DAYS - 1),
        today,
        force_dates={today},
    )
    export_lactate_threshold(api, Path(data_dir))


def backfill_health(data_dir: Path = DATA_DIR) -> None:
    """Scarica lo storico delle metriche di salute, da `history_start`
    (`user/config.yaml`) a oggi.

    E' un comando a parte (`make backfill_health`) e non un pezzo di
    `update_activity` per via di quanto costa: ogni giorno sono 11 chiamate, e
    con la pausa fra una e l'altra un anno di storico richiede 30-45 minuti. Si
    puo' interrompere con Ctrl+C e rilanciare: i giorni gia' scaricati e
    completi vengono saltati, quelli salvati a meta' giornata si riscaricano."""
    api = init_api()
    export_daily_health(api, Path(data_dir), HISTORY_START, today_local())
