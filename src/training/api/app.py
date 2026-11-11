"""L'API della pagina Day (todo 32). Tutto in sola lettura (`GET`), tranne il
terreno di un'attivita' a piedi (`PUT`, todo 35), il tipo di una corsa
(`PUT`, todo 36) e il tasto Refresh (`POST`, todo 41), che aggiorna i dati e
riscrive un report.

Lancio: `make api` (solo su 127.0.0.1: non c'e' ancora il login, e sono dati
di salute). La documentazione interattiva e' su `/docs`.

Gli endpoint sono sincroni: i calcoli (`db`, `run_chart`, `daily_data`) sono
codice bloccante, e FastAPI li serve su un pool di thread."""

import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from training.api import refresh
from training.api.cache import (
    invalidate,
    load_activities,
    load_health,
    race_pace_of,
    speed_samples_of,
)
from training.api.context import DIST_DIR, ICONS_DIR, REPO_ROOT, UserContext, get_user_context
from training.api.daily import daily_payload
from training.api.plans import (
    delete_plan,
    load_day_plan,
    load_plans,
    load_week_plan,
    planned_weeks,
    set_current,
    weeks_following,
)
from training.api.sections import DAILY, SECTIONS, WEEKLY
from training.api.sections import Report as Report_
from training.api.weekly import weekly_payload
from training.interface.block_data import (
    adherence_payload,
    block_of,
    block_payload,
    block_shape_payload,
)
from training.api.models import (
    Activity,
    ActivityDetail,
    Adherence,
    BlockProgress,
    BlockShape,
    ChartBin,
    ChartData,
    DailyData,
    DayPlan,
    EffectSeconds,
    Lap,
    LapList,
    Pause,
    Plan,
    PlanList,
    PlanSummary,
    RefreshStatus,
    Report,
    ReportSection,
    Route,
    RunTypeUpdate,
    Sport,
    PlannedWeeks,
    SportList,
    TerrainUpdate,
    TrendData,
    WeeklyData,
    WeeksFollowing,
    WeekTrendData,
    WeekPlan,
    ZoneBand,
)
from training.interface.daily_data import (
    TREND_DEFAULT_WEEKS,
    TREND_MAX_DAYS,
    TREND_MAX_WEEKS,
    TREND_MIN_DAYS,
    TREND_MIN_WEEKS,
    build_daily_data,
    fitness_on,
    trend_data,
    week_trend_data,
)
from training.interface.db import _clean
from training.interface.db import cache_state as db_cache_state
from training.interface.db import load_activity_laps, load_activity_records
from training.interface.health import load_lactate_threshold
from training.interface.report_text import parse_report, section_icon
from training.interface.run_chart import (
    EFFECTS,
    bins,
    effects,
    has_effects,
    pauses,
    run_analysis_chart,
    block_panel_charts,
    block_shape_spec,
    trend_panel_charts,
    week_trend_panel_charts,
    zone_bands,
    zone_bounds,
    zone_settings,
)
from training.interface.laps import session_laps
from training.interface.run_type import save_run_type_override
from training.interface.sports import REST_ICON_FILE, SPORT_ICON_FILES, has_distance, sport_label
from training.interface.terrain import save_terrain_override

# I giorni prima di `end` quando `start` non c'e': quattro settimane, `end`
# compreso.
DEFAULT_WINDOW_DAYS = 27

app = FastAPI(
    title="Training API",
    description=(
        "Read-only access to activities, charts, daily data and daily reports. "
        "The only writes are the terrain of an on-foot activity, the type of a run "
        "and the Refresh job, which downloads new data and rewrites a daily report."
    ),
    version="0.1.0",
)

Context = Annotated[UserContext, Depends(get_user_context)]

# Le icone degli sport e delle sezioni dei report, in sola lettura: le
# risposte danno solo il nome del file, e il frontend lo chiede qui.
#
# Con la guardia come per `dist/` qui sotto: `StaticFiles` su una cartella che
# non c'e' alza all'import, quindi un clone senza `icons/` non lasciava senza
# icone — lasciava senza API, perche' uvicorn non partiva affatto.
if ICONS_DIR.is_dir():
    app.mount("/icons", StaticFiles(directory=ICONS_DIR), name="icons")


def _report(found: list, subject: date, missing: str) -> Report:
    """Il report dalle sue sezioni, o 404.

    **Una cartella che esiste ma non ha ancora un frammento scritto vale come
    un report che non c'e'**: le sezioni vuote da sole non sono un report.
    Giorno e settimana avevano la stessa coda, parola per parola, e cambiarla
    per uno solo dei due e' il modo in cui le due pagine divergono."""
    if not any(body for _, body, _written, _verdict in found):
        raise HTTPException(status_code=404, detail=missing)
    return Report(
        day=subject,
        sections=[
            ReportSection(
                title=title,
                body=body,
                icon=section_icon(title) if title else None,
                written_at=written,
                verdict=verdict,
            )
            for title, body, written, verdict in found
        ],
    )


def _records_dicts(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    """Le righe di `frame`, solo `columns`, con `None` al posto di `NaN`."""
    return [{col: _clean(row[col]) for col in columns} for _, row in frame.iterrows()]


# Quello che la pagina non deve vedere degli sport senza distanza (todo 45):
# la distanza che il polso ha stimato e tutto quello che ne discende. Il
# database le tiene, cosi' se un giorno arriva un sensore calibrato il dato
# vecchio e' ancora li'; la pagina al loro posto mostra le calorie.
_DISTANCE_FIELDS = ("total_distance_km", "avg_speed_kmh", "equiv_speed_kmh")


def _activity_fields(row: pd.Series) -> dict[str, Any]:
    fields = {name: _clean(row[name]) for name in Activity.model_fields if name != "start_time"}
    fields["start_time"] = row["start_time"].to_pydatetime()
    if not has_distance(row["sport"]):
        fields.update(dict.fromkeys(_DISTANCE_FIELDS))
    return fields


def _activity_row(activity_id: int, ctx: UserContext) -> pd.Series:
    """La riga di `list_activities` dell'attivita', o 404."""
    activities = load_activities(ctx.data_dir)
    match = activities[activities["activity_id"] == activity_id]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Activity {activity_id} not found.")
    return match.iloc[0]


@app.get("/api/activities", response_model=list[Activity], summary="List activities")
def get_activities(
    ctx: Context,
    start: Annotated[date | None, Query(description="First day, included. Default: 27 days before `end`.")] = None,
    end: Annotated[date | None, Query(description="Last day, included. Default: today.")] = None,
    sport: Annotated[list[str] | None, Query(description="Keep only these sports. Repeatable.")] = None,
) -> list[Activity]:
    """Activities whose start day falls between `start` and `end`, most recent first."""
    end = end or date.today()
    start = start or end - timedelta(days=DEFAULT_WINDOW_DAYS)
    if start > end:
        raise HTTPException(status_code=422, detail="`start` must not be after `end`.")
    activities = load_activities(ctx.data_dir)
    days = activities["start_time"].dt.date
    selected = activities[(days >= start) & (days <= end)]
    if sport:
        selected = selected[selected["sport"].isin(sport)]
    selected = selected.sort_values("start_time", ascending=False)
    return [Activity(**_activity_fields(row)) for _, row in selected.iterrows()]


@app.get("/api/sports", response_model=SportList, summary="List sports")
def get_sports(ctx: Context) -> SportList:
    """The sports found in the activities, sorted by key, with their label and icon."""
    activities = load_activities(ctx.data_dir)
    return SportList(
        sports=[
            Sport(sport=sport, label=sport_label(sport), icon=SPORT_ICON_FILES.get(sport))
            for sport in sorted(activities["sport"].dropna().unique())
        ],
        rest_icon=REST_ICON_FILE,
    )


@app.get("/api/activities/{activity_id}", response_model=ActivityDetail, summary="Activity detail")
def get_activity(activity_id: int, ctx: Context) -> ActivityDetail:
    """One activity, with its heart-rate zones, threshold and estimated time per training effect."""
    row = _activity_row(activity_id, ctx)
    # `zone_settings` da' i tetti delle zone e la soglia **da usare** per
    # dividere lo sforzo, che possono essere prestati da un'altra seduta:
    # servono agli effetti qui sotto. Nella risposta invece il misurato e il
    # prestato restano separati, perche' dire che una pedalata ha misurato le
    # zone e la soglia di una corsa e' una bugia.
    bounds, threshold = zone_settings(row)
    effect_seconds = None
    if has_effects(bounds, threshold):
        records = load_activity_records(activity_id, ctx.data_dir)
        if not records.empty and records["heart_rate"].notna().any():
            seconds = effects(records, bounds, threshold)
            effect_seconds = EffectSeconds(
                low_aerobic_s=seconds[EFFECTS[0]],
                high_aerobic_s=seconds[EFFECTS[1]],
                anaerobic_s=seconds[EFFECTS[2]],
            )
    measured = _clean(row["threshold_hr"])
    return ActivityDetail(
        **_activity_fields(row),
        hr_zone_bounds=zone_bounds(_clean(row["hr_zone_bounds"])),
        hr_zone_bounds_borrowed=zone_bounds(_clean(row["hr_zone_bounds_borrowed"])),
        threshold_hr=measured if measured else None,
        threshold_hr_borrowed=_clean(row["threshold_hr_borrowed"]),
        effect_seconds=effect_seconds,
    )


@app.put("/api/activities/{activity_id}/terrain", response_model=Activity, summary="Set the terrain")
def put_activity_terrain(activity_id: int, update: TerrainUpdate, ctx: Context) -> Activity:
    """Set the terrain of an on-foot activity, or clear it with `null` to go back to the guess.

    422 for activities without a terrain (sports other than running, walking and hiking,
    and treadmill runs)."""
    row = _activity_row(activity_id, ctx)
    if _clean(row["terrain_source"]) is None:
        raise HTTPException(status_code=422, detail=f"Activity {activity_id} has no terrain.")
    save_terrain_override(ctx.data_dir, activity_id, update.terrain)
    invalidate(ctx.data_dir)
    return Activity(**_activity_fields(_activity_row(activity_id, ctx)))


@app.put("/api/activities/{activity_id}/run_type", response_model=Activity, summary="Set the run type")
def put_activity_run_type(activity_id: int, update: RunTypeUpdate, ctx: Context) -> Activity:
    """Set the type of a run, or clear it with `null` to go back to the guess.

    422 for activities that are not runs."""
    row = _activity_row(activity_id, ctx)
    if _clean(row["run_type_source"]) is None:
        raise HTTPException(status_code=422, detail=f"Activity {activity_id} is not a run.")
    save_run_type_override(ctx.data_dir, activity_id, update.run_type)
    invalidate(ctx.data_dir)
    return Activity(**_activity_fields(_activity_row(activity_id, ctx)))


@app.get("/api/activities/{activity_id}/chart", response_model=ChartData, summary="Activity chart data")
def get_activity_chart(activity_id: int, ctx: Context) -> ChartData:
    """The data of the activity chart: 30-second bins, heart-rate zone bands and pauses.

    Empty lists when the activity has no sampled data."""
    row = _activity_row(activity_id, ctx)
    bounds, threshold = zone_settings(row)
    records = load_activity_records(activity_id, ctx.data_dir)
    if records.empty:
        return ChartData(bins=[], zone_bands=[], pauses=[], hr_zone_bounds=bounds, threshold_hr=threshold)
    bands = zone_bands(records, bounds) if bounds else pd.DataFrame()
    binned = bins(records)
    # Gli sport senza distanza (il tapis roulant, todo 45) non hanno una
    # velocita' da dare: quella nei record e' la stima del polso, che il
    # grafico di riferimento non disegna (`run_chart.py`, `has_speed`) e che
    # le schede e i giri non mostrano. Qui usciva comunque: 107 punti fino a
    # 9.55 km/h su una camminata al tapis roulant, e 23 attivita' cosi'.
    if not has_distance(row["sport"]):
        binned = binned.assign(speed=None, equiv=None)
    return ChartData(
        bins=[ChartBin(**r) for r in _records_dicts(binned, list(ChartBin.model_fields))],
        zone_bands=[ZoneBand(**r) for r in _records_dicts(bands, list(ZoneBand.model_fields))],
        pauses=[Pause(start=a, end=b) for a, b in pauses(records)],
        hr_zone_bounds=bounds,
        threshold_hr=threshold,
    )


@app.get("/api/activities/{activity_id}/chart/vega", summary="Activity chart, Vega-Lite")
def get_activity_chart_vega(
    activity_id: int,
    ctx: Context,
    theme: Literal["light", "dark"] = "light",
) -> dict[str, Any]:
    """The activity chart as a ready-to-render Vega-Lite specification."""
    row = _activity_row(activity_id, ctx)
    bounds, threshold = zone_settings(row)
    records = load_activity_records(activity_id, ctx.data_dir)
    chart = run_analysis_chart(records, bounds, threshold, theme, _clean(row["sport"]))
    if chart is None:
        raise HTTPException(status_code=404, detail="Nothing to plot for this activity.")
    return chart.to_dict()


@app.get("/api/activities/{activity_id}/route", response_model=Route, summary="Activity route")
def get_activity_route(
    activity_id: int,
    ctx: Context,
    max_points: Annotated[int, Query(ge=2, description="Upper limit on the number of points.")] = 2000,
) -> Route:
    """The GPS track as [lat, lon] pairs. Longer tracks keep one point every N, always
    including the first and the last. Empty when the activity has no position."""
    _activity_row(activity_id, ctx)
    records = load_activity_records(activity_id, ctx.data_dir)
    if records.empty:
        return Route(points=[])
    points = records[["lat", "lon"]].dropna().to_numpy()
    if len(points) > max_points:
        # Indici distribuiti sull'intero percorso, primo e ultimo compresi:
        # con il passo arrotondato all'intero in su, chiedendone 2000 su 2001
        # punti il passo diventava 2 e tornavano 1001, cioe' meta' della
        # risoluzione chiesta. Qui ne tornano esattamente `max_points`.
        keep = np.unique(np.linspace(0, len(points) - 1, max_points).round().astype(int))
        points = points[keep]
    return Route(points=[(float(lat), float(lon)) for lat, lon in points])


@app.get("/api/activities/{activity_id}/laps", response_model=LapList, summary="Activity laps")
def get_activity_laps(activity_id: int, ctx: Context) -> LapList:
    """The laps of the session, named one by one (todo 79): the warm-up, the reps, the
    recoveries, the cool-down.

    Only for a session the watch ran as a workout (`structured`); for a free run the laps are
    the auto-lap every kilometre and the list is empty. The pace is missing where the distance
    is the wrist's guess (the treadmill)."""
    row = _activity_row(activity_id, ctx)
    laps = load_activity_laps(activity_id, ctx.data_dir)
    payload = session_laps(laps, _clean(row["sport"]))
    return LapList(structured=payload["structured"], laps=[Lap(**lap) for lap in payload["laps"]])


def _trend_window(start: date, end: date) -> int:
    """L'ampiezza della finestra in giorni, o 422 se gli estremi non stanno
    in piedi. Stesso stile del lunedi' di `/api/weekly/{monday}`: la pagina
    non deve poter chiedere una finestra che non si disegna."""
    if start > end:
        raise HTTPException(status_code=422, detail=f"{start} comes after {end}.")
    if end > date.today():
        raise HTTPException(status_code=422, detail=f"{end} is in the future.")
    days = (end - start).days + 1
    if not TREND_MIN_DAYS <= days <= TREND_MAX_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"The window is {days} days: it must be between {TREND_MIN_DAYS} and {TREND_MAX_DAYS}.",
        )
    return days


# Prima di `/api/daily/{day}`: le rotte si provano nell'ordine in cui sono
# scritte, e "trend" finirebbe dentro `{day}` come data non valida.
@app.get("/api/daily/trend", response_model=TrendData, summary="Daily trend series")
def get_daily_trend(
    ctx: Context,
    start: Annotated[date, Query(alias="from", description="First day, included.")],
    end: Annotated[date, Query(alias="to", description="Last day, included.")],
) -> TrendData:
    """The daily series between two days, panel by panel, each with its band (todo 55).

    The window is the one the Day cards already compare against, drawn instead of told.
    It must be between 5 and 365 days wide."""
    _trend_window(start, end)
    data = trend_data(start, end, ctx.data_dir, load_activities(ctx.data_dir), load_health(ctx.data_dir))
    return TrendData(**data)


@app.get("/api/daily/trend/charts/vega", summary="Daily trend charts, Vega-Lite")
def get_daily_trend_charts(
    ctx: Context,
    start: Annotated[date, Query(alias="from", description="First day, included.")],
    end: Annotated[date, Query(alias="to", description="Last day, included.")],
    theme: Literal["light", "dark"] = "light",
) -> list[dict[str, Any]]:
    """The charts of **every** panel, ready to render: one Vega-Lite specification per
    measure, grouped by panel (`[{key, charts: [{key, label, spec}]}]`).

    One chart per measure and not per panel: inside a panel the measures do not share a
    unit, and on a single axis the small one would read flat.

    All five panels in one answer, because the page draws all five: a request per panel
    made the window behind the series five times over and had the five Altair runs fight
    for the GIL in the server's threads. Measured on the live archive, one Trend view went
    from 2.9 s of wall clock to about 0.8."""
    days = _trend_window(start, end)
    data = trend_data(start, end, ctx.data_dir, load_activities(ctx.data_dir), load_health(ctx.data_dir))
    return [
        {"key": panel["key"], "charts": trend_panel_charts(panel, days, theme)}
        for panel in data["panels"]
    ]


@app.get("/api/daily/{day}", response_model=DailyData, summary="Daily data")
def get_daily(day: date, ctx: Context) -> DailyData:
    """Everything known about one day (training, recovery, health, load), as built for the
    daily report."""
    if day > date.today():
        raise HTTPException(status_code=422, detail=f"{day} is in the future.")
    # Gli stessi fatti che l'orchestratore del Refresh mette nel file degli
    # agenti: una strada sola, cosi' la pagina e chi scrive il testo vedono
    # le stesse cose.
    return DailyData(**daily_payload(day, ctx.data_dir))


@app.get("/api/daily/{day}/plan", response_model=DayPlan, summary="Daily plan")
def get_day_plan(day: date, ctx: Context) -> DayPlan:
    """The session planned for one day, from the plan of its week (todo 63): the fields of
    the front matter entry, plus that day's row of the plan's table.

    A day with no planned session is a 404 and not an error — the days outside a block do
    not have one, and neither do the weeks whose file predates the front matter. A day in
    the future is allowed, unlike `/api/daily/{day}`: a block is written in advance, and
    the plan of a day that has not come is the normal case."""
    plan = load_day_plan(ctx.summary_dir, day)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"No plan for {day}.")
    return DayPlan(**{name: plan[name] for name in DayPlan.model_fields})


def _week_monday(monday: date) -> None:
    """Il lunedi' di una settimana che si puo' chiedere, o 422. La settimana in
    corso si guarda - e' il caso normale - quella che non e' ancora cominciata
    no.

    Stava dentro `get_weekly`; e' uscita quando le rotte del Trend della Week
    (todo 78) hanno avuto bisogno degli stessi due controlli, perche' le tre
    non possano divergere. `get_week_plan` tiene il suo: il piano di una
    settimana futura e' legittimo."""
    if monday.weekday() != 0:
        raise HTTPException(status_code=422, detail=f"{monday} is not a Monday.")
    if monday > date.today():
        raise HTTPException(status_code=422, detail=f"The week of {monday} has not started.")


# Le due rotte del Trend della Week stanno **prima** di `/api/weekly/{monday}`,
# per lo stesso motivo di `/api/daily/trend` (todo 55): le rotte si provano
# nell'ordine in cui sono scritte, e "trend" finirebbe dentro `{monday}` come
# data non valida.
@app.get("/api/weekly/trend", response_model=WeekTrendData, summary="Weekly trend series")
def get_weekly_trend(
    ctx: Context,
    to: Annotated[date, Query(description="The Monday of the last week, included.")],
    weeks: Annotated[
        int,
        Query(
            ge=TREND_MIN_WEEKS,
            le=TREND_MAX_WEEKS,
            description="Width of the window, in weeks.",
        ),
    ] = TREND_DEFAULT_WEEKS,
) -> WeekTrendData:
    """The weekly series over a window of ISO weeks, panel by panel (todo 78).

    One point per week: the mean of the week's measured days on Health, Recovery, Load and
    Fitness, the sum on Training. Each week carries a band — the mean plus and minus one and
    two standard errors. The variance behind them is pooled over the whole window, the mean
    of the within-week variances, and each week divides its square root by the root of its
    own measured days: the band widens where the average rests on fewer days. A week with
    fewer than `min_week_days` measured days shows none.

    Unlike `/api/weekly/{monday}`, load and fitness are means of the week's days and not
    the state at its end: one rule for every panel, so the lines compare.

    The last week may still be running: its mean is made of fewer days and its totals are
    partial, and every point says how many days are behind it."""
    _week_monday(to)
    first = to - timedelta(weeks=weeks - 1)
    return WeekTrendData(
        **week_trend_data(first, to, ctx.data_dir, load_activities(ctx.data_dir), load_health(ctx.data_dir))
    )


@app.get("/api/weekly/trend/charts/vega", summary="Weekly trend charts, Vega-Lite")
def get_weekly_trend_charts(
    ctx: Context,
    to: Annotated[date, Query(description="The Monday of the last week, included.")],
    weeks: Annotated[
        int, Query(ge=TREND_MIN_WEEKS, le=TREND_MAX_WEEKS, description="Width of the window, in weeks.")
    ] = TREND_DEFAULT_WEEKS,
    theme: Literal["light", "dark"] = "light",
) -> list[dict[str, Any]]:
    """The charts of every weekly panel, one Vega-Lite spec per measure, grouped by panel
    (todo 78).

    Four panels draw a line with its band underneath, as two areas and not the two
    full-width rectangles of the Day: here the band changes from week to week, with how many
    days each average rests on. Training draws **bars**, because a weekly sum is a quantity,
    and carries no band.

    All five in one answer, for the reason given on the daily one."""
    _week_monday(to)
    first = to - timedelta(weeks=weeks - 1)
    data = week_trend_data(first, to, ctx.data_dir, load_activities(ctx.data_dir), load_health(ctx.data_dir))
    return [
        {"key": panel["key"], "charts": week_trend_panel_charts(panel, weeks, theme)}
        for panel in data["panels"]
    ]


@app.get("/api/weekly/planned", response_model=PlannedWeeks, summary="Weeks with a plan")
def get_planned_weeks(ctx: Context) -> PlannedWeeks:
    """The Mondays of the weeks that have a written plan in `summary/05.plan/`, oldest first.

    This is how far the Week page lets you walk forward (todo 88): past the last planned week
    there is nothing to look at, and an arrow that lights up on empty weeks is an arrow that
    lies. No plans means no forward, which is the right answer and not a failure.

    The Monday is the **file name**, which is the rule of the format
    (`summary/05.plan/README.md`), so a file whose front matter cannot be read still counts:
    if the file is there, the week can be looked at.

    **Declared before `/api/weekly/{monday}`**, or the path would be read as a date and
    answered with a 422.

    It does not come from the block of the current goal (`block_start` + `block_weeks` in
    `/api/plans`): that is what the goal *declares*, and the two diverge — changing goal
    leaves the written weeks where they were (todo 86). The boundary is the files that exist."""
    return PlannedWeeks(weeks=planned_weeks(ctx.summary_dir))


@app.get("/api/weekly/{monday}", response_model=WeeklyData, summary="Weekly data")
def get_weekly(monday: date, ctx: Context) -> WeeklyData:
    """Everything known about one ISO week, Monday to Sunday (todo 52).

    The Health and Recovery measures are averages of the seven days, each with the band it
    has moved in over the last twelve weeks; load and fitness are the state at the end of
    the week, which is today for a week still running."""
    _week_monday(monday)
    data = weekly_payload(monday, ctx.data_dir)
    return WeeklyData(**{name: data[name] for name in WeeklyData.model_fields})


# Le tre rotte del blocco (todo 96) stanno **dopo** `/api/weekly/{monday}` e
# non prima, a differenza di quelle del Trend: hanno due segmenti o piu', e un
# percorso di due segmenti non puo' finire dentro uno di uno. La guardia e'
# quella di `get_week_plan` e non `_week_monday`, per la stessa ragione: una
# settimana futura e' legittima qui, che il blocco e' scritto in anticipo e la
# vista Training si apre anche in avanti (todo 88).
def _plan_monday(monday: date) -> None:
    """Il lunedi' di una settimana di cui si puo' chiedere il piano."""
    if monday.weekday() != 0:
        raise HTTPException(status_code=422, detail=f"{monday} is not a Monday.")


def _block(monday: date, ctx: UserContext) -> dict[str, Any]:
    """I dati del blocco della settimana, o 404."""
    _plan_monday(monday)
    data = block_payload(
        ctx.summary_dir,
        ctx.plan_dir,
        load_activities(ctx.data_dir),
        monday,
        lambda activity_id, target: race_pace_of(ctx.data_dir, activity_id, target),
    )
    if data is None:
        raise HTTPException(
            status_code=404, detail=f"The week of {monday} is not part of a block."
        )
    return data


@app.get("/api/weekly/{monday}/block", response_model=BlockProgress, summary="Block progress")
def get_block(monday: date, ctx: Context) -> BlockProgress:
    """How far the block has carried you, week by week (todo 96) — the **response**, which is
    not the adherence: this says whether the plan is working, `/adherence` says whether you are
    following it. `docs/aderenza.md` keeps them apart on purpose.

    Three KPIs — weekly kilometres, the long run, and the longest continuous stretch at race
    pace — each as a percentage of what the race asks. Every week carries what the plan asked
    and what was done (the bars) and the best up to there (the line, a ratchet). The ratchet is
    not decoration: a block's planned kilometres are a saw, with four deliberate dips over
    eighteen weeks, and a line of weekly values would read as four collapses.

    A week outside any block is a 404 and not an error — the weeks before the block started
    have no file. A Monday in the future is allowed, as for the plan."""
    data = _block(monday, ctx)
    return BlockProgress(**{name: data[name] for name in BlockProgress.model_fields})


@app.get("/api/weekly/{monday}/block/charts/vega", summary="Block charts, Vega-Lite")
def get_block_charts(
    monday: date, ctx: Context, theme: Literal["light", "dark"] = "light"
) -> list[dict[str, Any]]:
    """One Vega-Lite spec per KPI, all three in one answer (todo 96).

    Plural like the trend's, and for the same reason: three panels that are drawn together or
    are not compared. They share the y domain, declared and identical — three separate specs
    would each compute their own, and two panels side by side with two scales are compared
    **wrongly**."""
    data = _block(monday, ctx)
    return block_panel_charts(data, theme)


def _week_comment_written(monday: date, ctx: UserContext) -> bool:
    """Se il commento della settimana c'e', cioe' se la settimana e' stata
    **chiusa**: il frammento `training` del report settimanale, scritto dal
    giro della domenica alle 21.

    E' quello che decide se il grafico del blocco si vede (vedi
    `_week_shape`), e si guarda questa sezione e non la cartella perche' il
    commento e' quella: e' il riquadro che sta sopra il grafico nella pagina,
    e il grafico arriva con lui."""
    folder = ctx.summary_dir / WEEKLY.folder / monday.isoformat()
    path = _fragment_path(folder, "training", WEEKLY)
    return path.exists() and path.stat().st_size > 0


def _week_shape(monday: date, ctx: UserContext) -> dict[str, Any]:
    """La forma del blocco a cui la settimana appartiene, tagliata a quella
    settimana, o 404."""
    _plan_monday(monday)
    block = block_of(ctx.summary_dir, monday)
    if block is None:
        raise HTTPException(
            status_code=404, detail=f"The week of {monday} is not part of a block."
        )
    # **Niente grafico prima che la settimana sia chiusa.** Il punto di una
    # settimana e' quello di sette giorni, e fino a domenica sera non c'e':
    # arriva col report, cioe' col commento, che il giro della domenica alle
    # 21 scrive. Prima di allora il disegno direbbe una settimana a meta' e
    # cambierebbe a ogni apertura della pagina, che e' esattamente quello che
    # `partial` evita per il punto dei chilometri.
    #
    # Il confine e' il commento e non l'orologio: se la domenica sera il giro
    # non gira, la settimana non e' chiusa e il grafico non c'e' — e appare
    # da se' appena quel testo viene scritto, anche a mano dal tasto della
    # card.
    if not _week_comment_written(monday, ctx):
        raise HTTPException(
            status_code=404,
            detail=f"The week of {monday} has no comment yet: the block arrives with the "
            "weekly report, on Sunday evening.",
        )
    data = block_shape_payload(
        ctx.summary_dir,
        ctx.plan_dir,
        load_activities(ctx.data_dir),
        block["slug"],
        lambda activity_id: speed_samples_of(ctx.data_dir, activity_id),
        until=monday,
    )
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"No block for the week of {monday}: the goal {block['slug']!r} is gone "
            "from plan/, so there are no targets to read it against.",
        )
    return data


@app.get("/api/weekly/{monday}/shape", response_model=BlockShape, summary="The block of a week")
def get_week_shape(monday: date, ctx: Context) -> BlockShape:
    """The block this week belongs to, week by week: the kilometres the plan asked for, the
    kilometres run, and how the equivalent speed of each week is spread.

    The same reading as `/api/plans/<slug>/block`, **keyed by the week and cut at it**: the
    goal is the one the week's file declares (`plan:` in `summary/05.plan/<monday>.md`), and
    nothing after this Monday is measured. So the answer for a past week is the block as it
    stood at the end of that week.

    **Only a closed week has one.** The answer arrives with the week's comment — the
    `training` section of its report, written by the Sunday 21:00 run — and before that it is
    a 404: a block is read once a week, not live, and half a week drawn as a week is the thing
    `partial` already refuses to do for the kilometres. The gate is the comment and not the
    clock, so a week whose Sunday run did not run has no chart until that text exists, by
    timer or by the card's own button.

    404, then, when the week has no plan file, when its plan declares no goal, when that goal
    is gone from `plan/`, or when the week has not been commented yet — none of the four is an
    error, they are states. A Monday in the future is allowed, as for `/plan`, and answers 404
    for the same reason as this week: nobody has commented it."""
    data = _week_shape(monday, ctx)
    return BlockShape(**{name: data[name] for name in BlockShape.model_fields})


@app.get("/api/weekly/{monday}/shape/chart/vega", summary="The block of a week, Vega-Lite")
def get_week_shape_chart(
    monday: date, ctx: Context, theme: Literal["light", "dark"] = "light"
) -> dict[str, Any]:
    """One Vega-Lite spec of `/shape`: the kilometres on the left axis, the spread of speed on
    the right. This is what the Training view of the Week draws, under the week's work — and
    only for a week that has been closed and commented, like `/shape` itself.

    Singular, unlike the three panels of `/api/weekly/<monday>/block/charts/vega`: here the
    two readings are drawn **together on purpose**, because the week that ran the most
    kilometres is also a week run at some pace, and two stacked panels would make the eye
    jump."""
    return block_shape_spec(_week_shape(monday, ctx), theme)


@app.get("/api/weekly/{monday}/adherence", response_model=Adherence, summary="Weekly adherence")
def get_adherence(monday: date, ctx: Context) -> Adherence:
    """How well the week was executed against its plan (todo 96) — the **adherence**.

    Session by session, `s_vol = max(0, 1 - |ln r| / ln 2)` on the kilometres: one on target,
    zero at half or double, symmetric in log scale, so overshooting weighs as much as falling
    short. The week is their mean weighted by the planned kilometres, with long and quality
    sessions counting double. Beside it, always, the ratio of kilometres run to kilometres
    asked — adherence says *how* you executed, the ratio says whether you were over or under.

    A week with no plan file is a 404, like `/plan`."""
    _plan_monday(monday)
    data = adherence_payload(ctx.summary_dir, load_activities(ctx.data_dir), monday)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No plan for the week of {monday}.")
    return Adherence(**{name: data[name] for name in Adherence.model_fields})


@app.get("/api/weekly/{monday}/plan", response_model=WeekPlan, summary="Weekly plan")
def get_week_plan(monday: date, ctx: Context) -> WeekPlan:
    """The plan of one week, from `summary/05.plan/<monday>.md` (todo 60): the sessions of
    the seven days, with the front matter numbers as fields and the rest as Markdown.

    A week with no file is a 404 and not an error: the weeks before the block started do
    not have one. Unlike the other weekly endpoints a Monday in the future is allowed —
    the plan of a week that has not begun is the normal case, and the whole block is
    written in advance."""
    if monday.weekday() != 0:
        raise HTTPException(status_code=422, detail=f"{monday} is not a Monday.")
    plan = load_week_plan(ctx.summary_dir, monday)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"No plan for the week of {monday}.")
    return WeekPlan(**{name: plan[name] for name in WeekPlan.model_fields})


def _fragment_path(folder: Path, key: str, kind: Report_) -> Path:
    """Il file del frammento, o il primo dei suoi nomi vecchi che esiste.

    I nomi vecchi stanno nel registro (`Report.old_fragments`), che e' dove
    si sa come si chiamavano le sezioni prima: il giorno ha perso il verdetto
    in due pezzi col todo 66, la settimana col todo 68, e i periodi scritti
    allora si leggono ancora."""
    path = folder / f"{key}.md"
    # Vuoto vale come assente: un frammento di zero byte col nome nuovo
    # copriva quello col nome vecchio, e la card restava bianca con il testo
    # di prima irraggiungibile. 89 periodi del giorno e 13 della settimana
    # hanno il Summary solo sotto un nome vecchio.
    if path.exists() and path.stat().st_size > 0:
        return path
    for old in kind.old_fragments.get(key, ()):
        legacy = folder / f"{old}.md"
        if legacy.exists() and legacy.stat().st_size > 0:
            return legacy
    return path


def _fragment_sections(
    folder: Path, kind: Report_ = DAILY
) -> list[tuple[str | None, str, datetime | None, str | None]]:
    """Le sezioni dai frammenti di una cartella (todo 44, 53): un file per
    sezione, nell'ordine in cui si leggono.

    **Le sezioni ci sono tutte, anche quelle senza frammento**, con il corpo
    vuoto. Il file manca quando il suo agente non ha ancora scritto o e'
    fallito, e quella e' una card senza testo, non una card senza nome: la
    pagina prende da qui anche il titolo e l'icona di ogni riquadro, e
    saltando la sezione le toglieva tutte e due. Si vedeva rifacendo una
    sola card su un giorno mai scritto: restava la sua, e le altre sei
    perdevano l'icona.

    Di ognuna si da' anche quando e' stata scritta, cioe' l'`mtime` del suo
    file: dal todo 47 le sezioni di uno stesso giorno portano ore diverse,
    perche' il giro della mattina ne scrive alcune e quello della sera altre,
    e la pagina lo dice sotto ogni testo.

    Niente testo senza titolo: la riga "Data: ..." del file unico la scartava
    gia' `parse_report`, quindi alla pagina non e' mai arrivata."""
    found: list[tuple[str | None, str, datetime | None, str | None]] = []
    for section in kind.sections:
        path = _fragment_path(folder, section.key, kind)
        body = path.read_text(encoding="utf-8").strip() if path.exists() else ""
        # Prima si toglie il verdetto, poi si guarda se e' rimasto del testo:
        # un frammento che contiene solo `verdict: high` non e' una sezione
        # scritta, e con l'ordine di prima prendeva l'ora e un corpo vuoto.
        #
        # E si toglie **solo a chi lo scrive**, che e' Training: sulle altre
        # quella riga non e' un voto, e' la prima frase del commento. Le due
        # meta' del patto — chiederlo e toglierlo — stanno in due moduli, e
        # la bandiera del registro e' quello che le tiene insieme (prima era
        # la stringa "training" battuta a mano in entrambi).
        verdict = None
        if section.writes_verdict:
            verdict, body = _verdict(body)
        written = datetime.fromtimestamp(path.stat().st_mtime) if body else None
        found.append((section.title, body, written, verdict))
    return found


# La prima riga di un frammento, quando l'agente ha dato un voto (todo 92):
# `verdict: high`. Solo in cima, e solo le cinque parole della scala — una
# riga che dice altro e' testo, e il testo non si tocca.
# La parola deve stare **da sola sulla sua riga**: `\b` non basterebbe, perche'
# fra "medium" e "-high" un confine di parola c'e'. Senza l'ancora, una frase
# che comincia per una delle cinque parole veniva mangiata: `verdict:
# medium-high` dava faccia "medium" e corpo "-high", e `verdict: high resting
# heart rate this week` perdeva tre parole. E spazi e tabulazioni, non `\s`,
# che comprende il fine riga e accettava la parola sulla riga dopo.
_VERDICT_LINE = re.compile(
    r"\A[ \t]*verdict[ \t]*:[ \t]*(terrible|low|medium|high|perfect)[ \t]*(?:\r?\n|\Z)",
    re.IGNORECASE,
)


def _verdict(body: str) -> tuple[str | None, str]:
    """Il voto scritto dall'agente e il corpo senza quella riga.

    La scrive la sola sezione Training (todo 92): le altre card prendono la
    faccia dai numeri. Qui si toglie prima che il testo arrivi alla pagina —
    se restasse, si leggerebbe come la prima frase del commento.

    I frammenti scritti prima non ce l'hanno: niente voto, nessuna faccia, e
    il corpo intero."""
    match = _VERDICT_LINE.match(body)
    if not match:
        return None, body
    return match.group(1).lower(), body[match.end() :].strip()


@app.get("/api/reports/daily/{day}", response_model=Report, summary="Daily report")
def get_daily_report(day: date, ctx: Context) -> Report:
    """The written daily report of `day`, split into its sections.

    Dal todo 44 ogni sezione e' un file suo in `01.daily/<giorno>/`, scritto
    dal suo agente. I giorni di prima hanno il file unico `<giorno>.md`, e si
    continuano a leggere da li'."""
    folder = ctx.summary_dir / DAILY.folder / day.isoformat()
    path = ctx.summary_dir / DAILY.folder / f"{day.isoformat()}.md"
    if folder.is_dir():
        found = _fragment_sections(folder)
    elif path.exists():
        # Il file unico l'ha scritto un agente solo, in una volta: le sue
        # sezioni portano tutte l'ora del file, e **nessuna ha un verdetto**
        # — la riga `verdict:` e' del todo 92, questi report sono di prima.
        # Il quarto posto va messo comunque: chi legge disfa quattro valori
        # (il todo 92 ha cambiato `_fragment_sections` e non questo ramo, e
        # da allora ogni giorno in formato vecchio rispondeva 500).
        written = datetime.fromtimestamp(path.stat().st_mtime)
        found = [(title, body, written, None) for title, body in parse_report(path)]
    else:
        raise HTTPException(status_code=404, detail=f"No daily report for {day}.")
    return _report(found, day, f"No daily report for {day}.")


@app.post(
    "/api/reports/daily/{day}/refresh",
    response_model=RefreshStatus,
    status_code=202,
    summary="Refresh data and rewrite the whole daily report",
)
def post_daily_refresh(day: date, ctx: Context) -> RefreshStatus:
    """Download new data from Garmin and rewrite every section of the daily report of
    `day`, in the background: one agent per section, one after another, so a few minutes.
    One job at a time: while one runs, this returns it and starts nothing. Follow it with
    `GET /api/refresh`."""
    if day > date.today():
        raise HTTPException(status_code=422, detail=f"{day} is in the future.")
    return RefreshStatus(**refresh.start(day, REPO_ROOT, ctx.summary_dir, ctx.data_dir))


@app.post(
    "/api/reports/daily/{day}/refresh/{section}",
    response_model=RefreshStatus,
    status_code=202,
    summary="Rewrite one section of the daily report",
)
def post_daily_refresh_section(day: date, section: str, ctx: Context) -> RefreshStatus:
    """Rewrite a single section: only its agent runs, the other sections keep the text they
    have. 422 for a section that does not exist."""
    if day > date.today():
        raise HTTPException(status_code=422, detail=f"{day} is in the future.")
    try:
        keys = refresh.section_keys(section)
    except KeyError:
        known = ", ".join(s.key for s in SECTIONS)
        raise HTTPException(status_code=422, detail=f"Unknown section {section!r}. Known: {known}.")
    return RefreshStatus(**refresh.start(day, REPO_ROOT, ctx.summary_dir, ctx.data_dir, keys))


@app.get("/api/reports/weekly/{monday}", response_model=Report, summary="Weekly report")
def get_weekly_report(monday: date, ctx: Context) -> Report:
    """The written weekly report of the week starting `monday`, split into its sections
    (todo 53).

    One file per section in `02.weekly/<monday>/`, written by its agent. The three old
    single-file reports of the previous format are not read: nobody writes them any more."""
    if monday.weekday() != 0:
        raise HTTPException(status_code=422, detail=f"{monday} is not a Monday.")
    folder = ctx.summary_dir / WEEKLY.folder / monday.isoformat()
    if not folder.is_dir():
        raise HTTPException(status_code=404, detail=f"No weekly report for {monday}.")
    found = _fragment_sections(folder, WEEKLY)
    return _report(found, monday, f"No weekly report for {monday}.")


@app.post(
    "/api/reports/weekly/{monday}/refresh",
    response_model=RefreshStatus,
    status_code=202,
    summary="Rewrite the whole weekly report",
)
def post_weekly_refresh(monday: date, ctx: Context) -> RefreshStatus:
    """Rewrite every section of the weekly report, in the background: one agent per
    section, one after another, so a few minutes. It does not download: the week is
    written on the data already here. One job at a time, daily ones included."""
    _week_monday(monday)
    return RefreshStatus(
        **refresh.start(monday, REPO_ROOT, ctx.summary_dir, ctx.data_dir, kind=WEEKLY)
    )


@app.post(
    "/api/reports/weekly/{monday}/refresh/{section}",
    response_model=RefreshStatus,
    status_code=202,
    summary="Rewrite one section of the weekly report",
)
def post_weekly_refresh_section(monday: date, section: str, ctx: Context) -> RefreshStatus:
    """Rewrite a single section of the week: only its agent runs, the other sections keep
    the text they have. 422 for a section that does not exist."""
    _week_monday(monday)
    try:
        keys = refresh.section_keys(section, kind=WEEKLY)
    except KeyError:
        known = ", ".join(WEEKLY.by_key)
        raise HTTPException(status_code=422, detail=f"Unknown section {section!r}. Known: {known}.")
    return RefreshStatus(
        **refresh.start(monday, REPO_ROOT, ctx.summary_dir, ctx.data_dir, keys, kind=WEEKLY)
    )




@app.get("/api/plans", response_model=PlanList, summary="List training plans")
def get_plans(ctx: Context) -> PlanList:
    """The training plans written by hand in `plan/`, the nearest race first, without their
    text.

    Every plan in the folder is listed, front matter or not: a plan the page cannot show is
    worse than a plan without its numbers.

    At most one carries `current`, the goal being followed right now (todo 84). The order does
    not put it first: the list is the calendar of what he means to do, and `current` is a badge
    on one of its rows.

    `ahead` says which goal the weekly plans from this Monday on were written from, so the page
    can tell when they no longer match the current one."""
    return _plan_list(ctx)


def _plan_list(ctx: UserContext) -> PlanList:
    """The list as the three plan endpoints return it: the two that change a goal answer with
    it too, so one call both acts and refreshes the page."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return PlanList(
        plans=[
            PlanSummary(**{name: plan[name] for name in PlanSummary.model_fields})
            for plan in load_plans(ctx.plan_dir)
        ],
        ahead=[
            WeeksFollowing(slug=slug, weeks=weeks)
            for slug, weeks in sorted(weeks_following(ctx.summary_dir, monday).items())
        ],
    )


@app.put("/api/plans/{slug}/current", response_model=PlanList, summary="Make a goal the current one")
def put_plan_current(slug: str, ctx: Context) -> PlanList:
    """Make this goal the current one: `current: true` goes into its file and leaves the others.

    Only the flag is written — the rest of the file is left byte for byte as the person wrote
    it, comments and key order included.

    **It does not regenerate the weekly plans.** There is a generator since todo 86 — `make
    week_plans`, one agent per week — but it writes ~3 h of agent runs over a whole block, so
    it is a command a person runs, not something a click sets off. The `ahead` field of the
    answer says how many weeks in `summary/05.plan/` still come from each goal, which is how
    the page tells you there is generating to do. 404 when no goal has that slug."""
    try:
        set_current(ctx.plan_dir, slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No plan named {slug!r}.")
    except ValueError as exc:
        # Un file col front matter illeggibile non si riscrive: meglio dirlo
        # che rovinare un documento scritto a mano (vedi `_set_current_flag`).
        raise HTTPException(status_code=409, detail=str(exc))
    return _plan_list(ctx)


@app.delete("/api/plans/{slug}", response_model=PlanList, summary="Delete a goal")
def delete_plan_file(slug: str, ctx: Context) -> PlanList:
    """Move this goal out of `plan/` and answer with the list that is left.

    **The file is moved to `plan/.trash/`, not removed**: a goal is a document a person wrote,
    this API has no login, and the page that calls this is reachable by the whole tailnet. The
    name carries the moment, so deleting twice never covers the first copy.

    Deleting the current goal is allowed and leaves no goal current — refusing would mean a
    goal one keeps only because it is flagged. The weekly plans that declared it keep saying so
    and are reported in `ahead`, pointing at a goal that is no longer in the folder.

    404 when no goal has that slug."""
    try:
        delete_plan(ctx.plan_dir, slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No plan named {slug!r}.")
    return _plan_list(ctx)


@app.get("/api/plans/{slug}", response_model=Plan, summary="Training plan")
def get_plan(slug: str, ctx: Context) -> Plan:
    """One training plan, with its Markdown text: the front matter and the title are not in
    it, they come back as fields.

    `slug` is the file name without `.md`, and it is looked up among the plans found, never
    joined onto a path: a slug cannot walk out of `plan/`."""
    for plan in load_plans(ctx.plan_dir):
        if plan["slug"] == slug:
            return Plan(**{name: plan[name] for name in Plan.model_fields})
    raise HTTPException(status_code=404, detail=f"No plan named {slug!r}.")


def _block_shape(slug: str, ctx: UserContext) -> dict[str, Any]:
    """Il blocco di un goal settimana per settimana, o 404."""
    data = block_shape_payload(
        ctx.summary_dir,
        ctx.plan_dir,
        load_activities(ctx.data_dir),
        slug,
        lambda activity_id: speed_samples_of(ctx.data_dir, activity_id),
    )
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"No block for {slug!r}: either the goal is gone or no written week declares it.",
        )
    return data


@app.get("/api/plans/{slug}/block", response_model=BlockShape, summary="The block of a goal")
def get_plan_block(slug: str, ctx: Context) -> BlockShape:
    """A goal's block, week by week: the kilometres the plan asked for, the kilometres run, and
    how the equivalent speed of each week is spread (five numbers: 5th, quartiles, 95th).

    This is **not** `/api/weekly/<monday>/block`, which answers in percentages of what the race
    asks over three KPIs. This one answers in kilometres and km/h — how the block actually
    moved, week by week — and is keyed by the goal, because a block lasts as long as the goal
    that declares it, not as long as a week.

    The week in progress comes back with `partial: true`: its kilometres are those run so far,
    so the chart leaves its point out of the line while still using its speed samples.

    404 when the goal is gone or no written week declares it — a goal just written has no block
    yet, and that is a state, not an error."""
    data = _block_shape(slug, ctx)
    return BlockShape(**{name: data[name] for name in BlockShape.model_fields})


@app.get("/api/plans/{slug}/block/chart/vega", summary="The block of a goal, Vega-Lite")
def get_plan_block_chart(
    slug: str, ctx: Context, theme: Literal["light", "dark"] = "light"
) -> dict[str, Any]:
    """One Vega-Lite spec: the kilometres on the left axis, the spread of speed on the right.

    Singular, unlike the three panels of `/api/weekly/<monday>/block/charts/vega`: here the two
    readings are drawn **together on purpose**, because the week that ran the most kilometres is
    also a week run at some pace, and two stacked panels would make the eye jump."""
    return block_shape_spec(_block_shape(slug, ctx), theme)


@app.get("/api/refresh", response_model=RefreshStatus, summary="Refresh job status")
def get_refresh(ctx: Context) -> RefreshStatus:
    """The state of the latest Refresh job, and whether the activity cache is current.

    The two travel together because both pages already poll this one route, and both already
    know how to show an `ok: false` with a message — that is how a failed download is told.
    A stale cache is the same kind of fact: what you are reading is true, and older than the
    code that computes it."""
    state = db_cache_state(ctx.data_dir)
    return RefreshStatus(**refresh.status(), cache=None if state["ok"] else state)


# La pagina compilata sotto `/`, **in fondo a tutto**: un mount su `/` prende
# qualunque percorso, e le rotte dichiarate prima di lui vincono solo perche'
# Starlette le prova in ordine. Spostarlo piu' su oscurerebbe `/api`.
#
# Serve al servizio di systemd (todo 82): cosi' la macchina ha un processo
# solo invece di uvicorn piu' vite, e la tailnet punta a una porta sola. In
# sviluppo non c'entra niente — `make frontend` resta vite su 5173, con il
# ricaricamento a caldo — e se `dist/` non c'e' il mount non si fa affatto:
# l'API funziona lo stesso e `/` rende 404 finche' non si lancia
# `make frontend_build`.
#
# `html=True` serve solo a far rendere `index.html` sulla radice: la pagina
# tiene il suo stato nella stringa di ricerca (`?period=`, vedi
# `navigation.ts`) e non ha percorsi veri, quindi non c'e' nessun fallback di
# history da gestire.
if DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="page")
