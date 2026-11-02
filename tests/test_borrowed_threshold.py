"""La soglia prestata sta in una colonna sua.

Il profilo Bici dell'orologio non salva la soglia anaerobica, e alcune
escursioni la salvano a zero: senza nessuna soglia le zone non si possono
dividere, quindi si presta quella della corsa piu' vicina. Scritta in
`threshold_hr` non si distingueva piu' da una misurata — 32 attivita' la
portavano come se fosse loro — e una riga che l'aveva ricevuta in prestito
faceva da donatrice alla successiva.
"""

import json

import pytest

BOUNDS = json.dumps([110, 130, 150, 165, 180])


@pytest.fixture
def conn(tmp_path):
    from training.interface.db import _connect

    (tmp_path / "db").mkdir()
    connection = _connect(tmp_path)
    _say_it_is_current(connection)
    yield connection
    connection.close()


def _say_it_is_current(conn) -> None:
    """Dichiara la versione corrente, cosi' `sync()` non ricostruisce: senza,
    la prima lettura butterebbe le righe messe a mano qui."""
    from training.interface.db import LOGIC_VERSION

    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('logic_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (LOGIC_VERSION,),
    )


def add(conn, activity_id: int, day: str, sport: str, threshold, bounds: str | None = BOUNDS):
    conn.execute(
        "INSERT INTO activities (activity_id, path, sport, start_time, hr_zone_bounds, "
        "threshold_hr, parsed_at) VALUES (?, ?, ?, ?, ?, ?, '2026-10-20 10:00:00')",
        (activity_id, f"{activity_id}.fit", sport, f"{day} 10:00:00", bounds, threshold),
    )


def row(conn, activity_id: int) -> tuple:
    return conn.execute(
        "SELECT threshold_hr, threshold_hr_borrowed FROM activities WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()


class TestWhereTheBorrowedValueGoes:
    def test_it_does_not_touch_the_measured_column(self, conn):
        from training.interface.db import _fill_missing_thresholds

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "hiking", None)
        _fill_missing_thresholds(conn)

        assert row(conn, 1) == (152, None), "chi ne ha una sua resta com'era"
        assert row(conn, 2) == (None, 152), "chi non ne ha una la riceve a parte"

    def test_a_zero_counts_as_missing(self, conn):
        from training.interface.db import _fill_missing_thresholds

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "hiking", 0)
        _fill_missing_thresholds(conn)

        assert row(conn, 2) == (0, 152)

    def test_a_borrowed_row_is_not_a_donor(self, conn):
        """Era il difetto che rendeva il risultato dipendente dall'ordine:
        la corsa senza soglia riceveva 152 e poi lo passava avanti."""
        from training.interface.db import _fill_missing_thresholds

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "running", None)
        add(conn, 3, "2026-08-25", "hiking", None)
        _fill_missing_thresholds(conn)
        _fill_missing_thresholds(conn)

        assert row(conn, 2) == (None, 152)
        assert row(conn, 3) == (None, 152), "da 1, non da 2"

    def test_the_nearest_run_before_wins(self, conn):
        from training.interface.db import _fill_missing_thresholds

        add(conn, 1, "2026-08-01", "running", 148)
        add(conn, 2, "2026-08-10", "running", 152)
        add(conn, 3, "2026-08-20", "cycling", None)
        _fill_missing_thresholds(conn)

        assert row(conn, 3) == (None, 152)

    def test_without_one_before_it_looks_forward(self, conn):
        """Scelta dichiarata: l'orologio salva soglie vere solo da
        settembre, e lo storico di agosto non ne ha nessuna prima."""
        from training.interface.db import _fill_missing_thresholds

        add(conn, 1, "2026-08-20", "hiking", None)
        add(conn, 2, "2026-09-15", "running", 154)
        _fill_missing_thresholds(conn)

        assert row(conn, 1) == (None, 154)

    def test_nothing_before_the_fallback_date(self, conn):
        from training.interface.db import _fill_missing_thresholds

        add(conn, 1, "2026-07-20", "hiking", None)
        add(conn, 2, "2026-09-15", "running", 154)
        _fill_missing_thresholds(conn)

        assert row(conn, 1) == (None, None), "lo storico piu' vecchio resta com'e'"

    def test_an_activity_without_zones_gets_nothing(self, conn):
        from training.interface.db import _fill_missing_thresholds

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "strength", None, bounds=None)
        _fill_missing_thresholds(conn)

        assert row(conn, 2) == (None, None), "senza i tetti delle zone non c'e' niente da dividere"


class TestWhoUsesWhich:
    def test_zone_settings_falls_back_to_the_borrowed_one(self):
        """Il grafico deve continuare a stimare gli effetti: li' serve un
        numero per dividere le zone, non la misura di quella seduta."""
        import pandas as pd

        from training.interface.run_chart import zone_settings

        measured = pd.Series({"hr_zone_bounds": BOUNDS, "threshold_hr": 160, "threshold_hr_borrowed": None})
        borrowed = pd.Series({"hr_zone_bounds": BOUNDS, "threshold_hr": None, "threshold_hr_borrowed": 152})
        neither = pd.Series({"hr_zone_bounds": BOUNDS, "threshold_hr": None, "threshold_hr_borrowed": None})

        assert zone_settings(measured) == ([110, 130, 150, 165, 180], 160)
        assert zone_settings(borrowed) == ([110, 130, 150, 165, 180], 152)
        assert zone_settings(neither) == ([110, 130, 150, 165, 180], None)

    @pytest.mark.parametrize(
        "heart_rate, expected, why",
        [
            (151, (0.0, 5.0, 0.0), "fra il tetto di Z3 (150) e la soglia prestata (152)"),
            (155, (0.0, 0.0, 5.0), "sopra la soglia prestata"),
            (140, (5.0, 0.0, 0.0), "sotto il tetto di Z3"),
        ],
    )
    def test_the_zone_minutes_use_the_borrowed_one(self, conn, heart_rate, expected, why):
        """Senza la soglia prestata la divisione non si potrebbe fare: e' il
        motivo per cui il prestito esiste."""
        from training.interface.db import _fill_missing_thresholds, _zone_minutes

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "hiking", None)
        conn.executemany(
            "INSERT INTO records (activity_id, ts_epoch, heart_rate) VALUES (2, ?, ?)",
            [(t, heart_rate) for t in range(0, 300)],
        )
        _fill_missing_thresholds(conn)

        assert _zone_minutes(conn, 2) == pytest.approx(expected, abs=0.1), why


class TestWhatTheApiSays:
    """Nella risposta i due numeri restano separati: dire che una pedalata
    ha misurato la soglia di una corsa e' una bugia, ed e' quella che
    l'endpoint raccontava prima — passava nel campo della misurata il valore
    che `zone_settings` da' per dividere le zone."""

    def test_a_borrowed_threshold_is_not_reported_as_measured(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        from training.api.app import app
        from training.api.context import UserContext, get_user_context
        from training.interface.db import _connect, _fill_missing_thresholds

        (tmp_path / "db").mkdir()
        (tmp_path / "fit").mkdir()
        conn = _connect(tmp_path)
        _say_it_is_current(conn)
        add(conn, 1, "2026-09-15", "running", 154)
        add(conn, 2, "2026-09-20", "cycling", None)
        _fill_missing_thresholds(conn)
        conn.commit()
        conn.close()

        app.dependency_overrides[get_user_context] = lambda: UserContext(
            data_dir=tmp_path, summary_dir=tmp_path, plan_dir=tmp_path
        )
        try:
            client = TestClient(app)
            borrowed = client.get("/api/activities/2").json()
            measured = client.get("/api/activities/1").json()
        finally:
            app.dependency_overrides.clear()

        assert borrowed["threshold_hr"] is None, "la pedalata non ha misurato niente"
        assert borrowed["threshold_hr_borrowed"] == 154
        assert measured["threshold_hr"] == 154
        assert measured["threshold_hr_borrowed"] is None
