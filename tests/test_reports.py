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


def test_every_fragment_row_has_four_values(tmp_path):
    """I due rami devono dare righe della stessa forma: era il disaccordo da
    cui veniva il 500."""
    folder = tmp_path / "2026-10-01"
    folder.mkdir()
    (folder / "health.md").write_text("Il corpo ha tenuto.", encoding="utf-8")

    rows = _fragment_sections(folder, DAILY)

    assert rows, "le sezioni ci sono tutte, anche senza frammento"
    assert all(len(row) == 4 for row in rows)


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

        rows = {title: (body, verdict) for title, body, _written, verdict in _fragment_sections(folder, DAILY)}
        health = next(v for k, v in rows.items() if k and "ealth" in k)
        training = next(v for k, v in rows.items() if k and "rain" in k)

        assert health == ("verdict: high\n\nIl corpo ha tenuto.", None)
        assert training == ("Buona seduta.", "high")
