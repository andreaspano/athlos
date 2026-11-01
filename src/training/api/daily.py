"""I fatti di un giorno come li vede la pagina: `build_daily_data` piu' quello
che l'API aggiunge sopra (todo 37 e 38).

Sta qui e non in `daily_data.py` perche' il JSON del report (`make
daily_data`) deve restare com'e': la card Fitness e il sonno in minuti li
vuole la pagina, non il report settimanale.

Lo usano due strade, e devono vedere le stesse cose: l'endpoint
`/api/daily/{day}` e l'orchestratore del Refresh, che scrive questo stesso
dizionario nel file che gli agenti leggono. Quando l'agente di Fitness
leggeva il JSON di `make daily_data`, che il blocco `fitness` non ce l'ha,
scriveva che i punteggi non c'erano mentre la card accanto li mostrava."""

from datetime import date
from pathlib import Path
from typing import Any

from training.api.cache import load_activities, load_health
from training.api.score import daily_scores
from training.interface.daily_data import build_daily_data, fitness_on
from training.interface.health import load_lactate_threshold


def daily_payload(day: date, data_dir: Path) -> dict[str, Any]:
    """Tutto quello che si sa del giorno, nella forma che la pagina riceve."""
    health = load_health(data_dir)
    data = build_daily_data(day, data_dir, load_activities(data_dir), health)
    # Il sonno della mattina in minuti, per scriverlo "8h04": `sleep_hours`
    # e' arrotondato a 0.1 h (6 minuti), le ore notte per notte a 0.01.
    hours = data["sleep_last_7"]["hours"].get(day.isoformat())
    # La card Fitness (todo 37). La soglia e' quella di `hr_zones`, ripetuta
    # con un tipo.
    fitness = fitness_on(health, day)
    zones = data["hr_zones"]
    if zones and zones.get("threshold_hr") is not None:
        fitness["threshold_hr"] = {"value": zones["threshold_hr"], "as_of": zones["as_of"]}
    else:
        fitness["threshold_hr"] = None
    # La soglia del lattato e' solo l'ultima (todo 38): vale dal giorno in cui
    # Garmin l'ha rilevata in poi, prima no.
    lactate = load_lactate_threshold(data_dir)
    fitness["lactate_threshold"] = lactate if lactate and lactate["as_of"] <= day.isoformat() else None
    payload = {
        **data,
        "sleep_minutes": round(hours * 60) if hours is not None else None,
        "fitness": fitness,
    }
    # La faccia di ogni card (todo 92): si calcola qui, sopra il payload
    # finito, perche' legge misure che stanno in tre blocchi diversi —
    # `morning`, `load` e `fitness` — e perche' **la pagina e gli agenti
    # devono vedere lo stesso voto**: questo dizionario e' quello che
    # l'orchestratore scrive nel file dei fatti.
    payload["scores"] = daily_scores(payload)
    return payload
