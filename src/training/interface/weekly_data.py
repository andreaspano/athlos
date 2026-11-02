"""I fatti di una settimana (lunedi'-domenica) per il report settimanale.

Lo script prepara i numeri, gli otto agenti `w1_health` ... `w7_summary` ne
scrivono il testo (todo 53): i conti non li fa il modello. Legge solo dati
locali
(`activities.db`, aggiornato dai FIT e dai JSON gia' scaricati): nessuna
chiamata a Garmin. Per avere la settimana aggiornata si lancia prima
`make update_activity`.

Contratto: una media su zero giorni e' `None` (`null` nel JSON), mai `0`; e
ogni media dice su quanti giorni e' fatta.
"""

import argparse
import contextlib
import math
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from training.garmin.config import DATA_DIR
from training.interface.db import list_activities
from training.interface.health_db import load_health_db
from training.interface.sports import has_distance

# Le misure di recupero di ogni mattina, in `days`. L'HRV e' sempre quella
# della notte (`hrv_last_night`): media settimanale e stato Garmin li porta
# avanti anche nei giorni senza orologio, e farebbero sembrare misurate notti
# che non lo sono.
RECOVERY_METRICS = (
    "readiness",
    "resting_hr",
    "hrv_last_night",
    "sleep_hours",
    "sleep_score",
    "stress_avg",
    "body_battery_high",
    "body_battery_low",
)

# Le metriche di cui si conta la copertura: quelle che il report commenta.
# Readiness e carico Garmin li calcola anche senza orologio al polso, le altre
# no: per questo la copertura e' per metrica e non per giorno. Niente SpO2,
# che l'orologio non misura.
COVERAGE_METRICS = (
    "readiness",
    "sleep_hours",
    "sleep_score",
    "hrv_last_night",
    "resting_hr",
    "stress_avg",
    "load_acute",
)

# Le medie di recupero confrontate nelle quattro settimane.
TREND_METRICS = ("readiness", "resting_hr", "hrv_last_night", "sleep_hours", "sleep_score", "stress_avg")

# Il carico di Garmin, a fine giornata.
LOAD_METRICS = (
    "load_acute",
    "load_chronic",
    "acwr",
    "acwr_status",
    "training_status",
    "training_status_phrase",
    "load_aerobic_low",
    "load_aerobic_high",
    "load_anaerobic",
    "load_balance_phrase",
)

# Le misure che la pagina Week mostra con la loro barra (todo 52), con
# l'etichetta a schermo, l'unita' e i decimali. Health e Recovery sono
# **medie** dei sette giorni: il corpo in quella settimana. Il carico e la
# forma no, sono stati di fine settimana, e stanno altrove.
WEEK_MEASURES: tuple[tuple[str, str, str, str, int], ...] = (
    ("health", "resting_hr", "Resting heart rate", "bpm", 0),
    ("health", "hrv_last_night", "HRV", "ms", 0),
    ("health", "resp_sleep_avg", "Breathing in sleep", "/min", 1),
    ("health", "stress_avg", "Stress", "", 0),
    ("recovery", "readiness", "Readiness", "", 0),
    ("recovery", "sleep_hours", "Sleep", "h", 1),
    ("recovery", "body_battery_high", "Body battery, wake-up", "", 0),
    ("recovery", "body_battery_low", "Body battery, low", "", 0),
)

# Le misure che vivono fra 0 e 100, come `MORNING_LIMITS` per il giorno: la
# fascia non deve promettere un valore che la misura non puo' avere.
WEEK_LIMITS: dict[str, tuple[float, float]] = {
    name: (0, 100)
    for name in ("readiness", "stress_avg", "body_battery_high", "body_battery_low")
}

# Quante settimane guarda indietro una fascia della Week, e quante ne
# servono perche' valga qualcosa (todo 52). Dodici settimane sono tre mesi:
# abbastanza da contenere un blocco di lavoro intero, abbastanza poche da
# seguire un cambio di passo. **Non sono i 28 giorni della Day**: attorno a
# una media settimanale quella fascia non direbbe niente, perche' una media
# di sette giorni oscilla molto meno di un singolo giorno e cadrebbe quasi
# sempre dentro.
BAND_WEEKS = 12
MIN_BAND_WEEKS = 6

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# Per i messaggi d'errore, che sono in italiano.
GIORNI = ("lunedi'", "martedi'", "mercoledi'", "giovedi'", "venerdi'", "sabato", "domenica")


def last_closed_monday(today: date) -> date:
    """Il lunedi' della settimana prima di quella di oggi."""
    return today - timedelta(days=today.weekday() + 7)


def _value(value: Any, digits: int = 1) -> Any:
    """Il valore pronto per il JSON: NaN e None diventano None, i numeri
    arrotondati, il resto (testo) com'e'.

    Gli interi di numpy vanno dichiarati: `np.float64` e' un `float` per
    Python, `np.int64` non e' un `int`, e passando di qui intatto faceva
    fallire `json.dumps` (la potenza massima, che e' una colonna di interi)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float, np.integer)):
        rounded = round(float(value), digits)
        return int(rounded) if digits == 0 else rounded
    return value


def _mean(series: pd.Series, digits: int = 1) -> dict[str, Any]:
    """Media e numero di giorni su cui e' fatta; `None` su zero giorni."""
    values = series.dropna()
    return {"mean": _value(values.mean(), digits) if len(values) else None, "days": int(len(values))}


def _week_activities(activities: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Le attivita' della settimana, in ordine di inizio. Un'attivita' sta nel
    giorno in cui comincia, anche se finisce dopo mezzanotte."""
    if activities.empty:
        return activities
    day = activities["start_time"].dt.date
    week = activities[(day >= start) & (day <= end)].copy()
    return week.sort_values("start_time")


def _week_health(health: pd.DataFrame, start: date) -> pd.DataFrame:
    """I 7 giorni di salute della settimana, uno per riga: NaN dove non c'e'
    il dato, anche fuori dall'intervallo che il database copre."""
    days = pd.date_range(start, periods=7, freq="D", name="day")
    return health.reindex(days)


def _activity_row(row: pd.Series) -> dict[str, Any]:
    start = row["start_time"]
    measured = has_distance(row["sport"])
    return {
        "date": start.date().isoformat(),
        "weekday": WEEKDAYS[start.weekday()],
        "start_time": start.strftime("%H:%M"),
        "sport": row["sport"],
        "sub_sport": row["sub_sport"] if row["sub_sport"] not in (None, "", "generic") else None,
        "name": row["activity_name"],
        # Niente distanza per il tapis roulant: e' una stima del polso (todo
        # 45). Di quelle sedute restano i minuti e il battito.
        "distance_km": _value(row["total_distance_km"], 2) if measured else None,
        "duration_min": _value(row["total_time_min"], 0),
        "ascent_m": _value(row["total_ascent_m"], 0),
        "avg_hr": _value(row["avg_heart_rate"], 0),
        "max_hr": _value(row["max_heart_rate"], 0),
    }


def _training(week: pd.DataFrame, start: date, last_day: date, today: date) -> dict[str, Any]:
    """Totali della settimana. Distanza e dislivello solo per sport: sommati
    fra sport diversi non vogliono dire niente, e per gli sport senza
    distanza (il tapis roulant) la distanza non si somma affatto. I giorni di riposo contano
    solo fino all'ultimo giorno passato, e oggi senza attivita' non e' ancora
    un riposo: la giornata non e' finita."""
    by_sport = {}
    for sport, group in week.groupby("sport", sort=False):
        by_sport[sport] = {
            "sessions": int(len(group)),
            "time_min": _value(group["total_time_min"].sum(), 0),
            "distance_km": (
                _value(group["total_distance_km"].sum(min_count=1), 1)
                if has_distance(sport)
                else None
            ),
            "ascent_m": _value(group["total_ascent_m"].sum(min_count=1), 0),
        }
    active = set(week["start_time"].dt.date) if not week.empty else set()
    elapsed = [start + timedelta(days=i) for i in range((last_day - start).days + 1)]
    rest = [WEEKDAYS[d.weekday()] for d in elapsed if d not in active and d < today]
    return {
        "sessions": int(len(week)),
        "time_min": _value(week["total_time_min"].sum(), 0) if not week.empty else 0,
        "by_sport": by_sport,
        "active_days": len(active),
        "rest_days": rest,
    }


def _days(week: pd.DataFrame, health: pd.DataFrame, start: date, last_day: date) -> list[dict[str, Any]]:
    """Una riga per giorno: le attivita' (o nessuna) e le misure di recupero
    di quella mattina. Il sonno con la data di un giorno e' la notte che porta
    a quel giorno: quello di lunedi' e' la notte fra domenica e lunedi'."""
    rows = []
    for i in range(7):
        day = start + timedelta(days=i)
        today_acts = week[week["start_time"].dt.date == day] if not week.empty else week
        morning = health.loc[pd.Timestamp(day)]
        rows.append(
            {
                "date": day.isoformat(),
                "weekday": WEEKDAYS[i],
                "future": day > last_day,
                "activities": [
                    {
                        "sport": a["sport"],
                        "name": a["activity_name"],
                        "distance_km": (
                            _value(a["total_distance_km"], 2) if has_distance(a["sport"]) else None
                        ),
                        "duration_min": _value(a["total_time_min"], 0),
                    }
                    for _, a in today_acts.iterrows()
                ],
                "recovery": {m: _value(morning[m], 1) for m in RECOVERY_METRICS},
                "sleep_night": f"the night going into {WEEKDAYS[i]}",
            }
        )
    return rows


def _load(health: pd.DataFrame, last_day: date) -> dict[str, Any] | None:
    """Il carico dell'ultimo giorno della settimana che lo ha (Garmin lo da' a
    fine giornata), e quale giorno e'. `None` se non c'e' in nessun giorno."""
    known = health.loc[: pd.Timestamp(last_day), "load_acute"].dropna()
    if known.empty:
        return None
    as_of = known.index[-1]
    row = health.loc[as_of]
    return {"as_of": as_of.date().isoformat(), **{m: _value(row[m], 2) for m in LOAD_METRICS}}


def _vo2max(health: pd.DataFrame, start: date, end: date) -> list[dict[str, Any]]:
    """Le misure di VO2max fatte nella settimana: quelle con `vo2max_date`
    dentro la settimana, una per data (Garmin ripete l'ultima nei giorni
    dopo)."""
    rows = health[["vo2max", "vo2max_date"]].dropna()
    # Senza il filtro in blocco questa funzione scorreva riga per riga tutto
    # lo storico, e la chiamano cinque volte per richiesta (la settimana e le
    # quattro del confronto): da sola era mezzo secondo.
    measured = rows["vo2max_date"].astype(str).str.slice(0, 10)
    inside = (measured >= start.isoformat()) & (measured <= end.isoformat())
    seen = {
        date.fromisoformat(d): float(v)
        for d, v in zip(measured[inside], rows.loc[inside, "vo2max"])
    }
    return [{"date": d.isoformat(), "value": _value(v, 1)} for d, v in sorted(seen.items())]


def _week_summary(
    activities: pd.DataFrame, health: pd.DataFrame, start: date, last_day: date, today: date
) -> dict[str, Any]:
    """I totali e le medie di una settimana, per il confronto fra settimane."""
    end = start + timedelta(days=6)
    week = _week_activities(activities, start, end)
    week_health = _week_health(health, start)
    training = _training(week, start, last_day, today)
    load = _load(week_health, last_day)
    vo2max = _vo2max(health, start, end)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sessions": training["sessions"],
        "time_min": training["time_min"],
        "by_sport": training["by_sport"],
        "rest_days": len(training["rest_days"]),
        "health_days": int(week_health["sleep_hours"].notna().sum()),
        "recovery": {m: _mean(week_health[m], 1) for m in TREND_METRICS},
        "load_acute": load["load_acute"] if load else None,
        "load_as_of": load["as_of"] if load else None,
        "vo2max": vo2max[-1]["value"] if vo2max else None,
    }


def _week_stats(health: pd.DataFrame, column: str, first: date, weeks: int) -> pd.DataFrame:
    """Settimana per settimana, dalla settimana di `first` per `weeks`
    settimane: la media dei giorni misurati (`mean`), quanti erano (`days`) e la
    varianza **dentro** quella settimana (`var`). Una riga per settimana,
    indicizzata sul lunedi'.

    Il raggruppamento e' per lunedi' (`index - dayofweek`), in **una passata
    sola** su tutta la finestra: una media alla volta vorrebbe un `reindex`
    per ogni settimana, cinquantadue per colonna e venti colonne.

    Qui si rende la **varianza**, non l'errore standard: l'errore standard non
    si puo' calcolare una settimana alla volta, perche' la sua varianza e'
    quella media di tutte le settimane della finestra (`_week_trend_points`).
    Una settimana con un giorno solo ha `var` a `NaN` e non entra in quella
    media; una senza nemmeno un giorno ha `mean` a `NaN`, il punto resta nullo e
    la linea si spezza, come i giorni senza misura del Trend della Day.

    Il `reindex` finale rimette le settimane che il raggruppamento non ha visto
    perche' non avevano un solo valore: senza, una settimana vuota sparirebbe
    dalla serie invece di restarci come buco."""
    days = pd.date_range(first, periods=weeks * 7, freq="D")
    daily = health.reindex(days)[column]
    mondays = daily.index - pd.to_timedelta(daily.index.dayofweek, unit="D")
    by_week = daily.groupby(mondays)
    stats = pd.DataFrame(
        {"mean": by_week.mean(), "days": by_week.count(), "var": by_week.var()}
    )
    return stats.reindex(pd.date_range(first, periods=weeks, freq="7D"))


def _week_means(
    health: pd.DataFrame, columns: list[str], first: date, weeks: int
) -> pd.DataFrame:
    """Le medie settimanali di **piu' colonne in una passata**: indice i
    lunedi' delle `weeks` settimane che cominciano con quella di `first`,
    colonne le misure.

    Stesso raggruppamento di `_week_stats` (`index - dayofweek`), e lo stesso
    motivo che il suo docstring spiega: una media alla volta vuole un
    `reindex` per ogni settimana, e per le otto misure di `_week_measures`
    sulle tredici settimane erano 104 reindex del frame intero a ogni
    richiesta della Week — 64 ms dei 159 di `build_weekly_data`, misurati.

    Il `reindex` finale rimette le settimane che il raggruppamento non ha
    visto perche' non avevano nemmeno un valore: senza, una settimana vuota
    spariderebbe invece di restare un buco."""
    days = pd.date_range(first, periods=weeks * 7, freq="D")
    daily = health.reindex(days)[columns]
    mondays = daily.index - pd.to_timedelta(daily.index.dayofweek, unit="D")
    means = daily.groupby(mondays).mean()
    return means.reindex(pd.date_range(first, periods=weeks, freq="7D"))


def _week_measures(health: pd.DataFrame, monday: date) -> dict[str, dict[str, Any]]:
    """Le misure di Health e Recovery della settimana (todo 52): la media
    dei sette giorni e la fascia in cui si e' mossa nelle `BAND_WEEKS`
    settimane precedenti.

    **La fascia non e' quella della Day.** Li' il confronto e' fra il valore
    di un giorno e i 28 giorni prima; qui fra una media settimanale e le
    dodici medie settimanali che la precedono. Attorno a una media la fascia
    giornaliera non direbbe niente: sette giorni oscillano molto meno di
    uno, e il valore cadrebbe quasi sempre dentro.

    `_band` e' la stessa della Day, con il minimo dei valori abbassato a
    `MIN_BAND_WEEKS`: e' importata qui dentro e non in testa al modulo
    perche' `daily_data` importa gia' da qui, e in testa sarebbe un giro
    chiuso."""
    from training.interface.daily_data import _band

    # Le tredici settimane — le dodici della fascia piu' questa — e le otto
    # misure, in una volta. L'ultima riga e' questa settimana, le altre
    # dodici sono la fascia.
    columns = [column for _, column, _, _, _ in WEEK_MEASURES]
    means = _week_means(health, columns, monday - timedelta(weeks=BAND_WEEKS), BAND_WEEKS + 1)
    out: dict[str, dict[str, Any]] = {}
    for card, column, label, unit, digits in WEEK_MEASURES:
        serie = means[column]
        before = serie.iloc[:-1].reset_index(drop=True).astype("float64")
        out[column] = {
            "card": card,
            "label": label,
            "unit": unit,
            "value": _value(serie.iloc[-1], digits),
            "band": _band(before, WEEK_LIMITS.get(column), digits, MIN_BAND_WEEKS),
            "weeks": int(before.notna().sum()),
        }
    return out


def _as_of(week_health: pd.DataFrame, last_day: date) -> date:
    """L'ultimo giorno della settimana che porta dei dati di salute, o
    `last_day` se non ce n'e' nessuno.

    Serve al carico, ai bersagli e alla forma: sono stati di fine settimana,
    e in una settimana ancora in corso l'ultimo giorno e' oggi, i cui file
    arrivano solo col giro della sera."""
    known = week_health[week_health["load_acute"].notna() | week_health["readiness"].notna()]
    if known.empty:
        return last_day
    return min(known.index[-1].date(), last_day)


# I punteggi di forma che la Week mostra con la loro barra. Niente soglia
# ne' acclimatamenti: la prima la conosciamo solo nell'ultima versione, i
# secondi stanno a zero quasi tutto l'anno.
FITNESS_SCORES: tuple[tuple[str, int], ...] = (
    ("vo2max", 1),
    ("endurance_score", 0),
    ("hill_score", 0),
)
# Come si chiamano nel blocco `fitness`, che viene da `fitness_on`.
FITNESS_KEYS = {"vo2max": "vo2max", "endurance_score": "endurance", "hill_score": "hill"}


def _at_end_of(health: pd.DataFrame, column: str, sunday: date) -> float | None:
    """L'ultimo valore noto di `column` fino alla domenica compresa: e' il
    valore "di fine settimana" di uno stato che si muove in settimane."""
    values = health.loc[: pd.Timestamp(sunday), column].dropna()
    return float(values.iloc[-1]) if len(values) else None


def _fitness_bands(health: pd.DataFrame, monday: date) -> dict[str, dict[str, Any] | None]:
    """Le fasce dei punteggi di forma sulle `BAND_WEEKS` settimane prima
    (todo 52).

    **A dodici settimane come tutto il resto della Week**, non ai 28 giorni
    della Day: qui il confronto e' fra la forma di fine settimana e quella
    delle dodici settimane che la precedono, e una fascia giornaliera
    direbbe un'altra cosa su una pagina che parla di settimane."""
    from training.interface.daily_data import _band

    out: dict[str, dict[str, Any] | None] = {}
    for column, digits in FITNESS_SCORES:
        before = pd.Series(
            [
                # La domenica che **chiude** la settimana che comincia
                # `monday - 7k`, scritta come la scrive `_week_load`. Con
                # `weeks=k, days=1` si campionava una settimana troppo
                # indietro per ogni k: le fasce stavano sulle settimane da 2
                # a 13 invece che sulle dodici precedenti, e la domenica che
                # chiude quella appena passata non veniva guardata mai.
                _at_end_of(health, column, monday - timedelta(weeks=k) + timedelta(days=6))
                for k in range(1, BAND_WEEKS + 1)
            ],
            dtype="float64",
        )
        out[FITNESS_KEYS[column]] = _band(before, None, digits, MIN_BAND_WEEKS)
    return out


# I tre tempi per zona della settimana (todo 54), nell'ordine in cui si
# leggono nella card: le colonne di `activities` le riempie `db._zone_minutes`
# dai record, seduta per seduta e con i confini di quella seduta.
ZONE_MINUTES: tuple[tuple[str, str], ...] = (
    ("low_aerobic", "min_low_aerobic"),
    ("high_aerobic", "min_high_aerobic"),
    ("anaerobic", "min_anaerobic"),
)


def _weeks_by_monday(
    activities: pd.DataFrame, first: date, weeks: int
) -> dict[date, pd.DataFrame]:
    """Le attivita' delle `weeks` settimane da `first`, divise per lunedi':
    **un filtro solo** invece di uno per settimana.

    `_zone_totals` chiamava `_week_activities` tredici volte, e ognuna
    passava su tutte le attivita' con la sua maschera, la sua copia e il suo
    ordinamento: 26 ms dei 159 di `build_weekly_data`, misurati. Le settimane
    senza sedute ci sono comunque, come frame vuoto: per le zone un riposo e'
    uno zero vero e deve pesare nella fascia (vedi `_zone_totals`)."""
    mondays = [first + timedelta(weeks=k) for k in range(weeks)]
    empty = activities.iloc[:0]
    if activities.empty:
        return {monday: empty for monday in mondays}
    day = activities["start_time"].dt.date
    start, end = mondays[0], mondays[-1] + timedelta(days=6)
    inside = activities[(day >= start) & (day <= end)].copy()
    inside = inside.sort_values("start_time")
    their_monday = inside["start_time"].dt.date.map(
        lambda d: d - timedelta(days=d.weekday())
    )
    groups = {monday: frame for monday, frame in inside.groupby(their_monday, sort=False)}
    return {monday: groups.get(monday, empty) for monday in mondays}


def _zone_totals(activities: pd.DataFrame, monday: date) -> dict[str, float | None]:
    """I minuti per zona di una settimana, dalle sue attivita'."""
    return _zone_totals_of(_week_activities(activities, monday, monday + timedelta(days=6)))


def _zone_totals_of(week: pd.DataFrame) -> dict[str, float | None]:
    """I minuti per zona sommati sulle sedute di una settimana. `None` dove
    nessuna seduta della settimana ha quel dato — che non e' zero: zero vuol
    dire che hai pedalato senza mai arrivarci."""
    totals: dict[str, float | None] = {}
    for key, column in ZONE_MINUTES:
        if week.empty or column not in week:
            totals[key] = None if not week.empty else 0.0
            continue
        values = week[column].dropna()
        # Una settimana senza sedute e' uno zero vero: il riposo e' un dato,
        # e nella fascia delle dodici settimane deve pesare come tale —
        # togliere i riposi direbbe "quanto alleni quando alleni", non come
        # va la stagione. Una settimana con sedute ma **senza** frequenza
        # cardiaca e' un'altra cosa, ed esce dal conto (`None`).
        totals[key] = float(values.sum()) if len(values) or week.empty else None
    return totals


# Del carico di Garmin, nella settimana resta quello che e' della settimana
# (todo 54). Le frasi restano: sono giudizi, non misure, e l'agente le usa
# per dire a parole quello che i minuti per zona dicono in numeri.
WEEK_LOAD_KEYS = (
    "as_of",
    "load_acute",
    "training_status",
    "training_status_phrase",
    "load_balance_phrase",
)


def _week_load(
    health: pd.DataFrame, week_health: pd.DataFrame, monday: date, last_day: date
) -> dict[str, Any] | None:
    """Il carico della settimana: il carico acuto e le frasi di Garmin,
    senza le finestre di 28 giorni, con la fascia delle dodici settimane.

    Il carico acuto e' la somma degli ultimi sette giorni: letto alla
    domenica e' esattamente la settimana, e per questo resta. La fascia
    prende il carico di ognuna delle dodici settimane prima, allo stesso
    modo — la domenica di ognuna."""
    from training.interface.daily_data import _band

    load = _load(week_health, last_day)
    if not load:
        return None
    kept = {k: load[k] for k in WEEK_LOAD_KEYS if k in load}
    history = []
    for k in range(BAND_WEEKS, 0, -1):
        start = monday - timedelta(weeks=k)
        before = _load(_week_health(health, start), start + timedelta(days=6))
        history.append(before["load_acute"] if before else None)
    series = pd.Series(history, dtype="float64")
    kept["band"] = _band(series, limits=(0, math.inf), digits=0, min_values=MIN_BAND_WEEKS)
    kept["weeks"] = int(series.notna().sum())
    return kept


def _week_zones(activities: pd.DataFrame, monday: date) -> dict[str, Any]:
    """Il tempo per zona della settimana, con la fascia delle dodici
    settimane prima (todo 54).

    Sostituisce i tre carichi per effetto di Garmin, che sono a 28 giorni:
    due settimane vicine ne condividevano tre quarti e si somigliavano per
    forza. Questi sono minuti misurati sui sette giorni.

    `sessions_without_hr` dice quante sedute non hanno la frequenza —
    l'arrampicata, le camminate con l'orologio in tasca — e
    `sessions_without_zones` quante non entrano nel conto dei minuti, che e'
    un insieme piu' grande: ci cadono anche le sedute con la frequenza ma
    senza una soglia con cui dividere le zone. Contava le seconde e le
    chiamava le prime, e cosi' per ogni settimana prima di agosto 2026
    diceva agli agenti che l'intera settimana era stata registrata senza
    frequenza cardiaca — 817 sedute dell'archivio hanno la frequenza e non
    hanno le zone.

    **La fascia vuole almeno una settimana misurata.** Le dodici settimane
    prima entrano cosi': una senza sedute vale zero, perche' il riposo e' un
    dato della stagione (vedi `_zone_totals`), una con sedute ma senza
    soglia non vale niente (`None`) e resta fuori. Dove nessuna delle dodici
    era misurabile restavano solo gli zeri dei riposi, e la fascia veniva
    0-0: la settimana del 3 agosto mostrava 385 minuti contro una fascia
    piatta, cioe' la barra li disegnava come un fuori scala assoluto, quando
    le settimane di confronto semplicemente non avevano una soglia. Su 52
    settimane dell'ultimo anno succedeva a 21, e tutte e 21 avevano la
    fascia 0-0."""
    from training.interface.daily_data import _band

    # Le tredici settimane in un filtro solo: le dodici della fascia e
    # questa. La settimana di `monday` e' l'ultima.
    by_monday = _weeks_by_monday(activities, monday - timedelta(weeks=BAND_WEEKS), BAND_WEEKS + 1)
    week = by_monday[monday]
    totals = _zone_totals_of(week)
    history = [
        _zone_totals_of(by_monday[monday - timedelta(weeks=k)])
        for k in range(BAND_WEEKS, 0, -1)
    ]
    # Quante delle dodici avevano sedute **e** si sono potute misurare: se
    # nessuna, la fascia non si disegna (vedi il docstring).
    measured_weeks = sum(
        1
        for k, h in zip(range(BAND_WEEKS, 0, -1), history)
        if len(by_monday[monday - timedelta(weeks=k)]) and h["low_aerobic"] is not None
    )
    zones: dict[str, Any] = {}
    for key, _column in ZONE_MINUTES:
        series = pd.Series([h[key] for h in history], dtype="float64")
        zones[key] = {
            "minutes": _value(totals[key], 0),
            # Il fondo della fascia si ferma a zero: due scarti tipo sotto la
            # media davano "-203 minuti", che sulla barra sarebbe una scala
            # piu' lunga del possibile (lo stesso rimedio del body battery,
            # todo 46).
            "band": (
                _band(series, limits=(0, math.inf), digits=0, min_values=MIN_BAND_WEEKS)
                if measured_weeks
                else None
            ),
            # Le settimane che hanno dato un valore restano contate anche
            # quando la fascia non si disegna: dicono che il confronto c'era,
            # ma era fatto di soli riposi.
            "weeks": int(series.notna().sum()),
        }
    without_hr = without_zones = 0
    if not week.empty:
        if "avg_heart_rate" in week:
            without_hr = int(week["avg_heart_rate"].isna().sum())
        if "min_low_aerobic" in week:
            without_zones = int(week["min_low_aerobic"].isna().sum())
    zones["sessions_without_hr"] = without_hr
    zones["sessions_without_zones"] = without_zones
    # Con tutte e tre le zone senza misura, la somma di niente faceva "0
    # minuti misurati", che si legge come "misurati, e sono zero". Nessuna
    # misura e' `None`, come ogni altro valore di questo payload.
    measured = [totals[k] for k, _ in ZONE_MINUTES if totals[k] is not None]
    zones["measured_min"] = _value(sum(measured), 0) if measured else None
    return zones


def _week_fitness(
    health: pd.DataFrame, activities: pd.DataFrame, monday: date, last_day: date, data_dir: Path
) -> dict[str, Any]:
    """La forma alla fine della settimana (todo 52): VO2max, i due punteggi,
    gli acclimatamenti e la soglia.

    Non si media: sono stati, non cose che succedono nei sette giorni. Vale
    quello dell'ultimo giorno — della domenica, o di oggi se la settimana e'
    ancora aperta. Sono gli stessi numeri della card Fitness della Day, ma
    le fasce no: i tre punteggi prendono quella delle dodici settimane
    (`_fitness_bands`), perche' la domanda della Week e' dove sta questa
    settimana nella stagione, non dove sta oggi nel mese."""
    from training.interface.daily_data import _hr_zones, fitness_on
    from training.interface.health import load_lactate_threshold

    fitness = fitness_on(health, last_day, data_dir)
    lactate = load_lactate_threshold(data_dir)
    fitness["lactate_threshold"] = (
        lactate if lactate and lactate["as_of"] <= last_day.isoformat() else None
    )
    # La soglia dell'orologio, il ripiego di quando Garmin non ne ha
    # rilevata una: viene dalle zone dell'ultima attivita' a piedi, come
    # nella Day (`api/daily.daily_payload`).
    zones = _hr_zones(activities, last_day)
    fitness["threshold_hr"] = (
        {"value": zones["threshold_hr"], "as_of": zones["as_of"]}
        if zones and zones.get("threshold_hr") is not None
        else None
    )
    # Le fasce che arrivano da `fitness_on` sono quelle della Day, a 28
    # giorni: qui si sostituiscono con quelle a dodici settimane.
    for chiave, banda in _fitness_bands(health, monday).items():
        if isinstance(fitness.get(chiave), dict):
            fitness[chiave]["band"] = banda
    return fitness


def build_weekly_data(
    monday: date,
    data_dir: Path = DATA_DIR,
    today: date | None = None,
    activities: pd.DataFrame | None = None,
    health: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """I fatti della settimana che comincia `monday`, come dizionario pronto
    per il JSON. Una settimana non ancora finita si puo' chiedere: `partial`
    e `last_day` dicono fin dove arriva.

    `activities` e `health` sono quelli di `list_activities` e
    `load_health_db`, come in `build_daily_data`: l'API li passa dalla sua
    cache, perche' rileggerli a ogni richiesta costa un secondo mentre tutto
    il conto della settimana ne costa un decimo; senza, si leggono qui."""
    if monday.weekday() != 0:
        raise ValueError(f"{monday} non e' un lunedi'")
    today = today or date.today()
    if monday > today:
        raise ValueError(f"la settimana del {monday} non e' ancora cominciata")

    end = monday + timedelta(days=6)
    partial = end >= today
    last_day = min(end, today)

    if activities is None:
        activities = list_activities(data_dir)
    if health is None:
        health = load_health_db(data_dir)

    week = _week_activities(activities, monday, end)
    week_health = _week_health(health, monday)

    return {
        "week": {
            "start": monday.isoformat(),
            "end": end.isoformat(),
            "partial": partial,
            "last_day": last_day.isoformat(),
        },
        "health_days": int(week_health["sleep_hours"].notna().sum()),
        "activities": [_activity_row(r) for _, r in week.iterrows()],
        "days": _days(week, week_health, monday, last_day),
        "training": _training(week, monday, last_day, today),
        # **Solo le misure della settimana** (todo 54): il carico acuto e'
        # la somma degli ultimi sette giorni, e letto alla domenica e'
        # esattamente lunedi-domenica. Il carico cronico, il rapporto fra i
        # due e i tre carichi per effetto sono finestre di 28 giorni: nella
        # Day raccontano il mese attorno al giorno, qui facevano somigliare
        # due settimane vicine solo perche' ne condividevano tre quarti.
        "load": _week_load(health, week_health, monday, last_day),
        # Il tempo per zona della settimana: la composizione del carico, che
        # il totale da solo non dice — lo stesso numero puo' essere dieci ore
        # lente o tre ore dure.
        "zones": _week_zones(activities, monday),
        "vo2max": _vo2max(health, monday, end),
        "coverage": {m: int(week_health[m].notna().sum()) for m in COVERAGE_METRICS},
        # Health e Recovery come medie dei sette giorni, con la fascia delle
        # dodici settimane prima; Fitness come stava alla fine (todo 52).
        "measures": _week_measures(health, monday),
        # **Non `last_day` ma l'ultimo giorno che ha dei dati.** In una
        # settimana in corso l'ultimo giorno e' oggi, e i file di oggi
        # arrivano col giro della sera: fino ad allora carico, bersagli e
        # acclimatamenti sarebbero vuoti, e le card senza barre.
        "fitness": _week_fitness(
            health, activities, monday, _as_of(week_health, last_day), data_dir
        ),
        # Dalla piu' vecchia a questa; le tre prima sono sempre chiuse.
        "four_weeks": [
            _week_summary(activities, health, start, min(start + timedelta(days=6), last_day), today)
            for start in (monday - timedelta(weeks=k) for k in (3, 2, 1, 0))
        ],
    }


def _monday(text: str) -> date:
    try:
        day = date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"data non valida: {text!r} (serve YYYY-MM-DD)")
    if day.weekday() != 0:
        raise argparse.ArgumentTypeError(f"{day} e' {GIORNI[day.weekday()]}, non lunedi'")
    return day


def main() -> None:
    """Stampa il JSON della settimana su stdout; i messaggi delle funzioni
    chiamate vanno su stderr, per lasciare stdout pulito a chi legge il
    JSON."""
    parser = argparse.ArgumentParser(description="I fatti di una settimana, in JSON, per il report settimanale.")
    parser.add_argument(
        "--week",
        type=_monday,
        help="il lunedi' della settimana (YYYY-MM-DD); di default l'ultima settimana chiusa",
    )
    args = parser.parse_args()
    monday = args.week or last_closed_monday(date.today())
    try:
        with contextlib.redirect_stdout(sys.stderr):
            data = build_weekly_data(monday)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
