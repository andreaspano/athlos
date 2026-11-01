"""Letture e scritture di JSON che non lasciano file a meta'.

Stesso mestiere di `save_json_map` in `interface/fit.py`, da questo lato del
confine: `interface` importa da `garmin`, non il contrario, quindi la funzione
non si puo' condividere senza invertire la dipendenza.
"""

import json
import os
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any, sort_keys: bool = False) -> None:
    """Scrive `data` in `path` passando da un temporaneo nella stessa cartella
    e poi da `os.replace`, che e' atomico: chi legge vede la versione vecchia
    o quella nuova, mai una a meta'.

    Serve perche' il Ctrl+C e' una via d'uscita dichiarata (vedi il Makefile):
    scrivendo dritto sul file giusto, un'interruzione in mezzo alla `json.dump`
    lasciava un file troncato che poi nessuno riusciva piu' a leggere."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str, sort_keys=sort_keys)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path, default: Any = None, label: str = "") -> Any:
    """Legge il JSON di `path`. Se il file non c'e' restituisce `default`; se
    c'e' ma non si legge lo dice e restituisce `default` ugualmente, perche' un
    file rovinato non deve fermare un giro che dura mezz'ora."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ATTENZIONE: {label or path} non si legge ({exc}): lo salto.")
        return default
