"""I modelli delle risposte dell'API.

Sono il contratto con il frontend: dall'OpenAPI che FastAPI ne ricava si
generano i tipi TypeScript. Per questo i nomi dei campi sono quelli delle
colonne di `activities` e `records`, e le descrizioni sono in inglese.

Un valore che manca e' `null`, mai `NaN` e mai `0`: la conversione la fa
chi costruisce il modello (`app.py`). Gli interi con buchi (`avg_heart_rate`)
arrivano da pandas come float, e qui sono `int | None`."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# I terreni di `interface/terrain.TERRAINS`, nello stesso ordine.
Terrain = Literal["track", "road", "gravel", "trail", "mountain"]
# I tipi di corsa di `interface/run_type.RUN_TYPES`, nello stesso ordine.
RunType = Literal["race", "intervals", "long", "tempo", "easy"]


class Activity(BaseModel):
    """One activity, as stored in the `activities` table."""

    activity_id: int
    sport: str | None
    sub_sport: str | None
    start_time: datetime = Field(description="Local time, no time zone.")
    activity_name: str | None
    total_distance_km: float | None
    total_time_min: float | None = Field(description="Elapsed time, pauses included.")
    total_ascent_m: float | None
    total_descent_m: float | None
    avg_speed_kmh: float | None = Field(description="Average speed over moving time.")
    equiv_speed_kmh: float | None = Field(description="Average grade-adjusted speed (on-foot sports).")
    avg_heart_rate: int | None
    max_heart_rate: int | None
    total_calories: int | None
    vo2max: float | None
    aerobic_te: float | None = Field(description="Garmin's aerobic Training Effect, 0-5.")
    anaerobic_te: float | None = Field(description="Garmin's anaerobic Training Effect, 0-5.")
    terrain: Terrain | None = Field(
        description="Terrain of on-foot activities: the user's choice, or else a guess. Null for other sports."
    )
    terrain_source: Literal["guess", "user"] | None = Field(
        description="Whether `terrain` is a guess or set by the user. Null when there is no terrain."
    )
    run_type: RunType | None = Field(
        description="Type of a run (race, intervals, long, tempo, easy): the user's choice, or else a guess "
        "from the planned workout and the duration. Null for sports other than running."
    )
    run_type_source: Literal["guess", "user"] | None = Field(
        description="Whether `run_type` is a guess or set by the user. Null when there is no run type."
    )


class RunTypeUpdate(BaseModel):
    """The run type chosen by the user for one run."""

    run_type: RunType | None = Field(description="Null clears the choice and goes back to the guess.")


class TerrainUpdate(BaseModel):
    """The terrain chosen by the user for one activity."""

    terrain: Terrain | None = Field(description="Null clears the choice and goes back to the guess.")


class EffectSeconds(BaseModel):
    """Seconds spent in each training effect, estimated from heart rate."""

    low_aerobic_s: float
    high_aerobic_s: float
    anaerobic_s: float


class ActivityDetail(Activity):
    """One activity with its heart-rate settings and estimated effects."""

    hr_zone_bounds: list[int] | None = Field(description="Upper limits of zones Z1-Z4, in bpm.")
    threshold_hr: int | None = Field(description="Anaerobic threshold, in bpm.")
    effect_seconds: EffectSeconds | None = Field(
        description="Null when the zones, the threshold or the heart rate are missing."
    )


class ChartBin(BaseModel):
    """One 30-second interval of the activity chart. Times in minutes from the start."""

    start: float
    end: float
    minute: float = Field(description="Middle of the interval.")
    hr: float | None
    speed: float | None = Field(description="Speed, smoothed over 30 s, in km/h.")
    equiv: float | None = Field(description="Grade-adjusted speed, in km/h.")
    slope_pct: float | None
    slope_deg: float | None


class ZoneBand(BaseModel):
    """A stretch of time in one heart-rate zone. Times in minutes from the start."""

    start: float
    end: float
    zone: int = Field(description="Heart-rate zone, 1-5.")
    hr: float = Field(description="Average heart rate in the band, in bpm.")


class Pause(BaseModel):
    """A pause in the recording. Times in minutes from the start."""

    start: float
    end: float


class ChartData(BaseModel):
    """The data behind the activity chart, for clients that draw it themselves."""

    bins: list[ChartBin]
    zone_bands: list[ZoneBand]
    pauses: list[Pause]
    hr_zone_bounds: list[int] | None
    threshold_hr: int | None


class Lap(BaseModel):
    """One lap of a structured session: a warm-up, a rep, a recovery (todo 79)."""

    index: int = Field(description="Position in the session, from 0.")
    label: str = Field(description='What the lap was: "Warm-up", "Rep 1", "Recovery", "Cool-down".')
    intensity: str | None = Field(description="The FIT intensity: active, rest, recovery, warmup, cooldown.")
    workout_step: int | None = Field(description="The step of the workout the watch was following.")
    time_s: float | None
    distance_m: float | None = Field(description="Null for sports without a distance (the treadmill).")
    pace_s_per_km: float | None = Field(description="Seconds per km. Null where there is no distance.")
    avg_hr: int | None
    max_hr: int | None


class LapList(BaseModel):
    """The laps of an activity, when they say something (todo 79).

    `structured` is true only when the watch was following a workout: then the laps are the
    pieces the session was made of. A free run's laps are the auto-lap every kilometre, and
    the list comes back empty.
    """

    structured: bool
    laps: list[Lap]


class Route(BaseModel):
    """The GPS track of an activity."""

    points: list[tuple[float, float]] = Field(description="[lat, lon] pairs, in recording order.")


class ReportSection(BaseModel):
    title: str | None = Field(description="Null for the text before the first section.")
    body: str = Field(description="Markdown.")
    verdict: Verdict | None = Field(
        default=None,
        description="How the section's agent judged it, from a `verdict:` line at the top of "
        "its fragment (todo 92). Only the Training section writes one; the other cards get "
        "their face from the numbers, in `scores`. Null on the reports written before.",
    )
    icon: str | None = Field(description="Icon file name, served under /icons. Null when the section has none.")
    written_at: datetime | None = Field(
        default=None,
        description="When this section's text was written. Sections of the same day can carry "
        "different times: the morning job writes some, the evening job others.",
    )


class Report(BaseModel):
    """A written report, split into its sections: one day, or one ISO week."""

    day: date = Field(description="The day, or the Monday of the week (todo 53).")
    sections: list[ReportSection]


class SectionRefresh(BaseModel):
    """How the agent of one section fared in the latest job."""

    status: Literal["idle", "running", "done", "failed"] = Field(
        description="idle until this section is rewritten for the first time since the API started."
    )
    started: datetime | None
    finished: datetime | None
    message: str | None = Field(
        description="Why this section failed; it then kept the text it had. Null otherwise."
    )


class Download(BaseModel):
    """How the download from Garmin fared at the start of a job."""

    ok: bool
    message: str | None = Field(description="Why it failed. Null when it worked.")


class RefreshStatus(BaseModel):
    """A job that rewrites a report: the Day page's Refresh button, the Week page's, or a
    cron run.

    One agent per section, run one after another (todo 44), so a section can fail on its
    own while the others are rewritten. One job at a time, whatever its kind."""

    status: Literal["idle", "running", "done", "failed"] = Field(
        description="idle until the first job since the API started. failed when any section did."
    )
    kind: Literal["daily", "weekly"] = Field(
        default="daily",
        description="Which report the job writes. The section keys depend on it, so a page "
        "should ignore a job of the other kind.",
    )
    day: date | None = Field(
        description="The day whose report the job rewrites, or the Monday of the week."
    )
    moment: Literal["morning", "evening", "end"] | None = Field(
        default=None,
        description="Which part of the period the job speaks from, and so the voice of the "
        "text: a day is written in the morning (the body, ahead of him) or in the evening "
        "(the session, behind him). A week has one moment, its close.",
    )
    started: datetime | None
    finished: datetime | None
    message: str | None = Field(description="Why the job failed. Null otherwise.")
    download: Download | None = Field(
        default=None,
        description="How the download from Garmin fared. Null when the job did not download. "
        "A failed download does not stop the job: the text is written on the data already here.",
    )
    sections: dict[str, SectionRefresh] = Field(
        description="One entry per section of the report being written, by key: health, "
        "load, recovery, fitness, training and summary. A day and a week have the same six."
    )


class Sport(BaseModel):
    """A sport found in the activities."""

    sport: str = Field(description="The key used in `Activity.sport`.")
    label: str = Field(description="The name to show.")
    icon: str | None = Field(description="Icon file name, served under /icons.")


class SportList(BaseModel):
    """The sports found in the activities, and the icon for rest days."""

    sports: list[Sport]
    rest_icon: str = Field(description="Icon file name for days without activities, served under /icons.")


# I fatti del giorno (`/api/daily/{day}`), tipati per la Day in React (todo
# 34). Sono i campi di `daily_data.build_daily_data`: i nomi e la forma non si
# cambiano qui, si descrivono. `sessions` e `hr_zones` restano senza tipo
# perche' la pagina non li usa (le attivita' le prende da `/api/activities`).
#
# Alcuni modelli hanno un campo `date`: dentro la classe il nome copre il
# tipo, per questo il tipo li' si chiama `Date`.
Date = date


class Mean(BaseModel):
    """An average over a window, with the number of days it is made of."""

    mean: float | None = Field(description="Null when no day in the window has a value.")
    days: int


class Measure(BaseModel):
    """One morning measure, with its 7- and 28-day averages and its usual band."""

    value: float | None
    date: Date = Field(description="The day the value is read from.")
    avg_7d: Mean
    avg_28d: Mean
    delta_vs_28d: float | None
    band: "Band | None" = Field(
        description="Where the measure usually sits, from the 28 days before it. Computed "
        "here, not Garmin's. Null under 14 measured days."
    )


class Range(BaseModel):
    low: float
    high: float


class Band(Range):
    """Where a measure usually sits: one standard deviation around its average, and two."""

    outer_low: float = Field(description="Two standard deviations below the average.")
    outer_high: float = Field(description="Two standard deviations above the average.")


Measure.model_rebuild()


class Morning(BaseModel):
    """Recovery and health measures of the morning. Stress and the body battery low are the
    day before's; everything else is the night/morning of the day."""

    readiness: Measure
    resting_hr: Measure
    hrv_last_night: Measure
    hrv_weekly_avg: Measure
    resp_sleep: Measure
    sleep_hours: Measure
    sleep_score: Measure
    stress_avg_yesterday: Measure
    body_battery_morning: Measure
    body_battery_low_yesterday: Measure
    spo2_avg: Measure
    hrv_status: str | None = Field(description="Garmin's word for the HRV status.")
    hrv_baseline: Range | None = Field(description="Garmin's balanced HRV range, in ms.")


class SleepLast7(BaseModel):
    hours: dict[date, float | None] = Field(description="Hours of sleep, night by night.")
    short_nights: int = Field(description="Nights under 7 h.")
    nights_measured: int


class Alert(BaseModel):
    """A warning sign, with its own numbers in extra fields."""

    model_config = ConfigDict(extra="allow")

    kind: str
    detail: str


class LoadNow(BaseModel):
    """Garmin's training load as of one day."""

    as_of: date
    load_acute: float | None
    load_chronic: float | None
    acwr: float | None
    acwr_status: str | None
    training_status: float | None
    training_status_phrase: str | None
    load_aerobic_low: float | None = Field(description="Monthly load, low aerobic.")
    load_aerobic_high: float | None = Field(description="Monthly load, high aerobic.")
    load_anaerobic: float | None = Field(description="Monthly load, anaerobic.")
    load_balance_phrase: str | None


class LoadBands(BaseModel):
    """Where the monthly load of each effect has sat over the last 28 days. Not Garmin's
    target: the same mean-and-standard-deviation band as every other bar on the page."""

    load_aerobic_low: Band | None
    load_aerobic_high: Band | None
    load_anaerobic: Band | None


class Vo2maxChange(BaseModel):
    now: float
    days_ago_28: float
    change: float


class Load(BaseModel):
    now: LoadNow | None
    bands: LoadBands | None = Field(
        description="Null when there is no load at all. A single band is null with too few "
        "measured days."
    )
    week_ago: LoadNow | None
    vo2max_change: Vo2maxChange | None = Field(description="Only when VO2max moved by 0.5 or more in 28 days.")


class Vo2maxNow(BaseModel):
    """The latest VO2max up to the day, shown even when it did not move."""

    now: float
    as_of: date = Field(description="The day Garmin measured it.")
    days_ago_28: float | None = Field(description="Null when there is no value 28 days before.")
    change: float | None = Field(description="Null when there is no value 28 days before.")
    band: Band | None = Field(
        default=None,
        description="Where it has sat over the last 28 days. Read the other way round from the "
        "bands of `morning`: above the band means it is still climbing. Null with too few "
        "measured days.",
    )


class ScoreNow(BaseModel):
    """The latest Garmin score up to the day (endurance or hill), shown even when it did not move."""

    now: int
    as_of: date = Field(description="The day of the health file it is read from.")
    days_ago_28: int | None = Field(description="Null when there is no value 28 days before.")
    change: int | None = Field(description="Null when there is no value 28 days before.")
    band: Band | None = Field(
        default=None,
        description="Where it has sat over the last 28 days. Read the other way round from the "
        "bands of `morning`: above the band means it is still climbing. Null with too few "
        "measured days.",
    )


class EnduranceNow(ScoreNow):
    level: str | None = Field(
        description="Garmin's level for the score (Recreational, Intermediate, Trained, Well-trained, "
        "Expert, Superior, Elite), from the limits in the same answer."
    )


class ThresholdHr(BaseModel):
    """The threshold heart rate saved by the watch in the latest on-foot activity with zones."""

    value: int = Field(description="In bpm.")
    as_of: date = Field(description="The day of the activity it is read from.")


class LactateThreshold(BaseModel):
    """Garmin's latest running lactate threshold. Only the latest one is known, so it is shown
    from the day it was detected on."""

    heart_rate: int | None = Field(description="In bpm.")
    speed_kmh: float | None
    pace_s_per_km: int | None = Field(description="Seconds per km, from the speed.")
    as_of: date = Field(description="The day Garmin detected it.")


_TREND = (
    "Garmin's word for the direction: ACCLIMATIZING, ACCLIMATIZED, DEACCLIMATIZING. "
    "Null when it has nothing to say."
)


class AltitudeAcclimation(BaseModel):
    """How high the body is acclimatised to, as Garmin works it out from where the
    activities happened. Built over days spent high up and lost just as fast."""

    metres: int = Field(description="Zero when there is no acclimatisation.")
    trend: str | None = Field(description=_TREND)


class HeatAcclimation(BaseModel):
    """How far the body has adapted to training in the heat, from the temperature of the
    activities. Same shape as the altitude: days to build, days to lose."""

    percent: int = Field(description="0 to 100. Zero when there is no acclimatisation.")
    trend: str | None = Field(description=_TREND)


class Fitness(BaseModel):
    """What the athlete can do, changing slowly over weeks (the Fitness card, todos 37 and 38).
    Only in the API: the daily report's JSON does not have it."""

    vo2max: Vo2maxNow | None = Field(description="Null when there is no VO2max up to the day.")
    endurance: EnduranceNow | None = Field(description="Garmin's endurance score. Null when there is none up to the day.")
    hill: ScoreNow | None = Field(description="Garmin's hill score. Null when there is none up to the day.")
    lactate_threshold: LactateThreshold | None = Field(
        description="Null before the day it was detected, or when it has not been downloaded."
    )
    threshold_hr: ThresholdHr | None = Field(
        description="Same as `hr_zones.threshold_hr`. Null when no activity has a valid threshold."
    )
    altitude_acclimation: AltitudeAcclimation | None = Field(
        default=None,
        description="Null for the days whose training status file does not carry the block, "
        "which is everything before 2025.",
    )
    heat_acclimation: HeatAcclimation | None = Field(
        default=None,
        description="Null for the days whose training status file does not carry the block, "
        "which is everything before 2025.",
    )


class DayActivities(BaseModel):
    date: Date
    weekday: str
    activities: list[str] = Field(description='One line per activity, e.g. "running 8.1 km".')


class RecentActivity(BaseModel):
    date: Date
    sport: str | None
    distance_km: float | None
    duration_min: float | None
    aerobic_te: float | None
    anaerobic_te: float | None


class Recent(BaseModel):
    """The days before the day. Counts ignore what was done on the day itself."""

    trained_today: bool
    last_activity_before_today: date | None
    days_since_last_activity_before_today: int | None
    last_hard_session_before_today: date | None
    days_since_last_hard_session_before_today: int | None
    hard_session_rule: str
    rest_days_last_7: int
    consecutive_training_days_before_today: int
    consecutive_rest_days_before_today: int
    last_7_days: list[DayActivities]
    activities_last_14_days: list[RecentActivity]


class WeekMeasure(BaseModel):
    """One of the week's measures, with the band it moved in over the last twelve
    weeks (todo 52). Health and Recovery are averages of the seven days."""

    card: Literal["health", "recovery"] = Field(description="Which card shows it.")
    label: str = Field(description="The name to show.")
    unit: str = Field(description="Empty for the measures that have none.")
    value: float | None = Field(description="Null when no day of the week was measured.")
    band: Band | None = Field(
        description="Where the weekly average has sat over the last twelve weeks. Null with "
        "fewer than six measured weeks. Not the daily band: around an average of seven days a "
        "28-day band would sit inside almost always."
    )
    weeks: int = Field(description="How many of the twelve weeks before carried a value.")


class WeekInfo(BaseModel):
    start: Date = Field(description="The Monday.")
    end: Date = Field(description="The Sunday.")
    partial: bool = Field(description="True while the week is still running.")
    last_day: Date = Field(description="The Sunday, or today for a week still running.")


class WeekLoad(BaseModel):
    """The week's training load (todo 54).

    Only what belongs to the week: the acute load is the sum of the last seven days, so
    read on the Sunday it is exactly Monday to Sunday. The chronic load, the ratio of the
    two and the per-effect loads are 28-day windows and live on the Day page instead —
    here they made neighbouring weeks look alike, because they share most of the window."""

    as_of: Date = Field(description="The last day of the week that carries a load.")
    load_acute: float | None = Field(description="The load of the week.")
    training_status: float | None
    training_status_phrase: str | None
    load_balance_phrase: str | None
    band: "Band | None" = Field(
        description="Where the week's load sits against the twelve weeks before it. Null "
        "under six measured weeks."
    )
    weeks: int = Field(description="Measured weeks behind the band, out of twelve.")


class WeekZone(BaseModel):
    """Minutes spent in one of Garmin's three effort bands, over the week (todo 54)."""

    minutes: float | None = Field(
        description="Null when no session of the week carries heart rate — which is not zero."
    )
    band: "Band | None" = Field(description="The twelve weeks before this one. Null under six.")
    weeks: int


class WeekZones(BaseModel):
    """The week's time by effort: the composition of the load, which the total alone does
    not give — the same load can be ten slow hours or three hard ones.

    Counted from the heart-rate samples of each session, with that session's own zone
    bounds: a threshold raised in September must not rewrite August."""

    low_aerobic: WeekZone
    high_aerobic: WeekZone
    anaerobic: WeekZone
    measured_min: float | None = Field(description="The three added up: time with heart rate.")
    sessions_without_hr: int = Field(
        description="Sessions of the week with no heart rate, so outside this count. Garmin's "
        "load sees them and these minutes do not."
    )



class TrendPoint(BaseModel):
    """One day of a trend series. `value` is null where the day has no measure: the line
    breaks there instead of joining the two sides of a gap."""

    day: date
    value: float | None


class TrendSeries(BaseModel):
    """One measure over the window, with the band it usually sits in."""

    key: str = Field(description="The column it is read from.")
    label: str
    unit: str | None = Field(description="Null for plain scores.")
    digits: int = Field(description="Decimals the measure is worth.")
    points: list[TrendPoint]
    band: Band | None = Field(
        description="Null under MIN_BAND_DAYS measured days, for the load ratio and for the "
        "Training panel."
    )


class TrendPanel(BaseModel):
    """One panel of the Trend, in the order of the Day cards."""

    key: str
    title: str
    icon: str | None = Field(description="The icon of the Report section with the same name.")
    series: list[TrendSeries]


class TrendData(BaseModel):
    """The daily series between two days, panel by panel (todo 55)."""

    from_: date = Field(alias="from", description="First day, included.")
    to: date = Field(description="Last day, included.")
    days: int = Field(description="Width of the window, in days.")
    min_band_days: int = Field(description="Measured days a band needs; under it there is none.")
    panels: list[TrendPanel]

    model_config = {"populate_by_name": True}


class WeekTrendPoint(BaseModel):
    """One ISO week of a weekly trend series.

    `value` is the arithmetic mean of the week's measured days - a sum, on the Training
    panel. Null where no day of the week was measured: the line breaks there instead of
    joining the two sides of a gap."""

    monday: date = Field(description="The Monday of the week.")
    week: int = Field(description="The ISO week number.")
    value: float | None
    days: int = Field(description="Measured days behind the value, out of seven.")
    band: Band | None = Field(
        description="Where this week's average would sit if nothing had changed: the window's "
        "centre - the mean of the weekly means - plus and minus one standard error, and two. "
        "It is a control chart: the week is the subgroup, the variance is pooled over the "
        "window, and each week divides its square root by the root of its own measured days, so "
        "the band widens where the average rests on fewer days. A point outside the outer edges "
        "is a week that did something different. Null under MIN_WEEK_DAYS measured days, for the "
        "load ratio and for the whole Training panel."
    )


class WeekTrendSeries(BaseModel):
    """One measure, week by week.

    No band of its own, unlike TrendSeries: here every week carries the band of its own
    days."""

    key: str = Field(description="The column it is read from.")
    label: str
    unit: str | None = Field(description="Null for plain scores.")
    digits: int = Field(description="Decimals the measure is worth.")
    centre: float | None = Field(
        description="The mean of the weekly means over the window, which the bands are built "
        "around and the chart draws as a dashed line. Null where there is no band: the load "
        "ratio and the whole Training panel."
    )
    points: list[WeekTrendPoint]


class WeekTrendPanel(BaseModel):
    """One panel of the weekly Trend, in the order of the Day cards."""

    key: str
    title: str
    icon: str | None = Field(description="The icon of the Report section with the same name.")
    series: list[WeekTrendSeries]


class WeekTrendData(BaseModel):
    """The weekly series over a window of ISO weeks, one point per week (todo 78).

    Health, Recovery, Load and Fitness are the mean of the week's days; Training is their
    sum. One rule for every panel, so the lines compare - which is why load and fitness are
    means here and not the end-of-week states the Week itself reads."""

    from_: date = Field(alias="from", description="The Monday of the first week.")
    to: date = Field(description="The Monday of the last week, included.")
    weeks: int = Field(description="Width of the window, in weeks.")
    min_week_days: int = Field(
        description="Measured days a weekly band needs; under it there is none."
    )
    panels: list[WeekTrendPanel]

    model_config = {"populate_by_name": True}


# La faccia di ogni card (todo 92): una parola per card, che la pagina
# traduce in una delle cinque icone della scala. Le regole stanno in
# `api/score.py`, e il voto viene dalle fasce che la pagina disegna gia'.
#
# `null` vuol dire **nessuna faccia**, cioe' niente da misurare: non e' un
# voto basso, e la card resta senza icona.
Verdict = Literal["terrible", "low", "medium", "high", "perfect"]


class Scores(BaseModel):
    """How each card is doing, in one word (todo 92)."""

    health: Verdict | None
    recovery: Verdict | None
    load: Verdict | None = Field(
        description="Never terrible or perfect: load has no good side, and the best this "
        "measure can say is that you are where you usually are."
    )
    fitness: Verdict | None
    summary: Verdict | None = Field(description="The average of the four cards above.")


class WeeklyData(BaseModel):
    """Everything known about one ISO week, Monday to Sunday (todo 52)."""

    week: WeekInfo
    measures: dict[str, WeekMeasure] = Field(
        description="By column name: the Health and Recovery measures, averaged over the week."
    )
    load: WeekLoad | None = Field(description="The week's load.")
    zones: WeekZones = Field(description="The week's time by effort.")
    fitness: Fitness = Field(description="What the body could do at the end of the week.")
    training: dict[str, Any] = Field(description="Sessions, time and totals by sport.")
    days: list[dict[str, Any]] = Field(description="One entry per day of the week.")
    activities: list[dict[str, Any]]
    coverage: dict[str, int] = Field(description="Measured days per metric, out of seven.")
    scores: Scores = Field(description="How each card is doing, from the bands (todo 92).")


class DailyData(BaseModel):
    """Everything known about one day, as built for the daily report."""

    day: date
    weekday: str
    health_data_up_to: date | None
    morning: Morning
    sleep_minutes: int | None = Field(
        description="Last night's sleep in whole minutes (sleep_hours is rounded to 0.1 h)."
    )
    sleep_last_7: SleepLast7
    alerts: list[Alert] = Field(description="Empty when there are no warning signs.")
    load: Load
    sessions: dict[str, Any]
    recent: Recent
    hr_zones: dict[str, Any] | None
    missing: list[str]
    fitness: Fitness
    scores: Scores = Field(description="How each card is doing, from the bands (todo 92).")


# I piani di allenamento scritti a mano in `plan/`: il front matter da' i
# numeri dei riquadri, il Markdown il testo. Tutti i campi del front matter
# sono facoltativi: un piano senza front matter si vede comunque, col solo
# testo (`api/plans.py`).
class PlanSummary(BaseModel):
    """One training plan, without its text: what the picker needs."""

    slug: str = Field(description="The file name without `.md`: the plan's id in the URL.")
    file: str = Field(description="The file name in `plan/`.")
    title: str = Field(description="The first heading of the text, or the slug when it has none.")
    race: date | None = Field(description="Race day.")
    race_name: str | None
    distance_km: float | None
    target_time: str | None = Field(description='Target finishing time, as written ("2:20:00").')
    target_pace: str | None = Field(description='Target pace per kilometre, as written ("6:38").')
    target_speed_kmh: float | None
    block_start: date | None = Field(description="First day of the block.")
    weeks: int | None = Field(description="How many weeks the block lasts.")
    peak_weekly_km: float | None = Field(description="The heaviest week of the block.")
    current: bool = Field(
        description="The goal being followed right now: `current: true` in the front matter. "
        "Exactly one plan at most has it — when more than one file carries the flag, the "
        "first of this list keeps it."
    )
    written_at: datetime | None = Field(description="When the file was last written.")


class Plan(PlanSummary):
    """One training plan, with its text."""

    body: str = Field(description="Markdown, without the front matter and without the title.")


class WeeksFollowing(BaseModel):
    """How many weekly plans, this Monday on, were written from one goal."""

    slug: str = Field(description="The goal those weeks declare in their `plan:` key.")
    weeks: int = Field(description="How many weekly plan files, from this Monday on.")


class PlanList(BaseModel):
    """The plans in `plan/`, the nearest race first."""

    plans: list[PlanSummary]
    ahead: list[WeeksFollowing] = Field(
        description="Which goal the weekly plans of `summary/05.plan/` still follow, counted "
        "from this Monday on. An entry whose `slug` is not the current goal means those weeks "
        "were written from another one and nothing has rewritten them: changing the flag does "
        "not regenerate them (todo 85). Weeks already past are not counted — they are the "
        "record of what was planned then."
    )


# La seduta che il piano prevede per un giorno (todo 71): i campi del front
# matter, piu' la riga che quel giorno ha nella tabella del testo.
#
# Sta da sola perche' la vogliono in due: `WeekPlan` ne manda sette, una per
# giorno della settimana, e `DayPlan` ne manda una con attorno da che file
# viene. Da cui l'ereditarieta', come `ActivityDetail` da `Activity`.
class PlannedSession(BaseModel):
    """One day's session, as the week's plan asks for it."""

    day: date = Field(description="The day the session is planned for.")
    sport: str | None = Field(description="A sport of `activities.sport`, or `rest`.")
    kind: str | None = Field(description="easy, quality, long or race.")
    distance_label: str | None = Field(description='Planned distance, as read ("10-11 km").')
    optional: str | None = Field(description="On a rest day, the sport that may be done anyway.")
    text: str | None = Field(
        description="The day's row of the plan's table, Markdown; null when it has none."
    )


# Il piano di una settimana, da `summary/05.plan/<lunedi>.md` (todo 60). Non
# e' il blocco di `plan/`: quello dura quattro mesi e parla di una gara,
# questo dura sette giorni e dice le sedute.
#
# **Le sette sedute sono qui dal todo 71**, una per giorno. Fino al todo 60
# non c'erano di proposito — le diceva la tabella del testo, e un campo che
# nessuno guarda non si manda — e il todo 70 ne aveva mandato i soli totali,
# che e' una domanda diversa da quella che si voleva.
class WeekPlan(BaseModel):
    """The plan of one week, from `summary/05.plan/<monday>.md`."""

    week: date = Field(description="The Monday of the week, which is also the file name.")
    file: str = Field(description="The file name in `summary/05.plan/`.")
    title: str = Field(description="The first heading of the text, or the file stem.")
    plan: str | None = Field(description="Slug of the block in `plan/` this week comes from.")
    block_week: int | None = Field(description="Which week of the block this is.")
    block_weeks: int | None = Field(description="How many weeks the block lasts.")
    phase: str | None = Field(description="base, build, specific, taper or race.")
    race: date | None = Field(description="Race day of the block.")
    target_time: str | None = Field(description='Target finishing time, as written ("2:20:00").')
    sessions: list[PlannedSession] | None = Field(
        description="The planned session of each day, Monday to Sunday, in order. Null for "
        "a file written before the front matter had them."
    )
    written_at: datetime | None = Field(description="When the file was last written.")
    body: str = Field(description="Markdown, without the front matter and without the title.")


# Il confine della navigazione della Week (todo 88): quali settimane hanno un
# piano. Una lista di lunedi' e niente altro — la pagina ne tiene il massimo,
# e di una settimana per volta chiede il piano a `/api/weekly/<lunedi>/plan`.
class PlannedWeeks(BaseModel):
    """The weeks that have a written plan."""

    weeks: list[Date] = Field(
        description="Mondays of the weeks with a file in `summary/05.plan/`, oldest first."
    )


# La seduta prevista per un giorno (todo 63), con attorno da che file viene:
# la chiede la vista Training della Day, per il giorno che sta mostrando.
class DayPlan(PlannedSession):
    """The session planned for one day, with the plan it comes from."""

    week: date = Field(description="The Monday of the week this comes from.")
    file: str = Field(description="The file name in `summary/05.plan/`.")
    written_at: datetime | None = Field(description="When the file was last written.")
