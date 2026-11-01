"""Esportazione dell'elenco attivita' e dei relativi file originali (FIT)."""

import io
import json
import re
import time
import zipfile
from pathlib import Path

from garminconnect import Garmin, GarminConnectAuthenticationError

from .auth import init_api
from .client import safe_call
from .config import DATA_DIR, REQUEST_DELAY
from .health import refresh_recent_health

_ACTIVITY_ID_RE = re.compile(r"(\d+)_ACTIVITY\.fit$")
_NAMES_FILENAME = "activity_names.json"
_TYPES_FILENAME = "activity_types.json"


def _names_path(data_dir: Path) -> Path:
    return Path(data_dir) / "json" / _NAMES_FILENAME


def _load_activity_names(data_dir: Path) -> dict:
    path = _names_path(data_dir)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_activity_names(data_dir: Path, names: dict) -> None:
    path = _names_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=2, sort_keys=True)


def _types_path(data_dir: Path) -> Path:
    return Path(data_dir) / "json" / _TYPES_FILENAME


def _load_activity_types(data_dir: Path) -> dict:
    path = _types_path(data_dir)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_activity_types(data_dir: Path, types: dict) -> None:
    path = _types_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(types, f, ensure_ascii=False, indent=2, sort_keys=True)


def _remember(act: dict, names: dict, types: dict) -> None:
    """Nome e tipo dell'attivita' non stanno nel file FIT: arrivano solo con
    l'elenco attivita', quindi li salviamo ora che li abbiamo. Il tipo serve
    perche' un'attivita' registrata seguendo un percorso preimpostato finisce
    nel FIT come sport "generic" (sotto-tipo "navigate"), mentre Garmin sa
    che era, ad esempio, una corsa."""
    activity_id = str(act["activityId"])
    if act.get("activityName"):
        names[activity_id] = act["activityName"]
    type_key = (act.get("activityType") or {}).get("typeKey")
    if type_key:
        types[activity_id] = type_key


def _download_or_warn(api: Garmin, activity_id, label: str):
    """Scarica il file originale di una attivita', e se non si puo' lo dice e
    restituisce `None`.

    `safe_call` alza l'eccezione sugli errori veri (vedi `client.py`): qui
    serve il comportamento di prima, cioe' che una singola attivita' che non
    si scarica non fermi le altre. L'errore di autenticazione invece esce:
    senza login non ne scarichera' nessuna."""
    try:
        return safe_call(
            api.download_activity, activity_id, dl_fmt=api.ActivityDownloadFormat.ORIGINAL
        )
    except GarminConnectAuthenticationError:
        raise
    except Exception as exc:
        print(f"  {label} ATTENZIONE: attivita' {activity_id} non scaricata: {exc}")
        return None


def export_activities(api: Garmin, out_dir: Path) -> list:
    activities_dir = out_dir / "activities"
    fit_dir = activities_dir / "fit"
    fit_dir.mkdir(parents=True, exist_ok=True)

    summary_path = activities_dir / "activities_summary.json"
    all_activities = []

    print("Recupero l'elenco di tutte le attivita'...")
    start, limit = 0, 100
    while True:
        batch = safe_call(api.get_activities, start, limit)
        if not batch:
            break
        all_activities.extend(batch)
        print(f"  ...{len(all_activities)} attivita' trovate finora")
        if len(batch) < limit:
            break
        start += limit
        time.sleep(REQUEST_DELAY)

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(all_activities, f, ensure_ascii=False, indent=2, default=str)
    print(f"Totale attivita' trovate: {len(all_activities)} (elenco salvato in {summary_path})")

    print("Scarico i file originali (FIT, zippati da Garmin) di ogni attivita'...")
    for i, act in enumerate(all_activities, 1):
        activity_id = act.get("activityId")
        if activity_id is None:
            continue
        target = fit_dir / f"{activity_id}.zip"
        if target.exists():
            continue  # gia' scaricata in un run precedente
        data = _download_or_warn(api, activity_id, f"[{i}/{len(all_activities)}]")
        if data:
            with open(target, "wb") as f:
                f.write(data)
            if i % 25 == 0 or i == len(all_activities):
                print(f"  [{i}/{len(all_activities)}] scaricate finora...")
        else:
            print(f"  [{i}/{len(all_activities)}] ATTENZIONE: impossibile scaricare l'attivita' {activity_id}")
        time.sleep(REQUEST_DELAY)

    return all_activities


def _existing_activity_ids(data_dir: Path) -> set:
    ids = set()
    for path in (data_dir / "fit").glob("*_ACTIVITY.fit"):
        match = _ACTIVITY_ID_RE.search(path.name)
        if match:
            ids.add(int(match.group(1)))
    return ids


def download_activities_between(
    api: Garmin, start_date: str, end_date: str, data_dir: Path = DATA_DIR
) -> list:
    """Scarica in data_dir tutte le attivita' comprese tra start_date e
    end_date (formato 'YYYY-MM-DD', estremi inclusi) non ancora presenti."""
    data_dir = Path(data_dir)
    (data_dir / "fit").mkdir(parents=True, exist_ok=True)
    existing_ids = _existing_activity_ids(data_dir)
    names = _load_activity_names(data_dir)
    types = _load_activity_types(data_dir)

    print(f"Recupero le attivita' tra {start_date} e {end_date} da Garmin Connect...")
    activities = safe_call(api.get_activities_by_date, start_date, end_date)
    activities = activities or []
    to_download = []
    for act in activities:
        activity_id = act.get("activityId")
        if activity_id is None:
            continue
        _remember(act, names, types)
        if activity_id not in existing_ids:
            to_download.append(act)

    _save_activity_names(data_dir, names)
    _save_activity_types(data_dir, types)

    if not to_download:
        print(f"Nessuna nuova attivita' da scaricare per l'intervallo {start_date} .. {end_date}.")
        return []

    print(f"Trovate {len(to_download)} nuove attivita'. Scarico ed estraggo in {data_dir.resolve()}...")
    downloaded = []
    for i, act in enumerate(to_download, 1):
        activity_id = act["activityId"]
        data = _download_or_warn(api, activity_id, f"[{i}/{len(to_download)}]")
        if data is None:
            time.sleep(REQUEST_DELAY)
            continue

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(data_dir / "fit")

        downloaded.append(activity_id)
        print(f"  [{i}/{len(to_download)}] estratta attivita' {activity_id}")
        time.sleep(REQUEST_DELAY)

    print(f"Fatto: {len(downloaded)} nuove attivita' aggiunte a {data_dir.resolve()}")
    return downloaded


def update_activity(data_dir: Path = DATA_DIR) -> list:
    """Si connette a Garmin Connect e scarica in data_dir le attivita' piu'
    recenti di quella gia' presente, estraendo lo zip originale di ognuna.

    Le attivita' vengono richieste dalla piu' recente alla piu' vecchia:
    ci si ferma alla prima gia' presente in data_dir, assumendo che tutte
    quelle precedenti siano gia' state scaricate.

    Alla fine rinfresca anche le metriche di salute degli ultimi giorni
    (`refresh_recent_health`): le card Recovery e Health della Day le leggono
    da li', e tenere aggiornate le attivita' e non la salute lascerebbe meta'
    dell'app indietro.
    Lo fa anche quando non c'e' nessuna attivita' nuova, che e' anzi il caso
    normale: un giorno di riposo non aggiunge uscite ma ha comunque il suo
    sonno, la sua readiness e il suo body battery. Lo storico, che costa
    tutt'altro, resta a `backfill_health`."""
    data_dir = Path(data_dir)
    (data_dir / "fit").mkdir(parents=True, exist_ok=True)
    existing_ids = _existing_activity_ids(data_dir)
    names = _load_activity_names(data_dir)
    types = _load_activity_types(data_dir)

    api = init_api()

    print("Recupero le attivita' piu' recenti da Garmin Connect...")
    new_ids = []
    start, limit = 0, 100
    while True:
        batch = safe_call(api.get_activities, start, limit)
        if not batch:
            break

        stop = False
        for act in batch:
            activity_id = act.get("activityId")
            if activity_id is None:
                continue
            _remember(act, names, types)
            if activity_id in existing_ids:
                stop = True
                break
            new_ids.append(activity_id)

        if stop or len(batch) < limit:
            break
        start += limit
        time.sleep(REQUEST_DELAY)

    _save_activity_names(data_dir, names)
    _save_activity_types(data_dir, types)

    if not new_ids:
        print("Nessuna nuova attivita' da scaricare.")
        refresh_recent_health(api, data_dir)
        return []

    print(f"Trovate {len(new_ids)} nuove attivita'. Scarico ed estraggo in {data_dir.resolve()}...")
    downloaded = []
    for i, activity_id in enumerate(new_ids, 1):
        data = _download_or_warn(api, activity_id, f"[{i}/{len(new_ids)}]")
        if data is None:
            time.sleep(REQUEST_DELAY)
            continue

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(data_dir / "fit")

        downloaded.append(activity_id)
        print(f"  [{i}/{len(new_ids)}] estratta attivita' {activity_id}")
        time.sleep(REQUEST_DELAY)

    print(f"Fatto: {len(downloaded)} nuove attivita' aggiunte a {data_dir.resolve()}")
    refresh_recent_health(api, data_dir)
    return downloaded


def backfill_activity_names(data_dir: Path = DATA_DIR) -> dict:
    """Recupera da Garmin Connect nome e tipo di tutte le attivita' gia'
    presenti in data_dir ma non ancora salvate in activity_names.json /
    activity_types.json (ad es. quelle scaricate prima che queste
    funzionalita' esistessero)."""
    data_dir = Path(data_dir)
    existing_ids = _existing_activity_ids(data_dir)
    names = _load_activity_names(data_dir)
    types = _load_activity_types(data_dir)
    missing = {i for i in existing_ids if str(i) not in names or str(i) not in types}
    if not missing:
        print("Nome e tipo di tutte le attivita' sono gia' presenti.")
        return names

    api = init_api()
    print(f"Recupero nome e tipo di {len(missing)} attivita'...")
    start, limit = 0, 100
    while missing:
        batch = safe_call(api.get_activities, start, limit)
        if not batch:
            break
        for act in batch:
            activity_id = act.get("activityId")
            if activity_id in missing:
                _remember(act, names, types)
                missing.discard(activity_id)
        if len(batch) < limit:
            break
        start += limit
        time.sleep(REQUEST_DELAY)

    _save_activity_names(data_dir, names)
    _save_activity_types(data_dir, types)
    if missing:
        print(f"ATTENZIONE: dati non trovati per {len(missing)} attivita': {sorted(missing)}")
    return names
