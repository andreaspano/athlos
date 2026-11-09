"""Le zone e la soglia prestate stanno in colonne loro.

Il profilo Bici dell'orologio non salva la soglia anaerobica, alcune
escursioni la salvano a zero, e un FIT che non viene da Garmin — una pedalata
al rullo esportata da MyWhoosh — non ha nemmeno il messaggio delle zone: senza
i due numeri lo sforzo non si puo' dividere, quindi si prendono dalla corsa
piu' vicina che li ha misurati.

Scritti nelle colonne misurate non si distinguevano piu' dalle misure — 32
attivita' portavano una soglia da corsa come se fosse loro — e una riga che
li aveva ricevuti in prestito faceva da donatrice alla successiva.

**I due valori vengono dalla stessa seduta**: i tetti del profilo Bici sono
calcolati sulla frequenza massima e quelli del profilo Corsa sulla soglia, e
mescolarli puo' dare un tetto di Z3 sopra la soglia, cioe' una fascia alta
aerobica vuota.
"""

import json

import pytest

BOUNDS = json.dumps([110, 130, 150, 165, 180])
OTHER_BOUNDS = json.dumps([100, 120, 140, 155, 170])


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
    """La soglia misurata e quella prestata."""
    return conn.execute(
        "SELECT threshold_hr, threshold_hr_borrowed FROM activities WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()


def zones(conn, activity_id: int) -> tuple:
    """I tetti misurati e quelli prestati."""
    return conn.execute(
        "SELECT hr_zone_bounds, hr_zone_bounds_borrowed FROM activities WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()


class TestWhereTheBorrowedValueGoes:
    def test_it_does_not_touch_the_measured_column(self, conn):
        from training.interface.db import _lend_zone_settings

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "hiking", None)
        _lend_zone_settings(conn)

        assert row(conn, 1) == (152, None), "chi ne ha una sua resta com'era"
        assert row(conn, 2) == (None, 152), "chi non ne ha una la riceve a parte"

    def test_a_zero_counts_as_missing(self, conn):
        from training.interface.db import _lend_zone_settings

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "hiking", 0)
        _lend_zone_settings(conn)

        assert row(conn, 2) == (0, 152)

    def test_a_borrowed_row_is_not_a_donor(self, conn):
        """Era il difetto che rendeva il risultato dipendente dall'ordine:
        la corsa senza soglia riceveva 152 e poi lo passava avanti."""
        from training.interface.db import _lend_zone_settings

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "running", None)
        add(conn, 3, "2026-08-25", "hiking", None)
        _lend_zone_settings(conn)
        _lend_zone_settings(conn)

        assert row(conn, 2) == (None, 152)
        assert row(conn, 3) == (None, 152), "da 1, non da 2"

    def test_the_nearest_run_before_wins(self, conn):
        from training.interface.db import _lend_zone_settings

        add(conn, 1, "2026-08-01", "running", 148)
        add(conn, 2, "2026-08-10", "running", 152)
        add(conn, 3, "2026-08-20", "cycling", None)
        _lend_zone_settings(conn)

        assert row(conn, 3) == (None, 152)

    def test_without_one_before_it_looks_forward(self, conn):
        """Scelta dichiarata: l'orologio salva soglie vere solo da
        settembre, e lo storico di agosto non ne ha nessuna prima."""
        from training.interface.db import _lend_zone_settings

        add(conn, 1, "2026-08-20", "hiking", None)
        add(conn, 2, "2026-09-15", "running", 154)
        _lend_zone_settings(conn)

        assert row(conn, 1) == (None, 154)

    def test_nothing_before_the_fallback_date(self, conn):
        from training.interface.db import _lend_zone_settings

        add(conn, 1, "2026-07-20", "hiking", None)
        add(conn, 2, "2026-09-15", "running", 154)
        _lend_zone_settings(conn)

        assert row(conn, 1) == (None, None), "lo storico piu' vecchio resta com'e'"
        assert zones(conn, 1) == (BOUNDS, None)

    def test_a_loan_that_cannot_be_made_again_goes_away(self, conn):
        """Il prestito e' un valore derivato: si azzera e si rifa' da se'. Se
        la corsa donatrice sparisse dall'archivio, il prestito che le
        sopravvive resterebbe in tabella per sempre."""
        from training.interface.db import _lend_zone_settings

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "cycling", None, bounds=None)
        _lend_zone_settings(conn)
        assert row(conn, 2) == (None, 152)

        conn.execute("DELETE FROM activities WHERE activity_id = 1")
        _lend_zone_settings(conn)

        assert row(conn, 2) == (None, None)
        assert zones(conn, 2) == (None, None)


class TestTheZonesAreLentToo:
    """Il profilo Bici non salva la soglia ma le zone si'; un FIT che non
    viene da Garmin non salva nessuna delle due, e prima restava fuori dalla
    divisione fra lavoro facile e duro."""

    def test_an_activity_without_zones_gets_them(self, conn):
        from training.interface.db import _lend_zone_settings

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "cycling", None, bounds=None)
        _lend_zone_settings(conn)

        assert zones(conn, 2) == (None, BOUNDS)
        assert row(conn, 2) == (None, 152)

    def test_who_has_its_own_zones_keeps_them(self, conn):
        from training.interface.db import _lend_zone_settings

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "cycling", None, bounds=OTHER_BOUNDS)
        _lend_zone_settings(conn)

        assert zones(conn, 2) == (OTHER_BOUNDS, None), "solo la soglia le manca"
        assert row(conn, 2) == (None, 152)

    def test_both_come_from_the_same_run(self, conn):
        """La coppia deve restare coerente: un tetto di Z3 calcolato sulla
        frequenza massima e una soglia di un'altra seduta possono invertirsi,
        e allora la fascia alta aerobica non esiste piu'."""
        from training.interface.db import _lend_zone_settings

        add(conn, 1, "2026-08-10", "running", 148, bounds=OTHER_BOUNDS)
        add(conn, 2, "2026-09-10", "running", 152, bounds=BOUNDS)
        add(conn, 3, "2026-09-20", "cycling", None, bounds=None)
        _lend_zone_settings(conn)

        assert (zones(conn, 3)[1], row(conn, 3)[1]) == (BOUNDS, 152), "tutto dalla corsa 2"

    def test_a_run_that_measured_only_the_threshold_does_not_lend(self, conn):
        """I donatori sono le corse che hanno misurato **entrambi**: a
        prestare mezza coppia si torna a mescolare due sedute."""
        from training.interface.db import _lend_zone_settings

        add(conn, 1, "2026-08-10", "running", 152, bounds=None)
        add(conn, 2, "2026-08-20", "cycling", None, bounds=None)
        _lend_zone_settings(conn)

        assert zones(conn, 2) == (None, None)
        assert row(conn, 2) == (None, None)


class TestWhoUsesWhich:
    def test_zone_settings_falls_back_to_the_borrowed_ones(self):
        """Il grafico deve continuare a stimare gli effetti: li' serve un
        numero per dividere le zone, non la misura di quella seduta."""
        import pandas as pd

        from training.interface.run_chart import zone_settings

        def series(**kwargs):
            base = {
                "hr_zone_bounds": None,
                "hr_zone_bounds_borrowed": None,
                "threshold_hr": None,
                "threshold_hr_borrowed": None,
            }
            return pd.Series(base | kwargs)

        tops = [110, 130, 150, 165, 180]
        assert zone_settings(series(hr_zone_bounds=BOUNDS, threshold_hr=160)) == (tops, 160)
        assert zone_settings(series(hr_zone_bounds=BOUNDS, threshold_hr_borrowed=152)) == (tops, 152)
        assert zone_settings(
            series(hr_zone_bounds_borrowed=BOUNDS, threshold_hr_borrowed=152)
        ) == (tops, 152), "una seduta che non ha misurato niente"
        assert zone_settings(series(hr_zone_bounds=BOUNDS)) == (tops, None)
        assert zone_settings(series(threshold_hr=160)) == (None, 160)

    @pytest.mark.parametrize(
        "heart_rate, expected, why",
        [
            (151, (0.0, 5.0, 0.0), "fra il tetto di Z3 (150) e la soglia prestata (152)"),
            (155, (0.0, 0.0, 5.0), "sopra la soglia prestata"),
            (140, (5.0, 0.0, 0.0), "sotto il tetto di Z3"),
        ],
    )
    def test_the_zone_minutes_use_the_borrowed_ones(self, conn, heart_rate, expected, why):
        """Senza i valori prestati la divisione non si potrebbe fare: e' il
        motivo per cui il prestito esiste. Qui la seduta non ha misurato ne'
        i tetti ne' la soglia, come una pedalata esportata da MyWhoosh."""
        from training.interface.db import _lend_zone_settings, _zone_minutes

        add(conn, 1, "2026-08-10", "running", 152)
        add(conn, 2, "2026-08-20", "cycling", None, bounds=None)
        conn.executemany(
            "INSERT INTO records (activity_id, ts_epoch, heart_rate) VALUES (2, ?, ?)",
            [(t, heart_rate) for t in range(0, 300)],
        )
        _lend_zone_settings(conn)

        assert _zone_minutes(conn, 2) == pytest.approx(expected, abs=0.1), why


class TestWhatTheApiSays:
    """Nella risposta il misurato e il prestato restano separati: dire che una
    pedalata ha misurato le zone e la soglia di una corsa e' una bugia, ed e'
    quella che l'endpoint raccontava prima — passava nel campo della misurata
    il valore che `zone_settings` da' per dividere le zone."""

    @pytest.fixture
    def client(self, tmp_path):
        from fastapi.testclient import TestClient

        from training.api.app import app
        from training.api.context import UserContext, get_user_context
        from training.interface.db import _connect, _lend_zone_settings

        (tmp_path / "db").mkdir()
        (tmp_path / "fit").mkdir()
        conn = _connect(tmp_path)
        _say_it_is_current(conn)
        add(conn, 1, "2026-09-15", "running", 154)
        add(conn, 2, "2026-09-20", "cycling", None, bounds=None)
        _lend_zone_settings(conn)
        conn.commit()
        conn.close()

        app.dependency_overrides[get_user_context] = lambda: UserContext(
            data_dir=tmp_path, summary_dir=tmp_path, plan_dir=tmp_path
        )
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()

    def test_a_borrowed_threshold_is_not_reported_as_measured(self, client):
        borrowed = client.get("/api/activities/2").json()
        measured = client.get("/api/activities/1").json()

        assert borrowed["threshold_hr"] is None, "la pedalata non ha misurato niente"
        assert borrowed["threshold_hr_borrowed"] == 154
        assert measured["threshold_hr"] == 154
        assert measured["threshold_hr_borrowed"] is None

    def test_borrowed_zones_are_not_reported_as_measured(self, client):
        borrowed = client.get("/api/activities/2").json()
        measured = client.get("/api/activities/1").json()

        assert borrowed["hr_zone_bounds"] is None
        assert borrowed["hr_zone_bounds_borrowed"] == [110, 130, 150, 165, 180]
        assert measured["hr_zone_bounds"] == [110, 130, 150, 165, 180]
        assert measured["hr_zone_bounds_borrowed"] is None

    def test_the_effects_are_estimated_with_the_borrowed_settings(self, client, tmp_path):
        """E' il punto del prestito: la scheda di una seduta senza zone sue
        stima comunque i minuti per fascia di sforzo."""
        from training.interface.db import _connect

        conn = _connect(tmp_path)
        conn.executemany(
            "INSERT INTO records (activity_id, ts_epoch, heart_rate) VALUES (2, ?, 140)",
            [(t,) for t in range(0, 300)],
        )
        conn.commit()
        conn.close()

        seconds = client.get("/api/activities/2").json()["effect_seconds"]

        assert seconds["low_aerobic_s"] == pytest.approx(300, abs=2), "140 e' sotto il tetto di Z3"
        assert seconds["high_aerobic_s"] == 0
