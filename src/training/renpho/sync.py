"""Le pesate della bilancia: scaricate, scritte in `health/body_composition/`
e rimandate a Garmin (todo 97).

Tre passi in fila, e ognuno si regge se gli altri due non vanno: lo scarico
non tocca disco, la scrittura non parla con nessuno, e l'invio a Garmin e'
l'ultimo — se Garmin e' giu', i file sono gia' a posto.

Qui dentro non si calcola niente sul corpo: i numeri sono quelli che la
bilancia ha misurato, e l'unico lavoro e' dargli i nostri nomi e decidere
quali **non** ci sono.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from training.garmin.config import DATA_DIR, RENPHO_PWD, RENPHO_USR
from training.garmin.files import write_json

# La cartella sotto `health/`, una come quelle di Garmin: un file per giorno.
FOLDER = "body_composition"

# I campi che si tengono, col nome nostro davanti. Dei 122 che Renpho manda
# questi sono quelli che misurano il corpo: il resto sono zeri, fasce di
# riferimento della bilancia e impedenze degli elettrodi, e un file di dati e'
# un documento che si legge, non un dump.
#
# I tre muscoli vanno letti insieme, che i nomi di Renpho ingannano:
# `muscle` e' la **percentuale di muscolo scheletrico**, `smmMass` la sua
# massa, `sinew` la massa muscolare intera (che e' la magra meno l'osso —
# 73.67 - 4.9 = 68.77 contro 68.74 dichiarati).
MEASURES: tuple[tuple[str, str], ...] = (
    ("weight_kg", "weight"),
    ("bmi", "bmi"),
    ("body_fat_pct", "bodyfat"),
    ("water_pct", "water"),
    ("skeletal_muscle_pct", "muscle"),
    ("skeletal_muscle_kg", "smmMass"),
    ("muscle_mass_kg", "sinew"),
    ("fat_free_kg", "fatFreeWeight"),
    ("bone_kg", "bone"),
    ("protein_pct", "protein"),
    ("subcutaneous_fat_pct", "subfat"),
    ("visceral_fat", "visfat"),
    ("bmr_kcal", "bmr"),
    ("body_age", "bodyage"),
    ("body_score", "bodyScore"),
    ("whr", "whr"),
    ("smi", "smi"),
)

# Le due misure che **non** dipendono dall'impedenza: il peso lo pesa la
# cella di carico, e il BMI e' peso e altezza. Una pesata coi calzini ha
# queste due e nient'altro.
WITHOUT_IMPEDANCE = ("weight_kg", "bmi")

# I cinque segmenti, con il prefisso che Renpho gli da'. Di ognuno si tiene la
# massa grassa e la massa muscolare, in kg: le altre due colonne (`BodyFatPct`
# e `Muscle`) sono percentuali **dello standard** per quel segmento — 257% di
# grasso a un braccio non e' una composizione — e senza lo standard accanto
# non si leggono.
#
# La card non li mostra (todo 97): meritano un disegno loro. Si scaricano
# comunque, che il file e' il registro e un dato buttato oggi non torna.
SEGMENTS: tuple[tuple[str, str], ...] = (
    ("left_arm", "la"),
    ("right_arm", "ra"),
    ("left_leg", "ll"),
    ("right_leg", "rl"),
    ("trunk", "t"),
)


# Le **fasce di riferimento** della bilancia: dove quella misura dovrebbe
# stare per la tua altezza, eta' e sesso. `(nostro, min, max, ideale)`.
#
# Sono una proprieta' della persona e non della pesata — verificato: le
# ventisei soglie sono identiche nelle due pesate dell'8 e del 10 novembre,
# mentre peso e grasso erano cambiati — e per questo si possono disegnare
# come fascia dietro il numero (todo 97: e' quello che la card fa).
#
# Quattro arrivano in **massa** anche dove la misura corrispondente e' in
# percentuale (acqua, proteine): si tengono col nome della massa, che e' quello
# che sono, e la card non le usa — non si disegna una fascia in kg sotto un
# numero in percento.
REFERENCES: tuple[tuple[str, str, str, str | None], ...] = (
    ("weight_kg", "weightMin", "weightMax", "weightStd"),
    ("bmi", "bmiMin", "bmiMax", "bmiStd"),
    ("body_fat_pct", "bfpMin", "bfpMax", "bfpStd"),
    ("fat_mass_kg", "bfmMin", "bfmMax", "bfmStd"),
    ("water_mass_kg", "waterMassMin", "waterMassMax", None),
    ("muscle_mass_kg", "muscleMassMin", "muscleMassMax", None),
    ("skeletal_muscle_kg", "smmMin", "smmMax", "smmStd"),
    ("bone_kg", "boneMin", "boneMax", None),
    ("protein_mass_kg", "proteinMassMin", "proteinMassMax", None),
    ("bmr_kcal", "bmrMin", "bmrMax", "bmrStd"),
)


class RenphoNotConfigured(RuntimeError):
    """Le credenziali non ci sono: non e' un guasto, e' una bilancia che non
    si usa."""


def _number(value: Any) -> float | None:
    """Il numero di un campo di Renpho, o `None`.

    **Zero vuol dire "non misurato"**, e non zero: nessuno ha lo 0% di acqua.
    La pesata senza impedenza manda zeri su tutta la composizione, e tenerli
    farebbe disegnare un corpo che non esiste — e' la stessa regola delle
    settimane senza corse del blocco."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return None if value == 0 else float(value)


def measurement(row: dict[str, Any]) -> dict[str, Any]:
    """Una pesata coi nomi nostri, i campi non misurati a `None`.

    `impedance` dice se gli elettrodi hanno letto: e' `resistance` di Renpho,
    e quando e' falso resta in piedi solo quello che la cella di carico sa da
    sola."""
    impedance = bool(row.get("resistance"))
    stamp = int(row["timeStamp"])
    out: dict[str, Any] = {
        # L'ora locale, come la vede chi e' salito sulla bilancia: `timeStamp`
        # e' un epoch vero, e il fuso lo mette la macchina. E' anche la
        # chiave con cui si riconosce una pesata, su disco e su Garmin.
        "measured_at": datetime.fromtimestamp(stamp).isoformat(timespec="seconds"),
        "timestamp": stamp,
        # L'id di Renpho: serve a non duplicare una pesata quando il file si
        # riscrive. Stringa e non intero, che e' un numero a 19 cifre.
        "id": str(row.get("id")) if row.get("id") is not None else None,
        "impedance": impedance,
        "age": _number(row.get("measureAge")),
        "height_cm": _number(row.get("height")),
    }
    for nostro, loro in MEASURES:
        value = _number(row.get(loro))
        out[nostro] = value if (impedance or nostro in WITHOUT_IMPEDANCE) else None
    # Le fasce non vengono dagli elettrodi: il peso ideale per la tua altezza
    # vale anche per una pesata coi calzini, quindi si tengono comunque.
    out["reference"] = {
        nostro: {
            "low": _number(row.get(low)),
            "high": _number(row.get(high)),
            "ideal": _number(row.get(ideal)) if ideal else None,
        }
        for nostro, low, high, ideal in REFERENCES
        if _number(row.get(low)) is not None and _number(row.get(high)) is not None
    } or None
    out["segments"] = (
        {
            nome: {
                "fat_mass_kg": _number(row.get(f"{prefix}BodyFatMass")),
                "muscle_mass_kg": _number(row.get(f"{prefix}MuscleMass")),
            }
            for nome, prefix in SEGMENTS
        }
        if impedance
        else None
    )
    return out


def fetch(user: str | None = None, password: str | None = None) -> list[dict[str, Any]]:
    """Le pesate dell'account, coi nomi nostri, dalla piu' vecchia.

    L'import di `renpho` sta qui dentro e non in cima al modulo: cosi' chi
    non ha la bilancia non si porta dietro la libreria a ogni comando, ed e'
    lo stesso trattamento che `garmin/__init__.py` riserva a `garminconnect`.
    """
    user = user or RENPHO_USR
    password = password or RENPHO_PWD
    if not user or not password:
        raise RenphoNotConfigured(
            "Mancano le credenziali della bilancia: renpho_usr e renpho_pwd in "
            "user/config.yaml.\n"
            "  L'account creato con Google non ha una password: si imposta dall'app, "
            "Forgot password, 6-16 caratteri."
        )
    from renpho import RenphoClient

    client = RenphoClient(user, password)
    client.login()
    rows = [measurement(row) for row in client.get_all_measurements() if row.get("timeStamp")]
    return sorted(rows, key=lambda m: m["timestamp"])


def _merge(found: list[dict[str, Any]], path: Path) -> list[dict[str, Any]]:
    """Le pesate di un giorno: quelle che arrivano **sopra** quelle che c'erano
    gia', riconosciute dall'id.

    Si fonde invece di sovrascrivere perche' l'API rende quello che ha adesso:
    il giorno in cui rendesse una finestra piu' corta — o un giorno in meno —
    una scrittura secca cancellerebbe dal disco delle pesate vere. I file sono
    il registro, e un registro non si accorcia da solo."""
    old: list[dict[str, Any]] = []
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = []
    by_id = {m.get("id") or m.get("measured_at"): m for m in old if isinstance(m, dict)}
    for m in found:
        by_id[m.get("id") or m.get("measured_at")] = m
    return sorted(by_id.values(), key=lambda m: m.get("timestamp") or 0)


def write_days(rows: list[dict[str, Any]], data_dir: Path = DATA_DIR) -> list[Path]:
    """Scrive un file per giorno e rende i file toccati.

    Un file per giorno come le metriche di Garmin, e dentro **la lista** delle
    pesate di quel giorno: l'8 novembre 2026 ce ne sono due, alle 14:39 e alle
    14:42, e tenere solo l'ultima vorrebbe dire buttare un dato vero."""
    folder = Path(data_dir) / "health" / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    days: dict[str, list[dict[str, Any]]] = {}
    for m in rows:
        days.setdefault(m["measured_at"][:10], []).append(m)
    written = []
    for day, found in sorted(days.items()):
        path = folder / f"{day}.json"
        write_json(path, _merge(found, path))
        written.append(path)
    return written


# --- Verso Garmin ---


def _garmin_minutes(api, days: list[str]) -> set[int]:
    """I minuti in cui Garmin ha gia' una pesata, nell'intervallo dei giorni
    dati.

    Il minuto e non il giorno: due pesate dello stesso giorno sono due dati, e
    l'8 novembre 2026 ce ne sono due, a tre minuti di distanza.

    **`get_weigh_ins` e non `get_body_composition`**, che e' la differenza fra
    tutte le pesate e una al giorno: il secondo rende `dateWeightList` con una
    riga per giorno, quindi dell'8 novembre vedeva solo quella delle 14:42 e
    quella delle 14:39 ripartiva a ogni giro. Garmin non ne faceva un
    doppione — riconosce il minuto e sovrascrive — ma era un file FIT caricato
    per niente, ogni mattina.

    E `timestampGMT` e non `date`: il secondo e' l'ora locale travestita da
    epoch, e confrontarlo col nostro sbaglierebbe di quanto vale il fuso."""
    found = api.get_weigh_ins(min(days), max(days))
    minutes = set()
    for day in found.get("dailyWeightSummaries") or []:
        for row in day.get("allWeightMetrics") or []:
            stamp = row.get("timestampGMT")
            if stamp:
                minutes.add(int(stamp) // 60000)
    return minutes


def push_to_garmin(api, rows: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """Manda a Garmin le pesate che non ha, e rende quante e i problemi.

    **Perche' andarci**: l'orologio conta le calorie sul peso che conosce, e
    quello di Garmin erano due pesate a mano da 100.0 kg tondi, l'ultima del 5
    ottobre, contro i 102.6 della bilancia. Un peso vecchio di un mese sbaglia
    ogni stima che ci si appoggia.

    **Perche' non mandarle due volte**: Garmin non deduplica, accetta tutto, e
    due pesate identiche allo stesso minuto diventano due punti sul suo
    grafico. Quindi prima si guarda cosa ha.

    Un errore su una pesata non ferma le altre: si raccoglie e si dice alla
    fine, come fa `export_daily_health` con i giorni."""
    if not rows:
        return 0, []
    days = sorted({m["measured_at"][:10] for m in rows})
    try:
        already = _garmin_minutes(api, days)
    except Exception as exc:
        # Senza sapere cosa Garmin ha, mandare sarebbe duplicare: meglio
        # fermarsi e dirlo. I file su disco sono gia' scritti.
        return 0, [f"non si e' potuto leggere cosa Garmin ha gia': {exc}"]
    sent, problems = 0, []
    for m in rows:
        if m["timestamp"] // 60 in already:
            continue
        try:
            api.add_body_composition(
                timestamp=m["measured_at"],
                weight=m["weight_kg"],
                percent_fat=m["body_fat_pct"],
                percent_hydration=m["water_pct"],
                bone_mass=m["bone_kg"],
                muscle_mass=m["muscle_mass_kg"],
                basal_met=m["bmr_kcal"],
                metabolic_age=m["body_age"],
                # Il grasso viscerale di Renpho e' un **livello** (11), non una
                # massa in kg: va nel campo del voto, non in quello della massa,
                # o Garmin leggerebbe undici chili di grasso viscerale.
                visceral_fat_rating=m["visceral_fat"],
                bmi=m["bmi"],
                # L'eta' corporea la rimanda come **durata**: rileggendola,
                # 60 anni tornano come 1893415560000 ms, cioe' sessanta volte
                # un anno in millesimi di secondo. Sembra una data sbagliata e
                # non lo e' — vale la pena scriverlo, che il prossimo che la
                # guarda pensa a un difetto.
            )
        except Exception as exc:
            problems.append(f"{m['measured_at']}: {exc}")
        else:
            sent += 1
    return sent, problems


def update_weight(data_dir: Path = DATA_DIR, to_garmin: bool = True) -> dict[str, Any]:
    """Scarica le pesate, le scrive e le rimanda a Garmin. Rende il riassunto.

    **Senza credenziali non e' un errore**: chi non ha la bilancia non deve
    vedere un rosso ogni mattina, e il giro del mattino la chiama per tutti.
    Chi vuole saperlo guarda `configured` nel riassunto."""
    try:
        rows = fetch()
    except RenphoNotConfigured as exc:
        print(f"Bilancia non configurata, salto: {exc}")
        return {"configured": False, "measurements": 0, "files": 0, "to_garmin": 0}

    files = write_days(rows, data_dir)
    print(f"Bilancia: {len(rows)} pesate, {len(files)} file in health/{FOLDER}/")
    sent = 0
    if to_garmin and rows:
        from training.garmin.auth import init_api

        try:
            api = init_api()
        except Exception as exc:
            print(f"  ATTENZIONE: pesate non mandate a Garmin, login fallito: {exc}")
        else:
            sent, problems = push_to_garmin(api, rows)
            print(f"  a Garmin: {sent} pesate nuove")
            for problem in problems:
                print(f"  ATTENZIONE: {problem}")
    return {
        "configured": True,
        "measurements": len(rows),
        "files": len(files),
        "to_garmin": sent,
    }


def main() -> None:
    """`make update_weight`, e il giro del mattino."""
    update_weight()
