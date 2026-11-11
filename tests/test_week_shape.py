"""Il grafico del blocco nella Training della settimana: **quando c'e'**.

Due condizioni, e sono due domande diverse: la settimana sta in un blocco —
il suo file dichiara un goal — e la settimana e' **chiusa**, cioe' ha il suo
commento, che il giro della domenica alle 21 scrive. Finche' una delle due
manca la rotta risponde 404, la pagina non disegna la card, e nessuna delle
due e' un errore.

Qui si prova la rotta e non il conto (quello sta in `test_block_shape.py`):
il contesto dell'utente si sostituisce con delle cartelle di `tmp_path`, cosi'
i file sono quelli che il test scrive.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from training.api.app import app
from training.api.context import UserContext, get_user_context

MONDAY = date(2026, 10, 26)
SLUG = "half_marathon_2.20"

GOAL = """---
race: 2027-02-28
target_time: "2:20:00"
distance_km: 21.0975
block_weeks: 18
current: true
---

# Half marathon in 2h20
"""

WEEK = """---
week: {monday}
plan: half_marathon_2.20
block_week: {number}
block_weeks: 2
phase: base
sessions:
  - {{date: {monday}, sport: rest}}
  - {{date: {sunday}, sport: running, kind: long, distance_km: 14}}
---

# Week {number}
"""

# Una settimana scritta che **non dichiara un goal**: il file c'e', il blocco
# no. Sono le settimane prima che il blocco cominciasse.
LOOSE_WEEK = """---
week: {monday}
sessions:
  - {{date: {monday}, sport: rest}}
---

# Una settimana fuori dal blocco
"""


@pytest.fixture
def dirs(tmp_path):
    """Un data root finto: due settimane del blocco, una fuori, e il goal."""
    data_dir = tmp_path / "data"
    for name in ("db", "fit", "health"):
        (data_dir / name).mkdir(parents=True)
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    (plan_dir / f"{SLUG}.md").write_text(GOAL)
    weeks = tmp_path / "summary" / "05.plan"
    weeks.mkdir(parents=True)
    for number in (1, 2):
        monday = MONDAY + timedelta(weeks=number - 1)
        (weeks / f"{monday.isoformat()}.md").write_text(
            WEEK.format(
                monday=monday.isoformat(),
                sunday=(monday + timedelta(days=6)).isoformat(),
                number=number,
            )
        )
    loose = MONDAY - timedelta(weeks=1)
    (weeks / f"{loose.isoformat()}.md").write_text(LOOSE_WEEK.format(monday=loose.isoformat()))
    return tmp_path / "summary", plan_dir, data_dir


@pytest.fixture
def client(dirs):
    summary_dir, plan_dir, data_dir = dirs
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        data_dir=data_dir, summary_dir=summary_dir, plan_dir=plan_dir
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def comment(summary_dir, monday: date, text: str = "La settimana e' andata cosi'.") -> None:
    """Il commento della settimana, cioe' il frammento che il giro della
    domenica alle 21 scrive."""
    folder = summary_dir / "02.weekly" / monday.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "training.md").write_text(text)


class TestWhenTheChartIsThere:
    def test_a_week_without_its_comment_has_no_chart(self, client, dirs):
        """E' la regola: il grafico arriva **col commento**. Una settimana del
        blocco di cui nessuno ha ancora scritto il Training non ne ha uno —
        non e' chiusa, e una settimana a meta' disegnata come una settimana
        cambierebbe a ogni apertura della pagina."""
        assert client.get(f"/api/weekly/{MONDAY}/shape").status_code == 404
        assert client.get(f"/api/weekly/{MONDAY}/shape/chart/vega").status_code == 404

    def test_the_comment_brings_the_chart(self, client, dirs):
        """Scritto il commento, la stessa settimana risponde: e' il momento
        della domenica sera, e dopo quello il grafico c'e'."""
        summary_dir, _, _ = dirs
        comment(summary_dir, MONDAY)

        answer = client.get(f"/api/weekly/{MONDAY}/shape")

        assert answer.status_code == 200
        data = answer.json()
        assert data["plan"] == SLUG
        assert [w["block_week"] for w in data["weeks"]] == [1, 2]
        spec = client.get(f"/api/weekly/{MONDAY}/shape/chart/vega")
        assert spec.status_code == 200
        assert spec.json()["$schema"].startswith("https://vega.github.io/schema/vega-lite")

    def test_an_empty_comment_does_not_count(self, client, dirs):
        """Un frammento da zero byte e' un agente che non ha scritto, non una
        settimana chiusa: e' la stessa regola di `_fragment_path`, dove il
        vuoto vale come assente."""
        summary_dir, _, _ = dirs
        comment(summary_dir, MONDAY, text="")

        assert client.get(f"/api/weekly/{MONDAY}/shape").status_code == 404

    def test_a_week_outside_any_block_has_no_chart(self, client, dirs):
        """L'altra condizione, e viene prima: un file che non dichiara un goal
        non ha niente contro cui misurarsi. Col commento o senza."""
        summary_dir, _, _ = dirs
        loose = MONDAY - timedelta(weeks=1)
        comment(summary_dir, loose)

        answer = client.get(f"/api/weekly/{loose}/shape")

        assert answer.status_code == 404
        assert "not part of a block" in answer.json()["detail"]

    def test_a_day_that_is_not_a_monday_is_refused(self, client):
        """Come tutte le rotte della settimana: 422, che e' una domanda
        sbagliata e non una risposta vuota."""
        assert client.get(f"/api/weekly/{MONDAY + timedelta(days=1)}/shape").status_code == 422
