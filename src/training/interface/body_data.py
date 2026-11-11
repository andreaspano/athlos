"""Il corpo di un giorno, dai file della bilancia (todo 97).

Legge `health/body_composition/<giorno>.json`, che scrive `renpho/sync.py`, e
decide **quale pesata** risponde per il giorno che si guarda. Niente conti sul
corpo: i numeri sono quelli misurati, qui si scelgono e si vestono di etichetta
e unita', che e' la regola del todo 52 — la pagina non calcola e non sa come si
chiamano i campi di Renpho.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from training.interface.daily_data import _band
from training.renpho.sync import FOLDER

# Le dieci misure della card, nell'ordine in cui si leggono: prima quanto
# pesi, poi di cosa sei fatto, poi cosa consumi. L'unita' e i decimali
# viaggiano col numero, come fa la settimana (`WeekMeasure`), cosi' la pagina
# disegna quello che arriva.
MEASURES: tuple[tuple[str, str, str, int], ...] = (
    ("weight_kg", "Weight", "kg", 1),
    ("bmi", "BMI", "", 1),
    ("body_fat_pct", "Body fat", "%", 1),
    ("water_pct", "Water", "%", 1),
    ("skeletal_muscle_kg", "Skeletal muscle", "kg", 1),
    ("fat_free_kg", "Fat-free mass", "kg", 1),
    ("bone_kg", "Bone", "kg", 1),
    ("protein_pct", "Protein", "%", 1),
    ("visceral_fat", "Visceral fat", "", 0),
    ("bmr_kcal", "Basal metabolism", "kcal", 0),
)

# Quante settimane guarda indietro la fascia: le stesse dodici delle card
# della settimana, cosi' "dove sta di solito" vuol dire lo stesso in tutta
# l'applicazione.
BAND_WEEKS = 12

# Quante pesate servono prima di disegnare una fascia. Meno dei quattordici
# giorni della Day (`MIN_BAND_DAYS`) perche' una pesata non e' un giorno: su
# una bilancia ci si sale quando si vuole, e pretendere quattordici misure
# vorrebbe dire niente fascia per mesi. Sotto otto lo scarto tipo e' rumore.
MIN_BAND_WEIGHINS = 8


def _read(path: Path) -> list[dict[str, Any]]:
    """Le pesate di un file, o niente se il file non si legge.

    Un file storto non e' un errore da far salire fino alla pagina: la card
    dira' che non ci sono pesate, che e' la stessa risposta di una cartella
    vuota."""
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [m for m in found if isinstance(m, dict)]


def _days(data_dir: Path) -> list[date]:
    """I giorni che hanno un file, dal piu' vecchio. Il nome del file **e'** il
    giorno, come in tutte le cartelle di `health/`."""
    folder = Path(data_dir) / "health" / FOLDER
    if not folder.is_dir():
        return []
    found = []
    for path in folder.glob("*.json"):
        try:
            found.append(date.fromisoformat(path.stem))
        except ValueError:
            continue
    return sorted(found)


def _of_day(data_dir: Path, day: date) -> dict[str, Any] | None:
    """La pesata che rappresenta un giorno, o `None` se quel giorno non ne ha.

    **L'ultima completa**, cioe' con l'impedenza; se nessuna lo e', l'ultima.
    L'8 novembre 2026 ci sono due pesate a tre minuti di distanza, la prima
    senza impedenza: la seconda e' quella che dice qualcosa.

    Si sceglie una pesata sola e non il meglio di tante: il peso di stasera e
    il grasso di stamattina sono due momenti, e cuciti insieme darebbero un
    corpo che non e' mai esistito."""
    found = _read(Path(data_dir) / "health" / FOLDER / f"{day.isoformat()}.json")
    if not found:
        return None
    found = sorted(found, key=lambda m: m.get("timestamp") or 0)
    complete = [m for m in found if m.get("impedance")]
    return (complete or found)[-1]


def _history(data_dir: Path, before: date, weeks: int = BAND_WEEKS) -> list[dict[str, Any]]:
    """Le pesate delle settimane prima di `before`, una per giorno: sono i
    valori su cui si misura la fascia."""
    start = before - timedelta(weeks=weeks)
    found = []
    for day in _days(data_dir):
        if start <= day < before:
            measure = _of_day(data_dir, day)
            if measure:
                found.append(measure)
    return found


def body_on(data_dir: Path, day: date) -> dict[str, Any] | None:
    """Il corpo del giorno `day`: le dieci misure, quando sono state prese e
    quanti giorni fa.

    **Se quel giorno non ha una pesata si prende la piu' recente fino a quel
    giorno** — mai una successiva: aprendo il 15 ottobre non si deve vedere la
    pesata di stamattina, o un giorno passato racconterebbe il futuro. E'
    `days_ago` a dirlo, zero quando la pesata e' di quel giorno.

    Nessuna scadenza oltre la quale smette di rispondere: un peso di sei
    giorni fa e' ancora il tuo peso, basta sapere di quando e'.

    `None` quando di pesate non ce n'e' nessuna fino a quel giorno — una
    bilancia comprata la settimana scorsa, o nessuna bilancia."""
    giorni = [d for d in _days(data_dir) if d <= day]
    measure = None
    for candidate in reversed(giorni):
        measure = _of_day(data_dir, candidate)
        if measure:
            break
    if measure is None:
        return None
    measured_day = date.fromisoformat(measure["measured_at"][:10])
    storia = _history(data_dir, measured_day)
    measures = []
    for key, label, unit, digits in MEASURES:
        values = pd.Series([m.get(key) for m in storia], dtype="float64")
        measures.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "digits": digits,
                "value": measure.get(key),
                "band": _band(values, digits=digits, min_values=MIN_BAND_WEIGHINS),
            }
        )
    return {
        "day": day,
        "measured_at": measure["measured_at"],
        "measured_day": measured_day,
        "days_ago": (day - measured_day).days,
        # Falso quando gli elettrodi non hanno letto: c'e' il peso, il resto e'
        # `None`, e la card lo dice invece di disegnare un corpo di zeri.
        "impedance": bool(measure.get("impedance")),
        "measures": measures,
        "body_age": measure.get("body_age"),
        "age": measure.get("age"),
        "weighings": len(storia) + 1,
    }
