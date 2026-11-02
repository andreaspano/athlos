"""Il tipo delle corse (todo 36): gara, ripetute, lunga, tempo, facile.

Il tipo si stima dall'allenamento pianificato nel FIT (messaggi `workout` e
`workout_step`, salvati in `activities.db` da `fit._workout`) e dalla durata,
e Andrea lo puo' correggere dalla Day in React. La stima si calcola in
lettura; le correzioni stanno in `activity_run_type.json` nella cartella
dati, accanto a `activity_terrain.json`, perche' `db.rebuild()` cancella il
database e le perderebbe."""

import threading
from pathlib import Path

from training.interface.fit import _load_json_map, save_json_map

RUN_TYPES = ("race", "intervals", "long", "tempo", "easy")

# La soglia della corsa lunga, in minuti di durata totale. Guardate le corse
# in `activities.db` al 2026-10-16: nell'ultimo anno (22 corse) stanno tra 32
# e 90 minuti e tra 111 e 139, niente in mezzo; su tutto lo storico (353
# corse) attorno a 100 ce ne sono solo due, a 99 e a 101. A 100 il taglio
# cade nel buco e non dipende da un minuto in piu' o in meno.
LONG_MIN = 100

# Il passo `active` piu' corto che fa di un allenamento con un solo passo
# attivo una corsa a ritmo (tempo): sotto i 10 minuti e' un allungo, non un
# tempo.
TEMPO_STEP_MIN_S = 10 * 60

_RUN_TYPE_FILENAME = "activity_run_type.json"
_write_lock = threading.Lock()


def has_run_type(sport: str | None) -> bool:
    """Solo le corse hanno un tipo. Il tapis roulant no: e' uno sport a se'
    (todo 45), e di una seduta sul nastro non si dice se era facile o a
    ripetute guardando il passo, perche' il passo e' una stima del polso."""
    return sport == "running"


def _missing(value) -> bool:
    # I NaN di pandas arrivano qui come float: `x != x` e' vero solo per NaN.
    return value is None or value != value


def guess_run_type(
    sport: str | None,
    total_time_min: float | None,
    workout_name: str | None,
    workout_active_steps: int | None,
    workout_active_max_s: float | None,
) -> str | None:
    """Il tipo stimato, o `None` per gli sport che non sono corsa.

    Le regole, in ordine: allenamento con almeno 2 passi `active` ->
    ripetute; con un solo passo `active` di almeno 10 minuti -> tempo; lunga
    almeno `LONG_MIN` minuti -> lunga; altrimenti facile. Gara non si stima
    mai, e nemmeno tempo senza allenamento: dai battiti non si distingue una
    corsa libera forte da una gara.

    **La regola della lunga guarda la durata e basta.** Stava attaccata a un
    `elif` del ramo dell'allenamento, quindi una corsa che l'orologio ha
    fatto girare come allenamento non poteva essere lunga per quanto durasse:
    il lungo di 115 minuti del 31 ottobre, con il workout `w01_long`, usciva
    `easy`. Una corsa con un allenamento e' se mai **piu'** probabile che sia
    un lungo pianificato, non meno. Le ripetute e il tempo restano prima: una
    seduta a ripetute di due ore e' una seduta a ripetute."""
    if not has_run_type(sport):
        return None
    has_workout = not _missing(workout_name) or not _missing(workout_active_steps)
    if has_workout:
        steps = 0 if _missing(workout_active_steps) else int(workout_active_steps)
        if steps >= 2:
            return "intervals"
        longest = 0 if _missing(workout_active_max_s) else float(workout_active_max_s)
        if steps == 1 and longest >= TEMPO_STEP_MIN_S:
            return "tempo"
    if not _missing(total_time_min) and total_time_min >= LONG_MIN:
        return "long"
    return "easy"


def _run_type_path(data_dir: Path) -> Path:
    return Path(data_dir) / "json" / _RUN_TYPE_FILENAME


def load_run_type_overrides(data_dir: Path) -> dict[str, str]:
    """Le correzioni di Andrea, `{"<activity_id>": "<run_type>"}`."""
    return _load_json_map(_run_type_path(data_dir))


def save_run_type_override(data_dir: Path, activity_id: int, run_type: str | None) -> None:
    """Salva la correzione di una corsa; con `None` la toglie (si torna alla
    stima). Scrive un file temporaneo e lo sostituisce, sotto un lock: due
    richieste insieme non lasciano il JSON a meta'."""
    if run_type is not None and run_type not in RUN_TYPES:
        raise ValueError(f"Unknown run type: {run_type}")
    path = _run_type_path(data_dir)
    with _write_lock:
        overrides = load_run_type_overrides(data_dir)
        if run_type is None:
            overrides.pop(str(activity_id), None)
        else:
            overrides[str(activity_id)] = run_type
        save_json_map(path, overrides)
