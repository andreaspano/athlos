"""Le attivita' e la salute di una cartella dati, tenute in memoria per un
minuto.

`list_activities()` (db.py) chiama `sync()`, che scandisce la cartella di
export, e `load_health_db()` chiama `sync_health()`, che guarda l'mtime di
ogni file di salute (decine di migliaia, circa un secondo): a ogni richiesta
renderebbero lenta ogni chiamata.

FastAPI serve gli endpoint sincroni su piu' thread: il lock evita che due
richieste insieme facciano due scansioni (e due `sync()` sullo stesso
database)."""

import threading
import time
from pathlib import Path

import pandas as pd

from training.interface.block_data import race_pace_km
from training.interface.db import list_activities, load_activity_records
from training.interface.health_db import load_health_db

# Un minuto: un'attivita' scaricata mentre il server gira compare da se',
# senza riavviarlo.
ACTIVITIES_TTL_SECONDS = 60


class _Cached:
    """Un lettore tenuto in memoria per `ACTIVITY_TTL_SECONDS`, con il suo
    lucchetto.

    **Uno per lettore, non uno per tutti**: la salute impiega un secondo e le
    attivita' non devono aspettarla. Era scritto due volte, identico a meno
    del lettore e di quale coppia lock/dizionario toccava, e `invalidate`
    doveva ricordarsi di svuotare entrambi a mano."""

    def __init__(self, loader):
        self._loader = loader
        self._lock = threading.Lock()
        self._store: dict[Path, tuple[float, pd.DataFrame]] = {}

    def get(self, data_dir: Path) -> pd.DataFrame:
        """Il frame, riletto al piu' una volta al minuto per cartella dati.
        Rende una copia: chi la riceve puo' filtrarla e aggiungere colonne
        senza sporcare la cache."""
        key = Path(data_dir)
        with self._lock:
            cached = self._store.get(key)
            if cached is None or time.monotonic() - cached[0] > ACTIVITIES_TTL_SECONDS:
                cached = (time.monotonic(), self._loader(key))
                self._store[key] = cached
        return cached[1].copy()

    def forget(self, data_dir: Path) -> None:
        with self._lock:
            self._store.pop(Path(data_dir), None)


_ACTIVITIES = _Cached(list_activities)
_HEALTH = _Cached(load_health_db)

# Il ritmo gara di ogni seduta (todo 96), **senza scadenza**: a differenza dei
# due lettori qui sopra questo non guarda una cartella che cambia, ma una
# seduta gia' letta, e una seduta gia' letta non cambia piu'. La chiave porta
# anche il bersaglio, che viene dal goal e non dall'attivita': cambiando goal i
# numeri sono altri, e i vecchi restano validi per il goal vecchio.
#
# Serve perche' il conto legge i `records` di ogni corsa del blocco: a blocco
# pieno sono una cinquantina di sedute da tre-cinquemila campioni, cioe' un
# quarto di milione di righe per richiesta, e il grafico si ridisegna a ogni
# cambio di settimana.
_RACE_PACE: dict[tuple[Path, int, float], float] = {}
_RACE_PACE_LOCK = threading.Lock()


def load_activities(data_dir: Path) -> pd.DataFrame:
    """Le attivita' come `list_activities()`, dalla cache."""
    return _ACTIVITIES.get(data_dir)


def load_health(data_dir: Path) -> pd.DataFrame:
    """La salute come `load_health_db()`, dalla cache."""
    return _HEALTH.get(data_dir)


def race_pace_of(data_dir: Path, activity_id: int, target_kmh: float) -> float:
    """Il tratto continuo piu' lungo a ritmo gara di una seduta, dalla cache.

    Il lucchetto e' solo attorno al dizionario: il conto si fa fuori, perche'
    tenerlo dentro bloccherebbe ogni altra richiesta per tutta la lettura dei
    campioni. Due richieste insieme sulla stessa seduta lo fanno due volte, che
    costa un po' di lavoro e niente di sbagliato — e' la stessa scelta che fa
    `_Cached` fra le cartelle dati diverse."""
    key = (Path(data_dir), int(activity_id), float(target_kmh))
    with _RACE_PACE_LOCK:
        found = _RACE_PACE.get(key)
    if found is not None:
        return found
    records = load_activity_records(
        activity_id, data_dir, columns=("distance_km", "equiv_speed_kmh")
    )
    value = race_pace_km(records, target_kmh)
    with _RACE_PACE_LOCK:
        _RACE_PACE[key] = value
    return value


def invalidate(data_dir: Path) -> None:
    """Dimentica attivita' e salute di una cartella dati: la prossima richiesta le
    rilegge. Dopo una scrittura (il terreno, todo 35; il tipo di corsa, todo
    36) e alla fine di un Refresh (todo 41), cosi' la modifica si vede subito
    e non dopo un minuto.

    Il ritmo gara va via con loro: un Refresh puo' aver scaricato sedute nuove,
    e soprattutto un `make rebuild` riscrive i campioni da cui quel numero
    viene."""
    _ACTIVITIES.forget(data_dir)
    _HEALTH.forget(data_dir)
    root = Path(data_dir)
    with _RACE_PACE_LOCK:
        for key in [k for k in _RACE_PACE if k[0] == root]:
            del _RACE_PACE[key]
