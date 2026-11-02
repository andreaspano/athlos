"""Pendenza e velocita' equivalente in piano, dai record di un'attivita'.

La velocita' equivalente e' quella che in piano costerebbe la stessa energia
spesa sulla pendenza reale: serve a confrontare uscite con dislivelli diversi.

Il costo viene da Minetti et al. 2002, "Energy cost of walking and running at
extreme uphill and downhill slopes" (J Appl Physiol 93:1039-1046): il
polinomio del costo della corsa in J/kg/m, con la pendenza come frazione,
valido fra -45% e +45%. E' misurato in laboratorio sulla corsa: per camminata
ed escursione e' un'approssimazione. In salita e' piu' severo del GAP di
Strava (che e' tarato sulla frequenza cardiaca), quindi i numeri non
coincidono con quelli di Strava.
"""

import numpy as np
import pandas as pd

# Gli sport per cui il modello ha senso: la bici dipende soprattutto
# dall'aria e lo sci dalla neve, e li' la cella resta vuota.
EQUIV_SPEED_SPORTS = {"running", "hiking", "walking"}

# L'intervallo in cui Minetti ha misurato il polinomio: fuori si estrapola.
MODEL_SLOPE_LIMIT_PCT = 45
_FLAT_COST = 3.6

# Un buco fra due record oltre questa soglia e' una pausa: l'orologio fermo
# non scrive record. Le medie mobili si fanno dentro i tratti fra due pause,
# mai a cavallo, se no mescolano i due lati della sosta. I 5 s valgono per i
# file a un record al secondo; quelli vecchi (registrazione "smart") ne hanno
# uno ogni 3-9 s anche in movimento, e li' la soglia sale a quattro volte
# l'intervallo tipico del file, se no ogni campione sarebbe una pausa.
_PAUSE_GAP_MIN = pd.Timedelta(seconds=5)
_PAUSE_GAP_INTERVALS = 4

# La pendenza (todo 28): quota lisciata nel tempo, poi dislivello su una
# finestra in metri attorno al campione. In metri e non in secondi perche'
# nei tratti lenti pochi secondi coprono pochi metri e il rapporto impazzisce.
_ALTITUDE_SMOOTH = "15s"
_SLOPE_HALF_WINDOW_M = 30
_SLOPE_MIN_SPAN_M = 20
# La pendenza che entra nel modello di costo e' lisciata a 90 s: con meno la
# velocita' equivalente amplifica ogni oscillazione del barometro, e nel
# tempo una salita lunga resta intatta mentre i saliscendi brevi si
# compensano.
_COST_SLOPE_SMOOTH = "90s"


def pause_gap(index: pd.DatetimeIndex) -> pd.Timedelta:
    """Il buco oltre il quale c'e' una pausa, per questo file: 5 s, o quattro
    volte l'intervallo mediano fra due record se e' piu' lungo."""
    step = index.to_series().diff().median()
    if pd.isna(step):
        return _PAUSE_GAP_MIN
    return max(_PAUSE_GAP_MIN, step * _PAUSE_GAP_INTERVALS)


def sample_seconds(index: pd.DatetimeIndex) -> np.ndarray:
    """Quanti secondi vale ogni campione: fino al campione dopo, e **uno
    solo** attraverso una pausa e per l'ultimo.

    Con un record al secondo e' un conteggio; i file vecchi ne hanno di piu'
    radi. Una pausa e' un buco oltre `pause_gap`, cioe' 5 s o quattro volte
    l'intervallo mediano: il tempo in cui l'orologio era fermo non e' tempo
    allenato, e caricarlo sul campione prima vorrebbe dire contare il
    semaforo come fatica.

    Qui perche' la regola serve a due padroni: `run_chart.durations_s`, che
    la usa per il grafico e per gli effetti, e `db._zone_minutes`, che
    scrive i minuti per zona nel database. Avevano due conti diversi —
    questo e un tetto di 30 s per buco — e sulle sedute recenti non
    andavano d'accordo: 16.1 minuti contro 12.1 di basso aerobico sulla
    stessa uscita, con la Day che leggeva uno e la Week l'altro."""
    if len(index) == 0:
        return np.array([], dtype="float64")
    gap = np.diff(index.to_numpy()).astype("timedelta64[s]").astype("float64")
    paused = gap > pause_gap(index) / pd.Timedelta("1s")
    return np.append(np.where(paused, 1.0, gap), 1.0)


def segments(index: pd.DatetimeIndex) -> pd.Series:
    """Il numero del tratto continuo di ogni campione: cresce di uno a ogni
    pausa (vedi `pause_gap`)."""
    gaps = index.to_series().diff() > pause_gap(index)
    return gaps.cumsum()


def rolling_mean(series: pd.Series, window: str) -> pd.Series:
    """Media mobile centrata nel tempo, dentro ogni tratto fra due pause.

    Su una finestra di tempo e non di campioni: i file vecchi non hanno un
    record al secondo. Estremi compresi, cosi' la finestra e' simmetrica
    attorno al campione (90 s sono 45 s prima e 45 dopo)."""
    return series.astype(float).groupby(segments(series.index), group_keys=False).apply(
        lambda part: part.rolling(window, min_periods=1, center=True, closed="both").mean()
    )


def slope_pct(records: pd.DataFrame) -> pd.Series:
    """La pendenza in percentuale, campione per campione, senza clip.

    La quota si liscia a 15 s; poi, per ogni campione, il primo punto a non
    piu' di 30 m indietro e l'ultimo a non piu' di 30 m avanti lungo la
    distanza: dislivello diviso distanza fra i due. Sotto i 20 m di finestra
    (fermi, o distanza mancante) la pendenza e' NaN. La distanza
    dell'orologio e' trattata come orizzontale. Le lisciature successive e
    la clip le fa chi chiama: il modello e il grafico ne vogliono di diverse."""
    if records.empty:
        return pd.Series(dtype=float, index=records.index)
    altitude = rolling_mean(records["altitude_m"], _ALTITUDE_SMOOTH).to_numpy()
    # Cummax: la distanza non deve mai tornare indietro, se no la ricerca
    # binaria sotto non vale.
    distance_m = records["distance_km"].astype(float).fillna(0).cummax().to_numpy() * 1000
    back = np.searchsorted(distance_m, distance_m - _SLOPE_HALF_WINDOW_M, side="left")
    ahead = np.searchsorted(distance_m, distance_m + _SLOPE_HALF_WINDOW_M, side="right") - 1
    span_m = distance_m[ahead] - distance_m[back]
    rise_m = altitude[ahead] - altitude[back]
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(span_m >= _SLOPE_MIN_SPAN_M, rise_m / span_m * 100, np.nan)
    return pd.Series(slope, index=records.index)


def minetti_cost(i):
    """Il costo energetico della corsa (J/kg/m) alla pendenza `i` (frazione)."""
    return 155.4 * i**5 - 30.4 * i**4 - 43.3 * i**3 + 46.3 * i**2 + 19.5 * i + _FLAT_COST


def _cost_factor(records: pd.DataFrame) -> pd.Series:
    """Il costo di ogni campione relativo alla pianura (1 = come in piano).

    Dove la pendenza non si sa (quota mancante in quel tratto) il campione
    vale come in piano: meglio che buttarlo."""
    limit = MODEL_SLOPE_LIMIT_PCT
    slope = rolling_mean(slope_pct(records), _COST_SLOPE_SMOOTH).clip(-limit, limit) / 100
    return (minetti_cost(slope) / _FLAT_COST).fillna(1.0)


def equivalent_speed_series(records: pd.DataFrame) -> pd.Series:
    """La velocita' equivalente in piano campione per campione, in km/h.

    Grezza, non lisciata: il rumore dell'altimetro passa nel fattore, e la
    media mobile la fa chi la disegna. Una media nel tempo di questa serie e'
    vicina ma non uguale a `equivalent_speed_kmh`, che pesa i tratti per la
    distanza e parte dalla velocita' media di Garmin."""
    return records["speed_kmh"].astype(float) * _cost_factor(records)


def equivalent_speed_kmh(records: pd.DataFrame, avg_speed_kmh: float | None) -> float | None:
    """La velocita' equivalente in piano dell'attivita', in km/h, o None.

    Si sommano i tratti di distanza pesati per il costo relativo alla
    pianura: il rapporto fra la distanza equivalente e quella vera e' il
    fattore che porta `avg_speed_kmh` in piano. Si moltiplica la velocita'
    media dell'attivita' invece di ridividere per un tempo in movimento
    stimato dai record: il divisore resta quello di Garmin (vedi
    `fit._avg_speed_kmh`), e in piano le due velocita' coincidono. Pesare per
    la distanza fa contare ogni tratto per quanto e' lungo; le soste (distanza
    ferma) non pesano. Senza quota, distanza o velocita' media non c'e'
    valore."""
    if (
        avg_speed_kmh is None
        or pd.isna(avg_speed_kmh)
        or records.empty
        or records["altitude_m"].isna().all()
    ):
        return None

    distance_diff_m = (records["distance_km"].astype(float).diff() * 1000).clip(lower=0)
    total_m = float(np.nansum(distance_diff_m))
    if total_m <= 0:
        return None

    equivalent_m = float(np.nansum(distance_diff_m * _cost_factor(records)))
    return avg_speed_kmh * equivalent_m / total_m
