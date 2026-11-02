"""La scansione dei file di salute: una sola passata, e gli stessi mtime di
prima.

E' la parte lenta di `sync_health`, cioe' il costo della prima richiesta dopo
ogni minuto di cache — col lock della salute preso per tutto il tempo.
"""

import os
from datetime import date

from training.interface.health import _USED_ENDPOINTS
from training.interface.health_db import _source_mtimes


def write(health_dir, endpoint, name, when=None):
    folder = health_dir / endpoint
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("{}", encoding="utf-8")
    if when is not None:
        os.utime(path, (when, when))
    return path


class TestSourceMtimes:
    def test_it_takes_the_newest_file_of_each_day(self, tmp_path):
        day = "2026-10-20"
        write(tmp_path, "stats", f"{day}.json", when=1000)
        write(tmp_path, "sleep", f"{day}.json", when=3000)
        write(tmp_path, "hrv", f"{day}.json", when=2000)

        assert _source_mtimes(tmp_path) == {day: 3000}

    def test_a_day_with_one_file_is_a_day(self, tmp_path):
        """`available_days` guardava l'unione degli undici endpoint: un giorno
        senza sonno ma con la readiness e' comunque un giorno."""
        write(tmp_path, "training_readiness", "2026-10-21.json", when=500)
        assert set(_source_mtimes(tmp_path)) == {"2026-10-21"}

    def test_names_that_are_not_dates_are_skipped(self, tmp_path):
        write(tmp_path, "stats", "2026-10-22.json", when=100)
        write(tmp_path, "stats", "appunti.json", when=200)
        write(tmp_path, "stats", "2026-13-99.json", when=300)
        assert set(_source_mtimes(tmp_path)) == {"2026-10-22"}

    def test_other_extensions_are_skipped(self, tmp_path):
        write(tmp_path, "stats", "2026-10-23.json", when=100)
        write(tmp_path, "stats", "2026-10-24.json.tmp", when=200)
        assert set(_source_mtimes(tmp_path)) == {"2026-10-23"}

    def test_a_missing_endpoint_folder_is_not_an_error(self, tmp_path):
        write(tmp_path, _USED_ENDPOINTS[0], "2026-10-25.json", when=100)
        assert set(_source_mtimes(tmp_path)) == {"2026-10-25"}

    def test_an_empty_tree_is_no_days(self, tmp_path):
        assert _source_mtimes(tmp_path) == {}

    def test_it_reads_every_endpoint_folder(self, tmp_path):
        """Undici cartelle, undici giorni distinti: nessuna resta fuori."""
        for index, endpoint in enumerate(_USED_ENDPOINTS):
            write(tmp_path, endpoint, f"2026-10-{index + 1:02d}.json", when=100 + index)
        assert len(_source_mtimes(tmp_path)) == len(_USED_ENDPOINTS)

    def test_the_mtimes_are_the_ones_the_filesystem_reports(self, tmp_path):
        path = write(tmp_path, "stats", "2026-10-26.json")
        assert _source_mtimes(tmp_path)["2026-10-26"] == path.stat().st_mtime
