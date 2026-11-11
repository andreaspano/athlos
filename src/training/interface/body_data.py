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

from training.interface.daily_data import _band as _history_band
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

# La finestra della fascia: le stesse dodici settimane delle card della
# settimana, cosi' "dove sta di solito" vuol dire lo stesso in tutta
# l'applicazione.
BAND_WEEKS = 12

# Quante pesate servono prima di disegnarla. E' il **pavimento** e non un
# consiglio: con tre valori lo scarto tipo e' sottile, e la fascia va letta
# come quello che e' — l'intervallo di tre mattine, non una norma. Meno dei
# quattordici giorni della Day (`MIN_BAND_DAYS`) e delle sei settimane della
# Week (`MIN_BAND_WEEKS`) per un motivo di cadenza: su una bilancia ci si sale
# quando si vuole, e pretenderne sei o quattordici vorrebbe dire niente fascia
# per mesi.
MIN_BAND_WEIGHINS = 3

# La pesata **fa parte** della sua finestra, a differenza della Day, dove la
# fascia guarda i 28 giorni *prima* del giorno che giudica. Qui la fascia non
# giudica la pesata, descrive un periodo — l'intervallo in cui il peso si e'
# mosso nelle ultime dodici settimane — e un periodo contiene anche l'ultima
# mattina. In pratica vuol dire anche vedere la fascia una pesata prima, che
# all'inizio di uno storico non e' poco.



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


def _window(data_dir: Path, until: date, weeks: int = BAND_WEEKS) -> list[dict[str, Any]]:
    """Le pesate delle dodici settimane che finiscono con `until`, **compresa
    quella di quel giorno**, una per giorno: sono i valori della fascia.

    Una per giorno e non tutte: l'8 novembre 2026 ce ne sono due a tre minuti
    di distanza, e due numeri cosi' vicini non sono due misure di come stai —
    contati entrambi, stringerebbero la fascia per una ragione che non e' il
    corpo."""
    start = until - timedelta(weeks=weeks)
    found = []
    for day in _days(data_dir):
        if start <= day <= until:
            measure = _of_day(data_dir, day)
            if measure:
                found.append(measure)
    return found


def _band(window: list[dict[str, Any]], key: str, digits: int) -> dict[str, Any] | None:
    """Dove quella misura sta di solito: la fascia dello storico, **la stessa
    delle altre card** — media delle pesate della finestra piu' e meno uno
    scarto tipo, e piu' e meno due.

    Passa da `daily_data._band`, che e' dove quel disegno vive da sempre
    (`weekly_data` fa lo stesso per le fasce della settimana): una funzione
    sola che sa la forma, e chi la chiama le porta i valori.

    Le fasce di riferimento della bilancia — dove quel numero *dovrebbe* stare
    per altezza, eta' e sesso — restano nei file e non si disegnano. Erano
    state provate qui, e la ragione per cui non sono rimaste e' che danno allo
    stesso disegno un secondo significato: sulla barra di ogni altra card
    fuori dalla fascia vuol dire "diverso dal solito", e qui avrebbe voluto
    dire "fuori da dove dovresti stare". Una card che si legge come le altre
    vale piu' di una fascia che arriva prima.

    `None` sotto `MIN_BAND_WEIGHINS` pesate, e allora la card dice quante ne
    ha: una traccia vuota senza spiegazione si legge come un guasto."""
    values = pd.Series([m.get(key) for m in window], dtype="float64")
    return _history_band(values, digits=digits, min_values=MIN_BAND_WEIGHINS)


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
    window = _window(data_dir, measured_day)
    # Il bersaglio della bilancia, dove ce n'e' uno: `ideal` del riferimento,
    # preso **per chiave**, cosi' nessuna tabella in piu' da tenere
    # d'accordo. Ce l'hanno peso (79.4 kg), BMI (22.0), grasso (15%), muscolo
    # scheletrico (38.1 kg) e metabolismo basale (1828 kcal); acqua, proteine,
    # massa magra, grasso viscerale e osso no, e allora la linea verde non si
    # disegna. Il BMI qui ha un bersaglio sensato pur non avendo una fascia
    # usabile: 22.0 e' un BMI a cui mirare, 25-30 non e' un intervallo in cui
    # stare.
    reference = measure.get("reference") or {}
    measures = [
        {
            "key": key,
            "label": label,
            "unit": unit,
            "digits": digits,
            "value": measure.get(key),
            "band": _band(window, key, digits),
            "target": (reference.get(key) or {}).get("ideal"),
        }
        for key, label, unit, digits in MEASURES
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
        # Quante pesate ha la finestra: serve alla riga che spiega perche' le
        # barre sono ancora vuote.
        "weighings": len(window),
    }
