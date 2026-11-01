// La pagina Week (todo 51): una settimana ISO alla volta, dal lunedi alla
// domenica. Per ora e' il guscio — l'intestazione, la striscia dei sette
// giorni e le sedute — e usa solo quello che l'API gia' offre
// (`/api/activities` e `/api/sports`). I numeri della settimana con le loro
// fasce arrivano col todo 52, i testi col 53.
//
// Il lunedi sta nell'URL (`?page=week&monday=2026-10-19`), come il giorno
// nella Day: una settimana si apre da un link e il tasto indietro torna a
// quella prima.
//
// Dal todo 59 la pagina ha le sue viste, che il menu scambia con `?view=`: lo
// **Snap**, cioe' la settimana com'e' andata — le card e le sedute, quello
// che la pagina ha sempre mostrato — il **Plan**, cioe' come doveva andare
// (todo 60), e il **Trend**, che dal todo 78 e' la fila delle settimane: un
// punto per settimana invece che per giorno. L'intestazione e la scelta
// della settimana sono le stesse per tutte e tre, che la settimana serve a
// tutte: cambiandola, Snap e Plan parlano degli stessi sette giorni.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  api,
  iconUrl,
  isAbort,
  type Activity,
  type Band,
  type RefreshStatus,
  type Report,
  type SportList,
  type WeeklyData,
  type WeekMeasure,
  type WeekPlan,
} from "../api/client";
import {
  addDays,
  daysBetween,
  durationLabel,
  fixed,
  longDayLabel,
  mondayOf,
  shortDayLabel,
  timeOf,
  weekdayShort,
  today,
  weekLabel,
} from "../format";
import { markdown, sectionBody, sectionWrittenAt } from "../markdown";
import { ETICHETTE, paramFromUrl, pushUrl, weeksFromUrl, type View } from "../navigation";
import { useColorScheme } from "../useColorScheme";
import { WeekCalendar } from "./WeekCalendar";
import { CardHead, EmptyBar, RangeBar, Stat, WrittenAt, num } from "./Stat";
import { SectionRefresh } from "./SectionRefresh";
import { SummaryCard } from "./SummaryCard";
import { TopBar } from "./TopBar";
import { WeekPicker } from "./WeekPicker";
import { WeekTrendPanels } from "./WeekTrendPanels";
import { WeekPlanBrief, WeekPlanCard } from "./WeekPlanCard";

const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const API_DOWN = "Cannot reach the API. Is it running (make api)?";

/** Il lunedi dell'URL, se e' una data valida; se no quello della settimana
 * di oggi. Un giorno qualunque viene riportato al suo lunedi, cosi' un link
 * storto apre comunque la settimana giusta. */
function mondayFromUrl(now: string): string {
  const value = paramFromUrl("monday");
  const current = mondayOf(now);
  if (!value || !DAY_PATTERN.test(value) || Number.isNaN(Date.parse(value)))
    return current;
  // **Una settimana futura si tiene** (todo 88): fin dove si possa andare
  // avanti lo dice il piano, e il piano qui non si sa ancora — arriva da
  // `/api/weekly/planned` un istante dopo. Chi esagera lo riporta indietro
  // quel confine, quando c'e'; prima di questo todo tornava subito a oggi.
  return mondayOf(value);
}

/** Quanti decimali vuole una misura: dall'unita', come fa la Day. */
function digitsOf(m: WeekMeasure): number {
  return m.unit === "h" || m.unit === "/min" ? 1 : 0;
}

/** Un riquadro della settimana: il numero e, sotto, la barra della fascia
 * delle dodici settimane. Gli stessi mattoni della Day (`Stat`, `RangeBar`),
 * guidati da quello che l'API manda: etichetta, unita', valore e fascia. */
function WeekStat({ m }: { m: WeekMeasure }) {
  const digits = digitsOf(m);
  const fmt = (v: number) => v.toFixed(digits);
  return (
    <Stat
      label={m.label}
      value={num(m.value, digits)}
      unit={m.unit || undefined}
      sub={
        m.band ? (
          <RangeBar value={m.value} band={m.band} tick={fmt} />
        ) : (
          <EmptyBar />
        )
      }
    />
  );
}

/** Una card di misure settimanali: Health o Recovery. Sotto i numeri, il
 * testo della sua sezione del report (todo 53) con l'ora in cui e' stato
 * scritto e il tasto per rifarlo, come nella Day. */
function MeasureCard({
  title,
  icon,
  cls,
  measures,
  text,
  writtenAt,
  monday,
  refresh,
}: {
  title: string;
  icon: string | null;
  cls?: string;
  measures: WeekMeasure[];
  text: string | null;
  writtenAt: string | null;
  monday: string;
  refresh?: ReactNode;
}) {
  return (
    <section className={cls ? `card ${cls}` : "card"} aria-label={title}>
      <CardHead icon={icon} title={title} refresh={refresh} />
      <div className="stats two">
        {measures.map((m) => (
          <WeekStat key={m.label} m={m} />
        ))}
      </div>
      {text && <div className="prose">{markdown(text)}</div>}
      <WrittenAt when={writtenAt} day={monday} />
    </section>
  );
}

/** Le misure di una card, nell'ordine in cui l'API le manda. */
function byCard(data: WeeklyData, card: "health" | "recovery"): WeekMeasure[] {
  return Object.values(data.measures).filter((m) => m.card === card);
}

/** L'icona di una card: gli stessi file della Day, che l'API serve sotto
 * /icons. Scritte qui e non prese dal report come fa la Day
 * (`sectionIcon`): il report della settimana c'e' (todo 53), ma le sue
 * sezioni non portano un'icona propria, e queste sono le stesse per tutte le
 * settimane. */
const CARD_ICONS: Record<string, string> = {
  health: "health.png",
  load: "trend.png",
  recovery: "recovery.png",
  fitness: "fitness.png",
  training: "training.png",
  // Il fumetto del giudizio, come nella Day: il commento prendeva il
  // manubrio della sezione Training, lo stesso della card delle sedute che
  // ha sotto, e due riquadri di fila con lo stesso segno si leggevano come
  // uno solo.
  comment: "comment.png",
};
const sectionIconFile = (card: string) => CARD_ICONS[card] ?? null;

/** Un punteggio di forma con la sua barra: la fascia e' quella delle dodici
 * settimane, e **sopra vuol dire che stai migliorando**, come nella Day. */
function ScoreStat({
  label,
  score,
  digits = 0,
}: {
  label: string;
  score: { now: number; band?: Band | null } | null;
  digits?: number;
}) {
  return (
    <Stat
      label={label}
      value={num(score?.now, digits)}
      sub={
        score?.band ? (
          <RangeBar value={score.now} band={score.band} />
        ) : (
          <EmptyBar />
        )
      }
    />
  );
}

// Le tre fasce di sforzo di Garmin, nell'ordine in cui si leggono: il
// tempo della settimana dentro ognuna (todo 54).
const ZONE_ROWS: {
  key: "low_aerobic" | "high_aerobic" | "anaerobic";
  label: string;
}[] = [
  { key: "low_aerobic", label: "Low aerobic" },
  { key: "high_aerobic", label: "High aerobic" },
  { key: "anaerobic", label: "Anaerobic" },
];

export function WeekPage({ view = "snap" }: { view?: View }) {
  const now = today();
  const currentMonday = mondayOf(now);
  const [monday, setMonday] = useState(() => mondayFromUrl(now));
  const [sportList, setSportList] = useState<SportList | null>(null);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [data, setData] = useState<WeeklyData | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [plan, setPlan] = useState<WeekPlan | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  // I lunedi' che hanno un piano (todo 88): il confine fin dove si puo'
  // andare avanti. Vuoto finche' non arriva, e allora avanti non si va —
  // che e' la pagina di prima.
  const [planned, setPlanned] = useState<string[]>([]);
  const [refresh, setRefresh] = useState<RefreshStatus | null>(null);
  // Vero da quando si e' premuto un tasto: prima di allora un lavoro
  // fallito e' roba di qualcun altro, e non si annuncia.
  const [watched, setWatched] = useState(false);
  const [reloads, setReloads] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const theme = useColorScheme();
  const [weeks, setWeeks] = useState(() => weeksFromUrl());
  const sunday = addDays(monday, 6);
  // Fin dove si guarda: l'ultima settimana che ha un piano, o questa se non
  // ce n'e' nessuno (todo 88). Oltre il piano non c'e' niente da vedere.
  const limit = planned.length > 0 ? planned[planned.length - 1] : currentMonday;
  const last = limit > currentMonday ? limit : currentMonday;
  // Una settimana che **non e' cominciata**: non ha fatti, non ha report,
  // non ha sedute. Ha un piano, e basta.
  const future = monday > currentMonday;

  const changeWeek = (next: string) => {
    if (next === monday || next > last) return;
    pushUrl({ period: "week", page: null, monday: next });
    setMonday(next);
  };

  // L'ampiezza del Trend va nell'URL, cosi' un link se la porta dietro, ma
  // **senza lasciare una voce nella cronologia**: il cursore ne attraversa
  // decine, e con una voce per valore il tasto indietro non tornerebbe piu'
  // alla settimana di prima. E' la stessa regola di `changeDays` nella Day.
  const changeWeeks = useCallback((next: number) => {
    const url = new URL(window.location.href);
    url.searchParams.set("weeks", String(next));
    window.history.replaceState(window.history.state, "", url);
    setWeeks(next);
  }, []);

  useEffect(() => {
    const onPop = () => {
      setMonday(mondayFromUrl(today()));
      setWeeks(weeksFromUrl());
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    // Da `ETICHETTE` e non da un ternario: quello diceva "Plan" anche sulla
    // vista Training, che non e' ne' `snap` ne' `trend` e finiva nel ramo
    // sbagliato. Cosi' una vista nuova non puo' restare senza nome.
    const coda = view === "snap" ? "" : ` · ${ETICHETTE[view]}`;
    document.title = `Training · ${weekLabel(monday)}${coda}`;
  }, [monday, view]);

  // Ogni chiamata solo sulla vista che la guarda. Gli sport e le sedute sono
  // della **Training** dal todo 68: nello Snap non ci sono piu'. Quella dei
  // numeri della settimana invece parte sempre, che il cerotto "N of 7 days"
  // sta nel titolo, che e' di tutte e quattro.
  useEffect(() => {
    if (view !== "training") return;
    const controller = new AbortController();
    api
      .sports(controller.signal)
      .then(setSportList)
      .catch((e) => !isAbort(e) && setError(API_DOWN));
    return () => controller.abort();
  }, [view]);

  // Il confine (todo 88): i lunedi' che hanno un piano. Una volta sola — i
  // file cambiano quando qualcuno lancia `make week_plans`, non mentre si
  // guarda la pagina.
  //
  // Qui si rimedia anche a un `?monday=` che va oltre: `mondayFromUrl` non
  // puo' saperlo, il confine arriva dopo. Si torna a questa settimana e
  // l'indirizzo si riscrive **senza** lasciare una voce nella cronologia,
  // che non e' un passo che qualcuno ha fatto.
  useEffect(() => {
    const controller = new AbortController();
    api
      .plannedWeeks(controller.signal)
      .then(({ weeks }) => {
        setPlanned(weeks);
        const furthest = weeks.length > 0 ? weeks[weeks.length - 1] : currentMonday;
        if (monday > furthest && monday > currentMonday) {
          const url = new URL(window.location.href);
          url.searchParams.set("monday", currentMonday);
          window.history.replaceState(window.history.state, "", url);
          setMonday(currentMonday);
        }
      })
      .catch((e) => !isAbort(e) && setError(API_DOWN));
    return () => controller.abort();
    // Solo all'apertura: `monday` qui si legge, non si segue.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (view !== "training" || future) {
      setActivities([]);
      return;
    }
    const controller = new AbortController();
    api
      .activities(monday, sunday, [], controller.signal)
      .then((list) => {
        setActivities(list);
        setError(null);
      })
      .catch((e) => !isAbort(e) && setError(API_DOWN));
    return () => controller.abort();
  }, [monday, sunday, view]);

  // I fatti della settimana. **Di una settimana futura non si chiedono**
  // (todo 88): l'API risponde 422 — *the week has not started* — e quella
  // risposta finirebbe nell'avviso che l'API e' giu'. Non e' giu': la
  // domanda e' senza senso, e a non farla e' la pagina.
  useEffect(() => {
    setData(null);
    if (future) return;
    const controller = new AbortController();
    api
      .weekly(monday, controller.signal)
      .then(setData)
      .catch((e) => !isAbort(e) && setError(API_DOWN));
    return () => controller.abort();
  }, [monday, future]);

  // Il testo della settimana: lo leggono lo Snap (il Summary e le quattro
  // card) e la Training (il commento e il Next). `reloads` lo rilegge quando
  // un lavoro finisce, senza ricaricare la pagina.
  useEffect(() => {
    setReport(null);
    // Il report di una settimana futura non esiste e non esistera' prima del
    // tempo: nessun agente scrive il verdetto di qualcosa che deve ancora
    // succedere (todo 56).
    if ((view !== "snap" && view !== "training") || future) return;
    const controller = new AbortController();
    api
      .weeklyReport(monday, controller.signal)
      .then(setReport)
      .catch((e) => !isAbort(e) && setError(API_DOWN));
    return () => controller.abort();
  }, [monday, reloads, view, future]);

  // Il piano della settimana (todo 60), sulle due viste che lo mostrano: il
  // documento nel Plan, i suoi totali nella Training (todo 70). Una
  // settimana senza file rende `null`, che qui vuol dire "non ce n'e' uno" e
  // non "non si e' potuto chiedere": `planLoading` tiene separate le due
  // cose, cosi' la card non annuncia un piano mancante mentre lo cerca.
  useEffect(() => {
    if (view !== "plan" && view !== "training") return;
    const controller = new AbortController();
    setPlan(null);
    setPlanLoading(true);
    api
      .weekPlan(monday, controller.signal)
      .then((found) => {
        setPlan(found);
        setPlanLoading(false);
      })
      .catch((e) => {
        if (isAbort(e)) return;
        setPlanLoading(false);
        setError(API_DOWN);
      });
    return () => controller.abort();
  }, [monday, view]);


  // Lo stato del lavoro, solo se e' di questo tipo: giorno e settimana
  // condividono un lavoro alla volta, e le chiavi delle sezioni sono
  // diverse. Finche' gira si richiede ogni due secondi.
  const running = refresh?.status === "running";
  useEffect(() => {
    const controller = new AbortController();
    api
      .refresh(controller.signal)
      .then((status) => {
        if (status.kind !== "weekly") return;
        if (status.status === "running") setWatched(true);
        setRefresh(status);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [monday]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      api
        .refresh()
        .then((status) => {
          if (status.kind !== "weekly") return;
          setRefresh(status);
          if (status.status !== "running") setReloads((n) => n + 1);
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [running]);

  // Il tasto di una sezione: gira il suo agente e lascia le altre com'erano.
  const refreshSection = (section: string) => {
    setWatched(true);
    api
      .startWeeklySectionRefresh(monday, section)
      .then((status) => {
        setRefresh(status);
        setWatched(true);
      })
      .catch(() => undefined);
  };
  const sectionButton = (key: string) => (
    <SectionRefresh
      section={key}
      state={refresh?.sections?.[key]}
      onRefresh={refreshSection}
    />
  );
  const rewriteWeek = () => {
    setWatched(true);
    api
      .startWeeklyRefresh(monday)
      .then(setRefresh)
      .catch(() => undefined);
  };
  const text = (title: string) => sectionBody(report, title);
  const when = (title: string) => sectionWrittenAt(report, title);

  const sportIcons = useMemo(
    () =>
      new Map((sportList?.sports ?? []).map((s) => [s.sport, s.icon ?? null])),
    [sportList],
  );
  const sportLabel = (key: string | null | undefined) =>
    sportList?.sports.find((s) => s.sport === key)?.label ?? key ?? "?";

  // Dalla piu' vecchia alla piu' recente: una settimana si legge in avanti.
  // I sette giorni della settimana, e le sedute di ognuno: la vista li mette
  // in fila uno per riga, accanto alle righe del piano (todo 77).
  const weekDays = Array.from({ length: 7 }, (_, i) => addDays(monday, i));
  const ordered = useMemo(
    () =>
      [...activities].sort((a, b) => a.start_time.localeCompare(b.start_time)),
    [activities],
  );
  const byDay = useMemo(() => {
    const map = new Map<string, Activity[]>();
    for (const a of ordered) {
      const day = a.start_time.slice(0, 10);
      map.set(day, [...(map.get(day) ?? []), a]);
    }
    return map;
  }, [ordered]);
  // Un giorno della striscia, o una seduta, aprono la Day di quel giorno:
  // `pushUrl` cambia l'URL e avvisa `App`, che scambia la pagina senza
  // ricaricare niente.
  const openDay = (day: string) =>
    pushUrl({ period: null, page: null, view: null, monday: null, day });

  return (
    <>
      <TopBar current="week" view={view} />
      <main className="page">
        <div className="day-header">
          <div className="day-title">
            <h1>
              {weekLabel(monday)}
              {data?.week.partial && (
                <span
                  className="week-partial"
                  title={`The week is still running: the Health and Recovery averages cover Monday to ${longDayLabel(data.week.last_day)}, while the bands are twelve full weeks. Load and fitness are the state right now, so they read as usual.`}
                >
                  {daysBetween(monday, data.week.last_day).length} of 7 days
                </span>
              )}
            </h1>
            <div className="day-nav">
              <button
                type="button"
                className="btn icon-btn"
                onClick={() => changeWeek(addDays(monday, -7))}
                aria-label="Previous week"
                title="Previous week"
              >
                ‹
              </button>
              <button
                type="button"
                className="btn icon-btn"
                onClick={() => changeWeek(addDays(monday, 7))}
                disabled={monday >= last}
                aria-label="Next week"
                title="Next week"
              >
                ›
              </button>
              <button
                type="button"
                className="btn icon-btn"
                onClick={() => changeWeek(currentMonday)}
                disabled={monday === currentMonday}
                aria-label="This week"
                title="This week"
              >
                ›|
              </button>
              <WeekCalendar
                monday={monday}
                current={currentMonday}
                limit={last}
                onSelect={changeWeek}
              />
              {/* Rifa' tutta la settimana: otto agenti in fila, qualche
                  minuto. Non scarica niente, a differenza del Refresh
                  della Day: la settimana si scrive sui dati che ci sono.
                  **Su una settimana futura non c'e'** (todo 88): l'API
                  risponde 422 per scelta, ed e' la regola del todo 56 —
                  chiudere un periodo che deve ancora succedere vuol dire
                  giudicarlo prima del tempo. Un tasto che risponde 422 e'
                  peggio di un tasto che non c'e'. */}
              {!future && (
              <button
                type="button"
                className="btn icon-btn refresh-btn"
                onClick={rewriteWeek}
                disabled={running}
                aria-busy={running}
                aria-label={
                  running
                    ? "Rewriting the week…"
                    : "Rewrite the whole weekly report"
                }
                title={
                  running
                    ? "Rewriting the week…"
                    : "Rewrite the whole weekly report (a few minutes)"
                }
              >
                <svg
                  aria-hidden="true"
                  viewBox="0 0 16 16"
                  width="14"
                  height="14"
                >
                  <path
                    d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                  <path
                    d="M12.5 1.5v3h-3"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
              )}
            </div>
          </div>
          <WeekPicker
            monday={monday}
            current={currentMonday}
            limit={last}
            onSelect={changeWeek}
          />
        </div>
        {error && <p className="warning">{error}</p>}
        {watched && refresh?.status === "failed" && (
          <p className="warning">
            The week of {refresh.day} was not rewritten: {refresh.message}
          </p>
        )}
        {/* La fila delle settimane: il Trend (todo 78). Un punto per
            settimana invece che per giorno, sulla stessa griglia della Day. */}
        {/* Il Trend resta sulle settimane **misurate** anche guardando una
            settimana prevista (todo 88): e' una carta di controllo, e dei
            punti che non ci sono non fanno un grafico vuoto, fanno un
            grafico sbagliato. La finestra finisce sulla settimana corrente. */}
        {view === "trend" && (
          <WeekTrendPanels
            monday={future ? currentMonday : monday}
            weeks={weeks}
            onWeeks={changeWeeks}
            theme={theme}
          />
        )}
        {/* Come doveva andare la settimana: il Plan (todo 60). */}
        {view === "plan" && (
          <WeekPlanCard plan={plan} monday={monday} loading={planLoading} />
        )}
        {/* La Training della settimana (todo 68), sulla linea di quella del
            giorno: cosa hai fatto, com'e' andato, cosa viene dopo. Le sedute
            e il grafico stavano dentro la card del commento; qui sono due
            riquadri, che sono due cose — i fatti e il giudizio. */}
        {view === "training" && (
          <>
            {/* Il commento e' il verdetto della settimana, e una settimana che
                non e' cominciata non ne ha uno: la cornice c'e' comunque e
                resta **vuota**, come nella Day (todo 63) — e' la stessa
                risposta che da' una settimana passata di cui nessun agente ha
                ancora scritto il Training, e la vista tiene la sua forma
                invece di perdere un riquadro su tre.
                Il tasto che lo scriverebbe no: su una settimana futura
                `POST .../refresh/<sezione>` risponde 422 per scelta, come il
                Refresh grande qui sopra. */}
            <section className="card comment-card" aria-label="Comment">
              <CardHead
                icon={sectionIconFile("comment")}
                title="Comment"
                refresh={future ? undefined : sectionButton("training")}
              />
              {text("Training") && (
                <div className="prose">{markdown(text("Training")!)}</div>
              )}
              <WrittenAt when={when("Training")} day={monday} />
            </section>
            {/* Il previsto e il fatto **affiancati** (todo 73): sono due
                liste corte della stessa settimana, e una sotto l'altra a
                tutta larghezza lasciavano tre quarti di riquadro bianchi e
                costringevano a scorrere per confrontarle. A sinistra cosa
                chiedeva, a destra cosa e' successo; sotto i 900 px tornano
                in colonna.

                Il commento sta sopra tutte e due (todo 74): e' il verdetto,
                e un verdetto si legge per primo. */}
            <div className="week-work">
            <WeekPlanBrief
              plan={plan}
              monday={monday}
              loading={planLoading}
              sport={{ label: sportLabel, icon: (key) => sportIcons.get(key ?? "") ?? null }}
              restIcon={sportList?.rest_icon ?? null}
            />
            <section className="card week-days" aria-label="Sessions">
              <CardHead icon={sectionIconFile("training")} title="Sessions" />
              {/* Una riga per giorno, come il piano accanto: le sedute
                  stanno sulla riga del loro giorno, e i giorni senza niente
                  lasciano la riga vuota. Cosi' previsto e fatto si leggono
                  sulla stessa riga invece che in due elenchi da far
                  combaciare a occhio. */}
              {weekDays.map((day) => (
                <div key={day} className="week-day-row">
                  {(byDay.get(day) ?? []).map((a) => {
                    const icon = sportIcons.get(a.sport ?? "") ?? null;
                    return (
                      <button
                        type="button"
                        key={a.activity_id}
                        className="week-session"
                        onClick={() => openDay(day)}
                      >
                        {icon && <img src={iconUrl(icon)} alt="" width={26} height={26} />}
                        <span className="week-session-name">
                          {a.activity_name ?? sportLabel(a.sport)}
                          <span className="muted">
                            {/* Il giorno resta scritto anche se la riga lo
                              dice gia': senza piano la colonna di sinistra
                              non c'e', e una seduta senza giorno in una
                              pagina di sette giorni non si colloca. La data
                              intera invece e' andata, che la settimana sta
                              nel titolo. */}
                          {sportLabel(a.sport)} · {weekdayShort(day)} ·{" "}
                          {timeOf(a.start_time)}
                          </span>
                        </span>
                        <span className="week-session-size">
                          {a.total_distance_km != null
                            ? fixed(a.total_distance_km, 1, " km")
                            : "–"}
                          <span className="muted">
                            {durationLabel(a.total_time_min)}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              ))}
              {/* Due frasi diverse per due cose diverse (todo 88): una
                  settimana finita senza sedute e' una settimana in cui non si
                  e' fatto niente; una che non e' cominciata non ha ancora
                  niente da dire. */}
              {ordered.length === 0 && (
                <p className="caption week-days-foot">
                  {future ? "The week has not started." : "No sessions this week."}
                </p>
              )}
            </section>
            </div>
          </>
        )}
        {/* Lo Snap e' il corpo, come quello del giorno (todo 68): il
            verdetto a tutta larghezza e le quattro card. Le sedute e il Next
            sono passati alla Training. */}
        {/* Lo Snap di una settimana prevista: una riga, e niente card (todo
            88). I numeri di una settimana che non e' cominciata non sono
            zero, non esistono, e sette riquadri di trattini si leggono come
            un guasto. Quello che di quella settimana si puo' guardare e' il
            piano, e sta nelle altre due viste. */}
        {view === "snap" && future && (
          <p className="info">
            The week of {shortDayLabel(monday)} has not started: nothing is measured yet.
            What it asks for is in the <strong>Plan</strong> and the <strong>Training</strong>
            {" "}views.
          </p>
        )}
        {view === "snap" && !future && (
        <>
        <SummaryCard
          day={monday}
          morning={{
            body: text("Summary"),
            writtenAt: when("Summary"),
            refresh: sectionButton("summary"),
          }}
          week
        />
        {data && (
          <div className="cards-grid">
            <MeasureCard
              title="Health"
              icon={sectionIconFile("health")}
              measures={byCard(data, "health")}
              text={text("Health")}
              writtenAt={when("Health")}
              monday={monday}
              refresh={sectionButton("health")}
            />
            <section className="card load-card" aria-label="Load">
              <CardHead
                icon={sectionIconFile("load")}
                title="Load"
                refresh={sectionButton("load")}
              />
              {/* Numeri della settimana, non del mese (todo 54): il carico
                  dei sette giorni e il tempo passato nelle tre fasce di
                  sforzo, ognuno contro le dodici settimane prima. */}
              <div className="stats two">
                <Stat
                  label="Load"
                  value={num(data.load?.load_acute)}
                  sub={
                    data.load?.band ? (
                      <RangeBar
                        value={data.load.load_acute}
                        band={data.load.band}
                        tick={(v) => v.toFixed(0)}
                      />
                    ) : (
                      <EmptyBar />
                    )
                  }
                />
                {ZONE_ROWS.map(({ key, label }) => {
                  const zone = data.zones[key];
                  return (
                    <Stat
                      key={key}
                      label={label}
                      value={durationLabel(zone.minutes)}
                      sub={
                        zone.band ? (
                          <RangeBar
                            value={zone.minutes}
                            band={zone.band}
                            tick={(v) => durationLabel(v)}
                          />
                        ) : (
                          <EmptyBar />
                        )
                      }
                    />
                  );
                })}
              </div>
              {data.zones.sessions_without_hr > 0 && (
                <p className="caption">
                  {data.zones.sessions_without_hr === 1
                    ? "One session has no heart rate and is not in these times."
                    : `${data.zones.sessions_without_hr} sessions have no heart rate and are not in these times.`}
                </p>
              )}
              {text("Load") && (
                <div className="prose">{markdown(text("Load")!)}</div>
              )}
              <WrittenAt when={when("Load")} day={monday} />
            </section>
            <MeasureCard
              title="Recovery"
              icon={sectionIconFile("recovery")}
              cls="recovery-card"
              measures={byCard(data, "recovery")}
              text={text("Recovery")}
              writtenAt={when("Recovery")}
              monday={monday}
              refresh={sectionButton("recovery")}
            />
            <section className="card fitness-card" aria-label="Fitness">
              <CardHead
                icon={sectionIconFile("fitness")}
                title="Fitness"
                refresh={sectionButton("fitness")}
              />
              <div className="stats">
                <ScoreStat
                  label="VO2max"
                  score={data.fitness.vo2max}
                  digits={1}
                />
                <ScoreStat
                  label="Endurance score"
                  score={data.fitness.endurance}
                />
                <ScoreStat label="Hill score" score={data.fitness.hill} />
                <Stat
                  label={
                    data.fitness.lactate_threshold
                      ? "Lactate threshold"
                      : "Threshold heart rate"
                  }
                  value={num(
                    data.fitness.lactate_threshold?.heart_rate ??
                      data.fitness.threshold_hr?.value,
                  )}
                  unit="bpm"
                />
                <Stat
                  label="Altitude acclimation"
                  value={num(data.fitness.altitude_acclimation?.metres)}
                  unit="m"
                />
                <Stat
                  label="Heat acclimation"
                  value={num(data.fitness.heat_acclimation?.percent)}
                  unit="%"
                />
              </div>
              {text("Fitness") && (
                <div className="prose">{markdown(text("Fitness")!)}</div>
              )}
              <WrittenAt when={when("Fitness")} day={monday} />
            </section>
          </div>
        )}
        </>
        )}
      </main>
    </>
  );
}
