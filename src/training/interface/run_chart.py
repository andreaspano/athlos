"""Il grafico a tre fasce della scheda di dettaglio (todo 28): battiti in
alto, velocita' reale ed equivalente in mezzo, pendenza in basso, con le
zone cardiache come bande verticali dietro a tutto.

I calcoli (bande, effetti, intervalli) sono separati dal disegno: le prime
funzioni lavorano sui record dell'attivita' (`db.load_activity_records`) e
non sanno niente di Altair. Il tempo in ascissa e' quello trascorso dalla
partenza, in minuti, pause comprese.

I parametri vengono da un grafico messo a punto fuori dal progetto sulla
corsa del 03/10/2026, e i valori attesi su quella corsa sono nel todo 28."""

import json
import math
import warnings

import altair as alt
import numpy as np
import pandas as pd

from training.interface.grade import (
    MODEL_SLOPE_LIMIT_PCT,
    rolling_mean,
    sample_seconds,
    segments,
    slope_pct,
)
from training.interface.sports import has_distance

BIN_S = 30
# Un intervallo con meno di 10 s di dati si scarta: 10 campioni a un record al
# secondo, ma contati in secondi, cosi' vale anche per i file piu' radi.
_MIN_SECONDS_PER_BIN = 10
_SPEED_SMOOTH = "30s"
_SLOPE_BAR_SMOOTH = "20s"
_HR_ZONE_SMOOTH = "45s"
_ZONE_MIN_BAND_S = 60
# Sotto queste frazioni della durata un'etichetta non ci sta e finirebbe
# sopra quella accanto: la zona, la media dei battiti, la scritta "pause".
_ZONE_LABEL_MIN_SHARE = 0.025
_AVG_LABEL_MIN_SHARE = 0.06
_PAUSE_LABEL_MIN_SHARE = 0.03

EFFECTS = ("Low aerobic", "High aerobic", "Anaerobic")

# Il passo (min/km) sull'asse di destra del pannello della velocita', solo
# per la corsa: chi corre legge il passo, non i km/h. L'asse e' lo stesso
# della velocita' (il passo e' 60 diviso i km/h), quindi si segnano dei passi
# tondi invece delle tacche che verrebbero dai km/h: 3:00, 3:30, 4:00 ... Sotto
# i 20:00 al km non si etichetta piu' niente, che e' gia' camminata piano.
_PACE_TICKS_S = (180, 210, 240, 270, 300, 330, 360, 420, 480, 600, 720, 900, 1200)
# Da km/h a "m:ss", dentro Vega: sull'asse il valore e' sempre una velocita'.
_PACE_LABEL = "format(floor(60 / datum.value), 'd') + ':' + format(round((60 / datum.value % 1) * 60), '02d')"

# Tema chiaro e scuro: gli stessi colori del grafico di riferimento. Le zone
# hanno un solo colore a intensita' crescente perche' verde e rosso sono gia'
# della pendenza; la velocita' reale e' nel colore del testo, perche' sul
# viola il blu si staccava poco.
#
# Todo 34: la discesa e' un grigio caldo e non piu' rosa, che resta solo
# all'anaerobico; il basso aerobico e' un colore pieno (non il viola a meta'
# trasparenza, che sul fondo delle zone alte spariva) e il fondo delle zone e'
# piu' leggero, cosi' le barre si staccano anche nelle ripetute in Z4.
_PALETTES = {
    "light": {
        "speed": "#0b0b0b",
        "equiv": "#eb6834",
        "up": "#008300",
        "down": "#a8a29e",
        "zone": "rgb(74,58,167)",
        "low_aerobic": "rgb(170,162,222)",
        "anaerobic": "#e87ba4",
        "zone_opacity": [0.02, 0.06, 0.11, 0.18, 0.26],
        "muted": "#6b7280",
    },
    "dark": {
        "speed": "#f0efec",
        "equiv": "#d95926",
        "up": "#199e70",
        "down": "#8f8983",
        "zone": "rgb(144,133,233)",
        "low_aerobic": "rgb(92,85,158)",
        "anaerobic": "#d55181",
        "zone_opacity": [0.03, 0.07, 0.12, 0.18, 0.24],
        "muted": "#9ca3af",
    },
}


def _elapsed_s(records: pd.DataFrame) -> np.ndarray:
    return (records.index - records.index[0]).total_seconds().to_numpy()


def durations_s(records: pd.DataFrame) -> pd.Series:
    """Quanti secondi vale ogni record, come serie indicizzata sui tempi.

    La regola sta in `grade.sample_seconds`, che la condivide con
    `db._zone_minutes`: i minuti per zona del database e i secondi per
    effetto del grafico devono venire dallo stesso conto."""
    return pd.Series(sample_seconds(records.index), index=records.index)


def pauses(records: pd.DataFrame) -> list[tuple[float, float]]:
    """Le pause, come (minuto di inizio, minuto di fine): dall'ultimo record
    di un tratto (piu' un secondo) al primo del tratto dopo."""
    if records.empty:
        return []
    t = _elapsed_s(records)
    seg = segments(records.index).to_numpy()
    starts = np.flatnonzero(np.diff(seg)) + 1
    return [((t[i - 1] + 1) / 60, t[i] / 60) for i in starts]


def zone_of(hr: float, bounds: list[int]) -> int:
    """La zona (1-5) dei battiti: 1 piu' i tetti superati."""
    return 1 + sum(hr > top for top in bounds)


def zone_bands(records: pd.DataFrame, bounds: list[int]) -> pd.DataFrame:
    """Le bande delle zone: inizio e fine in minuti, zona, media dei battiti.

    I battiti si lisciano a 45 s dentro ogni tratto e si raggruppano i
    secondi consecutivi nella stessa zona; ogni tratto sotto i 60 s si
    accorpa al vicino piu' lungo, poi si uniscono i vicini uguali, finche'
    non restano tratti corti. Senza lisciatura e accorpamento i battiti che
    oscillano intorno a una soglia fanno tante strisce sottili. La media e'
    sui battiti grezzi."""
    columns = ["start", "end", "zone", "hr"]
    hr_all = records["heart_rate"].astype(float)
    if hr_all.isna().all():
        return pd.DataFrame(columns=columns)
    smooth_all = rolling_mean(hr_all, _HR_ZONE_SMOOTH)
    t_all = _elapsed_s(records)
    seg_all = segments(records.index).to_numpy()

    bands = []
    for seg_id in np.unique(seg_all):
        mask = (seg_all == seg_id) & smooth_all.notna().to_numpy()
        if not mask.any():
            continue
        t = t_all[mask]
        hr = hr_all.to_numpy()[mask]
        zone = np.array([zone_of(h, bounds) for h in smooth_all.to_numpy()[mask]])

        runs, start = [], 0
        for i in range(1, len(t) + 1):
            if i == len(t) or zone[i] != zone[start]:
                runs.append([start, i - 1, int(zone[start])])
                start = i

        def length(run):
            return t[run[1]] - t[run[0]]

        changed = True
        while changed and len(runs) > 1:
            changed = False
            for i, run in enumerate(runs):
                if length(run) < _ZONE_MIN_BAND_S:
                    if i == 0:
                        j = 1
                    elif i == len(runs) - 1:
                        j = i - 1
                    else:
                        j = i - 1 if length(runs[i - 1]) >= length(runs[i + 1]) else i + 1
                    a, b = min(i, j), max(i, j)
                    runs[a] = [runs[a][0], runs[b][1], runs[j][2]]
                    del runs[b]
                    changed = True
                    break
            k = 0
            while k < len(runs) - 1:
                if runs[k][2] == runs[k + 1][2]:
                    runs[k] = [runs[k][0], runs[k + 1][1], runs[k][2]]
                    del runs[k + 1]
                else:
                    k += 1

        for a, b, z in runs:
            bands.append([t[a] / 60, (t[b] + 1) / 60, z, float(np.nanmean(hr[a : b + 1]))])
    return pd.DataFrame(bands, columns=columns)


def zone_settings(activity) -> tuple[list[int] | None, int | None]:
    """I tetti di Z1-Z4 e la soglia anaerobica salvati dal FIT, o None (file
    vecchi senza il messaggio delle zone). `activity` e' una riga di
    `list_activities`: nel database i tetti sono testo JSON."""
    bounds = json.loads(activity.hr_zone_bounds) if isinstance(activity.hr_zone_bounds, str) else None
    threshold = int(activity.threshold_hr) if pd.notna(activity.threshold_hr) else None
    return bounds, threshold


def has_effects(bounds: list[int] | None, threshold_hr: int | None) -> bool:
    """Se le soglie bastano per gli effetti: servono i tetti delle zone e una
    soglia anaerobica sopra il tetto di Z3. Alcune attivita' (la palestra)
    salvano la soglia a zero."""
    return bool(bounds) and threshold_hr is not None and threshold_hr > bounds[2]


def effect_of(hr: float, bounds: list[int], threshold_hr: int) -> str:
    """L'effetto stimato dai battiti: basso aerobico fino al tetto di Z3, alto
    aerobico fino alla soglia anaerobica, anaerobico sopra."""
    if hr <= bounds[2]:
        return EFFECTS[0]
    if hr <= threshold_hr:
        return EFFECTS[1]
    return EFFECTS[2]


def effects(records: pd.DataFrame, bounds: list[int], threshold_hr: int) -> dict[str, float]:
    """I secondi passati in ciascun effetto, sui battiti grezzi.

    E' una stima: Garmin calcola il Training Effect con un algoritmo suo, e
    nel file salva solo i totali della sessione."""
    hr = records["heart_rate"].astype(float)
    seconds = durations_s(records)
    result = dict.fromkeys(EFFECTS, 0.0)
    for value, duration in zip(hr, seconds):
        if pd.notna(value):
            result[effect_of(value, bounds, threshold_hr)] += duration
    return result


def bins(records: pd.DataFrame) -> pd.DataFrame:
    """Una riga per intervallo di 30 s con almeno 10 s di dati: minuto di
    inizio, di centro e di fine, velocita' (lisciata a 30 s), velocita'
    equivalente, pendenza (lisciata a 20 s, in % e in
    gradi) e battiti medi.

    La velocita' equivalente nel database e' grezza (`grade.equivalent_speed_series`):
    la media dell'intervallo e' gia' la sua lisciatura a 30 s, e una media
    mobile in piu' prima la spostava dai valori del grafico di riferimento.

    Le colonne senza dato restano vuote: una bici non ha velocita'
    equivalente, una palestra non ha ne' velocita' ne' pendenza."""
    t = _elapsed_s(records)
    frame = pd.DataFrame(index=records.index)
    frame["bin"] = (t // BIN_S).astype(int)
    frame["seconds"] = durations_s(records).to_numpy()
    frame["hr"] = records["heart_rate"].astype(float)
    frame["speed"] = rolling_mean(records["speed_kmh"], _SPEED_SMOOTH)
    frame["equiv"] = records["equiv_speed_kmh"].astype(float)
    frame["slope_pct"] = rolling_mean(slope_pct(records), _SLOPE_BAR_SMOOTH)

    grouped = frame.groupby("bin")
    out = grouped[["hr", "speed", "equiv", "slope_pct"]].mean()
    out = out[grouped["seconds"].sum() >= _MIN_SECONDS_PER_BIN]
    # Le barre si fermano dove si ferma il modello di costo (±45%, circa 24
    # gradi): oltre e' quasi sempre un salto dell'altimetro da fermi, e una
    # barra sola schiaccerebbe tutte le altre.
    out["slope_pct"] = out["slope_pct"].clip(-MODEL_SLOPE_LIMIT_PCT, MODEL_SLOPE_LIMIT_PCT)
    out["slope_deg"] = np.degrees(np.arctan(out["slope_pct"] / 100))
    out["start"] = out.index * BIN_S / 60
    out["end"] = (out.index + 1) * BIN_S / 60
    out["minute"] = (out["start"] + out["end"]) / 2
    return out.reset_index()


def _clock(minutes: float) -> str:
    seconds = round(minutes * 60)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _ceil(value: float, step: float = 1) -> float:
    return max(step, math.ceil(value / step) * step)




def run_analysis_chart(
    records: pd.DataFrame,
    bounds: list[int] | None,
    threshold_hr: int | None,
    theme: str = "light",
    sport: str | None = None,
) -> alt.VConcatChart | None:
    """Il grafico a tre fasce, o None se non c'e' niente da disegnare.

    Ogni pannello c'e' solo se c'e' il suo dato: battiti se c'e' la FC,
    velocita' se c'e' la velocita' ed e' uno sport che ha una distanza,
    pendenza se ci sono quota e distanza. La
    linea equivalente c'e' solo se il database ha `equiv_speed_kmh` (gli sport
    a piedi). Senza `bounds` niente bande, senza `threshold_hr` niente
    effetti. I pannelli hanno ognuno la sua scala: velocita' e pendenza non si
    confrontano in altezza, e i battiti non partono da zero.

    Con `sport` "running" il pannello della velocita' ha anche il passo
    (min/km) sull'asse di destra: stessa scala, altre etichette."""
    if records.empty:
        return None
    palette = _PALETTES.get(theme, _PALETTES["light"])
    data = bins(records)
    if data.empty:
        return None

    # Il passo si mostra solo a chi corre, come l'asse di destra: in bici e
    # sugli sci i km/h sono la lettura giusta.
    with_pace = sport == "running"
    has_hr = data["hr"].notna().any()
    # Gli sport senza distanza (il tapis roulant, todo 45) non hanno nemmeno
    # una velocita' da disegnare: quella nei record e' la stessa stima del
    # polso che altrove non mostriamo, solo campione per campione.
    has_speed = has_distance(sport) and (data["speed"] > 0).any()
    has_slope = data["slope_pct"].notna().any()
    has_equiv = data["equiv"].notna().any()
    if not (has_hr or has_speed):
        return None
    with_zones = bool(bounds) and has_hr
    with_effects = with_zones and has_effects(bounds, threshold_hr)

    t = _elapsed_s(records)
    total_min = (t[-1] + 1) / 60
    x_scale = alt.Scale(domain=[0, total_min], nice=False, zero=True)
    # Un po' di stacco fra le barre, proporzionale all'intervallo.
    data["bar_end"] = data["end"] - BIN_S / 60 * 0.15

    # Il tooltip e' uno solo per tutti i pannelli: ogni colonna che manca
    # resta fuori invece di comparire vuota.
    data["time"] = data["start"].map(_clock) + "–" + data["end"].map(_clock)
    tooltip = [alt.Tooltip("time:N", title="Time")]
    if has_hr:
        tooltip.append(alt.Tooltip("hr:Q", title="HR (bpm)", format=".0f"))
    if with_zones:
        data["zone"] = data["hr"].map(lambda h: f"Z{zone_of(h, bounds)}" if pd.notna(h) else None)
        tooltip.append(alt.Tooltip("zone:N", title="Zone"))
    if with_effects:
        data["effect"] = data["hr"].map(
            lambda h: effect_of(h, bounds, threshold_hr) if pd.notna(h) else None
        )
        tooltip.append(alt.Tooltip("effect:N", title="Effect (estimated)"))
    if has_speed:
        tooltip.append(alt.Tooltip("speed:Q", title="Speed (km/h)", format=".1f"))
        # Il passo accanto alla velocita', per chi corre: e' la stessa cosa
        # letta al contrario (60 diviso i km/h), ed e' quella che un podista
        # ha in testa. Si calcola qui invece che in Vega perche' `_clock` da'
        # gia' "m:ss", lo stesso formato delle tacche dell'asse di destra.
        # Da fermo non esiste un passo: resta un trattino.
        if with_pace:
            data["pace"] = data["speed"].map(
                lambda kmh: _clock(60 / kmh) if pd.notna(kmh) and kmh > 0 else "–"
            )
            tooltip.append(alt.Tooltip("pace:N", title="Pace (min/km)"))
    if has_equiv:
        tooltip.append(alt.Tooltip("equiv:Q", title="Grade-adjusted (km/h)", format=".1f"))
    if has_slope:
        tooltip.append(alt.Tooltip("slope_deg:Q", title="Slope (°)", format=".1f"))
        tooltip.append(alt.Tooltip("slope_pct:Q", title="Slope (%)", format=".1f"))

    hover = alt.selection_point(
        name="hovered", fields=["start"], nearest=True, on="pointermove", empty=False, clear="pointerout"
    )
    base = alt.Chart(data)
    bands = zone_bands(records, bounds) if with_zones else pd.DataFrame()
    pause_list = pauses(records)

    def background(x_axis: alt.Axis) -> list:
        """Le bande delle zone, a tutta altezza, e il crosshair: in ogni
        pannello, con le stesse x, cosi' sembrano una banda sola."""
        layers = []
        if not bands.empty:
            layers.append(
                alt.Chart(bands)
                .mark_rect(color=palette["zone"])
                .encode(
                    x=alt.X("start:Q", scale=x_scale, axis=x_axis),
                    x2="end:Q",
                    opacity=alt.Opacity(
                        "zone:O",
                        scale=alt.Scale(domain=[1, 2, 3, 4, 5], range=palette["zone_opacity"]),
                        legend=None,
                    ),
                )
            )
        return layers

    def crosshair(x_axis: alt.Axis) -> list:
        # Il selettore e' una regola trasparente per intervallo: il punto piu'
        # vicino al mouse lungo x accende la stessa regola in tutti i pannelli.
        rule = (
            base.mark_rule(color=palette["muted"], strokeDash=[4, 4])
            .encode(
                x=alt.X("minute:Q", scale=x_scale, axis=x_axis),
                opacity=alt.condition(hover, alt.value(1), alt.value(0)),
                tooltip=tooltip,
            )
            .add_params(hover)
        )
        return [rule]

    panels = []
    panel_count = sum([has_hr, has_speed, has_slope])

    def axis_for(position: int) -> alt.Axis:
        """L'asse del tempo: con le etichette solo nel pannello in fondo, che
        basta leggerle una volta; sopra, stessa scala e niente scritte."""
        if position == panel_count - 1:
            return alt.Axis(title="Elapsed time (min)")
        return alt.Axis(labels=False, ticks=False, title=None)

    position = 0
    if has_hr:
        x_axis = axis_for(position)
        x = alt.X("start:Q", scale=x_scale, axis=x_axis)
        position += 1
        hr_low = math.floor(data["hr"].min() / 10) * 10
        hr_high = _ceil(data["hr"].max(), 10)
        hr_scale = alt.Scale(domain=[hr_low, hr_high], zero=False, nice=False)
        y = alt.Y("hr:Q", title="HR (bpm)", scale=hr_scale, axis=alt.Axis(tickCount=3))
        color = (
            alt.Color(
                "effect:N",
                title="Effect (estimated)",
                scale=alt.Scale(
                    domain=list(EFFECTS),
                    range=[palette["low_aerobic"], palette["zone"], palette["anaerobic"]],
                ),
                legend=alt.Legend(orient="bottom", title=None),
            )
            if with_effects
            else alt.value(palette["zone"])
        )
        layers = background(x_axis)
        layers.append(
            base.mark_bar(clip=True)
            .encode(x=x, x2="bar_end:Q", y=y, y2=alt.datum(hr_low), color=color)
        )
        if with_effects:
            # Le due soglie degli effetti, sopra le barre, e il nome di ogni
            # fascia sul bordo destro, a meta' fra le soglie (se ci cade).
            limits = [hr_low, bounds[2], threshold_hr, hr_high]
            rules = pd.DataFrame({"y": [bounds[2], threshold_hr]})
            rules = rules[(rules["y"] > hr_low) & (rules["y"] < hr_high)]
            if not rules.empty:
                layers.append(
                    alt.Chart(rules)
                    .mark_rule(color=palette["muted"], strokeDash=[4, 3])
                    .encode(y=alt.Y("y:Q", scale=hr_scale))
                )
            labels = pd.DataFrame(
                {
                    "label": [e.lower() for e in EFFECTS],
                    "y": [(max(lo, hr_low) + min(hi, hr_high)) / 2 for lo, hi in zip(limits, limits[1:])],
                    "visible": [min(hi, hr_high) - max(lo, hr_low) >= (hr_high - hr_low) * 0.15
                                for lo, hi in zip(limits, limits[1:])],
                }
            )
            labels = labels[labels["visible"]]
            if not labels.empty:
                layers.append(
                    alt.Chart(labels)
                    .mark_text(align="right", baseline="middle", dx=-4, fontSize=10, color=palette["muted"])
                    .encode(x=alt.datum(total_min, scale=x_scale), y=alt.Y("y:Q", scale=hr_scale), text="label:N")
                )
        # Sopra il pannello piu' in alto, la zona di ogni banda e, se la banda
        # e' abbastanza larga, la media dei battiti; e "pause" sulle pause.
        if position == 1 and not bands.empty:
            band_labels = bands.assign(
                mid=(bands["start"] + bands["end"]) / 2,
                zone_label="Z" + bands["zone"].astype(str),
                avg_label=bands["hr"].map(lambda h: f"avg {h:.0f}"),
                labelled=(bands["end"] - bands["start"]) >= total_min * _ZONE_LABEL_MIN_SHARE,
                wide=(bands["end"] - bands["start"]) >= total_min * _AVG_LABEL_MIN_SHARE,
            )
            layers.append(
                alt.Chart(band_labels[band_labels["labelled"]])
                .mark_text(baseline="bottom", fontSize=11, fontWeight="bold", color=palette["zone"])
                .encode(x=alt.X("mid:Q", scale=x_scale), y=alt.value(-14), text="zone_label:N")
            )
            layers.append(
                alt.Chart(band_labels[band_labels["wide"]])
                .mark_text(baseline="bottom", fontSize=10, color=palette["muted"])
                .encode(x=alt.X("mid:Q", scale=x_scale), y=alt.value(-2), text="avg_label:N")
            )
        if position == 1 and pause_list:
            pause_frame = pd.DataFrame(pause_list, columns=["start", "end"])
            pause_frame["mid"] = (pause_frame["start"] + pause_frame["end"]) / 2
            pause_frame = pause_frame[
                pause_frame["end"] - pause_frame["start"] >= total_min * _PAUSE_LABEL_MIN_SHARE
            ]
            layers.append(
                alt.Chart(pause_frame)
                .mark_text(baseline="bottom", fontSize=10, fontStyle="italic", color=palette["muted"])
                .encode(x=alt.X("mid:Q", scale=x_scale), y=alt.value(-14), text=alt.value("pause"))
            )
        layers.extend(crosshair(x_axis))
        panels.append(alt.layer(*layers).properties(height=130, width="container"))

    if has_speed:
        x_axis = axis_for(position)
        position += 1
        # Le linee si interrompono dove manca un intervallo (pause, o tratti
        # con troppo pochi campioni): una riga vuota per ogni buco.
        full = data.set_index("bin").reindex(range(data["bin"].min(), data["bin"].max() + 1))
        full["start"] = (full.index + 0.5) * BIN_S / 60
        series = {"speed": "Speed"}
        if has_equiv:
            series["equiv"] = "Grade-adjusted"
        lines = full[["start", *series]].rename(columns=series).melt(
            id_vars="start", var_name="series", value_name="kmh"
        )
        speed_high = _ceil(np.nanmax(full[list(series)].to_numpy()))
        y_scale = alt.Scale(domain=[0, speed_high], nice=False)
        layers = background(x_axis)
        pace_axis = False
        if sport == "running":
            # Una riga trasparente solo per portare il secondo asse: la scala
            # e' la stessa della velocita', quindi le due letture non possono
            # discordare.
            pace_speeds = [3600 / seconds for seconds in _PACE_TICKS_S]
            pace_speeds = [kmh for kmh in pace_speeds if 0 < kmh <= speed_high]
            if pace_speeds:
                pace_axis = True
                layers.append(
                    alt.Chart(pd.DataFrame({"kmh": [speed_high]}))
                    .mark_rule(opacity=0)
                    .encode(
                        y=alt.Y(
                            "kmh:Q",
                            scale=y_scale,
                            title="Pace (min/km)",
                            axis=alt.Axis(
                                orient="right",
                                values=pace_speeds,
                                labelExpr=_PACE_LABEL,
                                grid=False,
                            ),
                        )
                    )
                )
        # Con intervalli tutti isolati (una vasca in piscina ha pochi record)
        # una linea non si vedrebbe: allora i punti.
        isolated = not (data["bin"].diff() == 1).any()
        layers.append(
            alt.Chart(lines)
            .mark_line(strokeWidth=2, point=isolated)
            .encode(
                x=alt.X("start:Q", scale=x_scale, axis=x_axis),
                y=alt.Y("kmh:Q", title="Speed (km/h)", scale=y_scale),
                color=alt.Color(
                    "series:N",
                    scale=alt.Scale(domain=list(series.values()), range=[palette["speed"], palette["equiv"]][: len(series)]),
                    legend=alt.Legend(orient="bottom", title=None),
                ),
                strokeDash=alt.StrokeDash(
                    "series:N",
                    scale=alt.Scale(domain=list(series.values()), range=[[1, 0], [5, 3]][: len(series)]),
                    legend=None,
                ),
            )
        )
        layers.extend(crosshair(x_axis))
        speed_panel = alt.layer(*layers).properties(height=260, width="container")
        if pace_axis:
            # Le due scale devono restare separate, se no Vega-Lite unisce i
            # due assi in uno solo a destra e il titolo diventa "Pace
            # (min/km), Speed (km/h)". Separate ma con lo stesso `y_scale`:
            # non possono dire due cose diverse.
            speed_panel = speed_panel.resolve_scale(y="independent")
        panels.append(speed_panel)

    if has_slope:
        x_axis = axis_for(position)
        x = alt.X("start:Q", scale=x_scale, axis=x_axis)
        position += 1
        data["slope_abs"] = data["slope_deg"].abs()
        data["direction"] = np.where(data["slope_deg"] >= 0, "Uphill", "Downhill")
        slope_base = alt.Chart(data)
        layers = background(x_axis)
        layers.append(
            slope_base.mark_bar(opacity=0.8)
            .encode(
                x=x,
                x2="bar_end:Q",
                y=alt.Y(
                    "slope_abs:Q",
                    title="Slope (°)",
                    scale=alt.Scale(domain=[0, _ceil(data["slope_abs"].max())], nice=False),
                    # A sinistra come gli altri due pannelli, per
                    # uniformita'. Un tempo a destra la pagina tagliava
                    # l'asse (tacche, numeri e titolo spariti); non succede
                    # piu' da quando il frontend chiede `autosize: fit-x,
                    # contains: padding` (`RunChart.themeConfig`), e si vede
                    # dal passo del pannello della velocita', che sta a
                    # destra e ci sta tutto anche a finestra stretta.
                    axis=alt.Axis(tickCount=3),
                ),
                y2=alt.datum(0),
                color=alt.Color(
                    "direction:N",
                    scale=alt.Scale(domain=["Uphill", "Downhill"], range=[palette["up"], palette["down"]]),
                    legend=alt.Legend(orient="bottom", title=None),
                ),
            )
        )
        layers.extend(crosshair(x_axis))
        panels.append(alt.layer(*layers).properties(height=100, width="container"))

    # Lo stesso `hover` sta in tutti i pannelli apposta, perche' il crosshair
    # si muova insieme su tutti: Altair lo unisce in un parametro solo e lo
    # segnala con un avviso, che qui non dice niente di nuovo.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Automatically deduplicated selection parameter")
        chart = alt.vconcat(*panels, spacing=8)
    return (
        chart
        .resolve_scale(color="independent", opacity="independent", strokeDash="independent")
        .properties(
            description="Activity chart over elapsed time: heart rate"
            + (" with heart-rate zones" if with_zones else "")
            + (", speed and grade-adjusted speed" if has_equiv else ", speed" if has_speed else "")
            + (", and slope in degrees" if has_slope else "")
            + "."
        )
    )


# Oltre questa ampiezza i pallini sui punti si impastano e restano le linee.
TREND_POINTS_UP_TO_DAYS = 60
# L'altezza di un grafico del Trend: bassa, perche' sono una ventina sulla
# stessa pagina e si leggono a colpo d'occhio, non uno alla volta.
TREND_HEIGHT = 110


# I colori delle card del Report (`styles.css`): ogni pannello del Trend
# prende quelli della sua, cosi' le due viste si leggono come la stessa cosa
# e non come due applicazioni diverse. `line` e' la tinta piena dell'icona
# della card, `band` il suo `--range-fill` e `wide` il `--range-wide-fill`:
# gli stessi tre livelli delle barre delle fasce, solo stesi su un'area
# invece che su una barra alta otto pixel.
TREND_PALETTES: dict[str, dict[str, dict[str, str]]] = {
    "health": {
        "light": {"line": "rgb(74,58,167)", "band": "rgb(170,162,222)", "wide": "rgb(74,58,167)"},
        "dark": {"line": "rgb(144,133,233)", "band": "rgb(92,85,158)", "wide": "rgb(144,133,233)"},
    },
    "recovery": {
        "light": {"line": "rgb(194,37,92)", "band": "rgb(226,153,178)", "wide": "rgb(194,37,92)"},
        "dark": {"line": "rgb(218,124,157)", "band": "rgb(171,69,105)", "wide": "rgb(218,124,157)"},
    },
    "load": {
        "light": {"line": "rgb(16,152,173)", "band": "rgb(136,203,214)", "wide": "rgb(16,152,173)"},
        "dark": {"line": "rgb(110,200,215)", "band": "rgb(50,122,138)", "wide": "rgb(110,200,215)"},
    },
    "fitness": {
        "light": {"line": "rgb(37,99,200)", "band": "rgb(154,184,232)", "wide": "rgb(37,99,200)"},
        "dark": {"line": "rgb(130,170,230)", "band": "rgb(70,108,166)", "wide": "rgb(130,170,230)"},
    },
}

# Il pannello Training non ha un colore solo: le sue serie sono i tre effetti,
# che nella card hanno gia' il loro (`--low`, `--high`, `--anaerobic`, gli
# stessi di `_PALETTES`). La distanza prende l'arancione della velocita'
# equivalente e il dislivello il verde della salita, gli stessi due che hanno
# nel grafico della seduta: le altre misure, che devono staccare dai tre.
TREND_TRAINING_COLORS = {
    "min_low_aerobic": "low_aerobic",
    "min_high_aerobic": "zone",
    "min_anaerobic": "anaerobic",
    "total_distance_km": "equiv",
    "total_ascent_m": "up",
}

# Sulla barra della card la fascia stretta e' una tinta piena; qui copre meta'
# del riquadro, e piena coprirebbe la linea. Queste sono le opacita' con cui
# le stesse tinte restano leggibili stese su un'area: la larga e' quella che
# `--range-wide-fill` ha gia' nel CSS.
TREND_BAND_OPACITY = {"light": 0.38, "dark": 0.32}
TREND_WIDE_OPACITY = {"light": 0.16, "dark": 0.22}


def palette_muted(theme: str) -> str:
    """Il grigio del tema, per i testi di contorno dei grafici del Trend."""
    return _PALETTES.get(theme, _PALETTES["light"])["muted"]


def _trend_colors(panel: str, series_key: str, theme: str) -> dict[str, str]:
    """I colori di una serie: quelli della card a cui il pannello
    corrisponde, o quelli del suo effetto nel pannello Training."""
    if panel in TREND_PALETTES:
        return TREND_PALETTES[panel].get(theme, TREND_PALETTES[panel]["light"])
    palette = _PALETTES.get(theme, _PALETTES["light"])
    tinta = palette[TREND_TRAINING_COLORS.get(series_key, "zone")]
    return {"line": tinta, "band": tinta, "wide": tinta}


def _trend_text(values, digits: int) -> list[str]:
    """I valori gia' scritti per il tooltip, con i decimali della misura, che
    Vega non conosce.

    Attenzione a cosa si passa: il `None` va riconosciuto, e una colonna di
    pandas al posto suo porta `NaN`, che `is None` non intercetta. Il Trend
    della Day passa la colonna e quindi sui giorni non misurati il tooltip
    scrive "nan" - e' cosi' da prima del todo 78 e non si tocca qui. Il Trend
    della Week passa la lista dei valori, dove il nullo e' nullo davvero."""
    return [
        "-" if v is None else (f"{v:.{digits}f}" if digits else f"{v:.0f}")
        for v in values
    ]


def _trend_hover(data: pd.DataFrame, x: str, tooltip: list, theme: str) -> alt.Chart:
    """La barra verticale che segue il mouse, e che porta il tooltip.

    `nearest` costruisce una tassellatura sulla x: il punto lo sceglie la
    vicinanza, quindi la barra si prende tutta l'altezza della colonna e
    funziona anche dove i pallini non ci sono. La stessa barra porta il
    tooltip, cosi' il numero si legge dovunque nella colonna invece che solo
    centrando il punto - e su una barra alta zero, nel Training della Week, e'
    l'unico modo di leggerlo."""
    vicino = alt.selection_point(
        name="hover",
        nearest=True,
        on="pointerover",
        clear="pointerout",
        encodings=["x"],
        empty=False,
    )
    return (
        alt.Chart(data)
        .mark_rule(color=palette_muted(theme), strokeWidth=1)
        .encode(
            x=alt.X(f"{x}:T", title=None),
            opacity=alt.condition(vicino, alt.value(0.8), alt.value(0)),
            tooltip=tooltip,
        )
        .add_params(vicino)
    )


def _trend_y(unit: str | None, theme: str, zero: bool) -> alt.Y:
    """L'asse y di un grafico del Trend: l'unita' sopra i numeri, orizzontale e
    allineata a destra sulla riga dell'asse. Girata lungo l'asse si leggerebbe
    una alla volta, e sono venti grafici bassi uno sotto l'altro.

    `zero` e' l'unica cosa che cambia fra una linea e una barra, ed e'
    importante in tutte e due i versi. Una **linea** su una misura che oscilla
    fra 49 e 52 schiacciata sullo zero sarebbe piatta, quindi `zero=False`. Una
    **barra** invece parte da zero per forza, o la sua altezza mente."""
    return alt.Y(
        "value:Q",
        title=unit,
        scale=alt.Scale(zero=zero, nice=True),
        axis=alt.Axis(
            titleFontSize=10,
            labelFontSize=10,
            titleAngle=0,
            titleAlign="right",
            titleX=0,
            titleY=-7,
            titleBaseline="bottom",
            titleColor=palette_muted(theme),
        ),
    )


def _trend_line(
    data: pd.DataFrame, x: str, colors: dict, unit: str | None, theme: str, with_points: bool
) -> alt.Chart:
    """La linea di una serie, coi pallini dove non si impastano."""
    return (
        alt.Chart(data)
        .mark_line(
            color=colors["line"],
            strokeWidth=2,
            point=alt.OverlayMarkDef(color=colors["line"], size=22) if with_points else False,
        )
        .encode(
            x=alt.X(f"{x}:T", title=None, axis=alt.Axis(format="%d %b", tickCount=5)),
            y=_trend_y(unit, theme, zero=False),
        )
    )


def _trend_bars(data: pd.DataFrame, x: str, colors: dict, unit: str | None, theme: str) -> alt.Chart:
    """Le barre di una serie, al posto della linea.

    Le vuole il pannello Training della Week (todo 78): una somma settimanale e'
    una quantita', e le quantita' si leggono a barre. Risolvono da se' due cose
    che sulla linea erano scomode - una settimana di riposo e' uno zero vero, e
    una barra alta zero si legge come zero invece che come un avvallamento fra
    due punti; e una settimana senza sedute non ha niente da spezzare."""
    return (
        alt.Chart(data)
        .mark_bar(color=colors["line"])
        .encode(
            x=alt.X(f"{x}:T", title=None, axis=alt.Axis(format="%d %b", tickCount=5)),
            y=_trend_y(unit, theme, zero=True),
        )
    )


def _trend_frame(strati: list[alt.Chart], label: str) -> alt.Chart:
    """Il telaio: gli strati sovrapposti, l'altezza fissa, la larghezza del
    contenitore e il nome della misura come titolo in alto a sinistra.

    E' una vista **a strati**, non composta: `width: "container"` dentro un
    `facet` o un `vconcat` viene largo zero (todo 52), mentre con `layer`
    funziona."""
    return alt.layer(*strati).properties(
        height=TREND_HEIGHT,
        width="container",
        title=alt.TitleParams(label, anchor="start", fontSize=11, offset=6, dy=-2),
    )


def trend_chart(series: dict, days: int, theme: str = "light", panel: str = "health") -> alt.Chart | None:
    """Una serie del Trend (todo 55): la linea giorno per giorno, con la
    fascia di `_band` come sfondo.

    Un grafico **per serie** e non per pannello: dentro un pannello le misure
    non hanno la stessa unita' (il VO2max sta a 42, il punteggio di resistenza
    a 5000), e su un asse solo la linea bassa diventa piatta. Ognuno tiene il
    suo asse nei numeri veri.

    E' una vista **a strati**, non composta: `width: "container"` dentro un
    `facet` o un `vconcat` viene largo zero (todo 52), mentre con `layer`
    funziona - e' gia' cosi' che si disegnano le barre della settimana.

    I giorni senza misura arrivano con `value` nullo e non si tolgono: la
    linea si spezza li', invece di unire i due estremi di un buco.

    `None` se nella finestra non c'e' nemmeno un valore."""
    points = [p for p in series["points"] if p["value"] is not None]
    if not points:
        return None
    colors = _trend_colors(panel, series["key"], theme)
    # Il nome della misura e la sua unita' stanno in due posti diversi: il
    # nome e' il titolo del grafico, in alto a sinistra e orizzontale;
    # l'unita' e' il titolo dell'asse y, sopra i numeri a cui si riferisce.
    # Le misure senza unita' (i punteggi, i carichi, il rapporto) l'asse lo
    # lasciano muto.
    unit = series.get("unit")

    data = pd.DataFrame(series["points"])
    data["day"] = pd.to_datetime(data["day"])
    digits = int(series.get("digits") or 0)
    data["testo"] = _trend_text(data["value"], digits)

    strati = []
    banda = series.get("band")
    if banda:
        # Due rettangoli senza `x`: presi per tutta la larghezza, come le
        # fasce delle barre della Day. Il piu' largo (due scarti tipo) sotto
        # e piu' chiaro, quello stretto sopra.
        # Una fascia a **un livello solo** (`outer` coincide con gli estremi,
        # cioe' scarto tipo zero: una misura ferma su un valore per tutta la
        # finestra) si disegna una volta: due rettangoli uguali sovrapposti
        # la scurirebbero e basta.
        un_livello = (
            banda.get("outer_low") == banda.get("low")
            and banda.get("outer_high") == banda.get("high")
        )
        livelli = (
            (("low", "high", colors["band"], TREND_BAND_OPACITY.get(theme, 0.38)),)
            if un_livello
            else (
                ("outer_low", "outer_high", colors["wide"], TREND_WIDE_OPACITY.get(theme, 0.16)),
                ("low", "high", colors["band"], TREND_BAND_OPACITY.get(theme, 0.38)),
            )
        )
        for low, high, tinta, opacity in livelli:
            if banda.get(low) is None or banda.get(high) is None:
                continue
            strati.append(
                alt.Chart(pd.DataFrame([{"low": banda[low], "high": banda[high]}]))
                .mark_rect(color=tinta, opacity=opacity)
                .encode(y=alt.Y("low:Q", title=unit), y2=alt.Y2("high:Q"))
            )

    tooltip = [
        alt.Tooltip("day:T", title="Day", format="%a %d %b %Y"),
        alt.Tooltip("testo:N", title=series["label"]),
    ]
    strati.append(_trend_hover(data, "day", tooltip, theme))
    strati.append(
        _trend_line(data, "day", colors, unit, theme, days <= TREND_POINTS_UP_TO_DAYS)
    )
    return _trend_frame(strati, series["label"])


def week_trend_chart(
    series: dict, weeks: int, theme: str = "light", panel: str = "health"
) -> alt.Chart | None:
    """Una serie del Trend della Week (todo 78): un punto per settimana, con la
    fascia di **ogni** settimana sotto.

    La differenza vera dal Trend della Day sta qui. La' la fascia e' una per
    tutta la finestra, e si disegna come due rettangoli senza `x`, larghi quanto
    il grafico. Qui cambia settimana per settimana - e' l'errore standard della
    media dei giorni di quella settimana - e due rettangoli non la possono dire:
    sono **due aree** con la `x` sui lunedi', una riga per settimana, nelle
    stesse due tinte e con le stesse due opacita' delle barre della card.

    Il pannello **Training** non ha fascia e si disegna a **barre**: una somma
    settimanale e' una quantita'. E' l'unico ramo che guarda il nome del
    pannello, e combacia con l'unico che la fascia gia' non ce l'ha, cosi'
    Training e' l'eccezione una volta sola e non due.

    Un telaio solo per tutti gli strati: le aree leggono le stesse righe della
    linea, quindi i lunedi' sono per costruzione gli stessi, e una settimana
    senza fascia porta `None` sui quattro bordi. L'area si spezza nel buco come
    la linea, che Vega sull'area taglia sul nullo esattamente come sulla
    spezzata.

    Sopra le aree va la **linea centrale tratteggiata**, x-bar-bar: il livello
    attorno a cui le due fasce sono costruite. Senza di lei la fascia sembra
    galleggiare, e il grafico non si legge per quello che e' - una carta di
    controllo, con la settimana come sottogruppo e i punti da guardare rispetto
    ai limiti, non rispetto a se stessi.

    Niente ramo "un livello solo" come nella Day: li' una fascia degenere
    restava un filo spesso quanto il grafico, e disegnarlo due volte lo
    scuriva; qui un'area di altezza zero non disegna niente.

    `None` se nella finestra non c'e' nemmeno un valore."""
    if not any(p["value"] is not None for p in series["points"]):
        return None
    colors = _trend_colors(panel, series["key"], theme)
    unit = series.get("unit")
    digits = int(series.get("digits") or 0)

    # Un telaio solo: il valore, i quattro bordi della fascia e i testi gia'
    # formattati. Le righe non si filtrano, che le settimane senza fascia
    # devono restare come righe a nullo.
    data = pd.DataFrame(
        [
            {
                "monday": point["monday"],
                "value": point["value"],
                "settimana": f"W{point['week']:02d}",
                "giorni": f"{point['days']} of 7",
                **{
                    edge: (point["band"] or {}).get(edge)
                    for edge in ("low", "high", "outer_low", "outer_high")
                },
            }
            for point in series["points"]
        ]
    )
    data["monday"] = pd.to_datetime(data["monday"])
    # Dalla lista e non dalla colonna: li' il nullo e' `None`, e `_trend_text`
    # lo riconosce. Nella colonna sarebbe gia' diventato `NaN`.
    data["testo"] = _trend_text([point["value"] for point in series["points"]], digits)

    strati = []
    for low, high, tinta, opacity in (
        ("outer_low", "outer_high", colors["wide"], TREND_WIDE_OPACITY.get(theme, 0.16)),
        ("low", "high", colors["band"], TREND_BAND_OPACITY.get(theme, 0.38)),
    ):
        if data[low].isna().all():
            continue
        strati.append(
            alt.Chart(data)
            .mark_area(color=tinta, opacity=opacity)
            # Senza `scale`: in un `layer` la scala y e' condivisa, e
            # dichiararla in due strati e' un conflitto. La dichiara la linea
            # (`_trend_y`), e il dominio comprende i bordi della fascia perche'
            # stanno sullo stesso asse.
            .encode(
                x=alt.X("monday:T", title=None),
                y=alt.Y(f"{low}:Q", title=unit),
                y2=alt.Y2(f"{high}:Q"),
            )
        )

    # La linea centrale, tratteggiata: x-bar-bar, la media delle medie
    # settimanali. Senza `x`, quindi presa per tutta la larghezza come le
    # fasce della Day. E' quella attorno a cui le due aree sono costruite, e
    # disegnarla e' meta' di come si legge il grafico: la fascia dice dove una
    # settimana starebbe se niente fosse cambiato, la riga dice il livello
    # attorno a cui tutto gira.
    centro = series.get("centre")
    if centro is not None:
        strati.append(
            alt.Chart(pd.DataFrame([{"centro": centro}]))
            .mark_rule(color=colors["line"], strokeWidth=1, strokeDash=[4, 3], opacity=0.55)
            .encode(y=alt.Y("centro:Q", title=unit))
        )

    tooltip = [
        alt.Tooltip("settimana:N", title="Week"),
        alt.Tooltip("monday:T", title="From", format="%d %b %Y"),
        alt.Tooltip("testo:N", title=series["label"]),
        alt.Tooltip("giorni:N", title="Days"),
    ]
    strati.append(_trend_hover(data, "monday", tooltip, theme))
    if panel == "training":
        strati.append(_trend_bars(data, "monday", colors, unit, theme))
    else:
        # I pallini sempre: una serie settimanale sono al piu' cinquantadue
        # punti, sotto i sessanta oltre i quali si impastano.
        strati.append(_trend_line(data, "monday", colors, unit, theme, with_points=True))
    return _trend_frame(strati, series["label"])


def _panel_charts(panel: dict, builder, span: int, theme: str) -> list[dict]:
    """I grafici di un pannello: uno per serie, gia' in dizionario Vega-Lite.

    Le serie senza nemmeno un valore nella finestra si saltano, invece di
    lasciare un riquadro vuoto."""
    charts = []
    for series in panel["series"]:
        chart = builder(series, span, theme, panel["key"])
        if chart is None:
            continue
        # `validate=False`: lo schema Vega-Lite lo ricontrollerebbe a ogni
        # richiesta, e quello che valida e' l'uscita dei costruttori di
        # questo stesso modulo. Misurato sull'archivio vero: 23 grafici per
        # una vista della Trend, 436 ms con la validazione e 210 senza.
        charts.append(
            {"key": series["key"], "label": series["label"], "spec": chart.to_dict(validate=False)}
        )
    return charts


def trend_panel_charts(panel: dict, days: int, theme: str = "light") -> list[dict]:
    """I grafici di un pannello del Trend della Day, uno per giorno."""
    return _panel_charts(panel, trend_chart, days, theme)


def week_trend_panel_charts(panel: dict, weeks: int, theme: str = "light") -> list[dict]:
    """I grafici di un pannello del Trend della Week, uno per settimana."""
    return _panel_charts(panel, week_trend_chart, weeks, theme)
