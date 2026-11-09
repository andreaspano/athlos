"""Il blocco di allenamento visto da fuori: la risposta e l'aderenza (todo 96).

Due misure, **separate**, come dice `docs/aderenza.md`: l'aderenza e' quanto
stai seguendo il piano, la risposta e' quanto il piano sta funzionando. Non si
fondono in un numero unico, perche' se l'aderenza e' alta e la risposta non
arriva va cambiato il piano, mentre se l'aderenza e' bassa il piano non e'
stato messo alla prova — e un numero solo non distingue i due casi, che sono i
due in cui si fa qualcosa di diverso.

Un modulo a se' e non dentro `weekly_data.py`: quello risponde su **una**
settimana, questo legge tutte le settimane di un blocco e tutte le corse che
ci stanno dentro.

Qui non si legge niente da disco se non attraverso chi chiama: le attivita'
arrivano gia' caricate (la cache dell'API) e la velocita' a ritmo gara
attraverso una funzione, perche' la sua cache vive in `api/cache.py`. Cosi'
questo modulo e' fatto di conti e si puo' provare con dei numeri scritti a
mano."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from training.api.plans import load_plans, load_week_plan, planned_weeks
from training.interface.grade import sample_seconds

# Lo sport dei tre KPI. **Solo `running`**: il tapis roulant e' uno sport a se'
# (todo 45) e la sua distanza la stima il polso, tanto che `sports.has_distance`
# la esclude da ogni somma del progetto. Un blocco che si misura in chilometri
# non puo' contare chilometri che non sono stati misurati.
RUNNING = "running"

# Il tratto continuo minimo che vale come "a ritmo gara", in km. Senza, ogni
# strappo in discesa dentro una corsa lenta finirebbe nel conto: la lunga del
# 7 novembre 2026, corsa a 8.17 km/h di media, regala tratti sopra 9.04 che
# non sono stati ritmo gara.
RACE_PACE_MIN_KM = 1.0

# Quante settimane prima dell'inizio del blocco si guardano per la partenza di
# un KPI che il piano non dichiara.
BASELINE_WEEKS = 4

# Le sedute che pesano doppio nell'aderenza. Il documento dice «lungo,
# ripetute, test»; il vocabolario del piano ha `easy | quality | long`.
KEY_KINDS = ("long", "quality")

# I tre KPI, nell'ordine in cui si leggono: quanto corri, quanto a lungo,
# quanto in fretta.
PANEL_KEYS = ("volume", "long_run", "race_pace")
PANEL_LABELS = {"volume": "Volume", "long_run": "Long run", "race_pace": "Race pace"}


# --- Il ritmo gara, dai campioni di una seduta ---


def race_pace_km(
    records: pd.DataFrame, target_kmh: float, min_km: float = RACE_PACE_MIN_KM
) -> float:
    """Il tratto continuo piu' lungo a velocita' equivalente media >=
    `target_kmh`, in km, dentro una seduta.

    E' il KPI della velocita', e la velocita' non lo e': il candidato ovvio —
    la velocita' migliore della settimana — era gia' sopra il bersaglio prima
    che il blocco cominciasse (9.38 km/h il 30 settembre 2026 contro 9.04 di
    bersaglio), quindi inchiodato al 100% dalla prima settimana. Questo invece
    e' il divario che il blocco dichiara di suo: «You have never run at 6'38"
    for more than 8 km».

    **Il tempo e' quello in movimento**: `sample_seconds` collassa le pause a
    un secondo, cosi' il semaforo non conta come fatica. Il tratto invece
    **attraversa** la pausa, e la scelta e' voluta: spezzare su `segments`
    faceva leggere 7.2 km la corsa del 25 ottobre 2026, che sono 8.0 km interi
    sopra il bersaglio con dentro una pausa dell'orologio. Otto e' il numero
    che il blocco dichiara di suo («more than 8 km»), 7.2 era un'invenzione
    del filtro. E' anche la regola che il progetto gia' segue altrove: i
    minuti per zona di `db._zone_minutes` sommano `sample_seconds` per tutta
    la seduta, pause comprese.

    Si paga che un tratto con dentro dieci minuti di sosta vera conta come
    continuo. Succede poco — `pause_gap` scatta a cinque secondi, quindi le
    soste ci sono tutte dentro — e sbaglia dalla parte che non inventa.

    Il conto non e' a coppie di punti, che e' O(n^2) — misurato, due minuti per
    trenta corse. La condizione `(d[k]-d[i]) / (t[k]-t[i]) >= v` si riscrive
    `g[k] >= g[i]` con `g = distanza - v * tempo`, e allora per ogni `i` serve
    solo l'ultimo `k` con `g[k] >= g[i]`, che si trova in binaria sul massimo
    suffisso di `g` — non crescente per costruzione. O(n log n), istantaneo.

    Zero vuol dire «nessun tratto lungo abbastanza», che e' un dato: una
    settimana di sole corse lente lo scrive."""
    if records.empty or "distance_km" not in records or "equiv_speed_kmh" not in records:
        return 0.0
    seconds = sample_seconds(records.index)
    distance = pd.to_numeric(records["distance_km"], errors="coerce").to_numpy(dtype="float64")
    # Il tempo in movimento cumulato: la durata di un campione vale **fino al
    # successivo**, quindi il tempo trascorso fino al campione `i` e' la somma
    # dei campioni prima di lui.
    elapsed = np.concatenate(([0.0], np.cumsum(seconds)[:-1])) / 3600.0
    ok = np.isfinite(distance) & np.isfinite(elapsed)
    d, t = distance[ok], elapsed[ok]
    if len(d) < 2:
        return 0.0
    g = d - target_kmh * t
    # Il massimo da ogni punto in poi: non crescente per costruzione, quindi
    # cercabile in binaria.
    suffix = np.maximum.accumulate(g[::-1])[::-1]
    best = 0.0
    for i in range(len(g) - 1):
        # L'ultimo k > i con `suffix[k] >= g[i]`: quello **e'** l'indice
        # cercato, perche' se k+1 non qualifica allora nessun indice oltre k
        # qualifica, e quindi a quel punto `suffix[k]` e' `g[k]` stesso.
        k = int(np.searchsorted(-suffix[i + 1 :], -g[i], side="right")) + i
        if k > i and suffix[k] >= g[i]:
            best = max(best, float(d[k] - d[i]))
    return best if best >= min_km else 0.0


# --- Le settimane del blocco, dai file del piano ---


def _planned_runs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Le sedute di corsa previste da una settimana, con i loro chilometri.

    Il riposo non e' una seduta da eseguire, e la bici facoltativa
    (`optional: cycling`) nemmeno: e' permessa, non richiesta. Una corsa senza
    chilometri nel front matter non si conta: non c'e' niente da confrontare."""
    runs = []
    for session in plan.get("sessions") or []:
        if session.get("sport") != RUNNING:
            continue
        km = session.get("distance_km")
        if km is None or km <= 0:
            continue
        runs.append(
            {
                "day": session["day"],
                "kind": session.get("kind"),
                "planned_km": float(km),
                "key": session.get("kind") in KEY_KINDS,
            }
        )
    return sorted(runs, key=lambda r: r["day"])


def block_of(summary_dir: Path, monday: date) -> dict[str, Any] | None:
    """Il blocco a cui appartiene la settimana di `monday`, settimana per
    settimana, o `None` se quella settimana non sta in un blocco.

    Il blocco e' l'insieme delle settimane scritte che dichiarano lo stesso
    `plan:` e hanno un `block_week`. **Non** si prende dal goal attuale
    (`block_start` + `block_weeks` in `plan/`): quello e' cio' che il goal
    dichiara, e i due divergono — cambiare goal non riscrive le settimane gia'
    scritte (todo 86). Una settimana che segue un piano vecchio mostra il
    **suo** blocco, che e' il registro di quello che era previsto allora."""
    here = load_week_plan(summary_dir, monday)
    if here is None or here.get("block_week") is None or not here.get("plan"):
        return None
    slug = here["plan"]
    weeks: dict[int, dict[str, Any]] = {}
    for week_monday in planned_weeks(summary_dir):
        plan = load_week_plan(summary_dir, week_monday)
        if plan is None or plan.get("plan") != slug or plan.get("block_week") is None:
            continue
        runs = _planned_runs(plan)
        weeks[plan["block_week"]] = {
            "block_week": plan["block_week"],
            "monday": week_monday,
            "phase": plan.get("phase"),
            "planned_km": sum(r["planned_km"] for r in runs) if runs else None,
            "planned_long": max((r["planned_km"] for r in runs), default=None),
            "runs": runs,
        }
    if not weeks:
        return None
    total = here.get("block_weeks") or max(weeks)
    return {
        "slug": slug,
        "block_weeks": int(total),
        "block_week": int(here["block_week"]),
        "monday": monday,
        "weeks": [weeks[n] for n in sorted(weeks)],
    }


def goal_of(plan_dir: Path, slug: str) -> dict[str, Any] | None:
    """Il goal da cui viene il blocco, per i bersagli. `None` se il file non
    c'e' piu': le settimane restano, il goal puo' essere stato cestinato."""
    return next((plan for plan in load_plans(plan_dir) if plan["slug"] == slug), None)


# --- Le misure di una settimana ---


def _runs_of(activities: pd.DataFrame, monday: date) -> pd.DataFrame:
    """Le corse di una settimana ISO, in ordine di inizio."""
    if activities.empty:
        return activities
    day = activities["start_time"].dt.date
    week = activities[
        (activities["sport"] == RUNNING) & (day >= monday) & (day <= monday + timedelta(days=6))
    ]
    return week.sort_values("start_time")


def week_measures(
    activities: pd.DataFrame,
    monday: date,
    target_speed_kmh: float | None,
    race_pace: Callable[[int, float], float],
) -> dict[str, float | None]:
    """I tre KPI misurati di una settimana. `None` dove non c'e' niente da
    misurare — una settimana senza corse non vale zero, non esiste — e la
    differenza si vede a schermo, dove una barra assente non e' una barra a
    zero."""
    runs = _runs_of(activities, monday)
    if runs.empty:
        return {"volume": None, "long_run": None, "race_pace": None}
    distance = pd.to_numeric(runs["total_distance_km"], errors="coerce")
    return {
        "volume": float(distance.sum(min_count=1)) if distance.notna().any() else None,
        "long_run": float(distance.max()) if distance.notna().any() else None,
        # Zero e' un dato: una settimana di sole corse lente non ha tratti a
        # ritmo gara, e lo dice.
        "race_pace": (
            max((race_pace(int(aid), target_speed_kmh) for aid in runs["activity_id"]), default=0.0)
            if target_speed_kmh
            else None
        ),
    }


# --- L'aderenza (docs/aderenza.md) ---


def s_vol(ratio: float) -> float:
    """La somiglianza di volume fra il fatto e il previsto.

        s_vol = max(0, 1 - |ln r| / ln 2)

    Uno se fai esattamente il previsto, zero se fai il doppio o la meta', e
    **simmetrico in scala logaritmica**: strafare pesa quanto fare meno."""
    if ratio <= 0:
        return 0.0
    return max(0.0, 1.0 - abs(math.log(ratio)) / math.log(2.0))


def _match(runs: pd.DataFrame, planned: list[dict[str, Any]]) -> dict[int, int]:
    """Quale corsa fatta corrisponde a quale seduta prevista: l'indice della
    riga di `runs` per ogni posizione di `planned`.

    Si cerca **nel suo giorno**; se quel giorno non ha una corsa, nei due
    giorni accanto, e vince la piu' vicina fra quelle non ancora abbinate.
    `docs/aderenza.md` lo lascia come domanda aperta: senza finestra una
    seduta spostata di un giorno viene punita due volte — zero sul giorno
    previsto **e** un'eccedenza sul giorno in cui e' stata fatta."""
    if runs.empty:
        return {}
    days = list(runs["start_time"].dt.date)
    taken: set[int] = set()
    found: dict[int, int] = {}
    for position, session in enumerate(planned):
        candidates = [
            (abs((day - session["day"]).days), index)
            for index, day in enumerate(days)
            if index not in taken and abs((day - session["day"]).days) <= 1
        ]
        if not candidates:
            continue
        _, index = min(candidates)
        taken.add(index)
        found[position] = index
    return found


def adherence(
    runs: pd.DataFrame, planned: list[dict[str, Any]], today: date | None = None
) -> dict[str, Any]:
    """L'aderenza di volume di una settimana, seduta per seduta e in totale.

    **Si contano solo le sedute il cui giorno e' passato.** Una settimana in
    corso ne ha davanti a se', e quelle non sono state saltate: non sono
    ancora arrivate. Senza questa regola il lunedi' mattina la settimana
    segnava zero con tre sedute «not done», cioe' un rimprovero per qualcosa
    che non e' successo — e il rapporto diceva «0.00, 0 of 33 km» su una
    settimana che deve ancora cominciare. Per una settimana finita non cambia
    niente, che sono passate tutte.

    Si chiama cosi' e non "aderenza" perche' e' **meta'** della misura del
    documento, che e' `(s_vol + s_int) / 2`: `s_int` vuole la distribuzione del
    tempo nelle zone prevista, e il front matter delle sedute non ce l'ha. Un
    numero chiamato `adherence` che vale la meta' della sua definizione e' il
    tipo di bugia che fra sei mesi nessuno ricorda di aver detto.

    Il punteggio della settimana e' la media dei punteggi pesata sui
    chilometri previsti, con le sedute chiave a peso doppio. La pesatura non
    e' un dettaglio: martedi' 27 ottobre 2026 era prevista `easy 5 km` e sono
    stati corsi 9.1 km a ritmo gara, cioe' `s_vol` 0.14 — e pesata sui 5 km
    previsti la settimana chiude a 82 invece che a 72."""
    today = today or date.today()
    found = _match(runs, planned)
    rows = runs.reset_index(drop=True)
    sessions = []
    numerator = weight_total = 0.0
    planned_km = 0.0
    for position, session in enumerate(planned):
        index = found.get(position)
        # Una seduta che deve ancora arrivare non ha un punteggio e non entra
        # nel previsto del rapporto. Resta nell'elenco, perche' la riga del
        # giorno c'e' lo stesso: semplicemente non dice ancora niente.
        pending = session["day"] > today
        done_km = done_day = None
        if index is not None:
            done_km = rows.at[index, "total_distance_km"]
            done_km = float(done_km) if pd.notna(done_km) else None
            done_day = rows.at[index, "start_time"].date()
        ratio = done_km / session["planned_km"] if done_km else None
        # Prevista e non fatta vale zero; fatta ma senza una distanza
        # confrontabile non vale niente, e sta fuori dalla media; e una che
        # deve ancora arrivare non vale niente nemmeno lei.
        if pending:
            score = None
        else:
            score = 0.0 if index is None else (s_vol(ratio) if ratio is not None else None)
            planned_km += session["planned_km"]
        if score is not None:
            weight = session["planned_km"] * (2 if session["key"] else 1)
            numerator += weight * score
            weight_total += weight
        sessions.append(
            {
                "day": session["day"],
                "kind": session["kind"],
                "key": session["key"],
                "planned_km": round(session["planned_km"], 1),
                "done_km": round(done_km, 1) if done_km is not None else None,
                "ratio": round(ratio, 3) if ratio is not None else None,
                "score": round(score, 3) if score is not None else None,
                # Scritto solo quando non e' il suo giorno: e' la finestra di
                # un giorno che ha lavorato, e si deve poter vedere.
                "moved_to": done_day if done_day and done_day != session["day"] else None,
                "pending": pending,
            }
        )
    # Il rapporto conta **tutte** le corse della settimana, anche quelle che il
    # piano non chiedeva: l'aderenza dice come hai eseguito, il rapporto se sei
    # sopra o sotto.
    done_km = float(pd.to_numeric(runs["total_distance_km"], errors="coerce").sum()) if not runs.empty else 0.0
    return {
        "sessions": sessions,
        "volume_adherence": round(100 * numerator / weight_total, 1) if weight_total else None,
        "planned_km": round(planned_km, 1) if planned_km else None,
        "done_km": round(done_km, 1),
        "ratio": round(done_km / planned_km, 2) if planned_km else None,
    }


# --- La risposta: i tre pannelli ---


def _ratchet(values: list[float | None]) -> list[float | None]:
    """Il migliore fino a qui: sale su un record, resta fermo altrimenti.

    E' obbligatorio, non un abbellimento: i chilometri previsti da un blocco
    sono una sega — quattro discese volute su diciotto settimane, le settimane
    di scarico e lo scarico finale — e una linea col valore della settimana
    scenderebbe quattro volte e si leggerebbe come un crollo quando e' il piano
    che funziona."""
    best: float | None = None
    out: list[float | None] = []
    for value in values:
        if value is not None:
            best = value if best is None else max(best, value)
        out.append(best)
    return out


def _baseline(
    activities: pd.DataFrame,
    block_start: date,
    key: str,
    target_speed_kmh: float | None,
    race_pace: Callable[[int, float], float],
) -> float | None:
    """La partenza misurata: il meglio delle quattro settimane prima che il
    blocco cominciasse. Si usa solo dove il piano non dichiara niente, cioe'
    sul ritmo gara."""
    values = [
        week_measures(activities, block_start - timedelta(weeks=n), target_speed_kmh, race_pace)[key]
        for n in range(1, BASELINE_WEEKS + 1)
    ]
    measured = [v for v in values if v is not None]
    return max(measured) if measured else None


def _panel(
    key: str,
    start: float | None,
    target: float | None,
    planned: list[float | None],
    done: list[float | None],
    block_weeks: int,
    measured_through: int,
) -> dict[str, Any] | None:
    """Un pannello: le barre, il cricchetto, la diagonale e le due righe.

    **L'asse e' sul bersaglio** (`valore / bersaglio`) e non sul guadagno dalla
    partenza, perche' e' la cadenza settimanale a pretenderlo: la settimana 4
    chiede esattamente i chilometri della riga di partenza, e una settimana
    con un acciacco ci va sotto — con l'asse ancorato alla partenza quelle
    barre sarebbero zero e negative, e una settimana persa (zero km) sfonderebbe
    la scala a -130%.

    Il progresso resta, come **numero**: `(migliore - partenza) / (bersaglio -
    partenza)`, che e' la risposta a «sono in pari» e nel disegno e' la
    distanza fra la linea del cricchetto e la riga della partenza."""
    if not target or start is None:
        return None
    pct = lambda v: round(100.0 * v / target, 1) if v is not None else None
    span = target - start
    gain = lambda v: round(100.0 * (v - start) / span, 1) if (v is not None and span) else None
    # Il cricchetto del fatto **si ferma alla settimana corrente**: oltre non
    # c'e' niente da dire, e una linea che prosegue piatta fino alla gara
    # racconterebbe che da qui alla fine non migliori piu'. Dentro il
    # misurato invece porta avanti il suo massimo anche attraverso una
    # settimana senza corse, che e' tutto il suo mestiere.
    best_done = [
        value if i < measured_through else None for i, value in enumerate(_ratchet(done))
    ]
    best_plan = _ratchet(planned)
    start_pct = 100.0 * start / target
    points = []
    for i in range(block_weeks):
        week = i + 1
        points.append(
            {
                "block_week": week,
                "plan": round(planned[i], 1) if planned[i] is not None else None,
                "plan_pct": pct(planned[i]),
                "done": round(done[i], 1) if done[i] is not None else None,
                "done_pct": pct(done[i]),
                "best": round(best_done[i], 1) if best_done[i] is not None else None,
                "best_pct": pct(best_done[i]),
                "best_plan_pct": pct(best_plan[i]),
                "progress_pct": gain(best_done[i]),
                "plan_progress_pct": gain(best_plan[i]),
                # La diagonale parte dalla settimana **zero** sulla riga della
                # partenza: all'inizio della settimana 1 non e' passato niente,
                # e il punto della settimana n e' la sua fine.
                "elapsed_pct": round(start_pct + (100.0 - start_pct) * week / block_weeks, 1),
                "time_pct": round(100.0 * week / block_weeks, 1),
            }
        )
    reached = next((p["best"] for p in reversed(points) if p["best"] is not None), None)
    return {
        "key": key,
        "label": PANEL_LABELS[key],
        "unit": "km",
        "start": round(start, 1),
        "start_pct": round(start_pct, 1),
        "target": round(target, 3),
        "has_plan": any(v is not None for v in planned),
        "now": round(reached, 1) if reached is not None else None,
        "progress_pct": gain(reached),
        "points": points,
    }


def block_payload(
    summary_dir: Path,
    plan_dir: Path,
    activities: pd.DataFrame,
    monday: date,
    race_pace: Callable[[int, float], float],
    today: date | None = None,
) -> dict[str, Any] | None:
    """I tre pannelli del blocco a cui appartiene la settimana di `monday`.

    `None` quando quella settimana non sta in un blocco, o quando il goal da
    cui viene non si trova piu': senza i bersagli non c'e' una percentuale da
    disegnare."""
    block = block_of(summary_dir, monday)
    if block is None:
        return None
    goal = goal_of(plan_dir, block["slug"])
    if goal is None:
        return None
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    target_speed = goal.get("target_speed_kmh")
    weeks = {week["block_week"]: week for week in block["weeks"]}
    block_weeks = block["block_weeks"]

    planned: dict[str, list[float | None]] = {key: [] for key in PANEL_KEYS}
    done: dict[str, list[float | None]] = {key: [] for key in PANEL_KEYS}
    calendar = []
    for number in range(1, block_weeks + 1):
        week = weeks.get(number)
        planned["volume"].append(week["planned_km"] if week else None)
        planned["long_run"].append(week["planned_long"] if week else None)
        # Il ritmo gara non ha previsto: il front matter non porta i km a ritmo
        # gara, quel lavoro vive solo nella prosa del piano.
        planned["race_pace"].append(None)
        week_monday = week["monday"] if week else None
        # Una settimana che non e' cominciata non ha misure, e non ha nemmeno
        # uno zero: il cricchetto si ferma alla settimana corrente.
        measured = (
            week_measures(activities, week_monday, target_speed, race_pace)
            if week_monday is not None and week_monday <= this_monday
            else {key: None for key in PANEL_KEYS}
        )
        for key in PANEL_KEYS:
            done[key].append(measured[key])
        calendar.append(
            {
                "block_week": number,
                "monday": week_monday,
                "phase": week["phase"] if week else None,
            }
        )

    # Quante settimane del blocco sono cominciate: oltre, il fatto non esiste
    # ancora. Si conta sui lunedi' veri e non sul numero della settimana,
    # perche' un blocco puo' avere un buco (una settimana senza file).
    measured_through = sum(
        1 for week in calendar if week["monday"] is not None and week["monday"] <= this_monday
    )
    block_start = block["weeks"][0]["monday"]
    starts = {
        # La partenza e' quella che il piano dichiara per la settimana 1, e se
        # non la dichiara la migliore delle quattro settimane misurate prima.
        # Non la media di quelle quattro: le settimane prima del blocco del 26
        # ottobre 2026 facevano 28.05 km di media e la settimana 1 ne chiede
        # 26, quindi il piano partirebbe a -11% su se stesso. E quella media
        # dipende da quante settimane indietro si guarda, cioe' da una
        # costante che nessuno ha motivo di scegliere.
        "volume": planned["volume"][0],
        "long_run": planned["long_run"][0],
        "race_pace": None,
    }
    targets = {
        "volume": goal.get("peak_weekly_km"),
        "long_run": goal.get("distance_km"),
        "race_pace": goal.get("distance_km"),
    }
    panels = []
    for key in PANEL_KEYS:
        start = starts[key]
        if start is None:
            start = _baseline(activities, block_start, key, target_speed, race_pace)
        panel = _panel(
            key, start, targets[key], planned[key], done[key], block_weeks, measured_through
        )
        if panel is not None:
            panels.append(panel)
    return {
        "plan": block["slug"],
        "title": goal.get("title"),
        "race": goal.get("race"),
        "target_time": goal.get("target_time"),
        "target_speed_kmh": target_speed,
        "block_week": block["block_week"],
        "block_weeks": block_weeks,
        "weeks": calendar,
        "panels": panels,
    }


def adherence_payload(
    summary_dir: Path, activities: pd.DataFrame, monday: date, today: date | None = None
) -> dict[str, Any] | None:
    """L'aderenza di volume della settimana di `monday`, o `None` se quella
    settimana non ha un piano."""
    plan = load_week_plan(summary_dir, monday)
    if plan is None:
        return None
    planned = _planned_runs(plan)
    measures = adherence(_runs_of(activities, monday), planned, today)
    return {
        "week": monday,
        "plan": plan.get("plan"),
        "block_week": plan.get("block_week"),
        **measures,
    }
