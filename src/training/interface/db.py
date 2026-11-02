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

import json
import sqlite3
from datetime import datetime
from pathlib import Path

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
from training.interface.grade import EQUIV_SPEED_SPORTS, equivalent_speed_kmh, equivalent_speed_series
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

# Bump when parsing/derivation logic changes (e.g. the UTC->local timezone
# fix): sync() compares this against the value stored in schema_meta and
# transparently triggers a full rebuild() when they differ, instead of
# silently serving rows computed under old logic.
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
LOGIC_VERSION = "9"

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
    threshold_hr      INTEGER,
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
# rileggere 979 file FIT per un dato che si calcola dai record gia' in
# tabella: tanto vale aggiungerle e riempirle (todo 54).
_ADDED_COLUMNS = {
    "min_low_aerobic": "REAL",
    "min_high_aerobic": "REAL",
    "min_anaerobic": "REAL",
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Le colonne di `_ADDED_COLUMNS` che la tabella non ha ancora."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(activities)")}
    for name, kind in _ADDED_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE activities ADD COLUMN {name} {kind}")


def _db_path(data_dir: Path) -> Path:
    return Path(data_dir) / "db" / DB_FILENAME


def _connect(data_dir: Path) -> sqlite3.Connection:
    # `db/` dal todo 65: sqlite il file lo crea, la cartella no.
    path = _db_path(data_dir)
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


def _epoch_to_local(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=LOCAL_TZ).replace(tzinfo=None)


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


def _parse_and_store(
    conn: sqlite3.Connection, path: Path, names: dict, types: dict, parsed_at: str
) -> bool:
    summary = load_activity_summary(path)
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
    with_equiv = summary["sport"] in EQUIV_SPEED_SPORTS
    summary["equiv_speed_kmh"] = (
        equivalent_speed_kmh(records, summary["avg_speed_kmh"]) if with_equiv else None
    )
    if not records.empty:
        records["equiv_speed_kmh"] = (
            equivalent_speed_series(records)
            if with_equiv and records["altitude_m"].notna().any()
            else None
        )
    _insert_activity(conn, summary, names.get(activity_id), parsed_at)
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


# Oltre mezzo minuto fra due campioni non e' tempo allenato ma una pausa o
# un buco di registrazione: il campione vale per l'intervallo che lo segue,
# fino a questo tetto. Sulle corse la somma delle tre zone torna al minuto
# con la durata della seduta; sul giro di nove ore del 17 ottobre resta
# sotto di un'ora e mezza, che sono le soste.
ZONE_GAP_CAP_SECONDS = 30


def _zone_minutes(conn: sqlite3.Connection, activity_id: int) -> tuple[float, float, float] | None:
    """I minuti passati nelle tre fasce di sforzo di Garmin — basso aerobico,
    alto aerobico, anaerobico — da `records` (todo 54).

    I confini sono quelli **di quella seduta** (`hr_zone_bounds`,
    `threshold_hr`), non quelli di oggi: una soglia alzata a settembre non
    deve riscrivere i minuti di agosto. Basso aerobico fino alla cima della
    terza zona, alto aerobico fino alla soglia, anaerobico oltre — gli stessi
    tagli di `daily_data._hr_zones`.

    `None` quando la seduta non ha frequenza cardiaca, zone o soglia: e' un
    dato che manca, e scriverci zero direbbe un'altra cosa. Lo storico
    prima di `THRESHOLD_FALLBACK_FROM` resta senza, perche' la soglia non
    si retrodata — sono 926 sedute su 979, tutte anteriori ad agosto 2026,
    e la Week guarda dodici settimane."""
    row = conn.execute(
        "SELECT hr_zone_bounds, threshold_hr FROM activities WHERE activity_id = ?",
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
    seconds = [0.0, 0.0, 0.0]
    for (start, heart_rate), (nxt, _) in zip(samples, samples[1:]):
        if heart_rate is None:
            continue
        span = min(nxt - start, ZONE_GAP_CAP_SECONDS)
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

    Gira dopo ogni `sync()`, come `_fill_missing_thresholds`, cosi' le
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


def _fill_missing_thresholds(conn: sqlite3.Connection) -> None:
    """La soglia dell'ultima corsa precedente (o, in mancanza, della prima
    successiva) alle attivita' senza soglia o con soglia zero, da
    THRESHOLD_FALLBACK_FROM in poi. Gira dopo ogni rebuild e sync, cosi' vale
    anche per i file nuovi e per gli sport riclassificati."""
    conn.execute(
        """
        UPDATE activities SET threshold_hr = COALESCE(
            (
                SELECT run.threshold_hr FROM activities AS run
                WHERE run.sport = 'running' AND run.threshold_hr > 0
                  AND run.start_time < activities.start_time
                ORDER BY run.start_time DESC LIMIT 1
            ),
            (
                SELECT run.threshold_hr FROM activities AS run
                WHERE run.sport = 'running' AND run.threshold_hr > 0
                  AND run.start_time > activities.start_time
                ORDER BY run.start_time LIMIT 1
            )
        )
        WHERE (threshold_hr IS NULL OR threshold_hr = 0) AND hr_zone_bounds IS NOT NULL AND start_time >= ?
        """,
        (THRESHOLD_FALLBACK_FROM,),
    )


def rebuild(data_dir: Path = DATA_DIR) -> int:
    """Drop and repopulate the cache from every .fit file in data_dir.
    Used after a parsing-logic change (LOGIC_VERSION bump) or on first run."""
    data_dir = Path(data_dir)
    db_path = _db_path(data_dir)
    db_path.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)

    conn = _connect(data_dir)
    try:
        names = load_activity_names(data_dir)
        types = load_activity_types(data_dir)
        parsed_at = datetime.now().isoformat(sep=" ")
        count = sum(
            _parse_and_store(conn, p, names, types, parsed_at) for p in list_activity_files(data_dir)
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
        _fill_missing_thresholds(conn)
        _fill_zone_minutes(conn)
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('logic_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (LOGIC_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()
    return count


def sync(data_dir: Path = DATA_DIR) -> int:
    """Parse and cache only .fit files not yet in the DB (by activity_id,
    read cheaply from the filename, no FIT parse needed). Also refreshes
    activity_name for already-cached rows from activity_names.json. Falls
    back to a full rebuild() if the cache predates the current
    LOGIC_VERSION."""
    data_dir = Path(data_dir)
    conn = _connect(data_dir)
    try:
        row = conn.execute("SELECT value FROM schema_meta WHERE key='logic_version'").fetchone()
        if row is None or row[0] != LOGIC_VERSION:
            conn.close()
            return rebuild(data_dir)

        existing_ids = {r[0] for r in conn.execute("SELECT activity_id FROM activities")}
        new_paths = [p for p in list_activity_files(data_dir) if activity_id_from_path(p) not in existing_ids]

        names = load_activity_names(data_dir)
        types = load_activity_types(data_dir)
        parsed_at = datetime.now().isoformat(sep=" ")
        added = sum(_parse_and_store(conn, p, names, types, parsed_at) for p in new_paths)

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
        _fill_missing_thresholds(conn)
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
