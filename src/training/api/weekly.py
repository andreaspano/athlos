"""I fatti di una settimana come li vede la pagina (todo 52 e 53).

Sta qui e non in `weekly_data.py` per la stessa ragione di `daily.py`: la
cache e' roba dell'API, e `build_weekly_data` deve restare chiamabile da
terminale senza server.

Lo usano due strade, e devono vedere le stesse cose: l'endpoint
`/api/weekly/{monday}` e l'orchestratore del report settimanale, che scrive
questo stesso dizionario nel file che gli agenti leggono."""

from datetime import date
from pathlib import Path
from typing import Any

from training.api.cache import load_activities, load_health
from training.api.score import weekly_scores
from training.interface.weekly_data import build_weekly_data


def weekly_payload(monday: date, data_dir: Path) -> dict[str, Any]:
    """Tutto quello che si sa della settimana, nella forma che la pagina
    riceve.

    Salute e attivita' arrivano dalla cache: senza, ogni richiesta rifa' la
    scansione dei file di salute (circa un secondo, dieci volte il conto
    della settimana)."""
    payload = build_weekly_data(
        monday,
        data_dir,
        activities=load_activities(data_dir),
        health=load_health(data_dir),
    )
    # La faccia di ogni card (todo 92), come nel giorno: le misure della
    # settimana arrivano gia' divise per card, il carico ha la sua fascia
    # sulle dodici settimane prima.
    payload["scores"] = weekly_scores(payload)
    return payload
