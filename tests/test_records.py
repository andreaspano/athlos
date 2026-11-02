"""La lettura dei campioni di una seduta.

Due cose insieme: leggere solo le colonne che servono — la scansione della
seduta impegnativa scorre indietro fino a diciotto sedute e di trenta colonne
ne usa una — e convertire i tempi in blocco invece che riga per riga.
"""

from datetime import datetime

import pandas as pd
import pytest

from training.garmin.config import DATA_DIR, LOCAL_TZ
from training.interface.db import load_activity_records

ARCHIVE = (DATA_DIR / "db" / "activities.db").exists()
pytestmark = pytest.mark.skipif(not ARCHIVE, reason="serve l'archivio vero")


@pytest.fixture(scope="module")
def an_activity() -> int:
    from training.interface.db import list_activities

    activities = list_activities(DATA_DIR)
    # La prima, fra le piu' recenti, che abbia dei campioni: il database non
    # tiene il loro numero, quindi si guarda.
    for activity_id in activities["activity_id"].head(20):
        if len(load_activity_records(int(activity_id), DATA_DIR)) > 100:
            return int(activity_id)
    pytest.skip("nessuna seduta con campioni")


def test_only_the_columns_asked_for(an_activity):
    light = load_activity_records(an_activity, DATA_DIR, columns=("heart_rate",))
    full = load_activity_records(an_activity, DATA_DIR)

    assert list(light.columns) == ["heart_rate"]
    assert len(light) == len(full)
    assert light.index.equals(full.index), "lo stesso indice, non uno approssimato"
    assert light["heart_rate"].equals(full["heart_rate"])


def test_the_timestamps_match_the_row_by_row_conversion(an_activity):
    """L'oracolo e' la conversione di prima: `datetime.fromtimestamp` nel fuso
    dell'account, una riga per volta."""
    from training.interface.db import _connect

    conn = _connect(DATA_DIR)
    try:
        epochs = pd.read_sql_query(
            "SELECT ts_epoch FROM records WHERE activity_id=? ORDER BY ts_epoch",
            conn,
            params=(an_activity,),
        )["ts_epoch"]
    finally:
        conn.close()

    expected = epochs.map(
        lambda e: datetime.fromtimestamp(e, tz=LOCAL_TZ).replace(tzinfo=None)
    )
    got = load_activity_records(an_activity, DATA_DIR, columns=("heart_rate",)).index

    assert list(got) == list(expected)


def test_an_activity_without_records_has_a_typed_index():
    """Zero righe non vuol dire indice senza tipo: era `object`, e un indice
    senza tipo e' il difetto che aveva fatto rispondere 500 a tre endpoint su
    una cartella dati vuota."""
    empty = load_activity_records(-1, DATA_DIR)
    assert empty.empty
    assert str(empty.index.dtype).startswith("datetime64")
