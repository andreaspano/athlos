"""Scaricamento ed estrazione delle attivita': una risposta sbagliata non deve
portarsi via ne' le altre attivita' ne' il rinfresco della salute, e la
scansione non deve perdere un'attivita' caricata fuori ordine."""

from datetime import date

import pytest

from conftest import FakeApi, activity, zip_bytes
from training.garmin import activities as A


class TestExtract:
    def test_a_good_zip_is_extracted(self, tmp_path):
        (tmp_path / "fit").mkdir()
        assert A._extract_or_warn(zip_bytes("123_ACTIVITY.fit"), tmp_path, 123, "[1/1]") is True
        assert (tmp_path / "fit" / "123_ACTIVITY.fit").exists()

    @pytest.mark.parametrize(
        "body, why",
        [
            (b"<html>Garmin Connect is under maintenance</html>", "pagina HTML con 200"),
            (zip_bytes()[:40], "zip troncato, che comincia comunque per PK"),
            (b"", "corpo vuoto"),
        ],
    )
    def test_a_body_that_is_not_a_zip_is_refused(self, tmp_path, body, why):
        (tmp_path / "fit").mkdir()
        assert A._extract_or_warn(body, tmp_path, 124, "[1/1]") is False, why


class TestStartedBefore:
    CUTOFF = date(2026, 10, 2)

    def test_older_than_the_window(self):
        assert A._started_before({"startTimeLocal": "2026-09-30 07:00:00"}, self.CUTOFF) is True

    def test_inside_the_window(self):
        assert A._started_before({"startTimeLocal": "2026-10-20 07:00:00"}, self.CUTOFF) is False

    def test_falls_back_to_gmt(self):
        assert A._started_before({"startTimeGMT": "2026-09-01 05:00:00"}, self.CUTOFF) is True

    @pytest.mark.parametrize("act", [{"startTimeLocal": "ieri"}, {}])
    def test_an_unreadable_date_does_not_stop_the_scan(self, act):
        """Meglio scorrere una pagina in piu' che perdere un'attivita'."""
        assert A._started_before(act, self.CUTOFF) is False


class TestMaps:
    def test_a_corrupt_map_is_moved_aside(self, tmp_path, capsys):
        """Prima un file troncato faceva morire ogni `update_activity` con un
        `JSONDecodeError`, prima ancora di contattare Garmin."""
        (tmp_path / "json").mkdir()
        path = tmp_path / "json" / "activity_names.json"
        path.write_text('{"123": "corsa"', encoding="utf-8")

        assert A._load_activity_names(tmp_path) == {}
        assert (tmp_path / "json" / "activity_names.json.corrupt").exists()
        assert not path.exists()
        assert "backfill_activity_names" in capsys.readouterr().out

    def test_a_missing_map_is_empty(self, tmp_path):
        assert A._load_activity_types(tmp_path) == {}

    def test_save_and_load(self, tmp_path):
        A._save_activity_names(tmp_path, {"9": "giro"})
        assert A._load_activity_names(tmp_path) == {"9": "giro"}


class TestUpdateActivity:
    def test_an_activity_imported_out_of_order_is_found(self, run_update):
        """Garmin ordina per data di inizio, non di caricamento: l'escursione
        di sabato importata dopo la corsa di oggi sta *sotto* di lei, e la
        vecchia regola (fermarsi alla prima conosciuta) la perdeva per
        sempre."""
        page = [activity(900, days_ago=0), activity(800, days_ago=6)]
        out, _ = run_update([page], {800: zip_bytes("800_ACTIVITY.fit")}, existing=[900])
        assert out == [800]

    def test_the_window_bounds_the_scan(self, run_update):
        page = [activity(900, 0), activity(700, 40), activity(600, 50)]
        out, trace = run_update([page], {}, existing=[900])
        assert out == []
        assert trace["pages"] == 1, "un mese di attivita' sta in una pagina"
        assert trace["downloaded_ids"] == [], "le vecchie non si chiedono nemmeno"

    def test_a_bad_zip_does_not_stop_the_others(self, run_update):
        page = [activity(901, 0), activity(902, 1), activity(903, 2)]
        downloads = {
            901: b"<html>manutenzione</html>",
            902: zip_bytes("902_ACTIVITY.fit"),
            903: zip_bytes("903_ACTIVITY.fit"),
        }
        out, trace = run_update([page], downloads)
        assert out == [902, 903]
        assert trace["downloaded_ids"] == [901, 902, 903]

    def test_the_health_refresh_runs_anyway(self, run_update):
        """Sonno, readiness e body battery non dipendono da un FIT."""
        out, trace = run_update([[activity(901, 0)]], {901: b"<html>no</html>"})
        assert out == []
        assert trace["health"] == 1

    def test_one_failed_download_warns_and_carries_on(self, run_update):
        """Contratto di `_download_or_warn`: quell'id non entra fra le
        scaricate, quindi al giro dopo si riprova."""
        out, trace = run_update([[activity(910, 0)]], {910: RuntimeError("500 vero")})
        assert out == []
        assert trace["health"] == 1

    def test_health_is_refreshed_even_if_the_list_never_arrives(self, tmp_path, monkeypatch):
        trace = {"health": 0}

        def list_fails(func, *args, **kwargs):
            raise RuntimeError("500 su /activities")

        monkeypatch.setattr(A, "safe_call", list_fails)
        monkeypatch.setattr(A, "init_api", FakeApi)
        monkeypatch.setattr(A, "REQUEST_DELAY", 0)
        monkeypatch.setattr(A, "refresh_recent_health", lambda api, d: trace.__setitem__("health", 1))

        with pytest.raises(RuntimeError):
            A.update_activity(tmp_path)
        assert trace["health"] == 1


class TestDownloadBetween:
    def test_it_returns_the_list_it_had_to_fetch(self, tmp_path, monkeypatch):
        """`fitness_status` lo prende da qui invece di richiederlo: una
        chiamata in meno, e nessun rischio di due elenchi diversi."""
        (tmp_path / "fit").mkdir()
        acts = [activity(1)]
        seen = {}

        def fake_safe_call(func, *args, **kwargs):
            if getattr(func, "__name__", "") == "get_activities_by_date":
                seen.update(kwargs)
                return acts
            return None

        monkeypatch.setattr(A, "safe_call", fake_safe_call)
        monkeypatch.setattr(A, "REQUEST_DELAY", 0)

        ids, listed = A.download_activities_between(FakeApi(), "2026-10-01", "2026-10-31", tmp_path)

        assert listed == acts
        assert ids == []
        assert seen.get("sortorder") == "asc", "l'ordine che lo snapshot ha sempre avuto"
