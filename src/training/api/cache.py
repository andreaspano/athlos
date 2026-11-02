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

from training.interface.db import list_activities
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


def load_activities(data_dir: Path) -> pd.DataFrame:
    """Le attivita' come `list_activities()`, dalla cache."""
    return _ACTIVITIES.get(data_dir)


def load_health(data_dir: Path) -> pd.DataFrame:
    """La salute come `load_health_db()`, dalla cache."""
    return _HEALTH.get(data_dir)


def invalidate(data_dir: Path) -> None:
    """Dimentica attivita' e salute di una cartella dati: la prossima richiesta le
    rilegge. Dopo una scrittura (il terreno, todo 35; il tipo di corsa, todo
    36) e alla fine di un Refresh (todo 41), cosi' la modifica si vede subito
    e non dopo un minuto."""
    _ACTIVITIES.forget(data_dir)
    _HEALTH.forget(data_dir)
