"""I giri di una seduta, dai messaggi `lap` del FIT alla tabella della card
Session (todo 79).

Un giro e' un pezzo di seduta: il riscaldamento, una ripetuta, un recupero.
L'orologio li scrive sempre, ma **non sempre vogliono dire qualcosa**: in una
corsa libera sono l'auto-lap al chilometro, e nove righe di numeri per una
corsa piana non le ha chieste nessuno.

Quel che distingue le due cose e' `workout_step`, il passo dell'allenamento
che il giro stava seguendo — ma **non la sua presenza**: guardando le 985
sedute, tre portano `workout_step` a zero su giri che sono l'auto-lap al
chilometro e nient'altro (una corsa del settembre 2025, una sul nastro). Il
segnale vero e' che i passi siano **piu' di uno**, cioe' che l'orologio sia
passato da un pezzo al successivo, e che almeno un giro sia di lavoro
(`is_structured`).

I nomi delle righe li decide questo modulo e non il browser, cosi' la
tabella e il testo del report chiamano le stesse cose con le stesse parole.
**Il nome lo da' il posto del giro, non la sua intensita'**: nelle ripetute
del 15 ottobre i recuperi fra una ripetuta e l'altra sono scritti
`cooldown`, come il defaticamento vero in fondo, e chiamarli tutti
"Cool-down" direbbe che quella seduta e' finita cinque volte.
"""

from typing import Any

import pandas as pd

from training.interface.sports import has_distance

# Un ultimo giro di pochi secondi, chiuso dalla fine della seduta, e' il
# tempo fra l'ultimo chilometro e il dito sul tasto: non e' un pezzo della
# seduta e non va in tabella. Il 29 ottobre erano sette secondi.
TAIL_LAP_MAX_SECONDS = 30

# Il giro di lavoro: l'unica intensita' di cui ci si fida, ed e' quella che
# fa le ripetute. Gli altri nomi li da' il posto (vedi `_label`).
WORK = "active"


def _pace_s_per_km(time_s: float | None, distance_m: float | None) -> float | None:
    """I secondi al chilometro di un giro. `None` dove non si puo' dire:
    senza distanza (il tapis roulant, dove la indovina il polso), o con un
    giro fermo."""
    if not time_s or not distance_m or distance_m <= 0:
        return None
    return float(time_s) / (float(distance_m) / 1000)


def is_structured(laps: pd.DataFrame) -> bool:
    """Se la seduta era fatta di pezzi da leggere riga per riga.

    Si guarda **i giri di lavoro**, non tutti: un allenamento con
    riscaldamento e defaticamento ha tre passi diversi anche quando di
    lavoro ce n'e' uno solo, e contandoli tutti bastava quello per dire
    "strutturata". Il lungo del 31 ottobre — 115 minuti continui sotto il
    workout `w01_long` — veniva presentato come **quattordici ripetute**,
    che sono i suoi auto-lap al chilometro dentro l'unico passo di lavoro:
    quattordici righe in tabella e quattordici "ripetute" nei fatti
    dell'agente di Training.

    Due vie, perche' le ripetute si scrivono in due modi (vedi
    `fit._workout`):

    - **passi di lavoro diversi**: l'orologio e' passato da un pezzo al
      successivo, ed e' il caso di `Rip_4x5`, dove i giri di lavoro portano
      i passi 1, 3, 5, 7, 9;
    - **un passo solo, chiuso a tempo**: `Rip_5min4T` scrive le quattro
      ripetute come un passo dentro un `repeat`, e i suoi giri di lavoro
      hanno tutti il passo 1 — ma li chiude la durata del passo
      (`trigger = time`), non l'auto-lap al chilometro
      (`trigger = distance`), che e' quello che fa le quattordici righe del
      lungo.

    Provata su tutte le 984 sedute con giri: una sola cambia verdetto, ed e'
    il lungo del 31 ottobre."""
    if laps.empty or "workout_step" not in laps:
        return False
    work = laps[laps["intensity"] == WORK]
    if work.empty:
        return False
    if len(work["workout_step"].dropna().unique()) >= 2:
        return True
    return bool((work["trigger"] == "time").any())


def _without_tail(laps: pd.DataFrame) -> pd.DataFrame:
    """Senza l'ultimo giro se e' la coda di pochi secondi della fine."""
    if laps.empty:
        return laps
    last = laps.iloc[-1]
    time_s = last.get("time_s")
    ends = last.get("trigger") == "session_end"
    if ends and time_s is not None and float(time_s) < TAIL_LAP_MAX_SECONDS:
        return laps.iloc[:-1]
    return laps


def _label(index: int, intensity: str | None, reps: int, first_work: int, last_work: int) -> str:
    """Come si chiama il giro numero `index`, dal suo posto fra i giri di
    lavoro: prima del primo e' riscaldamento, dopo l'ultimo e'
    defaticamento, in mezzo e' recupero. Un giro di lavoro e' la ripetuta
    numero `reps`."""
    if intensity == WORK:
        return f"Rep {reps}"
    if index < first_work:
        return "Warm-up"
    if index > last_work:
        return "Cool-down"
    return "Recovery"


def _value(value: Any, digits: int | None = None) -> Any:
    """Un numero pulito, o `None`: gli interi di sqlite tornano `numpy.int64`
    e i vuoti `NaN`, e nessuno dei due va in un JSON."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    number = float(value)
    return number if digits is None else round(number, digits)


def session_laps(laps: pd.DataFrame, sport: str | None) -> dict[str, Any]:
    """I giri di una seduta pronti da mostrare: se era strutturata, e la
    lista con il nome di ogni pezzo.

    Una seduta non strutturata rende la lista **vuota**: i suoi giri sono
    l'auto-lap al chilometro, e la card non ne fa una tabella.

    Degli sport senza distanza (il tapis roulant, todo 45) restano tempo e
    battiti: distanza e ritmo verrebbero dalla stima del polso, che in salita
    sbaglia di molto."""
    structured = is_structured(laps)
    if not structured:
        return {"structured": False, "laps": []}
    measured = has_distance(sport)
    body = _without_tail(laps)
    # Dove stanno i giri di lavoro: il nome di tutti gli altri dipende da
    # qui, e si sa solo guardando la seduta intera.
    work = [i for i, lap in enumerate(body.itertuples()) if getattr(lap, "intensity", None) == WORK]
    # Senza giri di lavoro non resta una tabella da leggere: succede solo se
    # l'unico attivo era la coda di pochi secondi appena tolta.
    if not work:
        return {"structured": False, "laps": []}
    first_work, last_work = work[0], work[-1]
    rows: list[dict[str, Any]] = []
    reps = 0
    for index, lap in enumerate(body.itertuples()):
        intensity = getattr(lap, "intensity", None)
        if intensity == WORK:
            reps += 1
        label = _label(index, intensity, reps, first_work, last_work)
        distance_m = _value(getattr(lap, "distance_m", None), 0) if measured else None
        time_s = _value(getattr(lap, "time_s", None), 0)
        rows.append(
            {
                "index": int(lap.lap_index),
                "label": label,
                "intensity": intensity,
                "workout_step": (
                    int(step) if (step := _value(getattr(lap, "workout_step", None))) is not None else None
                ),
                "time_s": time_s,
                "distance_m": distance_m,
                "pace_s_per_km": (
                    _value(_pace_s_per_km(time_s, distance_m), 0) if measured else None
                ),
                "avg_hr": (None if (hr := _value(getattr(lap, "avg_hr", None))) is None else int(hr)),
                "max_hr": (None if (hr := _value(getattr(lap, "max_hr", None))) is None else int(hr)),
            }
        )
    return {"structured": True, "laps": rows}
