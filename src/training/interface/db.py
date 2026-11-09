"""SQLite cache of parsed FIT activity data (data/activities.db).

Parsing FIT files with fitparse is slow (pure-Python, non-lazy: even the
small "session" summary message forces a full parse of the file, ~1s for
a ~450KB/~2800-sample activity). This module caches that parsed data in
SQLite so normal reads are indexed lookups instead of a FIT re-parse. The
.fit files remain the source of truth; the DB is always rebuildable from
them via rebuild().

Two entry points matter to callers: list_activities() and
load_activity_records(). list_activities() calls sync() first, so new .fit
files are picked up automatically without a manual cache-clear or restart;
load_activity_records() reads the records of one activity straight from the
DB, so it expects list_activities() to have synced already (that is the order
the API and the reports use).

L'API non chiama list_activities() a ogni richiesta: passa da
`api/cache.py`, che ci mette davanti una cache per non rifare la scansione
ogni volta.

Nello stesso file sta anche la tabella `health_daily`, ma non e' di questo
modulo: la costruisce `health_db.py` dai JSON di salute, non dai FIT, con la
sua versione (`health_logic_version` in schema_meta). rebuild() cancella il
file intero e quindi anche lei; il primo `health_db.sync_health()` dopo la
riempie di nuovo dai JSON.
"""

import fcntl
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pandas as pd

from training.garmin.config import DATA_DIR
from training.interface.fit import (
    LOCAL_TZ,
    activity_id_from_path,
    list_activity_files,
    load_activity_names,
    load_activity_summary,
    load_activity_types,
)
from training.interface.fit import load_activity_laps as _parse_fit_laps
from training.interface.fit import load_activity_records as _parse_fit_records
from training.interface.grade import (
    EQUIV_SPEED_SPORTS,
    equivalent_speed_kmh,
    equivalent_speed_series,
    sample_seconds,
)
from training.interface.run_type import guess_run_type, has_run_type, load_run_type_overrides
from training.interface.terrain import guess_terrain, has_terrain, load_terrain_overrides

DB_FILENAME = "activities.db"

# Il FIT di un'attivita' registrata seguendo un percorso preimpostato ha
# sport "generic" (sotto-tipo "navigate"): in quel caso lo sport vero lo
# sa solo Garmin Connect, che lo chiama con queste chiavi.
_GENERIC_SPORTS = {None, "", "generic"}
GARMIN_TYPE_TO_SPORT = {
    "running": "running",
    "trail_running": "running",
    "treadmill_running": "treadmill",
    "track_running": "running",
    "street_running": "running",
    "cycling": "cycling",
    "road_biking": "cycling",
    "mountain_biking": "cycling",
    "gravel_cycling": "cycling",
    "cyclocross": "cycling",
    "indoor_cycling": "cycling",
    "virtual_ride": "cycling",
    "e_bike_fitness": "cycling",
    "hiking": "hiking",
    "mountaineering": "hiking",
    "walking": "walking",
    "casual_walking": "walking",
    "speed_walking": "walking",
    "cross_country_skiing": "cross_country_skiing",
    "cross_country_skiing_ws": "cross_country_skiing",
    "skate_skiing": "cross_country_skiing",
    "backcountry_skiing": "cross_country_skiing",
}


def sport_from_garmin_type(
    sport: str | None, type_key: str | None, sub_sport: str | None = None
) -> str | None:
    """Lo sport da mostrare. Prima di tutto il tapis roulant: il `sub_sport`
    del FIT lo scrive il profilo dell'orologio, ed e' il solo segnale che c'e'
    sempre. Delle 23 sedute sul nastro dello storico una sola ha un tipo su
    Garmin Connect (`treadmill_running`), le altre 22 non ne hanno nessuno: la
    mappa qui sopra, da sola, ne prenderebbe una su ventitre.

    Poi vince il tipo di Garmin Connect, quando lo conosciamo: e' quello che
    l'utente puo' correggere dopo (una corsa registrata col profilo
    "Escursione" resta "hiking" nel FIT per sempre, anche se su Connect
    diventa "street_running"). Il FIT resta la risposta quando Connect non
    dice niente o usa una chiave che non mappiamo; se il FIT e' "generic" si
    mostra la chiave di Connect cosi' com'e'."""
    if sub_sport == "treadmill":
        return "treadmill"
    if type_key in GARMIN_TYPE_TO_SPORT:
        return GARMIN_TYPE_TO_SPORT[type_key]
    if sport not in _GENERIC_SPORTS or not type_key:
        return sport
    return type_key

# Due versioni, e **quale si alza non e' lo stesso** (todo 93):
#
# - `LOGIC_VERSION`: cambia quello che si ricava **dai file**. Rifarla vuol
#   dire rileggere tutti i FIT, e non c'e' scorciatoia: `make rebuild`, mezz'ora.
#   Esempi: una colonna nuova letta dal FIT, una lettura sbagliata dei tempi.
# - `DERIVED_VERSION`: cambia quello che si ricava **da cio' che la tabella ha
#   gia'** — i minuti per zona dai `records`, la soglia prestata dalle altre
#   righe. Si rifa' da se' al primo `sync()`, in secondi.
#
# Alzare quella sbagliata e' silenzioso: alzare `DERIVED_VERSION` quando
# serviva `LOGIC_VERSION` rifa' i conti sui dati vecchi e non lo dice nessuno.
# La domanda da farsi e' una: **questo numero si puo' ricavare dalle righe che
# ci sono?** Se si', e' derivato.
#
# `sync()` le confronta entrambe con `schema_meta`. Su `LOGIC_VERSION` diversa
# **non ricostruisce**: serve i dati che ci sono e lo dice (`cache_state`),
# perche' una ricostruzione dentro una richiesta HTTP ferma la pagina per
# mezz'ora. Su `DERIVED_VERSION` diversa rifa' i conti derivati e va avanti.
#
# "3": colonna `vo2max`, letta dal messaggio 140 dei file FIT. I file gia' in
# cache non la avevano, e sync() rilegge solo i file nuovi: il salto di versione
# e' quello che li fa rileggere tutti, una volta.
#
# "4": `avg_speed_kmh` leggeva solo il campo `avg_speed`, che l'orologio nuovo
# non scrive piu' (vedi `fit._avg_speed_kmh`): 45 attivita' erano in cache con
# 0 km/h al posto della velocita'.
#
# "5": colonna `equiv_speed_kmh`, la velocita' equivalente in piano (vedi
# `grade.py`), calcolata dai record: come per "3", i file gia' in cache vanno
# riletti tutti.
#
# "6": colonna `equiv_speed_kmh` anche nella tabella `records`, la velocita'
# equivalente campione per campione per il grafico Speed della scheda.
#
# "7": pendenza nuova (finestra di 30 m attorno al campione, vedi
# `grade.slope_pct`), quindi `equiv_speed_kmh` cambia in entrambe le tabelle;
# e colonne nuove in `activities` per il grafico della scheda (todo 28): i
# Training Effect di Garmin, i tetti delle zone cardiache e la soglia.
#
# "8": colonne `workout_name`, `workout_active_steps` e
# `workout_active_max_s`, l'allenamento pianificato letto dal FIT (vedi
# `fit._workout`), per stimare il tipo delle corse (todo 36).
#
# "9": tabella `laps`, i giri del FIT (todo 79). Nasce vuota e non si puo'
# riempire dai dati che ci sono: i giri stanno solo nei file, e per le sedute
# di prima vanno riletti da li'.
#
# "10": i minuti per zona vengono dalla stessa regola del grafico
# (`grade.sample_seconds`) e non piu' da un tetto di 30 secondi per buco,
# quindi `min_low_aerobic`, `min_high_aerobic` e `min_anaerobic` cambiano su
# tutte le sedute con una pausa: sul giro di nove ore 377.0 minuti invece di
# 379.7, su una pedalata del 28 ottobre 12.1 invece di 16.1.
#
# "11": colonna `threshold_hr_borrowed`. La soglia prestata non si scrive
# piu' in `threshold_hr`, che torna a essere solo quello che il FIT ha
# misurato: 32 righe la portavano come se fosse loro, e dal database non si
# poteva piu' sapere quali. Va riletto dai file perche' il valore misurato
# di quelle righe e' andato perso nella colonna.
LOGIC_VERSION = "11"

# I conti che si ricavano dalle righe in tabella. "1": il primo numero, da
# quando le due versioni si sono separate (todo 93).
#
# "2": si prestano anche i tetti delle zone, non solo la soglia
# (`hr_zone_bounds_borrowed`). Cambia chi ha dei minuti per zona: le sedute
# senza zone proprie, da `THRESHOLD_FALLBACK_FROM` in poi, prima non ne
# avevano nessuno — una pedalata al rullo esportata da MyWhoosh restava fuori
# dalla divisione fra lavoro facile e duro della Week.
DERIVED_VERSION = "2"

_LOGIC_KEY = "logic_version"
_DERIVED_KEY = "derived_version"

# Il nome del lucchetto delle scritture, accanto al database.
WRITE_LOCK_FILENAME = ".activities.lock"



_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id       INTEGER PRIMARY KEY,
    path              TEXT NOT NULL,
    sport             TEXT,
    sub_sport         TEXT,
    start_time        TEXT NOT NULL,
    total_distance_km REAL,
    total_time_min    REAL,
    avg_heart_rate    INTEGER,
    max_heart_rate    INTEGER,
    avg_speed_kmh     REAL,
    total_calories    INTEGER,
    total_ascent_m    REAL,
    total_descent_m   REAL,
    vo2max            REAL,
    equiv_speed_kmh   REAL,
    aerobic_te        REAL,
    anaerobic_te      REAL,
    hr_zone_bounds    TEXT,
    -- I tetti delle zone **prestati** da un'altra seduta, come
    -- `threshold_hr_borrowed` qui sotto e per la stessa ragione: il profilo
    -- Bici dell'orologio non salva il messaggio delle zone, e un FIT che non
    -- viene da Garmin (l'esportazione di MyWhoosh) non lo ha affatto. Stessa
    -- forma della colonna misurata, JSON. Le due cose arrivano **dalla stessa
    -- seduta donatrice** (vedi `_lend_zone_settings`).
    hr_zone_bounds_borrowed TEXT,
    threshold_hr      INTEGER,
    -- La soglia **prestata** da un'altra seduta, quando questa non ne ha una
    -- sua (vedi `_lend_zone_settings`). Sta in una colonna a parte
    -- perche' non e' una misura di questa seduta: scritta in `threshold_hr`
    -- non si distingueva da una vera, e l'API dava 148 come "la soglia" di
    -- una sessione di arrampicata. Chi divide i minuti per zona usa
    -- `COALESCE(threshold_hr, threshold_hr_borrowed)`; chi mostra un numero
    -- misurato usa solo la prima.
    threshold_hr_borrowed INTEGER,
    workout_name      TEXT,
    workout_active_steps INTEGER,
    workout_active_max_s REAL,
    min_low_aerobic   REAL,
    min_high_aerobic  REAL,
    min_anaerobic     REAL,
    activity_name     TEXT,
    parsed_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_start_time ON activities(start_time);
CREATE INDEX IF NOT EXISTS idx_activities_sport ON activities(sport);

CREATE TABLE IF NOT EXISTS records (
    activity_id INTEGER NOT NULL REFERENCES activities(activity_id) ON DELETE CASCADE,
    ts_epoch    INTEGER NOT NULL,
    heart_rate  INTEGER,
    speed_kmh   REAL,
    altitude_m  REAL,
    cadence     INTEGER,
    power       INTEGER,
    lat         REAL,
    lon         REAL,
    distance_km REAL,
    equiv_speed_kmh REAL,
    PRIMARY KEY (activity_id, ts_epoch)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS laps (
    activity_id   INTEGER NOT NULL REFERENCES activities(activity_id) ON DELETE CASCADE,
    lap_index     INTEGER NOT NULL,
    intensity     TEXT,
    trigger       TEXT,
    time_s        REAL,
    distance_m    REAL,
    speed_kmh     REAL,
    avg_hr        INTEGER,
    max_hr        INTEGER,
    cadence       INTEGER,
    ascent_m      REAL,
    workout_step  INTEGER,
    PRIMARY KEY (activity_id, lap_index)
) WITHOUT ROWID;
"""

_RECORD_COLUMNS = (
    "heart_rate", "speed_kmh", "altitude_m", "cadence", "power", "lat", "lon", "distance_km", "equiv_speed_kmh",
)

# `cadence` e' quella del FIT, le falcate di una gamba al minuto: la cadenza
# di chi corre e' il doppio. Resta com'e' scritta, come nei record.
_LAP_COLUMNS = (
    "intensity", "trigger", "time_s", "distance_m", "speed_kmh", "avg_hr", "max_hr", "cadence",
    "ascent_m", "workout_step",
)


# Le colonne che un database costruito prima di loro non ha. `CREATE TABLE
# IF NOT EXISTS` non le aggiunge, e un `LOGIC_VERSION` nuovo costringerebbe a
# rileggere 979 file FIT per un dato che si calcola dalle righe gia' in
# tabella: tanto vale aggiungerle e riempirle (todo 54).
#
# Qui ci sta solo cio' che si **ricava** da quello che c'e' — i minuti per
# zona, i tetti prestati: per quelle il salto di `DERIVED_VERSION` le riempie
# in secondi. Una colonna che si legge dal FIT non puo' stare in questa lista,
# perche' nascerebbe vuota e nessuno la riempirebbe: quella vuole
# `LOGIC_VERSION` e un rebuild.
_ADDED_COLUMNS = {
    "min_low_aerobic": "REAL",
    "min_high_aerobic": "REAL",
    "min_anaerobic": "REAL",
    "hr_zone_bounds_borrowed": "TEXT",
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Le colonne di `_ADDED_COLUMNS` che la tabella non ha ancora."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(activities)")}
    for name, kind in _ADDED_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE activities ADD COLUMN {name} {kind}")


def _db_path(data_dir: Path) -> Path:
    return Path(data_dir) / "db" / DB_FILENAME


@contextmanager
def write_lock(data_dir: Path) -> Iterator[None]:
    """Una scrittura per volta sul database, **anche fra processi**.

    `sync()` e `sync_health()` scrivono lo stesso `activities.db`, e il
    lucchetto di `api/cache.py` e' per lettore: serve a non farli aspettare
    in lettura, e non impedisce niente in scrittura. Questo e' del file —
    quindi vive qui, non nella cache — ed e' un `flock` come quello dei
    lavori (`api/refresh._claim`): i thread dell'API e il comando lanciato a
    mano da un terminale sono processi diversi, e un lucchetto di soli thread
    non li avrebbe visti.

    Aspetta invece di rifiutare: le attese sono brevi. Un `sync()` sono
    millisecondi, e `rebuild()` lo prende solo per lo scambio finale, non per
    la mezz'ora di letture."""
    path = Path(data_dir) / "db" / WRITE_LOCK_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        handle.close()


def _stored_version(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM schema_meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _write_version(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def cache_state(data_dir: Path = DATA_DIR) -> dict:
    """Se la cache e' in pari, e se no perche'.

    `sync()` non ricostruisce piu' da se' (todo 93): una ricostruzione dura
    mezz'ora e partiva dentro la richiesta di chi apriva una pagina. Quando
    la versione non coincide si servono i dati che ci sono — che sono veri,
    solo calcolati con il codice di prima — e questa funzione dice perche'.

    **Il messaggio e' la meta' del lavoro**: dati vecchi serviti in silenzio
    sono la stessa bugia che `api/refresh.py` si rifiuta di raccontare sullo
    scaricamento mancato, e per lo stesso motivo arriva alla pagina.

    Guarda la tabella ogni volta, invece di ricordarsi cosa ha visto
    `sync()`: la prima stesura teneva il motivo in un dizionario di modulo, e
    il motivo non arrivava mai, perche' `api/cache.py` tiene il frame in
    memoria per un minuto e serviva senza passare da `sync()`. Costa una
    `SELECT`."""
    data_dir = Path(data_dir)
    conn = _connect(data_dir)
    try:
        stored = _stored_version(conn, _LOGIC_KEY)
        rows = conn.execute("SELECT count(*) FROM activities").fetchone()[0]
    finally:
        conn.close()
    if stored is None or not rows:
        return {
            "ok": False,
            "message": (
                "the cache is empty — run `make rebuild` to build it from the "
                "FIT files."
            ),
        }
    if stored != LOGIC_VERSION:
        return {
            "ok": False,
            "message": (
                f"the cache is at version {stored} and the code wants "
                f"{LOGIC_VERSION} — what you see is true, but computed with the "
                f"code from before. To rebuild it: `make rebuild`."
            ),
        }
    return {"ok": True, "message": None}


def _connect(data_dir: Path) -> sqlite3.Connection:
    return _connect_path(_db_path(data_dir))


def _connect_path(path: Path) -> sqlite3.Connection:
    """La connessione a un file preciso: il database vivo, o quello che si sta
    costruendo accanto (`rebuild`)."""
    # `db/` dal todo 65: sqlite il file lo crea, la cartella no.
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    _add_missing_columns(conn)
    return conn


def _local_to_epoch(ts) -> int:
    localized = pd.Timestamp(ts).tz_localize(LOCAL_TZ, ambiguous=False, nonexistent="shift_forward")
    return int(localized.timestamp())


def _clean(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value.item() if hasattr(value, "item") else value


def _insert_activity(conn: sqlite3.Connection, summary: dict, name: str | None, parsed_at: str) -> None:
    payload = dict(summary)
    payload["start_time"] = payload["start_time"].isoformat(sep=" ")
    payload["activity_name"] = name
    payload["parsed_at"] = parsed_at
    conn.execute(
        """
        INSERT INTO activities (
            activity_id, path, sport, sub_sport, start_time, total_distance_km,
            total_time_min, avg_heart_rate, max_heart_rate, avg_speed_kmh,
            total_calories, total_ascent_m, total_descent_m, vo2max, equiv_speed_kmh,
            aerobic_te, anaerobic_te, hr_zone_bounds, threshold_hr,
            workout_name, workout_active_steps, workout_active_max_s, activity_name, parsed_at
        ) VALUES (
            :activity_id, :path, :sport, :sub_sport, :start_time, :total_distance_km,
            :total_time_min, :avg_heart_rate, :max_heart_rate, :avg_speed_kmh,
            :total_calories, :total_ascent_m, :total_descent_m, :vo2max, :equiv_speed_kmh,
            :aerobic_te, :anaerobic_te, :hr_zone_bounds, :threshold_hr,
            :workout_name, :workout_active_steps, :workout_active_max_s, :activity_name, :parsed_at
        )
        ON CONFLICT(activity_id) DO UPDATE SET
            path=excluded.path, sport=excluded.sport, sub_sport=excluded.sub_sport,
            start_time=excluded.start_time, total_distance_km=excluded.total_distance_km,
            total_time_min=excluded.total_time_min, avg_heart_rate=excluded.avg_heart_rate,
            max_heart_rate=excluded.max_heart_rate, avg_speed_kmh=excluded.avg_speed_kmh,
            total_calories=excluded.total_calories, total_ascent_m=excluded.total_ascent_m,
            total_descent_m=excluded.total_descent_m, vo2max=excluded.vo2max,
            equiv_speed_kmh=excluded.equiv_speed_kmh,
            aerobic_te=excluded.aerobic_te, anaerobic_te=excluded.anaerobic_te,
            hr_zone_bounds=excluded.hr_zone_bounds, threshold_hr=excluded.threshold_hr,
            workout_name=excluded.workout_name, workout_active_steps=excluded.workout_active_steps,
            workout_active_max_s=excluded.workout_active_max_s,
            activity_name=excluded.activity_name,
            parsed_at=excluded.parsed_at
        """,
        payload,
    )


def _insert_records(conn: sqlite3.Connection, activity_id: int, records: pd.DataFrame) -> None:
    if records.empty:
        return
    rows = [
        (activity_id, _local_to_epoch(ts), *(_clean(getattr(r, col)) for col in _RECORD_COLUMNS))
        for ts, r in records.iterrows()
    ]
    conn.executemany(
        f"INSERT OR IGNORE INTO records (activity_id, ts_epoch, {', '.join(_RECORD_COLUMNS)}) "
        f"VALUES ({', '.join(['?'] * (2 + len(_RECORD_COLUMNS)))})",
        rows,
    )


def _insert_laps(conn: sqlite3.Connection, activity_id: int, laps: pd.DataFrame) -> None:
    """I giri di una seduta (todo 79). Senza timestamp: un giro e' un pezzo
    di seduta, e il suo posto lo da' `lap_index`."""
    if laps.empty:
        return
    rows = [
        (activity_id, int(lap.lap_index), *(_clean(getattr(lap, col)) for col in _LAP_COLUMNS))
        for lap in laps.itertuples()
    ]
    conn.executemany(
        f"INSERT OR IGNORE INTO laps (activity_id, lap_index, {', '.join(_LAP_COLUMNS)}) "
        f"VALUES ({', '.join(['?'] * (2 + len(_LAP_COLUMNS)))})",
        rows,
    )


def _parse_and_store_or_warn(
    conn: sqlite3.Connection, path: Path, names: dict, types: dict, parsed_at: str
) -> bool:
    """`_parse_and_store`, ma un file che non si legge si salta con un
    avviso invece di fermare tutto.

    Senza questo, un FIT illeggibile — un corpo troncato dentro uno zip
    valido, un file copiato a mano, una pagina di errore salvata col nome
    giusto — faceva alzare `sync()`, e quindi `list_activities()`, e quindi
    **ogni endpoint** dietro `api/cache.py`: 500 a ogni richiesta, per
    sempre, perche' il file non viene consumato e la riga della versione non
    avanza. L'unico rimedio era cancellarlo a mano, sapendo quale.

    Il file resta sul posto e al giro dopo si riprova: se nel frattempo e'
    stato riscaricato intero, entra. Un'attivita' in meno e' un danno
    piccolo e visibile; l'API giu' non lo e'."""
    try:
        return _parse_and_store(conn, path, names, types, parsed_at)
    except Exception as exc:
        print(f"  ATTENZIONE: {path.name} non si legge ({type(exc).__name__}: {exc}): lo salto.")
        return False


def _parse_and_store(
    conn: sqlite3.Connection, path: Path, names: dict, types: dict, parsed_at: str
) -> bool:
    summary = load_activity_summary(path)
    # Non e' una colonna: e' il nome di ripiego letto dal FIT (vedi
    # `fit.load_activity_summary`), e la riga lo prende solo se Garmin Connect
    # non ne ha uno suo.
    fit_name = summary.pop("fit_name", None)
    if summary["activity_id"] is None or summary["start_time"] is None:
        return False
    records = _parse_fit_records(path)
    activity_id = str(summary["activity_id"])
    summary["sport"] = sport_from_garmin_type(
        summary.get("sport"), types.get(activity_id), summary.get("sub_sport")
    )
    # Dai record gia' letti qui sopra: il FIT non si rilegge. Solo per gli
    # sport in cui il modello di costo ha senso; per gli altri resta vuota.
    # Se `sync()` riclassifica lo sport piu' tardi, questi valori (quello
    # dell'attivita' e quelli dei record) non si ricalcolano fino al prossimo
    # rebuild.
    # La velocita' equivalente e' una colonna in piu', non il dato: se il
    # modello di costo non si puo' applicare resta vuota, come per gli sport
    # che non lo prevedono. Alzava su un file che attraversa il cambio d'ora
    # d'autunno — l'indice locale torna indietro e `grade.rolling_mean`
    # pretende un indice crescente — e si portava via l'attivita' intera.
    with_equiv = summary["sport"] in EQUIV_SPEED_SPORTS
    summary["equiv_speed_kmh"] = None
    if with_equiv:
        try:
            summary["equiv_speed_kmh"] = equivalent_speed_kmh(records, summary["avg_speed_kmh"])
        except Exception as exc:
            print(f"  {path.name}: velocita' equivalente non calcolata ({exc}).")
    if not records.empty:
        records["equiv_speed_kmh"] = None
        if with_equiv and records["altitude_m"].notna().any():
            try:
                records["equiv_speed_kmh"] = equivalent_speed_series(records)
            except Exception as exc:
                print(f"  {path.name}: serie della velocita' equivalente non calcolata ({exc}).")
    _insert_activity(conn, summary, names.get(activity_id) or fit_name, parsed_at)
    _insert_records(conn, summary["activity_id"], records)
    _insert_laps(conn, summary["activity_id"], _parse_fit_laps(path))
    return True


# Il profilo Bici dell'orologio calcola le zone sulla FC massima e non salva
# la soglia anaerobica, e senza soglia la scheda non stima gli effetti
# (`run_chart.has_effects`). Alle attivita' che hanno le zone ma non la soglia
# (o l'hanno a zero, come le escursioni e alcune corse) si da' quella
# dell'ultima corsa prima di loro che ne ha una vera. Se prima non ce n'e'
# (l'orologio salva soglie vere solo dall'11/09/2026), quella della prima corsa
# dopo. Solo dalla data qui sotto in poi, per scelta di Andrea: lo storico piu'
# vecchio resta com'e' nel FIT.
THRESHOLD_FALLBACK_FROM = "2026-08-01"


def _zone_minutes(conn: sqlite3.Connection, activity_id: int) -> tuple[float, float, float] | None:
    """I minuti passati nelle tre fasce di sforzo di Garmin — basso aerobico,
    alto aerobico, anaerobico — da `records` (todo 54).

    I confini sono quelli **di quella seduta**, non quelli di oggi: una
    soglia alzata a settembre non deve riscrivere i minuti di agosto. Dove la
    seduta non li ha misurati valgono quelli prestati dalla corsa piu' vicina
    (`_lend_zone_settings`), che e' una sola per entrambi. Basso aerobico fino
    alla cima della terza zona, alto aerobico fino alla soglia, anaerobico
    oltre — gli stessi tagli di `daily_data._hr_zones`.

    Quanto vale ogni campione lo dice `grade.sample_seconds`, **la stessa
    regola di `run_chart.effects`**: fino al campione dopo, e un secondo solo
    attraverso una pausa. Prima qui c'era un conto suo — ogni buco valeva
    fino a un tetto di 30 secondi — e i due non andavano d'accordo: su 8
    delle 12 sedute recenti con le zone i numeri erano diversi, 16.1 minuti
    contro 12.1 di basso aerobico sulla stessa uscita. La Day leggeva
    `effects()` e la Week queste colonne, quindi due card dicevano cose
    diverse della stessa seduta, e la fascia delle dodici settimane era
    costruita sull'altra convenzione.

    `None` quando la seduta non ha frequenza cardiaca, zone o soglia: e' un
    dato che manca, e scriverci zero direbbe un'altra cosa. Lo storico
    prima di `THRESHOLD_FALLBACK_FROM` resta senza, perche' la soglia non
    si retrodata — sono 926 sedute su 979, tutte anteriori ad agosto 2026,
    e la Week guarda dodici settimane."""
    row = conn.execute(
        "SELECT COALESCE(hr_zone_bounds, hr_zone_bounds_borrowed), "
        "COALESCE(threshold_hr, threshold_hr_borrowed) "
        "FROM activities WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if not row or not row[0] or not row[1]:
        return None
    bounds = json.loads(row[0])
    threshold = row[1]
    if len(bounds) < 3:
        return None
    low_top = bounds[2]
    samples = conn.execute(
        "SELECT ts_epoch, heart_rate FROM records WHERE activity_id = ? ORDER BY ts_epoch",
        (activity_id,),
    ).fetchall()
    if len(samples) < 2:
        return None
    index = pd.to_datetime([epoch for epoch, _ in samples], unit="s")
    seconds = [0.0, 0.0, 0.0]
    for (_, heart_rate), span in zip(samples, sample_seconds(index)):
        if heart_rate is None:
            continue
        if heart_rate <= low_top:
            seconds[0] += span
        elif heart_rate <= threshold:
            seconds[1] += span
        else:
            seconds[2] += span
    if not any(seconds):
        return None
    return tuple(round(s / 60, 1) for s in seconds)


def _store_zone_minutes(conn: sqlite3.Connection, activity_id: int) -> bool:
    """Scrive i minuti per zona di una seduta. Falso se non si possono
    calcolare."""
    minutes = _zone_minutes(conn, activity_id)
    if minutes is None:
        return False
    conn.execute(
        "UPDATE activities SET min_low_aerobic = ?, min_high_aerobic = ?, min_anaerobic = ? "
        "WHERE activity_id = ?",
        (*minutes, activity_id),
    )
    return True


def fill_zone_minutes(data_dir: Path = DATA_DIR, force: bool = False) -> tuple[int, int]:
    """Riempie i minuti per zona delle sedute che non li hanno (todo 54).
    Rende quante ne ha fatte e quante sono rimaste senza.

    Gira dopo ogni `sync()`, come `_lend_zone_settings`, cosi' le
    sedute nuove li hanno senza che nessuno ci pensi; da terminale
    (`make backfill_zones`) serve a rifare lo storico, e con `force` a
    ricalcolare tutto quando il modo di contarli cambia."""
    conn = _connect(data_dir)
    try:
        done, missing = _fill_zone_minutes(conn, force)
        conn.commit()
        return done, missing
    finally:
        conn.close()


def _fill_zone_minutes(conn: sqlite3.Connection, force: bool = False) -> tuple[int, int]:
    where = "" if force else "WHERE min_low_aerobic IS NULL"
    ids = [r[0] for r in conn.execute(f"SELECT activity_id FROM activities {where}")]
    done = sum(_store_zone_minutes(conn, activity_id) for activity_id in ids)
    return done, len(ids) - done


# La corsa che puo' prestare: una che ha **misurato** sia i tetti delle zone
# sia la soglia. Una riga che li aveva ricevuti in prestito faceva da
# donatrice alla successiva, e il risultato dipendeva dall'ordine in cui le
# righe venivano riempite.
_DONOR = """
    SELECT run.activity_id FROM activities AS run
    WHERE run.sport = 'running' AND run.threshold_hr > 0
      AND run.hr_zone_bounds IS NOT NULL
      AND run.start_time {order_sign} target.start_time
    ORDER BY run.start_time {order} LIMIT 1
"""


def _lend_zone_settings(conn: sqlite3.Connection) -> None:
    """Presta i tetti delle zone e la soglia anaerobica alle sedute che non li
    hanno: quelli dell'ultima corsa precedente che li ha misurati, o in
    mancanza della prima successiva, da THRESHOLD_FALLBACK_FROM in poi. Gira
    dopo ogni rebuild e sync, cosi' vale anche per i file nuovi e per gli
    sport riclassificati.

    **Vanno in colonne a parte** (`threshold_hr_borrowed`,
    `hr_zone_bounds_borrowed`), non in quelle misurate. Scritta nella stessa
    colonna di una soglia misurata non si distingueva piu' da lei: 32
    attivita' non di corsa portavano una soglia da corsa come se fosse loro,
    `GET /api/activities/<id>` dava 148 come soglia di una sessione di
    arrampicata e 154 per una camminata al tapis roulant con le zone della
    bici, e sedici escursioni di agosto portavano una soglia di settembre —
    mentre `_zone_minutes` promette che "una soglia alzata a settembre non
    deve riscrivere i minuti di agosto".

    **I due valori vengono dalla stessa seduta donatrice**, e non e' un
    dettaglio: i tetti del profilo Bici sono calcolati sulla frequenza
    massima, quelli del profilo Corsa sulla soglia. Mescolare il tetto di Z3
    di un profilo con la soglia di un altro puo' dare un tetto **sopra** la
    soglia, cioe' una fascia alta aerobica vuota in `_zone_minutes` e nessun
    effetto stimato in `run_chart.has_effects`.

    **Si azzera e si rifa' da se'.** E' un valore derivato, e un giro derivato
    che non sa togliere non e' un giro derivato: se la corsa donatrice sparisse
    dall'archivio, il prestito che le sopravvive resterebbe li' per sempre.

    Che li riceva qualunque sport e che si possa guardare avanti nel tempo
    sono invece scelte: il profilo Bici non salva la soglia, un FIT che non
    viene da Garmin non salva nemmeno le zone, e l'orologio salva soglie vere
    solo dall'11/09/2026 (vedi `THRESHOLD_FALLBACK_FROM`)."""
    conn.execute(
        "UPDATE activities SET threshold_hr_borrowed = NULL, hr_zone_bounds_borrowed = NULL"
    )
    conn.execute(
        f"""
        UPDATE activities AS target
           SET threshold_hr_borrowed = CASE
                   WHEN target.threshold_hr IS NULL OR target.threshold_hr = 0
                   THEN donor.threshold_hr
               END,
               hr_zone_bounds_borrowed = CASE
                   WHEN target.hr_zone_bounds IS NULL
                   THEN donor.hr_zone_bounds
               END
          FROM activities AS donor
         WHERE target.start_time >= ?
           AND (
                 target.threshold_hr IS NULL OR target.threshold_hr = 0
                 OR target.hr_zone_bounds IS NULL
               )
           AND donor.activity_id = COALESCE(
                 ({_DONOR.format(order_sign="<", order="DESC")}),
                 ({_DONOR.format(order_sign=">", order="ASC")})
               )
        """,
        (THRESHOLD_FALLBACK_FROM,),
    )


def _paths_to_parse(conn: sqlite3.Connection, data_dir: Path) -> list[Path]:
    """I FIT che la cache non ha ancora, nell'ordine in cui stanno su disco.

    **Due chiavi, perche' non tutti i file portano l'id nel nome.** Quelli di
    Garmin si riconoscono dal nome, e questo e' il punto: sapere che un file
    e' gia' dentro senza aprirlo, perche' aprirlo e' un secondo di parsing a
    testa (vedi la nota in testa al modulo). Gli altri — l'esportazione di
    MyWhoosh, un file portato a mano — l'id lo hanno solo dentro, e per loro
    la chiave e' il percorso, che la tabella conserva in `path`.

    Senza il controllo sul percorso un file senza id nel nome sarebbe stato
    riletto a **ogni** sync, cioe' a ogni apertura di una pagina dopo che la
    cache di `api/cache.py` e' scaduta: `activity_id_from_path` rende None, e
    None non e' mai fra gli id in tabella."""
    ids = {r[0] for r in conn.execute("SELECT activity_id FROM activities")}
    paths = {r[0] for r in conn.execute("SELECT path FROM activities")}
    pending = []
    for path in list_activity_files(data_dir):
        activity_id = activity_id_from_path(path)
        known = activity_id in ids if activity_id is not None else str(path) in paths
        if not known:
            pending.append(path)
    return pending


# Ogni quante attivita' si chiude una transazione durante la ricostruzione.
# Cento sono circa un decimo del lavoro: il giornale non cresce a dismisura, e
# un'interruzione lascia su disco quello che era stato letto.
REBUILD_BATCH = 100


def rebuild(data_dir: Path = DATA_DIR, say=print) -> int:
    """Rifa' la cache da tutti i FIT di `data_dir`. Rende quante attivita' ha
    letto in questo giro.

    **Costruisce accanto e scambia alla fine** (todo 93). Prima cancellava il
    database vivo e ci rileggeva dentro per mezz'ora: in quella mezz'ora ogni
    richiesta leggeva un file che non c'era o che non era finito, e
    un'interruzione lasciava un archivio a meta'. Adesso il lavoro va in
    `activities.db.new`, e solo quando e' finito un `os.replace` — atomico —
    lo mette al posto del vecchio: chi legge vede il vecchio o il nuovo, mai
    una via di mezzo. E' la stessa politica di `garmin/files.py`.

    **Si commette a pezzi** (`REBUILD_BATCH`), e un file accanto rimasto a
    meta' si riprende invece di ricominciare: le attivita' che ci sono gia'
    non si rileggono. Un `rebuild` che riparte da zero si ottiene cancellando
    `activities.db.new`.

    **Non la chiama nessuna richiesta**: la chiama `make rebuild`. Il servizio
    puo' restare accesso, e serve i dati vecchi finche' lo scambio non
    avviene (vedi `cache_state`)."""
    data_dir = Path(data_dir)
    target = _db_path(data_dir)
    building = target.with_name(target.name + ".new")

    conn = _connect_path(building)
    try:
        names = load_activity_names(data_dir)
        types = load_activity_types(data_dir)
        parsed_at = datetime.now().isoformat(sep=" ")
        done = conn.execute("SELECT count(*) FROM activities").fetchone()[0]
        if done:
            say(f"  {building.name} c'era gia': riprendo, {done} attivita' sono a posto")
        paths = _paths_to_parse(conn, data_dir)
        count = 0
        for index, path in enumerate(paths, 1):
            count += _parse_and_store_or_warn(conn, path, names, types, parsed_at)
            if index % REBUILD_BATCH == 0:
                conn.commit()
                say(f"  ...{index}/{len(paths)} letti")
        # Il nastro vince su tutto, anche su un tipo di Connect che dice
        # "running": lo `sub_sport` del FIT e' il solo segnale che c'e' sempre
        # (vedi `sport_from_garmin_type`). Questo UPDATE e' anche quello che
        # riclassifica lo storico dopo il todo 45, senza un rebuild: il
        # `sub_sport` e' gia' in tabella, e rileggere 978 file FIT per
        # ricavarne un dato che c'e' gia' non avrebbe senso. La velocita'
        # equivalente in piano va via con lo sport: il modello di costo vale
        # per chi si muove sul terreno, non per chi sta fermo su un nastro.
        conn.execute(
            "UPDATE activities SET sport='treadmill', equiv_speed_kmh=NULL "
            "WHERE sub_sport='treadmill'"
        )
        _lend_zone_settings(conn)
        _fill_zone_minutes(conn)
        _write_version(conn, _LOGIC_KEY, LOGIC_VERSION)
        _write_version(conn, _DERIVED_KEY, DERIVED_VERSION)
        conn.commit()
    finally:
        conn.close()

    # Lo scambio. `conn.close()` ha chiuso il giornale del file nuovo, quindi
    # quello che segue e' un file solo; il giornale del vecchio non vale piu'
    # per il file che prende il suo posto e va via con lui.
    with write_lock(data_dir):
        os.replace(building, target)
        for suffix in ("-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)
    say(f"  fatta: {count} attivita' lette, cache alla versione {LOGIC_VERSION}")
    return count


def refresh_derived(conn: sqlite3.Connection) -> None:
    """Rifa' i conti che si ricavano dalle righe in tabella, senza toccare i
    file: la soglia prestata e i minuti per zona (todo 93).

    E' la scorciatoia che non c'era: due delle tre correzioni del 2 novembre
    2026 cambiavano solo questi, e sono costate mezz'ora di ricostruzione
    ciascuna. Misurato sull'archivio: 0.2 secondi su 986 attivita'.

    **Si azzera prima di rifare**, i prestiti e i minuti per zona. Il
    prestito se ne occupa da se' (`_lend_zone_settings`); qui restano i minuti
    per zona, che `_store_zone_minutes` non mette mai a NULL: senza
    l'azzeramento un valore che non si puo' piu' calcolare — perche' la soglia
    che lo rendeva possibile e' sparita — resterebbe in tabella per sempre, e
    un giro derivato che non sa togliere non e' un giro derivato."""
    _lend_zone_settings(conn)
    conn.execute(
        "UPDATE activities SET min_low_aerobic = NULL, min_high_aerobic = NULL, "
        "min_anaerobic = NULL"
    )
    _fill_zone_minutes(conn, force=True)


def sync(data_dir: Path = DATA_DIR) -> int:
    """Legge e mette in cache i soli FIT che non ci sono ancora (quali, lo
    dice `_paths_to_parse`: per id quando il nome del file lo porta, per
    percorso quando no — in nessuno dei due casi si apre un file che c'e'
    gia'), e rinfresca i nomi dai JSON.

    **Non ricostruisce** (todo 93). Se `LOGIC_VERSION` non coincide con
    quella in tabella non si puo' fare niente di utile — le righe sono state
    calcolate con un altro codice, e aggiungerne di nuove mescolerebbe i due
    — quindi si lascia tutto com'e', si scrive il motivo in `cache_state()` e
    si rende zero. La ricostruzione la chiede una persona: `make rebuild`.
    Prima partiva da qui, cioe' dentro la richiesta di chi apriva una pagina:
    mezz'ora di attesa e il database cancellato nel frattempo.

    Se e' `DERIVED_VERSION` a non coincidere, i conti che si ricavano dalle
    righe si rifanno subito (`refresh_derived`): sono secondi."""
    data_dir = Path(data_dir)
    with write_lock(data_dir):
        return _sync_locked(data_dir)


def _sync_locked(data_dir: Path) -> int:
    conn = _connect(data_dir)
    try:
        stored = _stored_version(conn, _LOGIC_KEY)
        rows = conn.execute("SELECT count(*) FROM activities").fetchone()[0]
        if stored is None or not rows or stored != LOGIC_VERSION:
            # Niente di utile da fare: le righe vengono da un altro codice, e
            # aggiungerne di nuove mescolerebbe i due. Il motivo lo dice
            # `cache_state()`, che lo rilegge da se'.
            return 0

        new_paths = _paths_to_parse(conn, data_dir)

        names = load_activity_names(data_dir)
        types = load_activity_types(data_dir)
        parsed_at = datetime.now().isoformat(sep=" ")
        added = sum(
            _parse_and_store_or_warn(conn, p, names, types, parsed_at) for p in new_paths
        )

        conn.executemany(
            "UPDATE activities SET activity_name=? WHERE activity_id=?",
            [(name, int(activity_id)) for activity_id, name in names.items()],
        )
        # Anche il tipo puo' cambiare dopo il download (attivita' riclassificata
        # su Garmin Connect), quindi si aggiorna a ogni sync come il nome: un
        # tipo che mappiamo vale su qualunque riga, uno sconosciuto solo dove
        # il FIT non sapeva lo sport.
        conn.executemany(
            "UPDATE activities SET sport=? WHERE activity_id=?",
            [
                (GARMIN_TYPE_TO_SPORT[type_key], int(activity_id))
                for activity_id, type_key in types.items()
                if type_key in GARMIN_TYPE_TO_SPORT
            ],
        )
        conn.executemany(
            "UPDATE activities SET sport=? WHERE activity_id=? AND sport IN ('generic', '')",
            [
                (type_key, int(activity_id))
                for activity_id, type_key in types.items()
                if type_key and type_key not in GARMIN_TYPE_TO_SPORT
            ],
        )
        # Il nastro vince su tutto, anche su un tipo di Connect che dice
        # "running": lo `sub_sport` del FIT e' il solo segnale che c'e' sempre
        # (vedi `sport_from_garmin_type`). Questo UPDATE e' anche quello che
        # riclassifica lo storico dopo il todo 45, senza un rebuild: il
        # `sub_sport` e' gia' in tabella, e rileggere 978 file FIT per
        # ricavarne un dato che c'e' gia' non avrebbe senso. La velocita'
        # equivalente in piano va via con lo sport: il modello di costo vale
        # per chi si muove sul terreno, non per chi sta fermo su un nastro.
        conn.execute(
            "UPDATE activities SET sport='treadmill', equiv_speed_kmh=NULL "
            "WHERE sub_sport='treadmill'"
        )
        if _stored_version(conn, _DERIVED_KEY) != DERIVED_VERSION:
            refresh_derived(conn)
            _write_version(conn, _DERIVED_KEY, DERIVED_VERSION)
        else:
            _lend_zone_settings(conn)
            _fill_zone_minutes(conn)
        conn.commit()
        return added
    finally:
        conn.close()


def list_activities(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    data_dir = Path(data_dir)
    sync(data_dir)
    conn = _connect(data_dir)
    try:
        df = pd.read_sql_query("SELECT * FROM activities ORDER BY start_time DESC", conn)
    finally:
        conn.close()
    # Anche a zero righe, cioe' prima del primo `make update_activity`: senza
    # la conversione la colonna resta di tipo `object`, e i dodici posti che
    # fanno `start_time.dt.date` alzavano `AttributeError`. In pratica
    # `/api/activities`, `/api/daily/<giorno>` e `/api/weekly/<lunedi>`
    # rispondevano 500 su una cartella dati vuota, mentre `/api/sports`,
    # `/api/plans` e gli altri rispondevano 200 con la lista vuota: il primo
    # avvio di una installazione nuova sembrava un guasto.
    df["start_time"] = pd.to_datetime(df["start_time"])
    _add_terrain(df, data_dir)
    _add_run_type(df, data_dir)
    return df


def _add_terrain(df: pd.DataFrame, data_dir: Path) -> None:
    """Le colonne `terrain` e `terrain_source` (todo 35): la correzione di
    Andrea se c'e', altrimenti la stima di `terrain.guess_terrain`. Non stanno
    nel database: si calcolano qui a ogni lettura, e le correzioni vengono da
    `activity_terrain.json`, che sopravvive a rebuild()."""
    types = load_activity_types(data_dir)
    overrides = load_terrain_overrides(data_dir)
    terrains, sources = [], []
    for row in df.itertuples(index=False):
        key = str(row.activity_id)
        garmin_type = types.get(key)
        if not has_terrain(row.sport):
            terrains.append(None)
            sources.append(None)
        elif key in overrides:
            terrains.append(overrides[key])
            sources.append("user")
        else:
            terrains.append(
                guess_terrain(row.sport, row.sub_sport, garmin_type, row.total_distance_km, row.total_ascent_m)
            )
            sources.append("guess")
    df["terrain"] = pd.Series(terrains, index=df.index, dtype=object)
    df["terrain_source"] = pd.Series(sources, index=df.index, dtype=object)


def _add_run_type(df: pd.DataFrame, data_dir: Path) -> None:
    """Le colonne `run_type` e `run_type_source` (todo 36), come
    `_add_terrain`: la correzione di Andrea se c'e', altrimenti la stima di
    `run_type.guess_run_type` dall'allenamento salvato e dalla durata. Le
    correzioni vengono da `activity_run_type.json`, che sopravvive a
    rebuild()."""
    overrides = load_run_type_overrides(data_dir)
    run_types, sources = [], []
    for row in df.itertuples(index=False):
        key = str(row.activity_id)
        if not has_run_type(row.sport):
            run_types.append(None)
            sources.append(None)
        elif key in overrides:
            run_types.append(overrides[key])
            sources.append("user")
        else:
            run_types.append(
                guess_run_type(
                    row.sport,
                    row.total_time_min,
                    row.workout_name,
                    row.workout_active_steps,
                    row.workout_active_max_s,
                )
            )
            sources.append("guess")
    df["run_type"] = pd.Series(run_types, index=df.index, dtype=object)
    df["run_type_source"] = pd.Series(sources, index=df.index, dtype=object)


def load_activity_records(
    activity_id: int, data_dir: Path = DATA_DIR, columns: tuple[str, ...] | None = None
) -> pd.DataFrame:
    """I campioni di una seduta, con l'ora locale come indice.

    `columns` chiede solo quelle che servono. La tabella ne ha una trentina,
    e chi deve contare i minuti sopra una zona ne usa una: leggerle tutte
    costava quattro volte tanto (31.9 ms contro 8.1 su una seduta di 5000
    campioni), e la scansione della seduta impegnativa ne legge fino a
    diciotto in fila.

    La conversione dei tempi e' vettoriale e non riga per riga: su 40.000
    campioni 2.1 ms invece di 38.3, e il risultato e' lo stesso — provato su
    un campione casuale dell'archivio, cambi d'ora compresi."""
    data_dir = Path(data_dir)
    what = "*" if columns is None else ", ".join(("ts_epoch", *columns))
    conn = _connect(data_dir)
    try:
        df = pd.read_sql_query(
            f"SELECT {what} FROM records WHERE activity_id=? ORDER BY ts_epoch",
            conn,
            params=(int(activity_id),),
        )
    finally:
        conn.close()
    # `astype("datetime64[us]")` perche' la conversione riga per riga, che
    # passava da `datetime` di Python, dava un indice al microsecondo e questa
    # lo darebbe al secondo: gli istanti sono gli stessi, ma la risoluzione si
    # vede a valle (le differenze fra campioni, i grafici), e qui non deve
    # cambiare niente.
    df["timestamp"] = (
        pd.to_datetime(df["ts_epoch"], unit="s", utc=True)
        .dt.tz_convert(LOCAL_TZ)
        .dt.tz_localize(None)
        .astype("datetime64[us]")
    )
    extra = [c for c in ("activity_id", "ts_epoch") if c in df.columns]
    return df.drop(columns=extra).set_index("timestamp")


def load_activity_laps(activity_id: int, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """I giri di una seduta, nell'ordine in cui sono stati corsi (todo 79).
    Vuoto per chi non ne ha: le sedute in palestra, e quelle vecchie finche'
    il database non e' stato ricostruito."""
    data_dir = Path(data_dir)
    conn = _connect(data_dir)
    try:
        df = pd.read_sql_query(
            "SELECT * FROM laps WHERE activity_id=? ORDER BY lap_index",
            conn,
            params=(int(activity_id),),
        )
    finally:
        conn.close()
    return df.drop(columns=["activity_id"])
