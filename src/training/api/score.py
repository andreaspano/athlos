"""La faccia di una card: come sta andando quella cosa, in una parola (todo 92).

Cinque gradini — `terrible`, `low`, `medium`, `high`, `perfect` — e cinque
icone in `icons/`. Il voto **viene dai numeri**, non da un'opinione: le
fasce che la pagina disegna gia' sotto ogni misura (`low`/`high` una
deviazione standard attorno alla media, `outer_low`/`outer_high` due) dicono
dove sta il valore, e qui si decide che faccia fare.

Quello che mancava non erano le fasce, era **da che parte sta il male**:
scritto a parole in `.claude/agents/_style.md`, cioe' nel prompt degli
agenti, e in nessun posto che il codice potesse usare. La tabella qui sotto
e' la copia di quelle righe, e porta scritto da dove viene — se un giorno
quella cambia, questa va cambiata con lei.

**La faccia e' una lettura relativa, non un voto assoluto.** La fascia e' la
storia di quella persona, quindi `perfect` vuol dire *insolitamente bene per
te*, non *bene in assoluto*.

**Il Comment non passa di qui**: la Training non ha misure con fasce, ha una
seduta e un giudizio, e quella parola la scrive l'agente che il giudizio lo
da' (una riga `verdict:` in cima al frammento, che `_fragment_sections`
toglie)."""

from typing import Literal

Verdict = Literal["terrible", "low", "medium", "high", "perfect"]

# Dal gradino (-2..+2) alla parola.
_WORDS: tuple[Verdict, ...] = ("terrible", "low", "medium", "high", "perfect")

# Da che parte sta il bene, misura per misura (`.claude/agents/_style.md`).
#
# **Sotto e' male** per HRV, prontezza, sonno e body battery; **sopra e'
# male** per FC a riposo, respiro nel sonno e stress; e i punteggi di forma
# si leggono al contrario degli altri — sopra la fascia stanno ancora
# salendo, ed e' una buona notizia.
#
# Le chiavi sono quelle dei due payload, del giorno e della settimana: alcune
# misure hanno due nomi (`resp_sleep` e `resp_sleep_avg`) perche' una e' la
# lettura di una mattina e l'altra la media dei sette giorni, ma la direzione
# e' la stessa.
GOOD_HIGH: frozenset[str] = frozenset({
    "readiness",
    "hrv_last_night",
    "hrv_weekly_avg",
    "sleep_hours",
    "sleep_score",
    "body_battery_morning",
    "body_battery_low_yesterday",
    "body_battery_high",
    "body_battery_low",
    "vo2max",
    "endurance",
    "hill",
})
GOOD_LOW: frozenset[str] = frozenset({
    "resting_hr",
    "resp_sleep",
    "resp_sleep_avg",
    "stress_avg_yesterday",
    "stress_avg",
})


def step(value: float | None, band: dict | None, key: str) -> int | None:
    """Il gradino di una misura, da -2 a +2, o `None` se non si puo' dire.

    `None` quando manca il valore, manca la fascia (troppi pochi periodi
    misurati) o la misura non sta nella tabella delle direzioni: **non
    votare e' diverso da votare zero**, e una misura che non si sa leggere
    non deve tirare la media verso il centro."""
    if value is None or not band:
        return None
    if key in GOOD_HIGH:
        good_high = True
    elif key in GOOD_LOW:
        good_high = False
    else:
        return None
    low, high = band.get("low"), band.get("high")
    outer_low, outer_high = band.get("outer_low"), band.get("outer_high")
    if low is None or high is None:
        return None
    if low <= value <= high:
        return 0
    above = value > high
    far = (outer_high is not None and value > outer_high) if above else (
        outer_low is not None and value < outer_low
    )
    good_side = above == good_high
    size = 2 if far else 1
    return size if good_side else -size


def centred(value: float | None, band: dict | None) -> int | None:
    """Il gradino di una misura che **non ha un lato buono**: il carico.

    Tanto e' troppo e poco e' poco, e il bene sta dove uno di solito sta.
    Dentro la fascia **+1**, fra una e due sigma **0** da qualunque parte,
    oltre **-1**.

    Da cui il fatto che il carico **non arriva mai a `perfect` ne' a
    `terrible`**: il massimo che questa misura sa dire e' «sei dove stai di
    solito», e quella e' `high`. Un `perfect` sarebbe un bersaglio che i dati
    non hanno.

    I gradini sono +1/0/-1 e non 0/-1/-2 come erano: la tabella delle parole
    va da -2 a +2, quindi quei tre numeri cadevano su `medium`, `low` e
    `terrible` — il contrario di quello che questo docstring, `models.py`, lo
    schema OpenAPI e il README promettono tutti e quattro. In piu', una scala
    tutta da una parte tirava giu' la media di `_card_scores`: il Summary
    veniva lo stesso col carico al suo meglio e al suo peggio, cioe' la card
    del carico non riusciva a muoverlo."""
    if value is None or not band:
        return None
    low, high = band.get("low"), band.get("high")
    if low is None or high is None:
        return None
    if low <= value <= high:
        return 1
    outer_low, outer_high = band.get("outer_low"), band.get("outer_high")
    far = (outer_high is not None and value > outer_high) if value > high else (
        outer_low is not None and value < outer_low
    )
    return -1 if far else 0


def verdict(steps: list[int | None]) -> Verdict | None:
    """La faccia di una card: la media dei gradini che hanno votato.

    `None` quando non vota nessuno — la card non ha faccia, e **l'assenza di
    misure non e' un verdetto**.

    La media si arrotonda al gradino piu' vicino, con i mezzi verso lo zero:
    fra `medium` e `high` a meta' strada si dice la cosa piu' prudente."""
    voted = [s for s in steps if s is not None]
    if not voted:
        return None
    mean = sum(voted) / len(voted)
    # Mezzi verso lo zero (`int` tronca), il resto all'intero piu' vicino.
    rounded = int(mean) if abs(mean) % 1 == 0.5 else round(mean)
    return _WORDS[max(-2, min(2, rounded)) + 2]


def _measure(block: dict | None, key: str) -> int | None:
    """Il gradino di una misura del payload del giorno (`morning`), dove ogni
    voce e' `{value, band, ...}`."""
    entry = (block or {}).get(key)
    if not isinstance(entry, dict):
        return None
    return step(entry.get("value"), entry.get("band"), key)


def _score_fitness(fitness: dict | None) -> list[int | None]:
    """I tre punteggi di forma, che nel payload hanno `now` invece di
    `value`. Soglia e acclimatamenti restano fuori: non hanno una fascia, e
    senza fascia non c'e' niente da leggere."""
    out = []
    for key in ("vo2max", "endurance", "hill"):
        entry = (fitness or {}).get(key)
        if isinstance(entry, dict):
            out.append(step(entry.get("now"), entry.get("band"), key))
    return out


def daily_scores(payload: dict) -> dict[str, Verdict | None]:
    """Le facce del giorno, dal payload che riceve la pagina."""
    morning = payload.get("morning") or {}
    health = [
        _measure(morning, key)
        for key in ("resting_hr", "hrv_last_night", "resp_sleep", "stress_avg_yesterday")
    ]
    recovery = [
        _measure(morning, key)
        for key in (
            "readiness",
            "sleep_hours",
            "body_battery_morning",
            "body_battery_low_yesterday",
        )
    ]
    load_now = ((payload.get("load") or {}).get("now")) or {}
    bands = ((payload.get("load") or {}).get("bands")) or {}
    load = [
        centred(load_now.get(key), bands.get(key))
        for key in ("load_aerobic_low", "load_aerobic_high", "load_anaerobic")
    ]
    fitness = _score_fitness(payload.get("fitness"))
    return _card_scores(health, recovery, load, fitness)


# Le tre fasce di sforzo della card Load della Week, nell'ordine in cui le
# disegna (`ZONE_ROWS` in `WeekPage.tsx`). Stanno in `zones`, che tiene anche
# due numeri che non sono misure (`sessions_without_hr`, `measured_min`):
# qui si nominano le tre che votano.
WEEK_ZONE_KEYS = ("low_aerobic", "high_aerobic", "anaerobic")


def weekly_scores(payload: dict) -> dict[str, Verdict | None]:
    """Le facce della settimana. Le misure arrivano gia' divise per card
    (`measures[...]["card"]`).

    Il carico vota su **quello che la card disegna**: il carico dei sette
    giorni e i tre tempi per zona, ognuno contro le dodici settimane prima —
    quattro barre, quattro voti. Prima votava il solo `load_acute`, e su 90
    settimane 17 mostravano una faccia che le barre accanto contraddicevano,
    piu' 8 senza faccia perche' mancava la sua fascia mentre le tre delle
    zone c'erano. Il giorno lo fa gia' cosi' (`daily_scores`, che vota
    esattamente le tre barre di `LoadCard.tsx`)."""
    measures = payload.get("measures") or {}
    def by_card(card: str) -> list[int | None]:
        return [
            step(m.get("value"), m.get("band"), key)
            for key, m in measures.items()
            if isinstance(m, dict) and m.get("card") == card
        ]

    week_load = payload.get("load") or {}
    zones = payload.get("zones") or {}
    load = [centred(week_load.get("load_acute"), week_load.get("band"))]
    for key in WEEK_ZONE_KEYS:
        zone = zones.get(key)
        if isinstance(zone, dict):
            load.append(centred(zone.get("minutes"), zone.get("band")))
    return _card_scores(
        by_card("health"), by_card("recovery"), load, _score_fitness(payload.get("fitness"))
    )


def _card_scores(
    health: list[int | None],
    recovery: list[int | None],
    load: list[int | None],
    fitness: list[int | None],
) -> dict[str, Verdict | None]:
    """Le quattro card, piu' il Summary che e' la media delle loro.

    Il Summary non ha misure sue: e' il verdetto sulle altre, che e'
    esattamente quello che fa l'agente leggendo i frammenti. Si media sui
    **gradini delle card** e non su tutte le misure insieme, cosi' una card
    con quattro misure non pesa quattro volte una con una."""
    cards = {"health": health, "recovery": recovery, "load": load, "fitness": fitness}
    words = {name: verdict(steps) for name, steps in cards.items()}
    summary = verdict([
        _WORDS.index(word) - 2 if word is not None else None for word in words.values()
    ])
    return {**words, "summary": summary}
