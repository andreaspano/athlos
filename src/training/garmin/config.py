"""Configurazione, letta da `<radice dei dati>/user/config.yaml`.

**Due file, in quest'ordine** (todo 65). Nel repo c'e' `data.yaml`, che dice
una cosa sola: dove sta la cartella dei dati. Nella cartella dei dati c'e'
`user/config.yaml`, con tutto il resto. Il puntatore e' nel repo perche' non
puo' stare in quello che deve trovare, ed e' l'unica cosa che il repo sa dei
dati.

Sotto la radice stanno sette cartelle — `fit`, `health`, `json`, `db`,
`user`, `summary`, `plan` — e questo modulo le nomina tutte, una volta sola:
chi gli serve una di quelle importa la costante invece di ricostruirsela.

E' l'unica fonte: non ci sono default nel codice e nessuna variabile
d'ambiente la scavalca. Se un file manca, o manca una chiave, il programma si
ferma all'import con un `ConfigError` che elenca tutto quello che non va in
un messaggio solo, cosi' non si scoprono i problemi uno alla volta. Lo stesso
per le chiavi sconosciute (un refuso come `data_dirr` va detto per nome, non
come "manca data_dir") e per i valori del tipo sbagliato.

Il resto del codice importa i valori da qui, con i nomi di sempre
(`DATA_DIR`, `REQUEST_DELAY`, ...): cosa significa ogni chiave lo dicono i
commenti nei file YAML, che e' dove si cambiano.
"""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

# La radice del repo e non la cartella corrente: il puntatore si deve trovare
# da qualunque cartella si lanci il programma.
REPO_ROOT = Path(__file__).resolve().parents[3]
POINTER_PATH = REPO_ROOT / "data.yaml"


class ConfigError(RuntimeError):
    """La configurazione manca, e' incompleta o ha valori sbagliati."""


@dataclass(frozen=True)
class Config:
    token_store: str
    local_tz: ZoneInfo
    history_start: date
    request_delay: float
    health_refresh_days: int
    fitness_status_window_days: int


def _is_number(value: Any) -> bool:
    # I `bool` sono `int` in Python, ma `true` non e' una pausa ne' un numero
    # di giorni: e' una chiave scritta male, e va detto.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _path(value: Any) -> tuple[Any, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, "deve essere un path (testo non vuoto)"
    return Path(value).expanduser(), None


def _token_store(value: Any) -> tuple[Any, str | None]:
    path, problem = _path(value)
    return (str(path) if path is not None else None), problem


def _local_tz(value: Any) -> tuple[Any, str | None]:
    if not isinstance(value, str):
        return None, "deve essere un fuso orario, per esempio Europe/Rome"
    try:
        return ZoneInfo(value), None
    except (ZoneInfoNotFoundError, ValueError):
        return None, f"fuso orario sconosciuto: {value!r}"


def _history_start(value: Any) -> tuple[Any, str | None]:
    # YAML legge gia' 2025-01-01 come `date`; una stringa vuol dire che la
    # data e' scritta male (o tra virgolette).
    #
    # `datetime` e' sottoclasse di `date`, quindi `2025-01-01 00:00:00` passava
    # l'isinstance e poi rompeva il confronto qui sotto con un `TypeError` a
    # import di questo modulo: un traceback su ogni comando, invece dell'unico
    # ConfigError che questo file promette.
    if not isinstance(value, date) or isinstance(value, datetime):
        return None, "deve essere una data nella forma YYYY-MM-DD, senza l'ora"
    if value > date.today():
        return None, f"e' nel futuro: {value}"
    return value, None


def _request_delay(value: Any) -> tuple[Any, str | None]:
    if not _is_number(value) or value < 0:
        return None, "deve essere un numero di secondi, zero o piu'"
    return float(value), None


def _days(value: Any) -> tuple[Any, str | None]:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None, "deve essere un numero intero di giorni, almeno 1"
    return value, None


# Una funzione per chiave: torna il valore convertito, o il problema.
_FIELDS = {
    "token_store": _token_store,
    "local_tz": _local_tz,
    "history_start": _history_start,
    "request_delay": _request_delay,
    "health_refresh_days": _days,
    "fitness_status_window_days": _days,
}


def load_data_root(path: Path) -> Path:
    """La cartella dei dati, letta dal puntatore `data.yaml`.

    Tre modi di sbagliare e tre messaggi distinti — file assente, chiave
    assente o storta, cartella che non c'e' — perche' sono tre rimedi
    diversi.

    **La cartella non si crea.** Ovunque nel codice un `mkdir(parents=True)`
    su un percorso storto costruisce un albero vuoto invece di fermarsi, e
    quello e' il modo di accorgersi di un refuso tre giorni dopo, guardando
    dei report che non arrivano. Qui si pretende che esista: e' la radice di
    tutto, e crearla a vuoto non aiuta nessuno.

    Il percorso si espande (`~`) **e si risolve**: `Path(data_dir)` e' anche
    la chiave della cache in `api/cache.py`, e un percorso relativo darebbe
    una cache diversa per ogni cartella da cui si lancia un comando."""
    if not path.exists():
        raise ConfigError(
            f"Manca il puntatore dei dati: {path}\n"
            '  Una riga sola, per esempio:  data_root: ~/adrive/data/training'
        )
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} non e' YAML valido:\n{exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} deve contenere delle chiavi (chiave: valore)")
    value = raw.get("data_root")
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path}: data_root deve essere un path (testo non vuoto)")
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ConfigError(f"{path}: la cartella dei dati non esiste: {root}")
    return root


def load_config(path: Path) -> Config:
    """La configurazione letta da `path`, o `ConfigError` con tutti i
    problemi trovati."""
    if not path.exists():
        raise ConfigError(f"Manca il file di configurazione: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} non e' YAML valido:\n{exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} deve contenere delle chiavi (chiave: valore)")

    problems = []
    missing = [key for key in _FIELDS if key not in raw]
    if missing:
        problems.append("chiavi mancanti: " + ", ".join(missing))
    unknown = [str(key) for key in raw if key not in _FIELDS]
    if unknown:
        problems.append("chiavi sconosciute: " + ", ".join(unknown))

    values = {}
    for key, convert in _FIELDS.items():
        if key not in raw:
            continue
        value, problem = convert(raw[key])
        if problem:
            problems.append(f"{key}: {problem}")
        values[key] = value

    if problems:
        raise ConfigError(
            f"Configurazione non valida in {path}:\n" + "\n".join(f"  - {p}" for p in problems)
        )
    return Config(**values)


DATA_ROOT = load_data_root(POINTER_PATH)

# Le cartelle della radice (todo 65) che si nominano da qui. Sono sette sul
# disco — `fit/`, `health/`, `json/`, `db/` e queste tre — ma le prime
# quattro se le compone chi le usa a partire da `DATA_ROOT`, e una costante
# che nessuno legge e' una seconda verita' da tenere d'accordo con la prima.
USER_DIR = DATA_ROOT / "user"
SUMMARY_DIR = DATA_ROOT / "summary"
PLAN_DIR = DATA_ROOT / "plan"

CONFIG_PATH = USER_DIR / "config.yaml"
_config = load_config(CONFIG_PATH)

# La radice, col nome di sempre: e' il valore che una dozzina di funzioni
# prendono come argomento di default e che `api/cache.py` usa come chiave.
# Le sottocartelle se le costruisce chi legge, dove serve.
DATA_DIR = DATA_ROOT
TOKEN_STORE = _config.token_store
LOCAL_TZ = _config.local_tz
HISTORY_START = _config.history_start
REQUEST_DELAY = _config.request_delay
HEALTH_REFRESH_DAYS = _config.health_refresh_days
FITNESS_STATUS_WINDOW_DAYS = _config.fitness_status_window_days
