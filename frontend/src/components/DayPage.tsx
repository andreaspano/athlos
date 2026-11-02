// La pagina Day (todo 34), sul mockup `todo/assets/34_day_mockup.jpeg`: un
// giorno alla volta, con l'intestazione e la striscia della settimana in
// comune fra le viste.
//
// **Dal todo 66 le viste hanno un soggetto ciascuna.** Lo **Snap** e' il
// corpo: il Summary in cima e la griglia 2x2 (todo 37) con Health e Load
// sopra, Recovery e Fitness sotto. La Training e' la seduta: il piano, i
// dati, il giudizio. Il Trend sono i grafici della finestra scelta col
// cursore (todo 55). Prima lo Snap si chiamava Report e teneva anche il
// riquadro "Next" e un verdetto in due pezzi, e la seduta aveva il commento
// dentro.
//
// I numeri vengono da `/api/daily/{day}` e `/api/activities`, i testi dalle
// sezioni del report giornaliero. Il tasto Refresh (todo 41) aggiorna i dati e
// riscrive il report: alla fine la pagina li richiede.
//
// Il giorno sta nell'URL (`?day=2026-10-07`): un giorno si apre da un link e
// il tasto indietro torna a quello prima. Senza router: `URLSearchParams` e
// `history.pushState`.
//
// Le viste le sceglie il menu con `?view=` (todo 55 e 62). L'intestazione e
// la scelta del giorno sono le stesse, che il giorno serve a tutte.
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, isAbort, type Activity, type DailyData, type DayPlan, type RefreshStatus, type Report, type SportList } from "../api/client";
import { addDays, dayOf, today } from "../format";
import { preamble, sectionBody, sectionIcon, sectionVerdict, sectionWrittenAt } from "../markdown";
import { ETICHETTE, daysFromUrl, type View } from "../navigation";
import { useColorScheme } from "../useColorScheme";
import { DayHeader } from "./DayHeader";
import { DayPlanCard } from "./DayPlanCard";
import { FitnessCard } from "./FitnessCard";
import { HealthCard } from "./HealthCard";
import { LoadCard } from "./LoadCard";
import { RecoveryCard } from "./RecoveryCard";
import { SectionRefresh } from "./SectionRefresh";
import { SummaryCard } from "./SummaryCard";
import { TopBar } from "./TopBar";
import { TrainingCard } from "./TrainingCard";
import { TrainingCommentCard } from "./TrainingCommentCard";
import { TrendPanels } from "./TrendPanels";
import { WeekStrip } from "./WeekStrip";

// La striscia: otto giorni. Finisce oggi finche' il giorno scelto ci sta
// dentro; per un giorno piu' vecchio finisce qualche giorno dopo di lui, cosi'
// si vede anche cosa e' venuto dopo.
const STRIP_DAYS = 8;
const STRIP_AFTER = 3;

const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** Il giorno dell'URL, se e' una data valida e non nel futuro; se no oggi. */
function dayFromUrl(now: string): string {
  const day = new URLSearchParams(window.location.search).get("day");
  if (!day || !DAY_PATTERN.test(day) || Number.isNaN(Date.parse(day)) || day > now) return now;
  return day;
}

function stripRange(day: string, now: string): [string, string] {
  const end = day >= addDays(now, -(STRIP_DAYS - 1)) ? now : addDays(day, STRIP_AFTER);
  return [addDays(end, -(STRIP_DAYS - 1)), end];
}

const API_DOWN = "Cannot reach the API. Is it running (make api)?";

// Ogni quanto si chiede lo stato del Refresh mentre gira.
const REFRESH_POLL_MS = 3000;

export function DayPage({ view = "snap" }: { view?: View }) {
  const theme = useColorScheme();
  const now = today();
  const [day, setDay] = useState(() => dayFromUrl(now));
  const [days, setDays] = useState(() => daysFromUrl());
  const [sportList, setSportList] = useState<SportList | null>(null);
  const [stripActivities, setStripActivities] = useState<Activity[]>([]);
  const [data, setData] = useState<DailyData | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<DayPlan | null>(null);
  const [planLoading, setPlanLoading] = useState(true);
  const [refresh, setRefresh] = useState<RefreshStatus | null>(null);
  // Sale a ogni Refresh finito bene: dati e report si richiedono.
  const [reloads, setReloads] = useState(0);
  // Un errore del Refresh si mostra solo se questa pagina l'ha visto girare,
  // non per un lavoro fallito ore prima.
  const [watched, setWatched] = useState(false);
  const [stripStart, stripEnd] = stripRange(day, now);

  // Il tasto di una card: rifa' solo quella sezione, le altre tengono il
  // testo che hanno. Lo stato arriva dallo stesso `GET /api/refresh`.
  const refreshSection = (section: string) => {
    api
      .startSectionRefresh(day, section)
      .then((status) => {
        setWatched(true);
        setRefresh(status);
      })
      .catch(() => setError(API_DOWN));
  };

  const sectionButton = (key: string) => (
    <SectionRefresh section={key} state={refresh?.sections?.[key]} onRefresh={refreshSection} />
  );

  const startRefresh = () => {
    api
      .startRefresh(day)
      .then((status) => {
        setWatched(true);
        setRefresh(status);
      })
      .catch(() => setError(API_DOWN));
  };

  const changeDay = (next: string) => {
    if (next === day || next > now) return;
    const url = new URL(window.location.href);
    url.searchParams.set("day", next);
    window.history.pushState({ day: next }, "", url);
    setDay(next);
  };

  // L'ampiezza del Trend va nell'URL, cosi' un link se la porta dietro, ma
  // **senza lasciare una voce nella cronologia**: il cursore ne
  // attraverserebbe decine, e il tasto indietro non tornerebbe piu' al
  // giorno di prima.
  const changeDays = useCallback((next: number) => {
    const url = new URL(window.location.href);
    url.searchParams.set("days", String(next));
    window.history.replaceState(window.history.state, "", url);
    setDays(next);
  }, []);

  useEffect(() => {
    const onPop = () => {
      setDay(dayFromUrl(today()));
      setDays(daysFromUrl());
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    api
      .sports(controller.signal)
      .then(setSportList)
      .catch((e: unknown) => !isAbort(e) && setError(API_DOWN));
    return () => controller.abort();
  }, []);

  // Lo stato del lavoro, **solo se e' di questo tipo**: giorno e settimana
  // condividono un lavoro alla volta e lo chiedono allo stesso
  // `GET /api/refresh`, ma le sezioni hanno gli stessi nomi, quindi uno
  // stato settimanale qui non da' nessun errore — si limita a mentire. La
  // domenica alle 21 il giro della settimana accendeva lo spinner
  // dell'intestazione, i badge sulle card del giorno ("Rewriting the health
  // section..."), il banner "Refresh of <lunedi> failed" davanti a chi
  // guardava un altro giorno, e il ricaricamento alla fine. `WeekPage` la
  // guardia ce l'ha da sempre; questa e' la stessa, dall'altro lato.
  useEffect(() => {
    const controller = new AbortController();
    api
      .refresh(controller.signal)
      .then((status) => {
        if (status.kind !== "daily") return;
        if (status.status === "running") setWatched(true);
        setRefresh(status);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const running = refresh?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      api
        .refresh()
        .then((status) => {
          if (status.kind !== "daily") return;
          setRefresh(status);
          if (status.status === "done") setReloads((n) => n + 1);
        })
        .catch(() => undefined);
    }, REFRESH_POLL_MS);
    return () => window.clearInterval(timer);
  }, [running]);

  useEffect(() => {
    const controller = new AbortController();
    api
      .activities(stripStart, stripEnd, [], controller.signal)
      .then((list) => {
        setError(null);
        setStripActivities(list);
      })
      .catch((e: unknown) => !isAbort(e) && setError(API_DOWN));
    return () => controller.abort();
  }, [stripStart, stripEnd, reloads]);

  // I dati del giorno e il report servono allo Snap e al Training, che la
  // card della seduta ha dentro il testo della sua sezione; il Trend no, che
  // ha i suoi pannelli e la sua finestra.
  useEffect(() => {
    if (view === "trend") return;
    const controller = new AbortController();
    setData(null);
    setReport(null);
    api
      .daily(day, controller.signal)
      .then(setData)
      .catch((e: unknown) => !isAbort(e) && setError(API_DOWN));
    api
      .dailyReport(day, controller.signal)
      .then(setReport)
      .catch((e: unknown) => !isAbort(e) && setError(API_DOWN));
    return () => controller.abort();
  }, [day, reloads, view]);

  // La seduta prevista (todo 63), solo sulla vista che la mostra. Un giorno
  // senza piano rende `null`, che qui vuol dire "non ce n'e' uno" e non "non
  // si e' potuto chiedere": `planLoading` tiene separate le due cose, cosi'
  // la card non annuncia un piano mancante mentre lo cerca.
  useEffect(() => {
    if (view !== "training") return;
    const controller = new AbortController();
    setPlan(null);
    setPlanLoading(true);
    api
      .dayPlan(day, controller.signal)
      .then((found) => {
        setPlan(found);
        setPlanLoading(false);
      })
      .catch((e: unknown) => {
        if (isAbort(e)) return;
        setPlanLoading(false);
        setError(API_DOWN);
      });
    return () => controller.abort();
  }, [day, view]);

  // Lo Snap e' la vista di partenza e non si nomina, come non si nomina
  // nell'URL; le altre prendono la loro etichetta dal menu, cosi' il nome e'
  // scritto in un posto solo.
  useEffect(() => {
    document.title =
      view === "snap" ? `Training · ${day}` : `Training · ${day} · ${ETICHETTE[view]}`;
  }, [day, view]);

  const dayActivities = useMemo(
    () =>
      stripActivities
        .filter((a) => dayOf(a.start_time) === day)
        .sort((a, b) => a.start_time.localeCompare(b.start_time)),
    [stripActivities, day],
  );

  const sportIcons = useMemo(
    () => new Map((sportList?.sports ?? []).map((s) => [s.sport, s.icon ?? null])),
    [sportList],
  );
  const sport = {
    label: (key: string | null | undefined) => sportList?.sports.find((s) => s.sport === key)?.label ?? key ?? "?",
    icon: (key: string | null | undefined) => sportIcons.get(key ?? "") ?? null,
  };
  const dataNote = preamble(report);

  return (
    <>
      <TopBar view={view} />
      <main className="page">
        <DayHeader
          day={day}
          maxDay={now}
          onChange={changeDay}
          refreshing={running ? (refresh?.started ?? null) : null}
          onRefresh={startRefresh}
        >
          <WeekStrip
            start={stripStart}
            end={stripEnd}
            selected={day}
            today={now}
            activities={stripActivities}
            sportIcons={sportIcons}
            restIcon={sportList?.rest_icon ?? null}
            onSelect={changeDay}
          />
        </DayHeader>
        {error && <p className="warning">{error}</p>}
        {watched && refresh?.status === "failed" && (
          <p className="warning multiline">
            Refresh of {refresh.day} failed: {refresh.message}
          </p>
        )}
        {/* Lo scaricamento che fallisce non ferma il lavoro: il testo si
            scrive sui dati che ci sono gia'. Ma va detto, perche' da quando
            a lanciare sono i timer non c'e' nessuno a guardare (todo 47). */}
        {watched && refresh?.download && !refresh.download.ok && (
          <p className="warning multiline">
            Garmin was not reached: the text of {refresh.day} was written on the data already here.
            {refresh.download.message && ` ${refresh.download.message}`}
          </p>
        )}
        {/* Tre viste, tre guardie: il ternario reggeva finche' erano due.
            Intestazione e avvisi stanno fuori, che servono a tutte. */}
        {view === "trend" && (
          <TrendPanels day={day} days={days} onDays={changeDays} theme={theme} />
        )}
        {view === "training" && (
          <>
            {/* Prima quello che era previsto, poi quello che si e' fatto. */}
            <DayPlanCard
              plan={plan}
              day={day}
              loading={planLoading}
              sport={sport}
              restIcon={sportList?.rest_icon ?? null}
            />
            <TrainingCard
              activities={dayActivities}
              data={data}
              icon={sectionIcon(report, "Training")}
              restIcon={sportList?.rest_icon ?? null}
              sport={sport}
              theme={theme}
            />
            {/* Il giudizio sotto i dati: guarda il piano sopra e la seduta
                che ha appena sopra di se'. */}
            <TrainingCommentCard
              comment={sectionBody(report, "Training")}
              writtenAt={sectionWrittenAt(report, "Training")}
              day={day}
              face={sectionVerdict(report, "Training")}
              refresh={sectionButton("training")}
            />
          </>
        )}
        {view === "snap" && (
        <>
        {/* Il verdetto a tutta larghezza sopra la griglia. La riga a due
            colonne che c'era qui e' sparita col todo 66, quando Next e'
            uscito dal giorno, e la regola CSS col todo 68, quando anche la
            Week ha smesso di usarla. */}
        <SummaryCard
          day={day}
          face={data?.scores.summary ?? null}
          morning={{
            body: sectionBody(report, "Summary"),
            writtenAt: sectionWrittenAt(report, "Summary"),
            refresh: sectionButton("summary"),
          }}
        />
        {data ? (
          <div className="cards-grid">
            <HealthCard
              data={data}
              text={sectionBody(report, "Health")}
              writtenAt={sectionWrittenAt(report, "Health")}
              day={day}
              icon={sectionIcon(report, "Health")}
              face={data.scores.health}
              refresh={sectionButton("health")}
            />
            <LoadCard
              data={data}
              text={sectionBody(report, "Load")}
              writtenAt={sectionWrittenAt(report, "Load")}
              day={day}
              icon={sectionIcon(report, "Load")}
              face={data.scores.load}
              refresh={sectionButton("load")}
            />
            <RecoveryCard
              data={data}
              text={sectionBody(report, "Recovery")}
              writtenAt={sectionWrittenAt(report, "Recovery")}
              day={day}
              icon={sectionIcon(report, "Recovery")}
              face={data.scores.recovery}
              refresh={sectionButton("recovery")}
            />
            <FitnessCard
              data={data}
              text={sectionBody(report, "Fitness")}
              writtenAt={sectionWrittenAt(report, "Fitness")}
              day={day}
              icon={sectionIcon(report, "Fitness")}
              face={data.scores.fitness}
              refresh={sectionButton("fitness")}
            />
          </div>
        ) : (
          !error && <p className="caption">Loading…</p>
        )}
        {dataNote && <p className="caption">{dataNote}</p>}
        </>
        )}
      </main>
    </>
  );
}
