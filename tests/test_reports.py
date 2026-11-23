"""La lettura dei report dal disco: i due formati, quello a frammenti e il
file unico di prima del todo 44."""

from datetime import date

import pytest

from training.api.app import _fragment_sections, get_daily_report
from training.api.sections import DAILY

LEGACY = """# Daily report - 2026-08-05

Data: local cache, health up to 2026-10-07

## Training

No training on this Wednesday, after another rest day yesterday.

## Recovery

Readiness 61, moderate.
"""


class FakeContext:
    """Il contesto che gli endpoint ricevono: solo le due cartelle."""

    def __init__(self, summary_dir, data_dir):
        self.summary_dir = summary_dir
        self.data_dir = data_dir


def test_a_single_file_report_is_still_readable(tmp_path):
    """Il todo 92 ha aggiunto il verdetto alle righe di `_fragment_sections`
    e ha lasciato indietro questo ramo: da allora ogni giorno in formato
    vecchio rispondeva 500, mentre il README promette che si leggono ancora.
    Sul disco vero ce ne sono 77."""
    folder = tmp_path / DAILY.folder
    folder.mkdir(parents=True)
    (folder / "2026-08-05.md").write_text(LEGACY, encoding="utf-8")

    report = get_daily_report(date(2026, 8, 5), FakeContext(tmp_path, tmp_path))

    written = {section.title: section.body for section in report.sections if section.body}
    assert "Training" in written
    assert written["Training"].startswith("No training on this Wednesday")
    assert "Recovery" in written
    assert all(section.verdict is None for section in report.sections), (
        "il file unico e' di prima dei verdetti"
    )


def test_every_fragment_row_has_five_values(tmp_path):
    """I due rami devono dare righe della stessa forma: era il disaccordo da
    cui veniva il 500. Erano quattro valori fino al todo 99, che ha aggiunto
    il francobollo — e il ramo del file unico e' passato di qui di nuovo."""
    folder = tmp_path / "2026-10-01"
    folder.mkdir()
    (folder / "health.md").write_text("Il corpo ha tenuto.", encoding="utf-8")

    rows = _fragment_sections(folder, DAILY)

    assert rows, "le sezioni ci sono tutte, anche senza frammento"
    assert all(len(row) == 5 for row in rows)


class TestVerdictLine:
    """`verdict: <parola>` e' una riga, non un prefisso: le cinque parole
    della scala sono anche inizi di parole inglesi ordinarie, e il testo
    degli agenti non si puo' vincolare."""

    def test_the_word_alone_on_its_line_is_a_verdict(self):
        from training.api.app import _verdict

        assert _verdict("verdict: high\n\nLa seduta e' andata bene.") == (
            "high", "La seduta e' andata bene."
        )

    @pytest.mark.parametrize(
        "body",
        [
            "verdict: medium-high\n\nLa seduta.",
            "verdict: perfection itself\n\nAltro.",
            "verdict: lowish day\n\nAltro.",
            "verdict: high resting heart rate this week, and it held.",
            "verdict:\n  high\n\nLa parola sulla riga dopo non e' un voto.",
        ],
    )
    def test_prose_is_not_a_verdict(self, body):
        from training.api.app import _verdict

        word, kept = _verdict(body)
        assert word is None
        assert kept == body, "e il testo non si tocca"

    def test_only_training_has_its_first_line_stripped(self, tmp_path):
        """La riga si chiede alla sola Training (`refresh.py`), e
        `models.py` lo dichiara: su un'altra sezione quella frase e' testo."""
        from training.api.app import _fragment_sections

        folder = tmp_path / "2026-10-01"
        folder.mkdir()
        (folder / "health.md").write_text("verdict: high\n\nIl corpo ha tenuto.", encoding="utf-8")
        (folder / "training.md").write_text("verdict: high\n\nBuona seduta.", encoding="utf-8")

        rows = {title: (body, verdict) for title, body, _written, verdict, _as_of in _fragment_sections(folder, DAILY)}
        health = next(v for k, v in rows.items() if k and "ealth" in k)
        training = next(v for k, v in rows.items() if k and "rain" in k)

        assert health == ("verdict: high\n\nIl corpo ha tenuto.", None)
        assert training == ("Buona seduta.", "high")


class TestStamp:
    """Il francobollo del todo 99: due date in cima al frammento, messe
    dall'orchestratore e tolte da chi legge."""

    def test_the_two_halves_agree(self, tmp_path):
        """Quello che scrive `refresh._stamp` lo rilegge `app._stamp`: le
        due meta' del patto stanno in due moduli, come il verdetto del todo
        92, ed e' la' che si scollano."""
        from datetime import datetime

        from training.api.app import _stamp as read
        from training.api.refresh import _stamp as write

        fragment = tmp_path / "health.md"
        fragment.write_text("verdict: high\n\nIl corpo ha tenuto.", encoding="utf-8")
        written_at = datetime(2026, 11, 23, 9, 21, 34)
        write(fragment, "2026-11-23", written_at)

        found, body = read(fragment.read_text(encoding="utf-8"))
        assert found["data_as_of"] == date(2026, 11, 23)
        assert found["written_at"] == written_at
        assert body == "verdict: high\n\nIl corpo ha tenuto.", "il testo non si tocca"

    def test_the_verdict_still_comes_off_underneath(self, tmp_path):
        """Il recinto sta sopra il verdetto: chi legge toglie prima l'uno e
        poi l'altro, e la Training deve uscirne con tutti e due via."""
        from datetime import datetime

        from training.api.refresh import _stamp as write

        folder = tmp_path / "2026-11-23"
        folder.mkdir()
        fragment = folder / "training.md"
        fragment.write_text("verdict: high\n\nBuona seduta.", encoding="utf-8")
        write(fragment, "2026-11-23", datetime(2026, 11, 23, 21, 0, 0))

        rows = {
            title: (body, written, verdict, as_of)
            for title, body, written, verdict, as_of in _fragment_sections(folder, DAILY)
        }
        body, written, verdict, as_of = next(v for k, v in rows.items() if k and "rain" in k)
        assert body == "Buona seduta."
        assert verdict == "high"
        assert as_of == date(2026, 11, 23)
        assert written == datetime(2026, 11, 23, 21, 0, 0), "l'ora del recinto, non l'mtime"

    def test_a_fragment_without_a_stamp_reads_as_before(self, tmp_path):
        """Sul disco ce ne sono centinaia scritti prima: niente recinto,
        niente date, e l'ora torna a essere quella del file."""
        folder = tmp_path / "2026-10-01"
        folder.mkdir()
        (folder / "health.md").write_text("Il corpo ha tenuto.", encoding="utf-8")

        rows = _fragment_sections(folder, DAILY)
        health = next(r for r in rows if r[0] and "ealth" in r[0])
        assert health[1] == "Il corpo ha tenuto."
        assert health[2] is not None, "l'mtime fa da ripiego"
        assert health[4] is None

    @pytest.mark.parametrize(
        "body",
        [
            "---\nqualcosa: altro\n---\n\nIl testo.",
            "---\ndata_as_of: non una data\n---\n\nIl testo.",
            "---\nIl corpo ha tenuto.\n---\n\nAltro.",
        ],
    )
    def test_a_fence_we_did_not_write_is_text(self, body):
        """Per sparire il recinto deve contenere soltanto quello che
        scriviamo noi: un `---` di un agente resta nella card."""
        from training.api.app import _stamp as read

        found, kept = read(body)
        assert found == {}
        assert kept == body, "e il testo non si tocca"

    def test_an_empty_stamp_is_not_a_crash(self, tmp_path):
        """La settimana non ha `health_data_up_to`: il recinto esce con la
        sola ora, e si rilegge lo stesso."""
        from datetime import datetime

        from training.api.app import _stamp as read
        from training.api.refresh import _stamp as write

        fragment = tmp_path / "summary.md"
        fragment.write_text("La settimana ha tenuto.", encoding="utf-8")
        write(fragment, None, datetime(2026, 11, 29, 21, 0, 0))

        found, body = read(fragment.read_text(encoding="utf-8"))
        assert "data_as_of" not in found
        assert found["written_at"] == datetime(2026, 11, 29, 21, 0, 0)
        assert body == "La settimana ha tenuto."
