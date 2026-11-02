"""Come e' stata corsa una seduta, in numeri, dai soli dati campionati.

Era un report testuale per attivita', scritto in `summary/00.activity/` da
uno script batch: 976 file che nessuno leggeva piu'. Il giudizio sulla
seduta lo scrive l'agente Training, che ha davanti tutto il giorno, e i
numeri qui sotto finiscono nel JSON che legge (`daily_data`, todo 43).
Cancellato con la pulizia del 2026-10-24; il resto del modulo e' il conto,
che serve.
"""

import pandas as pd

from training.interface.grade import slope_pct

# Le grandezze che dicono come e' stata corsa una seduta: le legge
# `daily_data`, che le mette nel JSON del giorno (todo 43).
_NUMBER_KEYS = (
    "speed_first_half_kmh",
    "speed_second_half_kmh",
    "speed_change_pct",
    "hr_first_half",
    "hr_second_half",
    "hr_change_pct",
    "cadence_mean",
    "cadence_variation_pct",
    "uphill_hr",
    "flat_hr",
)


# Le sole grandezze qui sopra che la distanza non la toccano: le due meta'
# sono meta' *di distanza*, quindi dove la distanza e' una stima del polso
# (il tapis roulant, todo 45) cade anche il confronto dei battiti, che non
# sarebbe fatto a meta' seduta ma in un punto deciso dalla stima.
NUMBERS_WITHOUT_DISTANCE = ("cadence_mean", "cadence_variation_pct")


def activity_numbers(records: pd.DataFrame) -> dict[str, float | None]:
    """Come e' stata corsa la seduta, in numeri: le medie della prima e della
    seconda meta' (per distanza) con la differenza in percento, la cadenza
    con la sua variabilita', e i battiti in salita contro quelli in piano.

    Grezzi, non arrotondati: `activity_comments()` ci scrive sopra le sue
    frasi e `daily_data` li arrotonda per il JSON, ognuno con i suoi
    decimali. `None` dove il dato non c'e' o non si puo' ricavare."""
    out: dict[str, float | None] = dict.fromkeys(_NUMBER_KEYS)

    has_distance = records["distance_km"].notna().any() and records["distance_km"].max() > 0
    if has_distance:
        half_distance = records["distance_km"].max() / 2
        first_half = records[records["distance_km"] <= half_distance]
        second_half = records[records["distance_km"] > half_distance]

        speed1, speed2 = first_half["speed_kmh"].mean(), second_half["speed_kmh"].mean()
        if pd.notna(speed1) and pd.notna(speed2) and speed1 > 0:
            out["speed_first_half_kmh"] = float(speed1)
            out["speed_second_half_kmh"] = float(speed2)
            out["speed_change_pct"] = (speed2 - speed1) / speed1 * 100

        hr1, hr2 = first_half["heart_rate"].mean(), second_half["heart_rate"].mean()
        if pd.notna(hr1) and pd.notna(hr2) and hr1 > 0:
            out["hr_first_half"] = float(hr1)
            out["hr_second_half"] = float(hr2)
            out["hr_change_pct"] = (hr2 - hr1) / hr1 * 100

    if (
        records["altitude_m"].notna().any()
        and has_distance
        and records["heart_rate"].notna().any()
    ):
        # La pendenza lisciata di `grade.slope_pct`, non il rapporto fra due
        # campioni: quello e' dominato dal barometro. Un metro di quota
        # sbagliato su cinque di distanza fa un 20%, e i campioni di un
        # tratto davvero piano finivano oltre il 3% mentre altri cadevano
        # dentro la banda del piano. Misurato sull'escursione del 17 ottobre:
        # 110 contro 101 battiti col conto grezzo, 110 contro 95 con la
        # pendenza vera — e i campioni "piani" da 497 a 125, cioe' quattro
        # quinti stavano nel secchio sbagliato. Il grafico della stessa
        # pagina disegna gia' questa.
        slope = slope_pct(records)
        uphill_hr = records.loc[slope > 3, "heart_rate"].mean()
        flat_hr = records.loc[slope.between(-1, 1), "heart_rate"].mean()
        if pd.notna(uphill_hr):
            out["uphill_hr"] = float(uphill_hr)
        if pd.notna(flat_hr):
            out["flat_hr"] = float(flat_hr)

    if records["cadence"].notna().any():
        cadence = records["cadence"].dropna()
        cadence_mean = cadence.mean()
        if pd.notna(cadence_mean) and cadence_mean:
            variation = cadence.std() / cadence_mean * 100
            out["cadence_mean"] = float(cadence_mean)
            out["cadence_variation_pct"] = float(variation) if pd.notna(variation) else None

    return out
