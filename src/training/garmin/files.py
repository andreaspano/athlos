"""Letture e scritture che non lasciano file a meta'.

`garmin` non importa da nessuno degli altri due pacchetti, mentre `interface`
e `api` importano da qui: questo e' il posto dove una scrittura atomica sta
senza invertire nessuna dipendenza. (Il docstring di prima diceva il
contrario — che non si poteva condividere — e non era vero: `interface/fit.py`
importa `garmin.config` da sempre. Una giustificazione sbagliata e' il modo in
cui un duplicato sopravvive.)

Chi fa la stessa cosa altrove: `interface/fit.py:save_json_map` (con un
temporaneo unico e il `mkdir`) e `api/plans.py:_write` per il testo, che ora
passa da `write_text` qui sotto.
"""

import json
import os
from pathlib import Path
from typing import Any


def write_text(path: Path, text: str) -> None:
    """Scrive `text` in `path` passando da un temporaneo nella stessa cartella
    e poi da `os.replace`, che e' atomico: chi legge vede la versione vecchia
    o quella nuova, mai una a meta'.

    Serve perche' il Ctrl+C e' una via d'uscita dichiarata (vedi il Makefile):
    scrivendo dritto sul file giusto, un'interruzione in mezzo alla scrittura
    lasciava un file troncato che poi nessuno riusciva piu' a leggere.

    **Qui vive la politica**: il nome del temporaneo e la `os.replace`. Chi
    scrive JSON passa da `write_json`, che e' questa piu' la serializzazione."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def json_text(data: Any, sort_keys: bool = False) -> str:
    """`data` come JSON, nella forma che scrive questo progetto.

    Separata da `write_json` perche' dal todo 94 lo stesso JSON va anche in
    un messaggio al modello invece che su un file, e una seconda `json.dumps`
    con gli stessi argomenti copiati a mano e' una seconda forma da tenere
    d'accordo con questa."""
    return json.dumps(data, ensure_ascii=False, indent=2, default=str, sort_keys=sort_keys)


def write_json(path: Path, data: Any, sort_keys: bool = False) -> None:
    """`data` come JSON in `path`, con la scrittura atomica di
    `write_text`."""
    write_text(path, json_text(data, sort_keys) + "\n")


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
