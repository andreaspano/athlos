"""I due endpoint dei grafici di tendenza: **tutti i pannelli in una
risposta**.

Prima ce n'era uno per pannello, e la pagina ne chiamava cinque in
parallelo: la finestra dietro le serie si calcolava cinque volte e le cinque
corse di Altair si contendevano il GIL nei thread del server.
"""

import pytest
from fastapi.testclient import TestClient

from training.api.app import app
from training.garmin.config import DATA_DIR

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "db" / "activities.db").exists(), reason="serve l'archivio vero"
)
PANELS = ("health", "recovery", "load", "fitness", "training")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.mark.parametrize(
    "url",
    [
        "/api/daily/trend/charts/vega?from=2026-10-01&to=2026-10-31&theme=dark",
        "/api/weekly/trend/charts/vega?to=2026-10-26&weeks=8&theme=light",
    ],
)
def test_every_panel_comes_back_once(client, url):
    answer = client.get(url)

    assert answer.status_code == 200
    panels = answer.json()
    assert [p["key"] for p in panels] == list(PANELS), "nell'ordine delle card dello Snap"
    assert all("charts" in p for p in panels)


def test_each_chart_carries_its_spec(client):
    panels = client.get(
        "/api/daily/trend/charts/vega?from=2026-10-01&to=2026-10-31&theme=dark"
    ).json()

    charts = [chart for panel in panels for chart in panel["charts"]]
    assert charts, "qualche grafico c'e'"
    for chart in charts:
        assert set(chart) == {"key", "label", "spec"}
        assert chart["spec"].get("$schema", "").startswith("https://vega.github.io/schema/vega-lite")


def test_the_window_is_still_checked(client):
    """Il 422 della finestra non si perde cambiando la forma della
    risposta."""
    assert client.get("/api/daily/trend/charts/vega?from=2026-10-01&to=2026-09-01").status_code == 422
    assert client.get("/api/weekly/trend/charts/vega?to=2026-10-27").status_code == 422


def test_the_panel_parameter_is_gone(client):
    """Chi chiedesse ancora un pannello solo non deve ottenere mezza
    risposta: quel parametro non esiste piu', e di suo verrebbe ignorato —
    il controllo e' che l'endpoint vecchio non ci sia."""
    assert client.get(
        "/api/daily/trend/chart/vega?from=2026-10-01&to=2026-10-31&panel=load"
    ).status_code == 404
