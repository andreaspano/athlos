"""Il corpo di un giorno, dai file della bilancia (todo 97).

Legge `health/body_composition/<giorno>.json`, che scrive `renpho/sync.py`, e
decide **quale pesata** risponde per il giorno che si guarda. Niente conti sul
corpo: i numeri sono quelli misurati, qui si scelgono e si vestono di etichetta
e unita', che e' la regola del todo 52 — la pagina non calcola e non sa come si
chiamano i campi di Renpho.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from training.renpho.sync import FOLDER

# Le dieci misure della card, nell'ordine in cui si leggono: prima quanto
# pesi, poi di cosa sei fatto, poi cosa consumi. L'unita' e i decimali
# viaggiano col numero, come fa la settimana (`WeekMeasure`), cosi' la pagina
# disegna quello che arriva.
#
# L'ultima colonna e' **da quale riferimento della bilancia viene la fascia**,
# `None` dove non ce n'e' uno da disegnare. Tre motivi per cui manca:
#
# - la bilancia non lo manda: massa magra e grasso viscerale;
# - lo manda in **massa** dove la misura e' in percentuale (acqua, proteine):
#   una fascia in chili sotto un numero in percento non si legge, e ricavare
#   la percentuale dividendo per il peso vorrebbe dire inventare un dato;
# - il **BMI**, che lo manda ma vale 25.0-30.0 con ideale 22.0: quello non e'
#   un intervallo sano, e' la fascia del sovrappeso, cioe' dove il valore di
#   adesso casca. Disegnarla direbbe "il tuo BMI dovrebbe stare fra 25 e 30",
#   che e' falso.
MEASURES: tuple[tuple[str, str, str, int, str | None], ...] = (
    ("weight_kg", "Weight", "kg", 1, "weight_kg"),
    ("bmi", "BMI", "", 1, None),
    ("body_fat_pct", "Body fat", "%", 1, "body_fat_pct"),
    ("water_pct", "Water", "%", 1, None),
    ("skeletal_muscle_kg", "Skeletal muscle", "kg", 1, "skeletal_muscle_kg"),
    ("fat_free_kg", "Fat-free mass", "kg", 1, None),
    ("bone_kg", "Bone", "kg", 1, "bone_kg"),
    ("protein_pct", "Protein", "%", 1, None),
    ("visceral_fat", "Visceral fat", "", 0, None),
    ("bmr_kcal", "Basal metabolism", "kcal", 0, "bmr_kcal"),
)


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


def _band(reference: dict[str, Any] | None, key: str | None, digits: int) -> dict[str, Any] | None:
    """La fascia di una misura: l'intervallo di riferimento della bilancia.

    **Non e' la fascia delle altre card, e va detto.** Altrove una fascia dice
    *dove quella misura sta di solito* — media e scarto tipo dello storico — e
    uscirne vuol dire "oggi e' diverso dal solito". Qui dice *dove quella
    misura dovrebbe stare* per la tua altezza, eta' e sesso, e uscirne vuol
    dire un'altra cosa. La card lo scrive in una riga, perche' lo stesso
    disegno con due significati e' il modo di leggere male un numero.

    La scelta viene dai dati: di pesate ce ne sono tre, e una media con il suo
    scarto su tre valori non e' una fascia, e' rumore disegnato — mentre il
    riferimento la bilancia lo manda da subito ed e' una proprieta' della
    persona, identico in tutte le pesate.

    `outer` coincide con `low`/`high` perche' un intervallo di riferimento ha
    due estremi e non quattro: la fascia larga di `RangeBar` resta sotto
    quella piena e non si vede. Il valore fuori dall'intervallo lo disegna
    comunque, che `RangeBar` allarga la scala fin dove serve."""
    if not reference or not key:
        return None
    found = reference.get(key)
    if not found or found.get("low") is None or found.get("high") is None:
        return None
    low, high = round(float(found["low"]), digits), round(float(found["high"]), digits)
    return {"low": low, "high": high, "outer_low": low, "outer_high": high}


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
    reference = measure.get("reference")
    measures = [
        {
            "key": key,
            "label": label,
            "unit": unit,
            "digits": digits,
            "value": measure.get(key),
            "band": _band(reference, band_from, digits),
        }
        for key, label, unit, digits, band_from in MEASURES
    ]
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
    }
