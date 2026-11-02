"""I fatti di un giorno per il report giornaliero (todo 31).

Lo script prepara i numeri, l'agente `.claude/agents/fitness-status.md` scrive
il testo: i conti non li fa il modello, come per il report settimanale
(`weekly_data.py`). Legge solo dati locali (`activities.db` e i JSON di salute
gia' scaricati): nessuna chiamata a Garmin. Per avere il giorno aggiornato si
lancia prima `make update_activity`.

Il report del giorno D parla della mattina di D (readiness, notte appena
passata), della seduta del giorno prima (o del riposo), delle attivita' di D
gia' fatte, e serve a consigliare la seduta di D.

Contratto: una media su zero giorni e' `None` (`null` nel JSON), mai `0`; e
ogni media dice su quanti giorni e' fatta.
"""

import argparse
import contextlib
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from training.garmin.config import DATA_DIR
from training.interface.activity_report import NUMBERS_WITHOUT_DISTANCE, activity_numbers
from training.interface.db import list_activities, load_activity_laps, load_activity_records
from training.interface.health import _day_paths, _dig, _read_json
from training.interface.laps import session_laps
from training.interface.health_db import load_health_db
from training.interface.report_text import section_icon
from training.interface.grade import EQUIV_SPEED_SPORTS
from training.interface.run_chart import EFFECTS, durations_s, effects, has_effects, zone_settings
from training.interface.sports import has_distance
from training.interface.weekly_data import BAND_WEEKS, WEEKDAYS, _load, _mean, _value, _week_stats

# Le misure della mattina, con la riga di `health_daily` da cui si leggono:
# 0 e' il giorno D, -1 il giorno prima. Il sonno con la data di D e' la notte
# che porta a D. Stress e minimo della body battery sono quelli del giorno
# prima: la mattina di D quelli di D sono appena cominciati. Il massimo della
# body battery di D e' invece gia' quello del risveglio.
MORNING_METRICS: dict[str, tuple[str, int]] = {
    "readiness": ("readiness", 0),
    "resting_hr": ("resting_hr", 0),
    "hrv_last_night": ("hrv_last_night", 0),
    "hrv_weekly_avg": ("hrv_weekly_avg", 0),
    "resp_sleep": ("resp_sleep_avg", 0),
    "sleep_hours": ("sleep_hours", 0),
    "sleep_score": ("sleep_score", 0),
    "stress_avg_yesterday": ("stress_avg", -1),
    "body_battery_morning": ("body_battery_high", 0),
    "body_battery_low_yesterday": ("body_battery_low", -1),
    "spo2_avg": ("spo2_avg", 0),
}

# Le misure che vivono dentro un intervallo chiuso: punteggi e percentuali
# che Garmin da' da 0 a 100. La fascia di `_band` si ferma li' invece di
# promettere un valore che la misura non puo' avere (todo 46).
MORNING_LIMITS: dict[str, tuple[float, float]] = {
    name: (0, 100)
    for name in (
        "readiness",
        "sleep_score",
        "stress_avg_yesterday",
        "body_battery_morning",
        "body_battery_low_yesterday",
        "spo2_avg",
    )
}

# Le soglie degli allarmi della sezione Health. Sono qui e non nel testo
# dell'agente: il modello racconta gli allarmi, non li decide.
RHR_RISE_BPM = 3  # FC a riposo sopra la media di 28 giorni...
RHR_RISE_DAYS = 2  # ...per tanti giorni di fila (D compreso)
RESP_RISE = 1.0  # atti/min sopra la media di 28 giorni
SHORT_NIGHT_HOURS = 7
SHORT_NIGHTS_ALERT = 3  # notti corte negli ultimi 7 giorni
# Una seduta e' impegnativa con almeno 10 minuti sopra il tetto di Z3 (alto
# aerobico piu' anaerobico, vedi `run_chart.effects`).
HARD_SESSION_MIN = 10  # contati con `_minutes_above_z3`, anche senza soglia
VO2MAX_CHANGE = 0.5
RECENT_DAYS = 14
# Il confronto con le sedute simili di prima (todo 43): quanto si guarda
# indietro, e quante ne servono perche' una mediana voglia dire qualcosa. Con
# due sedute la mediana e' un caso, e l'allenatore non deve poterci costruire
# sopra un andamento.
COMPARE_WINDOW_DAYS = 90
MIN_COMPARABLE = 3
# I giorni misurati che servono perche' uno scarto tipo voglia dire qualcosa:
# sotto, la fascia del battito a riposo non si da'.
MIN_BAND_DAYS = 14
BASELINE_SHORT = 7
BASELINE_LONG = 28


def _health_row(health: pd.DataFrame, day: date) -> pd.Series:
    """La riga di salute di `day`, tutta NaN se il giorno non c'e'."""
    return health.reindex([pd.Timestamp(day)]).iloc[0]


def _window(health: pd.DataFrame, column: str, end: date, days: int) -> pd.Series:
    """I `days` giorni che finiscono il giorno prima di `end` (escluso)."""
    index = pd.date_range(end - timedelta(days=days), end - timedelta(days=1), freq="D")
    return health.reindex(index)[column]


def _band_edges(
    centre: float | None,
    spread: float | None,
    limits: tuple[float, float] | None = None,
    digits: int = 1,
) -> dict[str, Any] | None:
    """La forma di una fascia: `centre` piu' e meno `spread` (`low`, `high`) e
    piu' e meno due (`outer_low`, `outer_high`), fermata a `limits` e
    arrotondata.

    Qui sta il **disegno** della fascia, non da dove viene la sua larghezza. La
    Day passa lo scarto tipo dei giorni della finestra (`_band`), il Trend della
    Week l'errore standard della media dei giorni della settimana
    (`_week_trend_points`): una funzione sola che sa la forma, due che sanno la
    larghezza.

    `None` se il centro o la larghezza non ci sono."""
    if centre is None or spread is None or pd.isna(centre) or pd.isna(spread):
        return None
    floor, ceiling = limits or (-math.inf, math.inf)

    def edge(value: float) -> Any:
        return _value(min(max(value, floor), ceiling), digits)

    return {
        "low": edge(centre - spread),
        "high": edge(centre + spread),
        "outer_low": edge(centre - 2 * spread),
        "outer_high": edge(centre + 2 * spread),
    }


def _band(
    window: pd.Series,
    limits: tuple[float, float] | None = None,
    digits: int = 1,
    min_values: int = MIN_BAND_DAYS,
) -> dict[str, Any] | None:
    """Dove sta di solito una misura: la media della finestra piu' e meno uno
    scarto tipo (`low`, `high`) e piu' e meno due (`outer_low`,
    `outer_high`). Dentro la prima sta la normalita', fuori dalla seconda c'e'
    poco da discutere. La finestra e' quella di `avg_28d`, cosi' la media e la
    fascia raccontano lo stesso periodo.

    Con `limits` la fascia si ferma dove si ferma la misura: il body battery
    al risveglio ha una media alta e uno scarto largo, e due scarti sopra
    portavano la fascia a 118 su una batteria che arriva a 100 (todo 46). La
    barra ci costruiva sopra una scala piu' lunga del possibile.

    `digits` sono quelli della misura, non della media: il punteggio di
    resistenza e' un intero a quattro cifre, e una fascia "4841.8 - 5010.7"
    prometteva una precisione che il dato non ha (todo 48).

    Garmin una fascia la manda solo per l'HRV (`_hrv_baseline`); queste si
    calcolano dallo storico. Non sono soglie d'allarme - quello del battito
    a riposo scatta a `RHR_RISE_BPM` sopra la media per `RHR_RISE_DAYS`
    giorni di fila - ma dicono dove la misura sta di solito. `None` sotto
    `min_values` valori, dove lo scarto tipo sarebbe rumore: di suo sono i
    giorni di `MIN_BAND_DAYS`, ma la stessa funzione serve le fasce della
    settimana (todo 52), dove i valori sono dodici medie settimanali e ne
    bastano meno."""
    values = window.dropna()
    if len(values) < min_values:
        return None
    return _band_edges(values.mean(), values.std(), limits, digits)


def _morning(health: pd.DataFrame, day: date, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Ogni misura: il valore, le medie a 7 e 28 giorni (con quanti giorni) e
    la differenza dalla media a 28. Le medie sono calcolate rispetto al giorno
    da cui si legge la misura."""
    result = {}
    for name, (column, offset) in MORNING_METRICS.items():
        source = day + timedelta(days=offset)
        value = _value(_health_row(health, source)[column], 1)
        short = _mean(_window(health, column, source, BASELINE_SHORT), 1)
        long_window = _window(health, column, source, BASELINE_LONG)
        long = _mean(long_window, 1)
        delta = (
            _value(value - long["mean"], 1)
            if value is not None and long["mean"] is not None
            else None
        )
        result[name] = {
            "value": value,
            "date": source.isoformat(),
            "avg_7d": short,
            "avg_28d": long,
            "delta_vs_28d": delta,
            "band": _band(long_window, MORNING_LIMITS.get(name)),
        }
    result["hrv_status"] = _value(_health_row(health, day)["hrv_status"])
    result["hrv_baseline"] = _hrv_baseline(day, data_dir)
    return result


def _hrv_baseline(day: date, data_dir: Path = DATA_DIR) -> dict[str, Any] | None:
    """L'intervallo "balanced" dell'HRV secondo Garmin, dal JSON di salute di
    quel giorno: `health_daily` non lo tiene. `None` se il file non c'e'."""
    path = _day_paths(Path(data_dir) / "health", day.isoformat())["hrv"]
    baseline = _dig(_read_json(path), "hrvSummary", "baseline")
    if not isinstance(baseline, dict) or baseline.get("balancedLow") is None:
        return None
    return {"low": baseline.get("balancedLow"), "high": baseline.get("balancedUpper")}


def _sleep_last_7(health: pd.DataFrame, day: date) -> dict[str, Any]:
    """Le ore di sonno delle ultime 7 notti (quella che porta a D compresa)."""
    nights = health.reindex(pd.date_range(day - timedelta(days=6), day, freq="D"))["sleep_hours"]
    # Due decimali e non uno: una notte da 6,98 h e' corta, e a un decimale si
    # leggerebbe "7.0" fra le notti sotto le 7 ore.
    hours = {d.date().isoformat(): _value(v, 2) for d, v in nights.items()}
    known = nights.dropna()
    return {
        "hours": hours,
        "short_nights": int((known < SHORT_NIGHT_HOURS).sum()),
        "nights_measured": int(len(known)),
    }


def _alerts(health: pd.DataFrame, day: date, morning: dict[str, Any], sleep: dict[str, Any]) -> list[dict]:
    """Gli allarmi accesi, ognuno con i suoi numeri. Lista vuota: niente da
    segnalare."""
    alerts = []

    rhr_days = []
    for back in range(RHR_RISE_DAYS):
        source = day - timedelta(days=back)
        value = _health_row(health, source)["resting_hr"]
        baseline = _mean(_window(health, "resting_hr", source, BASELINE_LONG), 1)["mean"]
        rhr_days.append((source, value, baseline))
    if all(pd.notna(v) and b is not None and v >= b + RHR_RISE_BPM for _, v, b in rhr_days):
        alerts.append(
            {
                "kind": "resting_hr_up",
                "detail": f"resting HR {RHR_RISE_BPM}+ bpm above its 28-day average "
                f"for {RHR_RISE_DAYS} days in a row",
                "days": [
                    {"date": d.isoformat(), "value": _value(v, 0), "avg_28d": b} for d, v, b in rhr_days
                ],
            }
        )

    resp = morning["resp_sleep"]
    if resp["delta_vs_28d"] is not None and resp["delta_vs_28d"] >= RESP_RISE:
        alerts.append(
            {
                "kind": "sleep_breathing_up",
                "detail": f"breathing rate during sleep {RESP_RISE:g}+ breaths/min above its 28-day average",
                "value": resp["value"],
                "avg_28d": resp["avg_28d"]["mean"],
            }
        )

    weekly = morning["hrv_weekly_avg"]["value"]
    baseline = morning["hrv_baseline"]
    if weekly is not None and baseline and weekly < baseline["low"]:
        alerts.append(
            {
                "kind": "hrv_below_baseline",
                "detail": "HRV weekly average below the bottom of Garmin's balanced range",
                "value": weekly,
                "baseline_low": baseline["low"],
            }
        )

    if sleep["short_nights"] >= SHORT_NIGHTS_ALERT:
        alerts.append(
            {
                "kind": "short_sleep",
                "detail": f"{sleep['short_nights']} nights under {SHORT_NIGHT_HOURS} h in the last 7",
                "short_nights": sleep["short_nights"],
            }
        )
    return alerts


# Le tre intensita' del carico mensile di Garmin: le colonne di
# `health_daily` da cui prendono la barra la card Load e il pannello Load del
# Trend.
LOAD_ZONES = ("load_aerobic_low", "load_aerobic_high", "load_anaerobic")


def _load_bands(health: pd.DataFrame, as_of: str) -> dict[str, Any]:
    """Dove e' stata ognuna delle tre intensita' nei 28 giorni prima di
    `as_of`, il giorno del carico di `_load`: la fascia di `_band`, la stessa
    che hanno le misure di Health, Recovery e Fitness.

    **Non e' il bersaglio di Garmin.** Quello diceva dove Garmin vorrebbe che
    il carico stesse; questa dice dove il carico sta di solito, che e' la
    domanda che fanno tutte le altre barre della pagina. La finestra esclude
    il giorno del valore, come in `_morning`: la tacca si confronta con i
    giorni prima, non con se stessa.

    Il fondo si ferma a zero: un carico non e' mai negativo, e due scarti tipo
    sotto la media di un'anaerobica quasi sempre bassa portavano la barra su
    numeri che non esistono (lo stesso rimedio del body battery, todo 46). Il
    carico per zona e' un intero, quindi la fascia non ha decimali. `None` per
    la zona senza abbastanza giorni misurati."""
    source = date.fromisoformat(as_of)
    return {
        column: _band(_window(health, column, source, BASELINE_LONG), (0, math.inf), 0)
        for column in LOAD_ZONES
    }


def _vo2max_change(health: pd.DataFrame, day: date) -> dict[str, Any] | None:
    """Il VO2max di Garmin oggi e 28 giorni prima, solo se e' cambiato di
    almeno `VO2MAX_CHANGE`: spostamenti piu' piccoli sono rumore."""
    values = health.loc[: pd.Timestamp(day), "vo2max"].dropna()
    if values.empty:
        return None
    before = health.loc[: pd.Timestamp(day - timedelta(days=BASELINE_LONG)), "vo2max"].dropna()
    if before.empty:
        return None
    now, then = float(values.iloc[-1]), float(before.iloc[-1])
    if abs(now - then) < VO2MAX_CHANGE:
        return None
    return {"now": _value(now, 1), "days_ago_28": _value(then, 1), "change": _value(now - then, 1)}


def _effect_minutes(activity: pd.Series, records: pd.DataFrame) -> dict[str, float] | None:
    """I minuti per effetto stimato (`run_chart.effects`), o `None` senza zone,
    soglia o battiti."""
    bounds, threshold = zone_settings(activity)
    if not has_effects(bounds, threshold):
        return None
    if records.empty or records["heart_rate"].isna().all():
        return None
    seconds = effects(records, bounds, threshold)
    return {name: _value(seconds[name] / 60, 1) for name in EFFECTS}


def _minutes_above_z3(activity: pd.Series, records: pd.DataFrame) -> float | None:
    """I minuti con i battiti sopra il tetto di Z3 (alto aerobico piu'
    anaerobico). Servono solo i tetti delle zone, non la soglia: molti file
    (tutto agosto 2026, le uscite in bici) la salvano a zero o non ce
    l'hanno, e senza questo conto non si troverebbe nessuna seduta
    impegnativa. `None` senza zone o senza battiti."""
    bounds, _ = zone_settings(activity)
    if not bounds:
        return None
    if records.empty or records["heart_rate"].isna().all():
        return None
    above = records["heart_rate"].astype(float) > bounds[2]
    return _value(float(durations_s(records)[above].sum()) / 60, 1)


# Quanti decimali per ogni numero di `activity_numbers`: le velocita' e le
# percentuali uno, i battiti e la cadenza nessuno.
_EXECUTION_DIGITS = {
    "speed_first_half_kmh": 1,
    "speed_second_half_kmh": 1,
    "speed_change_pct": 1,
    "hr_first_half": 0,
    "hr_second_half": 0,
    "hr_change_pct": 1,
    "cadence_mean": 0,
    "cadence_variation_pct": 1,
    "uphill_hr": 0,
    "flat_hr": 0,
}


def _execution(records: pd.DataFrame, sport: str | None) -> dict[str, Any] | None:
    """Come e' stata corsa la seduta (todo 43): le due meta' per velocita' e
    battiti, la cadenza, i battiti in salita contro quelli in piano. I conti
    sono quelli di `activity_report.activity_numbers`, gli stessi che vanno
    nei report per attivita'; qui si arrotondano. `None` se dai record non si
    ricava niente (palestra, file senza campioni).

    Degli sport senza distanza resta la sola cadenza: tutto il resto e'
    costruito sui chilometri che il polso ha indovinato."""
    if records.empty:
        return None
    numbers = activity_numbers(records)
    if not has_distance(sport):
        numbers = {name: numbers[name] for name in NUMBERS_WITHOUT_DISTANCE}
    if all(value is None for value in numbers.values()):
        return None
    return {name: _value(value, _EXECUTION_DIGITS[name]) for name, value in numbers.items()}


def _short(activity: pd.Series) -> str:
    """Un'attivita' in una riga, per l'elenco dei giorni passati: "running 8.1
    km", o i minuti dove la distanza non c'e' (il tapis roulant) o non l'ha
    registrata nessuno."""
    km = _value(activity["total_distance_km"], 1) if has_distance(activity["sport"]) else None
    size = f"{km} km" if km else f"{_value(activity['total_time_min'], 0)} min"
    return f"{activity['sport']} {size}"


def _compared_with(activities: pd.DataFrame, activity: pd.Series) -> dict[str, Any]:
    """Le sedute simili dei `COMPARE_WINDOW_DAYS` giorni prima: stesso sport, e
    stesso tipo di corsa quando la seduta ne ha uno. Rende quante sono e le
    mediane con cui confrontarla.

    Il nastro si confronta con il nastro senza bisogno di dirlo: il tapis
    roulant e' uno sport a se' (todo 45), e di quelle sedute la distanza non
    si da' nemmeno come mediana.

    Il giorno stesso resta fuori: il confronto e' con quello che c'era prima.
    Sotto `MIN_COMPARABLE` sedute le mediane non si danno (restano `None`):
    il numero si da' comunque, cosi' chi scrive sa perche' non c'e' il
    paragone."""
    day = activity["start_time"].date()
    days = activities["start_time"].dt.date
    run_type = _value(activity["run_type"])
    similar = activities[
        (activities["sport"] == activity["sport"])
        & (days >= day - timedelta(days=COMPARE_WINDOW_DAYS))
        & (days < day)
    ]
    if run_type is not None:
        similar = similar[similar["run_type"] == run_type]
    median = None
    if len(similar) >= MIN_COMPARABLE:
        measured = has_distance(activity["sport"])
        median = {
            "distance_km": _value(similar["total_distance_km"].median(), 2) if measured else None,
            "duration_min": _value(similar["total_time_min"].median(), 0),
            "avg_hr": _value(similar["avg_heart_rate"].median(), 0),
            "grade_adjusted_speed_kmh": (
                _value(similar["equiv_speed_kmh"].median(), 1) if measured else None
            ),
        }
    return {
        "sport": _value(activity["sport"]),
        "run_type": run_type,
        "window_days": COMPARE_WINDOW_DAYS,
        "count": int(len(similar)),
        "median": median,
    }


def _power(records: pd.DataFrame) -> dict[str, Any]:
    """La potenza di corsa, media e massima, quando l'orologio la registra.
    Sul tapis roulant e' la misura di sforzo che non dipende da quanto bene
    il polso indovina la distanza."""
    if records.empty or "power" not in records:
        return {"avg_power": None, "max_power": None}
    power = records["power"].dropna()
    if power.empty:
        return {"avg_power": None, "max_power": None}
    return {"avg_power": _value(power.mean(), 0), "max_power": _value(power.max(), 0)}


def _session(activity: pd.Series, data_dir: Path, activities: pd.DataFrame) -> dict[str, Any]:
    start = activity["start_time"]
    # I record una volta sola: li vogliono gli effetti, i minuti sopra Z3 e
    # `_execution`.
    records = load_activity_records(int(activity["activity_id"]), data_dir)
    return {
        "date": start.date().isoformat(),
        "weekday": WEEKDAYS[start.weekday()],
        "start_time": start.strftime("%H:%M"),
        "sport": activity["sport"],
        "sub_sport": _value(activity["sub_sport"]),
        "name": activity["activity_name"],
        # La distanza c'e' sempre, ma sul tapis roulant e' una stima del
        # polso che in salita sbaglia di molto: `distance_unreliable` dice di
        # non costruirci sopra nessun giudizio (todo 45).
        "distance_km": _value(activity["total_distance_km"], 2),
        "distance_unreliable": not has_distance(activity["sport"]),
        "duration_min": _value(activity["total_time_min"], 0),
        "ascent_m": _value(activity["total_ascent_m"], 0),
        "avg_hr": _value(activity["avg_heart_rate"], 0),
        "max_hr": _value(activity["max_heart_rate"], 0),
        # Calorie e potenza: su un tapis roulant sono i segnali onesti, dove
        # distanza e velocita' le stima il polso e in salita sbagliano di
        # molto. Garmin le calorie le da' per tutte le sedute.
        "calories": _value(activity["total_calories"], 0),
        **_power(records),
        "aerobic_te": _value(activity["aerobic_te"], 1),
        "anaerobic_te": _value(activity["anaerobic_te"], 1),
        "grade_adjusted_speed_kmh": (
            _value(activity["equiv_speed_kmh"], 1) if has_distance(activity["sport"]) else None
        ),
        # Che seduta voleva essere: il tipo (scelto da Andrea o stimato), il
        # terreno e l'allenamento pianificato che l'orologio ha seguito.
        "run_type": _value(activity["run_type"]),
        "run_type_source": _value(activity["run_type_source"]),
        "terrain": _value(activity["terrain"]),
        "workout_name": _value(activity["workout_name"]),
        "workout_active_steps": _value(activity["workout_active_steps"], 0),
        "workout_active_max_s": _value(activity["workout_active_max_s"], 0),
        "effect_minutes": _effect_minutes(activity, records),
        "minutes_above_z3": _minutes_above_z3(activity, records),
        "execution": _execution(records, activity["sport"]),
        # I giri, solo per una seduta che l'orologio ha corso come
        # allenamento (todo 79): il riscaldamento, le ripetute una per una, i
        # recuperi. Vuoto per una corsa libera, dove sono l'auto-lap al
        # chilometro. **La tabella la disegna la card Session**: questi
        # numeri sono qui per poterli citare nel discorso.
        "laps": session_laps(load_activity_laps(int(activity["activity_id"]), data_dir), activity["sport"])["laps"],
        "compared_with": _compared_with(activities, activity),
    }


# Le misure di forma che vivono dentro un intervallo chiuso, come
# `MORNING_LIMITS` per quelle della mattina (todo 46 e 48). Il punteggio di
# salita Garmin lo da' da 0 a 100.
FITNESS_LIMITS: dict[str, tuple[float, float]] = {"hill_score": (0, 100)}


def _latest_with_change(health: pd.DataFrame, day: date, column: str, digits: int = 1) -> dict[str, Any] | None:
    """Il valore piu' recente di `column` fino a `day`, il giorno della riga
    da cui viene, la variazione rispetto al valore piu' recente di 28 giorni
    prima (None se allora non c'era) e la fascia in cui si e' mosso nelle
    ultime quattro settimane. None se non c'e' nessun valore.

    La fascia e' quella di `_band`, la stessa delle misure della mattina:
    stessa finestra, stesso minimo di giorni misurati. **Si legge pero' al
    contrario** (todo 48): qui sopra la fascia vuol dire che la misura sta
    ancora salendo, non che c'e' qualcosa da guardare. E siccome e' una media
    mobile, si muove anche nei giorni in cui il valore sta fermo: un VO2max
    che non cambia mentre la fascia lo raggiunge racconta che la salita si e'
    fermata."""
    values = health.loc[: pd.Timestamp(day), column].dropna()
    if values.empty:
        return None
    now = float(values.iloc[-1])
    before = health.loc[: pd.Timestamp(day - timedelta(days=BASELINE_LONG)), column].dropna()
    then = float(before.iloc[-1]) if not before.empty else None
    return {
        "now": _value(now, digits),
        "as_of": values.index[-1].date().isoformat(),
        "days_ago_28": _value(then, digits),
        "change": _value(now - then, digits) if then is not None else None,
        "band": _band(
            _window(health, column, day, BASELINE_LONG), FITNESS_LIMITS.get(column), digits
        ),
    }


def _acclimation(day: date, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """A che quota e a quanto caldo il corpo e' adattato, dal JSON del
    training status di quel giorno: `health_daily` non li tiene, come la
    fascia HRV.

    Garmin li tiene insieme, annidati dentro il VO2max piu' recente: la quota
    in metri, il caldo in percento. Sono due adattamenti rapidi da prendere e
    rapidi da perdere, e nello storico di Andrea si vede: la quota sale a
    1400 m nelle settimane in montagna, il caldo al 58% a settembre 2025 e
    poi torna a zero in dieci giorni. Il resto dell'anno sono zero tutti e
    due. `None` per ognuno che manchi, e per tutti i giorni prima del 2025,
    i cui file non portano affatto il blocco."""
    path = _day_paths(Path(data_dir) / "health", day.isoformat())["training_status"]
    block = _dig(_read_json(path), "mostRecentVO2Max", "heatAltitudeAcclimation")
    if not isinstance(block, dict):
        return {"altitude_acclimation": None, "heat_acclimation": None}
    metres = block.get("altitudeAcclimation")
    percent = block.get("heatAcclimationPercentage")
    return {
        "altitude_acclimation": (
            {"metres": int(metres), "trend": _value(block.get("altitudeTrend"))}
            if metres is not None
            else None
        ),
        "heat_acclimation": (
            {"percent": int(percent), "trend": _value(block.get("heatTrend"))}
            if percent is not None
            else None
        ),
    }


def fitness_on(
    health: pd.DataFrame, day: date, data_dir: Path = DATA_DIR
) -> dict[str, Any]:
    """La card Fitness della Day in React (todo 37 e 38): VO2max, endurance e
    hill score piu' recenti fino a `day`, sempre, con la data e la variazione
    in 28 giorni. Al contrario di `_vo2max_change` non c'e' soglia: la card li
    mostra anche quando non si sono mossi.

    La usa solo `GET /api/daily/{day}`, non `build_daily_data`: il JSON del
    report giornaliero non cambia."""
    vo2max = _latest_with_change(health, day, "vo2max")
    if vo2max is not None:
        # Il giorno in cui Garmin l'ha misurato, non quello del file che lo
        # porta (vedi `health._vo2max`).
        measured = health.at[pd.Timestamp(vo2max["as_of"]), "vo2max_date"]
        if isinstance(measured, str):
            vo2max["as_of"] = measured
    endurance = _latest_with_change(health, day, "endurance_score", digits=0)
    if endurance is not None:
        level = health.at[pd.Timestamp(endurance["as_of"]), "endurance_level"]
        endurance["level"] = level if isinstance(level, str) else None
    return {
        "vo2max": vo2max,
        "endurance": endurance,
        "hill": _latest_with_change(health, day, "hill_score", digits=0),
        **_acclimation(day, data_dir),
    }


# --- Il Trend della Day (todo 55) ---

# L'ampiezza della finestra: il cursore della pagina si muove fra questi due,
# e di suo parte dai 28 giorni di `BASELINE_LONG`, la finestra con cui le
# card del Report gia' si confrontano.
TREND_MIN_DAYS = 5
TREND_MAX_DAYS = 365
TREND_DEFAULT_DAYS = BASELINE_LONG

# Una serie del Trend: la colonna da cui si legge, come si chiama a schermo,
# l'unita' (`None` per i punteggi puri) e i decimali.
TrendSeries = tuple[str, str, str | None, int]

# I pannelli, nell'ordine delle card della Day: Report e Trend raccontano le
# stesse cose nello stesso ordine. Le colonne sono quelle di `health_daily`;
# il pannello Training non sta qui perche' i suoi numeri vengono dalle
# attivita'.
TREND_PANELS: dict[str, tuple[str, tuple[TrendSeries, ...]]] = {
    "health": (
        "Health",
        (
            ("resting_hr", "Resting HR", "bpm", 0),
            ("hrv_last_night", "HRV last night", "ms", 0),
            ("resp_sleep_avg", "Breathing in sleep", "br/min", 1),
            ("stress_avg", "Stress", None, 0),
        ),
    ),
    "recovery": (
        "Recovery",
        (
            ("readiness", "Readiness", None, 0),
            ("sleep_hours", "Sleep", "h", 2),
            ("sleep_score", "Sleep score", None, 0),
            ("body_battery_high", "Body battery high", None, 0),
            ("body_battery_low", "Body battery low", None, 0),
        ),
    ),
    "load": (
        "Load",
        (
            ("load_acute", "Acute load", None, 0),
            ("load_chronic", "Chronic load", None, 0),
            ("acwr", "Acute/chronic ratio", None, 2),
            ("load_aerobic_low", "Low aerobic load", None, 0),
            ("load_aerobic_high", "High aerobic load", None, 0),
            ("load_anaerobic", "Anaerobic load", None, 0),
        ),
    ),
    "fitness": (
        "Fitness",
        (
            ("vo2max", "VO2max", "ml/kg/min", 1),
            ("endurance_score", "Endurance score", None, 0),
            ("hill_score", "Hill score", None, 0),
        ),
    ),
}

# Il pannello Training: i minuti per intensita', i chilometri e il dislivello
# delle sedute, sommati per giorno. Le colonne sono quelle di `activities`.
TREND_TRAINING: tuple[TrendSeries, ...] = (
    ("min_low_aerobic", "Low aerobic", "min", 0),
    ("min_high_aerobic", "High aerobic", "min", 0),
    ("min_anaerobic", "Anaerobic", "min", 0),
    ("total_distance_km", "Distance", "km", 1),
    ("total_ascent_m", "Ascent", "m", 0),
)

# Le misure chiuse fra 0 e 100, come in `MORNING_LIMITS` e `FITNESS_LIMITS`:
# li' la chiave e' il nome della misura, qui la colonna.
TREND_LIMITS: dict[str, tuple[float, float]] = {
    column: (0, 100)
    for column in (
        "readiness",
        "sleep_score",
        "stress_avg",
        "body_battery_high",
        "body_battery_low",
        "hill_score",
    )
}
# Il rapporto acuto/cronico, come nella card, di fascia non ne ha nessuna:
# e' gia' un confronto fra due finestre, e dire dove sta di solito un numero
# che vale uno quando tutto e' normale non aggiunge niente.
#
# Tutto il resto del pannello Load, le tre intensita' comprese, ha la fascia
# di `_band`: la media dei giorni della finestra piu' e meno uno scarto tipo,
# come gli altri pannelli e come le barre della card Load (`_load_bands`).
# Il bersaglio di Garmin non si disegna piu' da nessuna delle due parti.
TREND_NO_BAND = ("acwr",)

# Tutte le altre hanno comunque un pavimento a zero: nessuna di queste misure
# puo' essere negativa, e due scarti tipo sotto la media di un carico che per
# meta' finestra sta a zero portavano la fascia a -200, allungando l'asse su
# numeri che non esistono (e' lo stesso motivo di `MORNING_LIMITS`, todo 46).
TREND_FLOOR = (0, math.inf)


def _trend_points(window: pd.Series, digits: int) -> list[dict[str, Any]]:
    """I punti di una serie, uno per giorno della finestra.

    I giorni senza misura restano con `value` a `None` e **non si tolgono**:
    e' quello che fa spezzare la linea dove i dati mancano invece di tirare
    una retta fra due punti lontani mesi (il buco fra dicembre 2024 e agosto
    2026 si attraversa tutto con il cursore a 365 giorni)."""
    return [
        {"day": stamp.date().isoformat(), "value": _value(value, digits)}
        for stamp, value in window.items()
    ]


def _training_daily(activities: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """I totali delle sedute giorno per giorno fra `start` e `end` compresi, una
    riga per giorno e una colonna per serie di `TREND_TRAINING`.

    Un giorno senza sedute vale **zero**, non "non misurato": il riposo e' un
    dato, al contrario di una notte che l'orologio non ha registrato.

    Lo usano il pannello Training della Day, un punto per giorno, e quello della
    Week, che poi somma i giorni di ogni settimana."""
    index = pd.date_range(start, end, freq="D")
    columns = [column for column, *_ in TREND_TRAINING]
    if activities.empty:
        return pd.DataFrame(0.0, index=index, columns=columns)
    inside = activities[
        (activities["start_time"] >= pd.Timestamp(start))
        & (activities["start_time"] < pd.Timestamp(end) + pd.Timedelta(days=1))
    ]
    by_day = inside.set_index(inside["start_time"].dt.normalize())[columns]
    return by_day.groupby(level=0).sum().reindex(index).fillna(0.0)


def _trend_training(activities: pd.DataFrame, start: date, end: date) -> dict[str, Any]:
    """Il pannello Training: minuti per intensita' e chilometri, per giorno.

    Qui non c'e' la fascia di `_band`, per lo stesso motivo per cui un giorno di
    riposo e' zero: fra i giorni a zero la media e lo scarto tipo direbbero
    poco."""
    daily = _training_daily(activities, start, end)
    return {
        "key": "training",
        "title": "Training",
        "icon": section_icon("training"),
        "series": [
            {
                "key": column,
                "label": label,
                "unit": unit,
                "digits": digits,
                "points": _trend_points(daily[column], digits),
                "band": None,
            }
            for column, label, unit, digits in TREND_TRAINING
        ],
    }


def trend_data(
    start: date,
    end: date,
    data_dir: Path = DATA_DIR,
    activities: pd.DataFrame | None = None,
    health: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Le serie giornaliere fra `start` e `end` compresi, pannello per
    pannello, con la fascia di ognuna.

    E' la stessa finestra delle card del Report, solo disegnata invece che
    raccontata: `_window` e `_band` sono quelle, non copie. `_window` conta
    all'indietro da un estremo escluso, quindi si chiede il giorno dopo
    `end`; l'ampiezza la controlla chi chiama (l'API rifiuta fuori da
    `TREND_MIN_DAYS`-`TREND_MAX_DAYS`).

    La fascia segue la finestra, perche' segue la serie su cui e' calcolata:
    sotto `MIN_BAND_DAYS` giorni misurati `_band` da' `None` e la banda non
    si disegna."""
    if activities is None:
        activities = list_activities(data_dir)
    if health is None:
        health = load_health_db(data_dir)

    span = (end - start).days + 1

    def _trend_band(column: str, window: pd.Series, digits: int) -> dict[str, Any] | None:
        if column in TREND_NO_BAND:
            return None
        return _band(window, TREND_LIMITS.get(column, TREND_FLOOR), digits)

    def _series(column: str, label: str, unit: str | None, digits: int) -> dict[str, Any]:
        """Una serie del pannello: i punti e la fascia, dalla **stessa**
        finestra.

        Prima la finestra si calcolava due volte con gli stessi argomenti,
        una per i punti e una per la fascia: mezzo millisecondo per serie,
        ventitre serie, a ogni richiesta dei grafici."""
        window = _window(health, column, end + timedelta(days=1), span)
        return {
            "key": column,
            "label": label,
            "unit": unit,
            "digits": digits,
            "points": _trend_points(window, digits),
            "band": _trend_band(column, window, digits),
        }

    panels = []
    for key, (title, series) in TREND_PANELS.items():
        panels.append(
            {
                "key": key,
                "title": title,
                # L'icona e' quella della sezione omonima del Report
                # (`report_text.section_icon`): il pannello e la card si
                # riconoscono dallo stesso segno, non da due.
                "icon": section_icon(title),
                "series": [
                    _series(column, label, unit, digits)
                    for column, label, unit, digits in series
                ],
            }
        )
    panels.append(_trend_training(activities, start, end))
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": span,
        "min_band_days": MIN_BAND_DAYS,
        "panels": panels,
    }


def _hr_zones(activities: pd.DataFrame, day: date) -> dict[str, Any] | None:
    """Le zone cardiache in bpm in vigore il giorno `day`: quelle dell'ultima
    attivita' a piedi fino a quel giorno che le ha salvate (l'orologio le scrive nel
    FIT e le aggiorna da solo: il 07/10/2026 il tetto di Z3 e' passato da 141 a
    142). Servono al report per dare i bersagli in bpm. `None` se nessuna
    attivita' le ha."""
    known = activities[
        (activities["start_time"].dt.date <= day) & activities["hr_zone_bounds"].notna()
    ].sort_values("start_time")
    # Le zone di un'attivita' a piedi: quelle della bici sono piu' basse e
    # senza soglia, e i bersagli di una corsa presi da li' venivano bassi
    # (il 24/09/2026 Z4 a 138-154 invece di 143-155). Le altre solo se non ce
    # n'e' nessuna a piedi.
    on_foot = known[known["sport"].isin(EQUIV_SPEED_SPORTS)]
    if not on_foot.empty:
        known = on_foot
    if known.empty:
        return None
    activity = known.iloc[-1]
    bounds, threshold = zone_settings(activity)
    if not bounds:
        return None
    z1, z2, z3, z4 = bounds
    zones = {
        "Z1": {"max": z1},
        "Z2": {"min": z1 + 1, "max": z2},
        "Z3": {"min": z2 + 1, "max": z3},
        "Z4": {"min": z3 + 1, "max": z4},
        "Z5": {"min": z4 + 1},
    }
    # Una soglia che non sta sopra Z3 (alcuni file la salvano a zero) non e'
    # una soglia: `None`, e niente fasce degli effetti.
    valid = has_effects(bounds, threshold)
    result = {
        "as_of": activity["start_time"].date().isoformat(),
        "zones": zones,
        "threshold_hr": threshold if valid else None,
    }
    # Le fasce degli effetti, con le stesse regole di `run_chart.effect_of`.
    if valid:
        result["effects"] = {
            EFFECTS[0]: {"max": z3},
            EFFECTS[1]: {"min": z3 + 1, "max": threshold},
            EFFECTS[2]: {"min": threshold + 1},
        }
    return result


def _on(activities: pd.DataFrame, day: date) -> pd.DataFrame:
    return activities[activities["start_time"].dt.date == day].sort_values("start_time")


def _recent(activities: pd.DataFrame, day: date, data_dir: Path) -> dict[str, Any]:
    """Il contesto prima di D: da quanto non ci si allena, da quanto non si fa
    una seduta impegnativa, i riposi della settimana e le attivita' delle
    ultime due settimane in una riga ciascuna.

    L'ultima attivita' e l'ultima seduta impegnativa sono *prima* di D, e lo
    dicono i nomi delle chiavi: un'attivita' gia' fatta in D e' in
    `trained_today` (e in `sessions.today`), cosi' "3 giorni dall'ultima
    attivita'" non sembra vero quando ci si e' gia' allenati oggi."""
    dates = activities["start_time"].dt.date
    before = activities[dates < day].sort_values("start_time")
    last = before.iloc[-1]["start_time"].date() if not before.empty else None

    last_hard = None
    window = before[before["start_time"].dt.date >= day - timedelta(days=BASELINE_LONG)]
    for _, activity in window.iloc[::-1].iterrows():
        # Dei campioni servono i battiti e l'ora: `_minutes_above_z3` guarda
        # quelli e l'indice. Leggere tutte le colonne costava quattro volte
        # tanto per seduta, e qui si scorre indietro fino a trovarne una
        # impegnativa — fino a diciotto sedute quando non ce n'e' nessuna.
        records = load_activity_records(
            int(activity["activity_id"]), data_dir, columns=("heart_rate",)
        )
        minutes = _minutes_above_z3(activity, records)
        if minutes is not None and minutes >= HARD_SESSION_MIN:
            last_hard = activity["start_time"].date()
            break

    week = {day - timedelta(days=k) for k in range(1, 8)}
    active = set(dates[dates.isin(week)])

    # I fatti di calendario li conta lo script, non il modello: quanti giorni
    # di fila ci si e' allenati (o riposati) fino al giorno prima di D, e i 7
    # giorni prima di D uno per uno. Senza, il modello scriveva "quattro giorni
    # di fila" contando da solo, e sbagliava.
    trained = set(dates)
    streak, rest_streak = 0, 0
    while day - timedelta(days=streak + 1) in trained:
        streak += 1
    while day - timedelta(days=rest_streak + 1) not in trained and rest_streak < BASELINE_LONG:
        rest_streak += 1
    last_7_days = []
    for k in range(7, 0, -1):
        d = day - timedelta(days=k)
        on_day = activities[dates == d].sort_values("start_time")
        last_7_days.append(
            {
                "date": d.isoformat(),
                "weekday": WEEKDAYS[d.weekday()],
                "activities": [_short(a) for _, a in on_day.iterrows()],
            }
        )
    listed = activities[(dates >= day - timedelta(days=RECENT_DAYS - 1)) & (dates <= day)].sort_values("start_time")
    return {
        "trained_today": bool((dates == day).any()),
        "last_activity_before_today": last.isoformat() if last else None,
        "days_since_last_activity_before_today": (day - last).days if last else None,
        "last_hard_session_before_today": last_hard.isoformat() if last_hard else None,
        "days_since_last_hard_session_before_today": (day - last_hard).days if last_hard else None,
        "hard_session_rule": f"{HARD_SESSION_MIN}+ minutes above the top of Z3, "
        f"looked for in the last {BASELINE_LONG} days",
        "rest_days_last_7": len(week - active),
        "consecutive_training_days_before_today": streak,
        "consecutive_rest_days_before_today": rest_streak if streak == 0 else 0,
        "last_7_days": last_7_days,
        "activities_last_14_days": [
            {
                "date": a["start_time"].date().isoformat(),
                "sport": a["sport"],
                "distance_km": _value(a["total_distance_km"], 1) if has_distance(a["sport"]) else None,
                "duration_min": _value(a["total_time_min"], 0),
                "aerobic_te": _value(a["aerobic_te"], 1),
                "anaerobic_te": _value(a["anaerobic_te"], 1),
            }
            for _, a in listed.iterrows()
        ],
    }


def build_daily_data(
    day: date,
    data_dir: Path = DATA_DIR,
    activities: pd.DataFrame | None = None,
    health: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """I fatti del giorno `day`, come dizionario pronto per il JSON.

    `activities` e `health` sono quelli di `list_activities` e
    `load_health_db`: l'API li passa dalla sua cache, perche' rileggerli a
    ogni richiesta costa un secondo; senza, si leggono qui."""
    if activities is None:
        activities = list_activities(data_dir)
    if health is None:
        health = load_health_db(data_dir)

    morning = _morning(health, day, data_dir)
    sleep = _sleep_last_7(health, day)
    load_now = _load(health, day)
    load_week_ago = _load(health, day - timedelta(days=7))
    health_known = health.index[health["sleep_hours"].notna() | health["resting_hr"].notna()]

    return {
        "day": day.isoformat(),
        "weekday": WEEKDAYS[day.weekday()],
        "health_data_up_to": health_known.max().date().isoformat() if len(health_known) else None,
        "morning": morning,
        "sleep_last_7": sleep,
        "alerts": _alerts(health, day, morning, sleep),
        "load": {
            "now": load_now,
            "bands": _load_bands(health, load_now["as_of"]) if load_now else None,
            "week_ago": load_week_ago,
            "vo2max_change": _vo2max_change(health, day),
        },
        "sessions": {
            "yesterday": [
                _session(a, data_dir, activities)
                for _, a in _on(activities, day - timedelta(days=1)).iterrows()
            ],
            "today": [_session(a, data_dir, activities) for _, a in _on(activities, day).iterrows()],
        },
        "recent": _recent(activities, day, data_dir),
        "hr_zones": _hr_zones(activities, day),
        "missing": [name for name, item in morning.items() if isinstance(item, dict) and "value" in item and item["value"] is None],
    }



# --- Il Trend della Week (todo 78) ---

# Un punto per settimana ISO invece che per giorno. Due cose da dire subito,
# perche' non sono quelle della Week Snap:
#
# 1. **La media, per tutti i pannelli.** Lo Snap legge carico e forma come
#    stati di fine settimana (`_load`, `_at_end_of`); qui sono la media
#    aritmetica dei giorni della settimana come salute e recupero. Una regola
#    sola, su tutti e quattro i pannelli: una linea i cui punti fossero "lo
#    stato di domenica" su un pannello e "la media dei sette giorni" su un
#    altro non si confronterebbe fra pannelli, e la fascia - che e' l'errore
#    di una media - vuole una media sotto. Il pannello Training somma, che i
#    minuti e i chilometri di una settimana sono la loro somma e non la loro
#    media.
#
# 2. **La fascia e' di ogni punto, non della finestra.** Nel Trend della Day
#    `_band` da' una fascia sola per tutta la finestra, e si disegna come due
#    rettangoli larghi quanto il grafico. Qui il disegno e' **una carta di
#    controllo**: la settimana e' il sottogruppo, la riga tratteggiata e' la
#    linea centrale (x-bar-bar, la media delle medie settimanali), e la fascia
#    sono i limiti a uno e due errori standard attorno a lei. La varianza e'
#    aggregata su tutta la finestra e ogni settimana ne divide la radice per la
#    radice dei suoi giorni, quindi la fascia si allarga dove una media sta su
#    **meno misure**. Il perche' per esteso sta in `_week_trend_points`. Si
#    disegna con due aree e non due rettangoli, che la larghezza cambia
#    (`run_chart.week_trend_chart`).

# L'ampiezza della finestra, in settimane. Di suo le dodici di `BAND_WEEKS`:
# sono quelle su cui la Week misura gia' le sue fasce, cosi' il Trend si apre
# sugli stessi tre mesi di cui parlano le card.
TREND_MIN_WEEKS = 4
TREND_MAX_WEEKS = 52
TREND_DEFAULT_WEEKS = BAND_WEEKS

# I giorni misurati che servono perche' una settimana porti la fascia.
#
# La ragione per cui erano tre e' caduta: valeva quando l'errore standard si
# calcolava sui giorni della singola settimana, e su due valori era un caso.
# Con la varianza aggregata non lo e' piu' - la larghezza viene dalla finestra
# intera - e una settimana di un giorno solo avrebbe una fascia definita, la
# piu' larga di tutte. Il minimo resta per un motivo diverso: una media fatta
# su uno o due giorni e' un punto debole, e disegnargli attorno una fascia
# **regolare** la farebbe sembrare una misura come le altre.
MIN_WEEK_DAYS = 3

# I decimali in piu' che si tengono sui bordi della fascia. `_band` arrotonda
# ai decimali della misura, e sullo scarto tipo dei 28 giorni va bene perche'
# e' grande; un **errore standard** e' radice di sette volte piu' piccolo e
# cade sotto il passo dell'arrotondamento. Misurato sul VO2max, che di
# decimali ne ha uno: la settimana del 5 ottobre 2026 ha la fascia a
# `[41.2803, 41.3483]`, che arrotondata diventa `[41.3, 41.3]` - un'area di
# altezza zero, cioe' niente. Il valore del punto tiene i suoi decimali; la
# fascia ne tiene due in piu'.
BAND_DIGITS = 2


def _week_trend_points(
    health: pd.DataFrame,
    column: str,
    first: date,
    weeks: int,
    digits: int,
    banda: bool,
) -> tuple[list[dict[str, Any]], Any]:
    """I punti di una serie settimanale, uno per settimana: il lunedi', il
    numero ISO della settimana, la media dei giorni misurati, quanti erano e
    la fascia del suo errore standard.

    Rende anche il **centro**: la media delle medie settimanali, x-bar-bar, uno
    solo per la finestra. E' quello attorno a cui la fascia si costruisce, ed e'
    la riga tratteggiata del grafico.

    **Messe insieme, queste due cose sono una carta di controllo.** Non e' un
    disegno nostro: la settimana e' il sottogruppo, x-bar-bar e' la linea
    centrale, la fascia sono i limiti a uno e due errori standard, e i punti
    sono le medie dei sottogruppi. Si legge come si leggono quelle: **dove sta
    la settimana rispetto a dove di solito sta il corpo**, e un punto fuori dai
    due errori standard e' una settimana che ha qualcosa di diverso.

    Da qui vengono le tre scelte, che insieme stanno in piedi e separate no:

    1. **la varianza e' aggregata**, non quella della singola settimana: si
       prende la varianza dentro ogni settimana, se ne fa la media, e lo scarto
       tipo e' la radice di quella. E' la dispersione *tipica* di una settimana,
       stimata su tutte invece che su sette giorni soli;
    2. **ogni settimana divide per la radice dei suoi giorni**, quindi la fascia
       si allarga dove la media sta su meno misure;
    3. **il centro e' x-bar-bar**, non la media della settimana. Una fascia
       centrata su ogni punto accompagnerebbe la linea e non direbbe niente:
       il punto starebbe dentro la sua fascia per costruzione, sempre.

            varianza_media = media delle varianze settimanali
            scarto_tipo    = radice(varianza_media)
            sterr(i)       = scarto_tipo / radice(giorni della settimana i)
            centro         = media delle medie settimanali

    Le settimane senza nemmeno un giorno misurato restano con `value` a `None`
    e **non si tolgono**, per lo stesso motivo dei giorni in `_trend_points`:
    la linea si spezza nel buco, invece di unire i due estremi di un vuoto che
    non e' mai stato misurato."""
    limits = TREND_LIMITS.get(column, TREND_FLOOR)
    stats = _week_stats(health, column, first, weeks)
    # Lo scarto tipo e' **uno solo per la finestra**, e viene dalla varianza
    # media delle settimane; per ogni settimana si divide per la radice dei
    # suoi giorni. `mean()` salta le settimane senza varianza (quelle con un
    # giorno solo o nessuno); se non ne resta nessuna viene `NaN`, e li'
    # `_band_edges` non disegna niente.
    scarto = math.sqrt(stats["var"].mean()) if stats["var"].notna().any() else float("nan")
    # x-bar-bar: la media delle medie settimanali, non quella di tutti i giorni
    # messi in fila. Sono diverse quando le settimane hanno un numero di giorni
    # diverso, e quella giusta per una carta di controllo e' la prima: ogni
    # settimana e' un'osservazione, e pesa una.
    centro = stats["mean"].mean()
    points = []
    for stamp, row in stats.iterrows():
        monday = stamp.date()
        giorni = 0 if pd.isna(row["days"]) else int(row["days"])
        sterr = scarto / math.sqrt(giorni) if giorni else float("nan")
        points.append(
            {
                "monday": monday.isoformat(),
                "week": monday.isocalendar()[1],
                "value": _value(row["mean"], digits),
                "days": giorni,
                "band": (
                    _band_edges(centro, sterr, limits, digits + BAND_DIGITS)
                    if banda and giorni >= MIN_WEEK_DAYS
                    else None
                ),
            }
        )
    return points, (_value(centro, digits + BAND_DIGITS) if banda else None)


def _week_trend_series(
    health: pd.DataFrame,
    column: str,
    first: date,
    weeks: int,
    digits: int,
    banda: bool,
) -> dict[str, Any]:
    """I punti di una serie e il suo centro, gia' nei nomi che l'API rende."""
    points, centre = _week_trend_points(health, column, first, weeks, digits, banda)
    return {"points": points, "centre": centre}


def _week_trend_training(
    activities: pd.DataFrame, first: date, weeks: int, last: date
) -> dict[str, Any]:
    """Il pannello Training settimana per settimana: i minuti per intensita',
    i chilometri e il dislivello **sommati** sui giorni della settimana.

    `last` taglia i giorni che non sono ancora stati vissuti, cosi' `days` dice
    la verita' sulla settimana in corso: la somma dell'ultimo punto copre i
    giorni che ci sono stati, e il tooltip dice quanti.

    Niente fascia, come nel pannello Training della Day: di una somma l'errore
    standard non e' definito, e fra le settimane di scarico e quelle di carico
    media e scarto tipo direbbero poco."""
    mondays = pd.date_range(first, periods=weeks, freq="7D")
    end = min(first + timedelta(days=weeks * 7 - 1), last)
    daily = _training_daily(activities, first, end)
    by_week = daily.groupby(daily.index - pd.to_timedelta(daily.index.dayofweek, unit="D"))
    somme = by_week.sum().reindex(mondays).fillna(0.0)
    giorni = by_week.size().reindex(mondays).fillna(0).astype(int)
    return {
        "key": "training",
        "title": "Training",
        "icon": section_icon("training"),
        "series": [
            {
                "key": column,
                "label": label,
                "unit": unit,
                "digits": digits,
                "centre": None,
                "points": [
                    {
                        "monday": stamp.date().isoformat(),
                        "week": stamp.date().isocalendar()[1],
                        "value": _value(somme[column].loc[stamp], digits),
                        "days": int(giorni.loc[stamp]),
                        "band": None,
                    }
                    for stamp in mondays
                ],
            }
            for column, label, unit, digits in TREND_TRAINING
        ],
    }


def week_trend_data(
    first: date,
    last: date,
    data_dir: Path = DATA_DIR,
    activities: pd.DataFrame | None = None,
    health: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Le serie settimanali dalla settimana di `first` a quella di `last`
    compresa, pannello per pannello.

    `first` e `last` sono lunedi': lo controlla chi chiama (l'API rifiuta un
    `to` che non lo sia, e un'ampiezza fuori da
    `TREND_MIN_WEEKS`-`TREND_MAX_WEEKS`).

    Gli stessi pannelli e le stesse serie del Trend della Day, nello stesso
    ordine - che e' quello delle card - perche' Report e Trend restino due
    forme della stessa struttura, su qualunque periodo."""
    if activities is None:
        activities = list_activities(data_dir)
    if health is None:
        health = load_health_db(data_dir)

    weeks = (last - first).days // 7 + 1

    panels = []
    for key, (title, series) in TREND_PANELS.items():
        panels.append(
            {
                "key": key,
                "title": title,
                "icon": section_icon(title),
                "series": [
                    {
                        "key": column,
                        "label": label,
                        "unit": unit,
                        "digits": digits,
                        **_week_trend_series(
                            health, column, first, weeks, digits, column not in TREND_NO_BAND
                        ),
                    }
                    for column, label, unit, digits in series
                ],
            }
        )
    panels.append(_week_trend_training(activities, first, weeks, date.today()))
    return {
        "from": first.isoformat(),
        "to": last.isoformat(),
        "weeks": weeks,
        "min_week_days": MIN_WEEK_DAYS,
        "panels": panels,
    }

def _day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"data non valida: {text!r} (serve YYYY-MM-DD)")


def main() -> None:
    """Stampa il JSON del giorno su stdout; i messaggi delle funzioni chiamate
    vanno su stderr, per lasciare stdout pulito a chi legge il JSON."""
    parser = argparse.ArgumentParser(description="I fatti di un giorno, in JSON, per il report giornaliero.")
    parser.add_argument("--day", type=_day, help="il giorno (YYYY-MM-DD); di default oggi")
    args = parser.parse_args()
    day = args.day or date.today()
    if day > date.today():
        parser.error(f"il {day} non e' ancora arrivato")
    with contextlib.redirect_stdout(sys.stderr):
        data = build_daily_data(day)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
