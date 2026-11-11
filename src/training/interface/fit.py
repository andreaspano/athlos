"""Parsing dei file FIT delle attivita' (`fit/*.fit`)."""

import json
import os
import re
import tempfile
from datetime import timezone
from pathlib import Path

import pandas as pd
from fitparse import FitFile

# LOCAL_TZ viene da `user/config.yaml`; `db.py` continua a prenderlo da qui.
from training.garmin.config import DATA_DIR, LOCAL_TZ

_ACTIVITY_ID_RE = re.compile(r"(\d+)_ACTIVITY\.fit$")
_SEMICIRCLE_TO_DEGREES = 180 / 2**31
_NAMES_FILENAME = "activity_names.json"
_TYPES_FILENAME = "activity_types.json"

# I FIT che non vengono da Garmin Connect non hanno un id nel nome: quello di
# MyWhoosh si chiama come il gettone con cui lo scarichi
# (`9xhBLisD1yrpjp0BGOC2JAOajk6OiLqYCkI717pw.fit`). Il loro id lo da'
# l'istante di partenza, che sta nel file e non cambia mai: due attivita' non
# possono cominciare nello stesso secondo, quindi l'id e' stabile fra un
# rebuild e l'altro — ed e' quello che la tabella pretende, perche' `path` e
# `activity_id` devono dire la stessa cosa a ogni lettura.
#
# L'offset tiene separati i due spazi di numeri. Gli id di Garmin sono
# progressivi e nell'archivio vanno da 634168011 a 24995834009: **attraversano**
# gli epoch di questi anni (1.76e9 oggi), e un epoch nudo sarebbe potuto
# cadere sull'id di un'attivita' vera. 1e12 Garmin lo raggiungera' fra secoli.
MANUAL_ID_BASE = 10**12


def _to_local(dt):
    """FIT timestamps are naive UTC (fitparse uses utcfromtimestamp);
    convert to naive local time so displayed times match the wall clock."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).replace(tzinfo=None)


def load_activity_names(data_dir: Path) -> dict:
    return _load_json_map(Path(data_dir) / "json" / _NAMES_FILENAME)


def load_activity_types(data_dir: Path) -> dict:
    """Il tipo attivita' secondo Garmin Connect (es. "running"), salvato da
    training.garmin.activities: serve quando il FIT non lo sa (sport
    "generic" delle attivita' registrate seguendo un percorso)."""
    return _load_json_map(Path(data_dir) / "json" / _TYPES_FILENAME)


def _load_json_map(path: Path) -> dict:
    """La mappa, o vuota se il file manca o non e' JSON valido.

    Un file troncato non deve far cadere la pagina: i nomi e i tipi che
    contiene sono un aiuto (il FIT da solo non li sa), non un dato
    indispensabile, e `make backfill_activity_names` li rifa'."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_json_map(path: Path, values: dict) -> None:
    """Scrive la mappa in `path`: un file temporaneo nella stessa cartella,
    poi `os.replace`. Chi legge vede la versione vecchia o quella nuova, mai
    un file a meta'. Il lock fra due scritture insieme lo mette chi chiama
    (`terrain.py`, `run_type.py`), uno per file.

    La cartella si crea se non c'e': dal todo 65 questi file stanno in
    `json/`, e la prima correzione di una cartella dati nuova la troverebbe
    vuota."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(values, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _semicircles_to_degrees(value: int | None) -> float | None:
    return value * _SEMICIRCLE_TO_DEGREES if value is not None else None


def list_activity_files(data_dir: Path = DATA_DIR) -> list[Path]:
    """Tutti i FIT della cartella dati, **anche nelle sottocartelle**.

    I FIT stanno in `fit/` dal todo 65; prima erano piatti nella radice,
    mischiati al database e ai JSON.

    **Tutti i `.fit`**, non solo i `*_ACTIVITY.fit` che scarica Garmin: una
    seduta registrata altrove — l'esportazione di MyWhoosh di una pedalata al
    rullo — e' un allenamento come gli altri, e restava fuori dall'archivio
    solo per il nome che porta. Un file che non si legge lo scarta
    `db._parse_and_store_or_warn`, come ha sempre fatto per i FIT rovinati.

    **E anche in una cartella sua**: `fit/mywhoosh/` e' l'11 novembre 2026 e
    non e' un disordine, e' il solo modo di distinguerli a occhio — i file di
    MyWhoosh si chiamano come il gettone con cui li hai scaricati
    (`HrnAYPiyUCixCFtArgblQVxFNFFaZFkFgetcl71x.fit`), e in mezzo a
    novecentottanta `<id>_ACTIVITY.fit` non si riconoscono. Garmin continua a
    scaricare piatto in `fit/`, e le due cose convivono.

    Lo scandaglio e' ricorsivo, quindi la chiave di chi non ha l'id nel nome
    (`db._paths_to_parse` usa il percorso) cambia se il file si **sposta**: il
    file viene riletto una volta e la riga si aggiorna da se', che
    l'`ON CONFLICT(activity_id)` scrive il percorso nuovo. Un id che nasce
    dall'istante di partenza non cambia perche' il file ha cambiato cartella.
    """
    return sorted((Path(data_dir) / "fit").rglob("*.fit"))


def activity_id_from_path(path: Path) -> int | None:
    """L'id di Garmin scritto nel nome del file, o None se non c'e'.

    None non vuol dire "file da scartare": vuol dire che l'id va cercato
    dentro, e lo fa `load_activity_summary` con `_manual_activity_id`. Chi
    deve sapere se un file e' gia' in cache senza aprirlo (`db._paths_to_parse`)
    si regge su questo nome finche' c'e', e sul percorso quando manca."""
    match = _ACTIVITY_ID_RE.search(Path(path).name)
    return int(match.group(1)) if match else None


def _manual_activity_id(start_time) -> int | None:
    """L'id di un FIT senza id nel nome, dal suo istante di partenza (vedi
    `MANUAL_ID_BASE`). None se il file non dice nemmeno quando e' cominciato:
    li' non c'e' niente da mettere in cache.

    `start_time` e' quello che scrive fitparse, cioe' UTC senza fuso: l'epoch
    si calcola da li' e non dall'ora locale, che cambia due volte l'anno."""
    if start_time is None:
        return None
    return MANUAL_ID_BASE + int(start_time.replace(tzinfo=timezone.utc).timestamp())


# Il VO2max stimato dall'orologio sta in un messaggio non documentato, il
# numero 140 (lo scrive il motore Firstbeat), nel campo 7, come intero scalato:
# VO2max = raw * 3.5 / 65536 (753282 -> 40.2 ml/kg/min). La formula viene dal
# lavoro di chi ha decodificato i file a mano, ed e' stata controllata contro
# i `vO2MaxValue` che l'API Garmin ha dato a `fitness-status` per le stesse
# corse (settembre 2026: 40.0/40, 39.5/39, 39.4/39, 40.1/40): combaciano, con
# un decimale in piu' nel file.
#
# Non e' sempre una stima fatta *su quella* attivita': e' il valore corrente
# dell'orologio a fine attivita'. Le corse che si qualificano lo aggiornano,
# le altre attivita' se lo portano dietro (lo hanno anche sci e camminate).
_VO2MAX_MESSAGE = 140
_VO2MAX_FIELD = 7
_VO2MAX_SCALE = 3.5 / 65536
# Fuori da qui il numero non e' un VO2max di una persona: il campo non e'
# documentato, un firmware nuovo potrebbe spostarlo, e una cella vuota e'
# meglio di un valore assurdo.
_VO2MAX_PLAUSIBLE = (10.0, 100.0)


def _vo2max(fit: FitFile) -> float | None:
    """Il VO2max dell'orologio a fine attivita', o None se non c'e'.

    Vuole lo stesso `FitFile` gia' aperto per `session`: fitparse il file lo
    legge tutto alla prima richiesta, quindi questa non costa un altro parsing.
    Un campo a zero vuol dire "nessuna stima" (succede per le corse che
    l'orologio non considera, come quelle su sentiero)."""
    for message in fit.get_messages(_VO2MAX_MESSAGE):
        for field in message.fields:
            if field.def_num == _VO2MAX_FIELD and isinstance(field.value, (int, float)):
                value = field.value * _VO2MAX_SCALE
                low, high = _VO2MAX_PLAUSIBLE
                return round(value, 1) if low <= value <= high else None
    return None


# Le zone cardiache stanno nel messaggio `time_in_zone` (216), che la
# versione di fitparse in uso non conosce per nome: i campi si leggono per
# numero, come il VO2max. Il messaggio c'e' una volta per la sessione
# (`reference_mesg` = 18) e una per ogni giro; serve quello della sessione.
# Nel campo 6 ci sono sei tetti: il primo e' quello della "zona 0", i tetti di
# Z1-Z4 sono i quattro dopo (il sesto e' il massimo). Nel 13 la soglia
# anaerobica. Sul file del 03/10/2026: (86, 106, 121, 141, 157, 176) e 155.
_TIME_IN_ZONE_MESSAGE = 216
_SESSION_MESSAGE = 18
_ZONE_FIELDS = {"reference_mesg": 0, "hr_zone_high_boundary": 6, "threshold_heart_rate": 13}


def _hr_zones(fit: FitFile) -> tuple[list[int] | None, int | None]:
    """I tetti di Z1-Z4 e la soglia anaerobica della sessione, o None.

    I file vecchi il messaggio non lo hanno, o lo hanno vuoto."""
    for message in fit.get_messages(_TIME_IN_ZONE_MESSAGE):
        fields = {field.def_num: field.value for field in message.fields}
        if fields.get(_ZONE_FIELDS["reference_mesg"]) != _SESSION_MESSAGE:
            continue
        bounds = fields.get(_ZONE_FIELDS["hr_zone_high_boundary"])
        threshold = fields.get(_ZONE_FIELDS["threshold_heart_rate"])
        tops = list(bounds[1:5]) if isinstance(bounds, (tuple, list)) and len(bounds) >= 5 else None
        if tops is not None and any(not isinstance(top, int) for top in tops):
            tops = None
        return tops, threshold if isinstance(threshold, int) else None
    return None, None


def _avg_speed_kmh(values: dict) -> float | None:
    """La velocita' media in km/h, o None se non si puo' ricavare.

    `avg_speed` e' il campo storico a 16 bit, soppiantato da
    `enhanced_avg_speed` a 32 bit: l'orologio nuovo (garmin_product 4759) il
    primo non lo scrive piu' e lascia solo il secondo, quindi si prova prima
    quello, come gia' si fa per la velocita' e la quota dei record.

    Escursioni e camminate non hanno nessuno dei due: li' la si ricava dalla
    distanza. Il divisore e' il tempo in movimento, non quello totale, perche'
    e' quello che usa Garmin: sull'uscita in bici del 23/09/2026 43407.66 m /
    7807.5 s danno 5.560 m/s, cioe' esattamente l'`avg_speed` scritto nel file,
    mentre col tempo totale verrebbe 5.011."""
    speed = values.get("enhanced_avg_speed") or values.get("avg_speed")
    if speed is None:
        distance = values.get("total_distance")
        moving = values.get("total_timer_time") or values.get("total_elapsed_time")
        if not distance or not moving:
            return None
        speed = distance / moving
    return speed * 3.6


def _workout(fit: FitFile) -> dict:
    """L'allenamento pianificato che l'orologio ha seguito (todo 36), dai
    messaggi `workout` e `workout_step`: il nome, quanti passi sono `active`
    e il piu' lungo di questi in secondi. Tutti None se l'attivita' non
    seguiva un allenamento.

    Vuole lo stesso `FitFile` gia' aperto per `session`, come `_vo2max`:
    nessun parsing in piu'.

    **I blocchi `repeat` si espandono.** Su molti file di Andrea (Rip_3x5,
    Rip_4x5) le ripetute sono passi distinti e contarli basta; su altri
    (Rip_5min4T) sono un passo solo piu' un passo di ripetizione, e contando
    i passi scritti venivano una ripetuta invece di quattro — quindi
    `guess_run_type` non arrivava mai a `intervals` e la corsa usciva
    `easy`, con una correzione a mano a rimediare.

    Un passo con `duration_type = repeat_until_steps_cmplt` dice da quale
    passo tornare (`duration_step`) e quante volte si fa il giro
    (`repeat_steps`): i passi di quel tratto valgono quelle volte. La
    moltiplicazione regge anche i blocchi dentro i blocchi, perche' il
    `repeat` esterno viene dopo e moltiplica di nuovo il tratto interno."""
    workout = next(fit.get_messages("workout"), None)
    if workout is None:
        return {"workout_name": None, "workout_active_steps": None, "workout_active_max_s": None}
    steps = [step.get_values() for step in fit.get_messages("workout_step")]
    times = dict.fromkeys(range(len(steps)), 1)
    for index, step in enumerate(steps):
        if step.get("duration_type") != "repeat_until_steps_cmplt":
            continue
        back, repeats = step.get("duration_step"), step.get("repeat_steps")
        if isinstance(back, int) and isinstance(repeats, int) and repeats > 1 and back < index:
            for inside in range(back, index):
                times[inside] *= repeats
    active = [
        (times[index], step.get("duration_time"))
        for index, step in enumerate(steps)
        if step.get("intensity") == "active"
    ]
    timed = [duration for _, duration in active if isinstance(duration, (int, float))]
    return {
        "workout_name": workout.get_value("wkt_name"),
        "workout_active_steps": sum(count for count, _ in active),
        "workout_active_max_s": max(timed) if timed else None,
    }


def load_activity_summary(path: Path) -> dict:
    """Legge il messaggio 'session' del file FIT: una riga di riepilogo."""
    fit = FitFile(str(path))
    session = next(fit.get_messages("session"), None)
    values = session.get_values() if session else {}
    zone_tops, threshold_hr = _hr_zones(fit)
    activity_id = activity_id_from_path(path)
    if activity_id is None:
        activity_id = _manual_activity_id(values.get("start_time"))

    return {
        "activity_id": activity_id,
        "path": str(path),
        # Il nome che il file si porta dietro, quando ce l'ha: `activity_names.json`
        # ha solo le attivita' di Garmin Connect, e di una pedalata esportata da
        # MyWhoosh il nome del percorso ("Al Qudra") sta in un campo dello
        # sviluppatore della sessione. Vince comunque il nome di Connect, dove
        # c'e': e' quello che Andrea puo' correggere (vedi `db._parse_and_store`).
        "fit_name": values.get("Title"),
        "sport": values.get("sport"),
        "sub_sport": values.get("sub_sport"),
        "start_time": _to_local(values.get("start_time")),
        "total_distance_km": (values.get("total_distance") or 0) / 1000,
        "total_time_min": (values.get("total_elapsed_time") or 0) / 60,
        "avg_heart_rate": values.get("avg_heart_rate"),
        "max_heart_rate": values.get("max_heart_rate"),
        "avg_speed_kmh": _avg_speed_kmh(values),
        "total_calories": values.get("total_calories"),
        "total_ascent_m": values.get("total_ascent"),
        "total_descent_m": values.get("total_descent"),
        "vo2max": _vo2max(fit),
        # I Training Effect di Garmin: il suo algoritmo, nel file solo i totali.
        "aerobic_te": values.get("total_training_effect"),
        "anaerobic_te": values.get("total_anaerobic_training_effect"),
        "hr_zone_bounds": json.dumps(zone_tops) if zone_tops else None,
        "threshold_hr": threshold_hr,
        **_workout(fit),
    }


def load_activity_records(path: Path) -> pd.DataFrame:
    """Legge i messaggi 'record' del file FIT: una riga per ogni istante campionato."""
    fit = FitFile(str(path))
    rows = []
    for record in fit.get_messages("record"):
        values = record.get_values()
        rows.append(
            {
                "timestamp": _to_local(values.get("timestamp")),
                "heart_rate": values.get("heart_rate"),
                "speed_kmh": (values.get("enhanced_speed") or values.get("speed") or 0) * 3.6,
                "altitude_m": values.get("enhanced_altitude") or values.get("altitude"),
                "cadence": values.get("cadence"),
                "power": values.get("power"),
                "lat": _semicircles_to_degrees(values.get("position_lat")),
                "lon": _semicircles_to_degrees(values.get("position_long")),
                "distance_km": (values.get("distance") or 0) / 1000,
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.set_index("timestamp")
    return df


# L'enum `intensity` di un giro. Il profilo di fitparse conosce i primi
# quattro valori e rende la stringa; gli altri li lascia interi, e senza
# questa mappa i recuperi di un allenamento resterebbero un `4`.
_LAP_INTENSITY = {
    0: "active",
    1: "rest",
    2: "warmup",
    3: "cooldown",
    4: "recovery",
    5: "interval",
    6: "other",
}


def _lap_intensity(value) -> str | None:
    """Il nome dell'intensita' di un giro: quello che il FIT ha scritto, o
    quello dell'enum quando arriva il numero. Un valore che non conosciamo
    resta com'e', scritto."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return _LAP_INTENSITY.get(value, str(value))


def load_activity_laps(path: Path) -> pd.DataFrame:
    """Legge i messaggi 'lap' del file FIT: una riga per giro (todo 79).

    I giri di una corsa libera sono quelli dell'auto-lap al chilometro;
    quelli di una seduta con un allenamento caricato sull'orologio portano
    anche `workout_step`, il passo che stavano seguendo — ed e' quel campo,
    non l'intensita', che distingue le due cose."""
    fit = FitFile(str(path))
    rows = []
    for index, lap in enumerate(fit.get_messages("lap")):
        values = lap.get_values()
        message_index = values.get("message_index")
        rows.append(
            {
                "lap_index": int(message_index) if message_index is not None else index,
                "intensity": _lap_intensity(values.get("intensity")),
                "trigger": values.get("lap_trigger"),
                "time_s": values.get("total_timer_time"),
                "distance_m": values.get("total_distance"),
                "speed_kmh": (values.get("enhanced_avg_speed") or values.get("avg_speed") or 0) * 3.6,
                "avg_hr": values.get("avg_heart_rate"),
                "max_hr": values.get("max_heart_rate"),
                "cadence": values.get("avg_running_cadence") or values.get("avg_cadence"),
                "ascent_m": values.get("total_ascent"),
                "workout_step": values.get("wkt_step_index"),
            }
        )
    return pd.DataFrame(rows)
