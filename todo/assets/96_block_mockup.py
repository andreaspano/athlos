"""Il mockup dei tre pannelli del todo 96: Vega-Lite -> SVG -> PNG.

Le prime due settimane sono i dati veri del blocco half_marathon_2.20
(26 ottobre e 2 novembre 2026); dalla terza alla sesta sono inventate.
"""
import json
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent
BLOCK_WEEKS = 18
VIEWING = 3          # la settimana che la pagina sta mostrando

MUTED = "#6b7280"
GRID = "#e5e7eb"
INK = "#374151"

PANELS = [
    {
        "key": "volume", "title": "Volume", "unit": "km", "color": "#1098AD",
        "start": 26.0, "target": 46.0,
        "plan": [26, 30, 33, 26, 35, 38],
        "done": [31.5, 33.8, 34.5, 27.0, 36.5, 33.0],
    },
    {
        "key": "long_run", "title": "Long run", "unit": "km", "color": "#4A3AA7",
        "start": 14.0, "target": 21.097,
        "plan": [14, 15, 16, 12, 17, 18],
        "done": [14.8, 15.5, 16.2, 12.5, 17.5, 15.0],
    },
    {
        "key": "race_pace", "title": "Race pace", "unit": "km", "color": "#EB6834",
        "start": 8.0, "target": 21.097,
        "plan": None,                     # il piano non lo dichiara
        "done": [9.1, 7.7, 10.5, 5.0, 11.0, 9.5],
    },
]


def ratchet(values):
    best, out = None, []
    for v in values:
        best = v if best is None else max(best, v)
        out.append(best)
    return out


def rows(panel):
    """Una riga per settimana, coi valori in km e in percentuale."""
    target, start = panel["target"], panel["start"]
    pct = lambda v: 100.0 * v / target
    best = ratchet(panel["done"])
    out = []
    for i in range(6):
        week = i + 1
        row = {
            "week": week,
            "done": panel["done"][i],
            "done_pct": pct(panel["done"][i]),
            "best": best[i],
            "best_pct": pct(best[i]),
            # la diagonale: dalla partenza alla settimana zero, al bersaglio
            # alla fine del blocco
            "elapsed_pct": pct(start) + (100.0 - pct(start)) * week / BLOCK_WEEKS,
        }
        if panel["plan"] is not None:
            row["plan"] = panel["plan"][i]
            row["plan_pct"] = pct(panel["plan"][i])
        out.append(row)
    return out


# Gli assi vanno dichiarati **uguali su ogni strato**: in un `layer` basta un
# `axis: null` perche' l'asse unito sparisca del tutto.
X_AXIS = {"title": "block week", "labelAngle": 0, "grid": False,
          "titleColor": MUTED, "labelColor": MUTED, "titleFontSize": 10,
          "domainColor": GRID, "tickColor": GRID}


def x_enc(_=None):
    """La x di uno strato che sta sulle settimane. Le righe orizzontali non la
    mettono affatto: cosi' non portano un 'undefined' nel dominio ordinale e
    restano larghe quanto il pannello."""
    return {"field": "week", "type": "ordinal", "axis": X_AXIS}


def y_enc(field, title=None):
    return {
        "field": field, "type": "quantitative",
        "scale": {"domain": [0, 100]},     # dichiarata, e uguale nei tre pannelli
        "axis": {"title": title, "titleColor": MUTED,
                 "labelColor": MUTED, "titleFontSize": 10, "gridColor": GRID,
                 "domain": False, "tickColor": GRID, "format": "d"},
    }


def chart(panel, first):
    data = rows(panel)
    start_pct = 100.0 * panel["start"] / panel["target"]
    colore = panel["color"]
    # Il titolo della y solo sul primo pannello: la scala e' la stessa per
    # tutti e tre, e ripeterlo tre volte ruba larghezza ai grafici.
    titolo = "% of what the race asks" if first else None
    layers = []

    # la settimana che si sta guardando, dietro a tutto
    layers.append({
        "data": {"values": [{"week": VIEWING}]},
        "mark": {"type": "rect", "fill": "#eef0f3"},
        "encoding": {"x": x_enc()},
    })

    # il bersaglio e la partenza: solo y, quindi orizzontali e a tutta larghezza
    layers.append({
        "data": {"values": [{"y": 100}]},
        "mark": {"type": "rule", "stroke": MUTED, "strokeDash": [1, 3], "strokeWidth": 1},
        "encoding": {"y": y_enc("y", titolo)},
    })
    layers.append({
        "data": {"values": [{"y": start_pct}]},
        "mark": {"type": "rule", "stroke": MUTED, "strokeDash": [4, 3], "strokeWidth": 1.2},
        "encoding": {"y": y_enc("y", titolo)},
    })

    # le barre: previsto a contorno, fatto piena
    if panel["plan"] is not None:
        layers.append({
            "mark": {"type": "bar", "width": 9, "xOffset": -5.5, "fill": "#ffffff",
                     "stroke": MUTED, "strokeWidth": 1.1, "cornerRadiusEnd": 2},
            "encoding": {"x": x_enc(), "y": y_enc("plan_pct", titolo)},
        })
    layers.append({
        "mark": {"type": "bar", "width": 9 if panel["plan"] else 11,
                 "xOffset": 5.5 if panel["plan"] else 0,
                 "fill": colore, "fillOpacity": 0.85, "cornerRadiusEnd": 2},
        "encoding": {"x": x_enc(), "y": y_enc("done_pct", titolo)},
    })

    # il tempo trascorso
    layers.append({
        "mark": {"type": "line", "stroke": MUTED, "strokeDash": [5, 3], "strokeWidth": 1.5},
        "encoding": {"x": x_enc(), "y": y_enc("elapsed_pct", titolo)},
    })

    # il cricchetto
    layers.append({
        "mark": {"type": "line", "stroke": colore, "strokeWidth": 2.5,
                 "point": {"size": 55, "fill": colore, "stroke": "#ffffff", "strokeWidth": 1.5}},
        "encoding": {"x": x_enc(), "y": y_enc("best_pct", titolo)},
    })

    # le etichette dirette, una volta sola dove c'e' posto. Inchiostro e non
    # il colore della serie: il testo non porta identita' (regola dataviz).
    note = []
    if first:
        note = [
            {"week": 4, "y": 88, "t": "best so far", "a": "left"},
            {"week": 4, "y": 60, "t": "elapsed time", "a": "left"},
        ]
    elif panel["key"] == "race_pace":
        note = [
            {"week": 1, "y": 33, "t": "the start line", "a": "left"},
            {"week": 1, "y": 95, "t": "what the race asks", "a": "left"},
        ]
    for n in note:
        layers.append({
            "data": {"values": [n]},
            "mark": {"type": "text", "fontSize": 10.5, "align": n["a"], "color": INK,
                     "dx": -2 if n["a"] == "left" else 2},
            "encoding": {"x": x_enc(), "y": y_enc("y", titolo), "text": {"field": "t"}},
        })

    return {
        "title": {"text": panel["title"], "anchor": "start", "fontSize": 13,
                  "color": INK, "subtitle": subtitle(panel), "subtitleFontSize": 10,
                  "subtitleColor": MUTED},
        "width": 230,
        "height": 210,
        "data": {"values": data},
        "layer": layers,
    }


def subtitle(panel):
    """Corti e di larghezza simile: un sottotitolo piu' largo del pannello
    allarga la sua colonna, e i tre grafici smettono di essere equidistanti."""
    start, target = panel["start"], panel["target"]
    unit = panel["unit"]
    base = f"start {start:g} {unit} · race {target:g} {unit}"
    if panel["plan"] is None:
        return [base, "no plan bars: the block does not say"]
    return [base, " "]


spec = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "background": "#ffffff",
    "title": {
        "text": "Block — half marathon in 2h20, weeks 1-6 of 18",
        "subtitle": [
            "bars: one per week, outline = asked by the plan, filled = done   ·   line: the best so far   ·   dashed: elapsed time, from the start line to the race",
            "weeks 1-2 are measured (26 Oct, 2 Nov 2026); weeks 3-6 are made up.  The grey band is the week the page is showing.",
        ],
        "anchor": "start", "fontSize": 15, "color": INK,
        "subtitleFontSize": 10.5, "subtitleColor": MUTED, "subtitlePadding": 6,
        "offset": 8,
    },
    "config": {
        "view": {"stroke": None},
        "font": "Helvetica, Arial, sans-serif",
        "axis": {"labelFontSize": 10, "ticks": False, "labelPadding": 4},
    },
    "hconcat": [chart(p, i == 0) for i, p in enumerate(PANELS)],
    "spacing": 26,
}

vl = OUT / "96_block_mockup.vl.json"
svg = OUT / "96_block_mockup.svg"
png = OUT / "96_block_mockup.png"
vl.write_text(json.dumps(spec, indent=1))
subprocess.run([str(OUT.parents[1] / "frontend/node_modules/.bin/vl2svg"), str(vl), str(svg)], check=True)
import cairosvg
cairosvg.svg2png(url=str(svg), write_to=str(png), scale=2)
print("ok", png, png.stat().st_size, "bytes")
