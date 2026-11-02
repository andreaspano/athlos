"""Cache SQLite delle metriche giornaliere di salute (`health_daily`).

La tabella sta in `activities.db`, accanto ad `activities`, ma si costruisce
dai JSON di `DATA_DIR/health/` come `activities` si costruisce dai `.fit`: i
JSON restano la fonte, e la tabella si puo' sempre buttare e rifare. Il
parsing e' in `health.py`; qui c'e' solo la cache, separata da `db.py` perche'
le due restino indipendenti: un cambio al parsing della salute svuota
`health_daily` e basta, senza rileggere i FIT.

Un `rebuild()` dei FIT cancella invece il file intero, tabella compresa: va
bene, il primo `sync_health()` dopo la riempie di nuovo dai JSON.

NULL vuol dire "non lo sappiamo", mai zero: lo stesso contratto di
`health._dig()`.
"""

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from training.garmin.config import DATA_DIR
from training.interface.db import _connect as _connect_db
from training.interface.health import (
    COLUMNS,
    TEXT_COLUMNS,
    _USED_ENDPOINTS,
    _day_row,
)

# Da cambiare quando cambia il parsing della salute in `health.py`:
# `sync_health()` lo confronta con quello in `schema_meta` (chiave
# `health_logic_version`, separata da `logic_version` dei FIT) e, se sono
# diversi, butta `health_daily` e la rifa' dai JSON.
#
# "2": colonne `endurance_score`, `endurance_level` e `hill_score` (todo
# 38). La tabella si ricrea (DROP, non DELETE): `CREATE TABLE IF NOT EXISTS`
# non aggiunge colonne a una tabella che c'e' gia'.
#
# "3": la readiness del risveglio e' la **prima per ora dell'orologio** e non
# la prima della lista (`health._readiness_score`). Senza alzare questo
# numero la tabella continuerebbe a servire i tredici giorni sbagliati: i
# file su disco non sono cambiati, quindi nessun mtime dice di rileggerli.
HEALTH_LOGIC_VERSION = "3"

_VERSION_KEY = "health_logic_version"


def _column_type(name: str) -> str:
    return "TEXT" if name in TEXT_COLUMNS else "REAL"


_HEALTH_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS health_daily (\n"
    "    day TEXT PRIMARY KEY,\n"
    + "".join(f"    {name} {_column_type(name)},\n" for name in COLUMNS)
    + "    source_mtime REAL NOT NULL,\n"
    "    parsed_at TEXT NOT NULL\n"
    ") WITHOUT ROWID;\n"
)

_UPSERT = (
    f"INSERT INTO health_daily (day, {', '.join(COLUMNS)}, source_mtime, parsed_at) "
    f"VALUES (:day, {', '.join(':' + name for name in COLUMNS)}, :source_mtime, :parsed_at) "
    "ON CONFLICT(day) DO UPDATE SET "
    + ", ".join(f"{name}=excluded.{name}" for name in [*COLUMNS, "source_mtime", "parsed_at"])
)


def _connect(data_dir: Path) -> sqlite3.Connection:
    """La connessione di `db.py`, con in piu' la tabella della salute."""
    conn = _connect_db(data_dir)
    conn.executescript(_HEALTH_SCHEMA)
    return conn


def _source_mtimes(health_dir: Path) -> dict[str, float]:
    """Per ogni giorno con almeno un file, l'mtime piu' recente fra i suoi
    undici: **una scansione sola** delle cartelle degli endpoint.

    Fa il lavoro di `available_days` e quello di un `stat` per ognuno degli
    undici file di ogni giorno, che messi insieme erano la parte lenta di
    `sync_health`: su 6150 giorni, undici `glob` piu' 67.650 `Path.stat()`.
    Misurato sull'archivio vero: **799 ms prima, 190 adesso**. Conta perche'
    questo e' il costo della prima richiesta dopo ogni minuto di cache
    (`api/cache.py`), e il lock della salute resta preso per tutta la
    scansione, quindi ogni richiesta che capita li' aspetta.

    `os.scandir` da' il nome senza chiedere niente al disco e `entry.stat()`
    riusa la voce di directory; `follow_symlinks=False` evita di risolvere
    link che qui non ci sono. I nomi che non sono una data si saltano, come
    faceva `available_days`: un file che non si chiama come un giorno non e'
    un giorno."""
    out: dict[str, float] = {}
    unreadable = 0
    for name in _USED_ENDPOINTS:
        try:
            entries = os.scandir(health_dir / name)
        except OSError as exc:
            # Una cartella che non c'e' e' normale (un endpoint mai
            # scaricato); una che non si legge no, e va detto: la differenza
            # fra "niente da leggere" e "non riesco a leggere" e' quella fra
            # un archivio vuoto e un disco smontato.
            if not isinstance(exc, FileNotFoundError):
                print(f"  ATTENZIONE: {health_dir / name} non si legge ({exc}).")
                unreadable += 1
            continue
        with entries:
            for entry in entries:
                if not entry.name.endswith(".json"):
                    continue
                day = entry.name[: -len(".json")]
                try:
                    date.fromisoformat(day)
                    mtime = entry.stat(follow_symlinks=False).st_mtime
                except (ValueError, OSError):
                    continue
                if mtime > out.get(day, 0.0):
                    out[day] = mtime
    if unreadable:
        raise OSError(
            f"{unreadable} cartelle di health/ non si leggono: la scansione non e' "
            f"attendibile e la cache non si tocca"
        )
    return out


def sync_health(data_dir: Path = DATA_DIR) -> int:
    """Porta `health_daily` in pari con i JSON; torna quanti giorni ha riletto.

    Un giorno si rilegge solo se manca dalla tabella o se uno dei suoi file e'
    piu' nuovo della riga: `export_daily_health` riscrive i file di un giorno
    finche' non sono completi (oggi a ogni giro, e un giorno salvato a meta'
    giornata al giro dopo, todo 39), e una riga messa in cache una volta per
    giorno resterebbe vecchia. Se `HEALTH_LOGIC_VERSION` non coincide con
    quella salvata, prima si ricrea la tabella vuota, con le colonne di oggi."""
    data_dir = Path(data_dir)
    health_dir = data_dir / "health"
    conn = _connect(data_dir)
    try:
        row = conn.execute("SELECT value FROM schema_meta WHERE key=?", (_VERSION_KEY,)).fetchone()
        if row is None or row[0] != HEALTH_LOGIC_VERSION:
            conn.execute("DROP TABLE IF EXISTS health_daily")
            conn.executescript(_HEALTH_SCHEMA)
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_VERSION_KEY, HEALTH_LOGIC_VERSION),
            )

        cached = dict(conn.execute("SELECT day, source_mtime FROM health_daily"))
        mtimes = _source_mtimes(health_dir)
        # **Una scansione vuota non e' la prova che i file sono spariti.** Con
        # la cartella dei dati smontata, spostata o in mezzo a un rsync, la
        # scansione non trova niente e la riga qui sotto cancellerebbe tutta
        # la tabella — 6150 giorni — senza che niente alzi: ogni endpoint
        # continuerebbe a rispondere 200 con la salute tutta vuota, le card
        # bianche e gli agenti a scrivere su un corpo vuoto. Per rimetterla a
        # posto servirebbe rileggere 11 x 6150 file JSON.
        #
        # Se la tabella ha delle righe e la scansione non ne trova nessuna, il
        # problema e' la scansione.
        if cached and not mtimes:
            raise OSError(
                f"nessun file di salute in {health_dir}, ma la cache ne ha "
                f"{len(cached)} giorni: non la svuoto"
            )

        parsed_at = datetime.now().isoformat(sep=" ")
        rows = []
        for day in sorted(mtimes):
            mtime = mtimes[day]
            if day in cached and mtime <= cached[day]:
                continue
            rows.append(
                {"day": day, **_day_row(health_dir, day), "source_mtime": mtime, "parsed_at": parsed_at}
            )
        conn.executemany(_UPSERT, rows)

        # Un giorno i cui file non ci sono piu' non deve restare in cache.
        gone = set(cached) - set(mtimes)
        conn.executemany("DELETE FROM health_daily WHERE day=?", [(day,) for day in gone])

        conn.commit()
        return len(rows)
    finally:
        conn.close()


def load_health_db(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Le metriche di salute da `health_daily`, dopo un `sync_health()`.

    Indice `DatetimeIndex` di nome `day`, continuo dal primo all'ultimo
    giorno: i giorni senza file ci sono comunque, con tutto a `NaN`, cosi'
    l'asse del tempo non si accorcia sui buchi. Colonne `COLUMNS`. DataFrame
    vuoto con le colonne giuste se non c'e' niente."""
    data_dir = Path(data_dir)
    sync_health(data_dir)
    conn = _connect(data_dir)
    try:
        cursor = conn.execute(f"SELECT day, {', '.join(COLUMNS)} FROM health_daily ORDER BY day")
        records = cursor.fetchall()
    finally:
        conn.close()

    if not records:
        return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([], name="day"))

    days = [datetime.fromisoformat(r[0]).date() for r in records]
    rows = [dict(zip(COLUMNS, r[1:])) for r in records]
    frame = pd.DataFrame(rows, columns=COLUMNS, index=pd.DatetimeIndex(days, name="day"))
    # Le colonne numeriche sempre `float`, anche quando sono tutte NULL (la
    # saturazione, se l'orologio non la misura): NaN e non None.
    numeric = [name for name in COLUMNS if name not in TEXT_COLUMNS]
    frame[numeric] = frame[numeric].astype(float)
    # Il calendario completo fra il primo e l'ultimo giorno: `reindex` mette
    # NaN dove il giorno non c'era.
    full_range = pd.date_range(days[0], days[-1], freq="D", name="day")
    return frame.reindex(full_range)
