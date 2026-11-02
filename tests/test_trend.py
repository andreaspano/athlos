"""I pannelli della Trend. Nessun test li toccava: e' il percorso in cui e'
passato un `NameError` durante questa stessa pulizia."""

from datetime import date

import pytest

from training.interface import daily_data as D
from training.garmin.config import DATA_DIR

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "db" / "activities.db").exists(), reason="serve l'archivio vero"
)
START, END = date(2026, 10, 1), date(2026, 10, 31)


@pytest.fixture(scope="module")
def frames():
    from training.interface.db import list_activities
    from training.interface.health_db import load_health_db

    return list_activities(DATA_DIR), load_health_db(DATA_DIR)


def test_the_panels_are_built(frames):
    activities, health = frames
    data = D.trend_data(START, END, DATA_DIR, activities, health)

    assert [p["key"] for p in data["panels"]] == ["health", "recovery", "load", "fitness", "training"]
    assert all(p["series"] for p in data["panels"])
    first = data["panels"][0]["series"][0]
    assert {"key", "label", "unit", "digits", "points", "band"} <= set(first)
    assert len(first["points"]) == 31


def test_the_window_is_computed_once_per_series(frames, monkeypatch):
    """Era calcolata due volte con gli stessi argomenti, una per i punti e
    una per la fascia."""
    activities, health = frames
    calls: list[tuple] = []
    original = D._window

    def counted(frame, column, end, days):
        calls.append((column, end, days))
        return original(frame, column, end, days)

    monkeypatch.setattr(D, "_window", counted)
    data = D.trend_data(START, END, DATA_DIR, activities, health)

    # Il pannello Training non passa da `_window` (i suoi numeri vengono
    # dalle attivita'), quindi le finestre sono meno delle serie. L'invariante
    # e' che nessuna sia chiesta due volte: prima erano esattamente il doppio.
    assert calls, "qualche finestra si chiede"
    assert len(calls) == len(set(calls)), (
        f"{len(calls)} chiamate per {len(set(calls))} finestre distinte"
    )
    series = sum(len(p["series"]) for p in data["panels"])
    assert len(calls) < series * 2
