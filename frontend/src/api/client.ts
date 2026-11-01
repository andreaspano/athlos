// Le chiamate all'API (todo 32), una funzione per endpoint. I tipi vengono
// da `schema.ts`, generato dall'OpenAPI con `npm run gen:api`: qui non si
// scrive a mano nessun tipo di risposta.
import type { components } from "./schema";

type Schemas = components["schemas"];
export type Activity = Schemas["Activity"];
export type Band = Schemas["Band"];
export type ActivityDetail = Schemas["ActivityDetail"];
export type DailyData = Schemas["DailyData"];
export type Measure = Schemas["Measure"];
export type RefreshStatus = Schemas["RefreshStatus"];
export type SectionRefresh = Schemas["SectionRefresh"];
export type Report = Schemas["Report"];
export type ReportSection = Schemas["ReportSection"];
export type Plan = Schemas["Plan"];
export type PlanSummary = Schemas["PlanSummary"];
export type PlanList = Schemas["PlanList"];
export type Route = Schemas["Route"];
export type Lap = Schemas["Lap"];
export type LapList = Schemas["LapList"];
export type Sport = Schemas["Sport"];
export type SportList = Schemas["SportList"];
export type WeeklyData = Schemas["WeeklyData"];
export type TrendData = Schemas["TrendData"];
export type TrendPanel = Schemas["TrendPanel"];
export type TrendSeries = Schemas["TrendSeries"];
export type WeekTrendData = Schemas["WeekTrendData"];
export type WeekTrendPanel = Schemas["WeekTrendPanel"];
export type WeekMeasure = Schemas["WeekMeasure"];
export type WeekPlan = Schemas["WeekPlan"];
export type PlannedWeeks = Schemas["PlannedWeeks"];
export type DayPlan = Schemas["DayPlan"];
export type PlannedSession = Schemas["PlannedSession"];
export type Terrain = NonNullable<Activity["terrain"]>;
export type RunType = NonNullable<Activity["run_type"]>;

// La specifica Vega-Lite del grafico non ha un modello: e' quella di Altair.
export type VegaSpec = Record<string, unknown>;

// Un grafico del Trend (todo 55): la specifica, piu' da che misura viene.
// Scritto a mano per lo stesso motivo di `VegaSpec`: dentro c'e' una
// specifica di Altair, che un modello non ce l'ha.
export type TrendChart = { key: string; label: string; spec: VegaSpec };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    url: string,
  ) {
    super(`${url}: HTTP ${status}`);
  }
}

/** L'errore di una chiamata annullata (`AbortController`), che non e' un
 * guasto: succede a ogni cambio di giorno e a ogni smontaggio. */
export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new ApiError(response.status, url);
  return (await response.json()) as T;
}

// Le scritture dell'API: il terreno di un'attivita' a piedi (todo 35) e il
// tipo di una corsa (todo 36).
async function putJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new ApiError(response.status, url);
  return (await response.json()) as T;
}

// Il tasto Refresh (todo 41): fa partire il lavoro, senza corpo.
async function postJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { method: "POST" });
  if (!response.ok) throw new ApiError(response.status, url);
  return (await response.json()) as T;
}

// Le due scritture senza corpo della pagina Goal (todo 85): il goal attuale e
// il cestino. Rispondono con l'elenco rimasto, cosi' una chiamata fa la cosa
// e aggiorna la pagina.
async function sendNoBody<T>(url: string, method: "PUT" | "DELETE"): Promise<T> {
  const response = await fetch(url, { method });
  if (!response.ok) throw new ApiError(response.status, url);
  return (await response.json()) as T;
}

// Per gli endpoint dove il 404 vuol dire "non c'e'" (il report di un giorno,
// il grafico di un'attivita' senza dati), non un errore.
async function getOrNull<T>(
  url: string,
  signal?: AbortSignal,
): Promise<T | null> {
  try {
    return await getJson<T>(url, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function iconUrl(file: string): string {
  return `/icons/${encodeURIComponent(file)}`;
}

export const api = {
  sports: (signal?: AbortSignal) => getJson<SportList>("/api/sports", signal),

  activities: (
    start: string,
    end: string,
    sports: string[],
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams({ start, end });
    for (const sport of sports) params.append("sport", sport);
    return getJson<Activity[]>(`/api/activities?${params}`, signal);
  },

  activity: (id: number, signal?: AbortSignal) =>
    getJson<ActivityDetail>(`/api/activities/${id}`, signal),

  // `null` toglie la scelta di Andrea e torna alla stima.
  setTerrain: (id: number, terrain: Terrain | null) =>
    putJson<Activity>(`/api/activities/${id}/terrain`, { terrain }),

  // `null` toglie la scelta di Andrea e torna alla stima.
  setRunType: (id: number, run_type: RunType | null) =>
    putJson<Activity>(`/api/activities/${id}/run_type`, { run_type }),

  chartVega: (id: number, theme: "light" | "dark", signal?: AbortSignal) =>
    getOrNull<VegaSpec>(
      `/api/activities/${id}/chart/vega?theme=${theme}`,
      signal,
    ),

  route: (id: number, signal?: AbortSignal) =>
    getJson<Route>(`/api/activities/${id}/route`, signal),

  // I giri della seduta (todo 79): `structured` false, e lista vuota, per
  // una corsa libera.
  laps: (id: number, signal?: AbortSignal) =>
    getJson<LapList>(`/api/activities/${id}/laps`, signal),

  daily: (day: string, signal?: AbortSignal) =>
    getJson<DailyData>(`/api/daily/${day}`, signal),

  // I fatti di una settimana ISO (todo 52): `monday` e' sempre un lunedi'.
  weekly: (monday: string, signal?: AbortSignal) =>
    getJson<WeeklyData>(`/api/weekly/${monday}`, signal),


  // Le serie giornaliere fra due giorni compresi (todo 55). La finestra sta
  // fra 5 e 365 giorni: fuori, l'API risponde 422.
  trend: (from: string, to: string, signal?: AbortSignal) =>
    getJson<TrendData>(`/api/daily/trend?from=${from}&to=${to}`, signal),

  // I grafici di un pannello, uno per misura, gia' pronti da disegnare.
  trendCharts: (
    from: string,
    to: string,
    panel: string,
    theme: "light" | "dark",
    signal?: AbortSignal,
  ) =>
    getJson<TrendChart[]>(
      `/api/daily/trend/chart/vega?from=${from}&to=${to}&panel=${panel}&theme=${theme}`,
      signal,
    ),

  // Le serie settimana per settimana (todo 78): `to` e' un lunedi' e `weeks`
  // sta fra 4 e 52. Fuori, l'API risponde 422. Un punto per settimana: la
  // media dei giorni misurati, la somma sul pannello Training.
  weekTrend: (to: string, weeks: number, signal?: AbortSignal) =>
    getJson<WeekTrendData>(`/api/weekly/trend?to=${to}&weeks=${weeks}`, signal),

  // I grafici di un pannello settimanale. `TrendChart` e' lo stesso della
  // Day: una specifica Altair non ha un modello, su nessuno dei due periodi.
  weekTrendCharts: (
    to: string,
    weeks: number,
    panel: string,
    theme: "light" | "dark",
    signal?: AbortSignal,
  ) =>
    getJson<TrendChart[]>(
      `/api/weekly/trend/chart/vega?to=${to}&weeks=${weeks}&panel=${panel}&theme=${theme}`,
      signal,
    ),

  dailyReport: (day: string, signal?: AbortSignal) =>
    getOrNull<Report>(`/api/reports/daily/${day}`, signal),

  // Aggiorna i dati e riscrive il report del giorno, in background: lo stato
  // si segue con `refresh()`.
  startRefresh: (day: string) =>
    postJson<RefreshStatus>(`/api/reports/daily/${day}/refresh`),

  // Una sezione sola: gira il suo agente, le altre tengono il testo che hanno.
  startSectionRefresh: (day: string, section: string) =>
    postJson<RefreshStatus>(`/api/reports/daily/${day}/refresh/${section}`),

  // Il report della settimana (todo 53), composto dalle otto sezioni.
  weeklyReport: (monday: string, signal?: AbortSignal) =>
    getOrNull<Report>(`/api/reports/weekly/${monday}`, signal),

  // Riscrive la settimana, in background. Non scarica niente: la settimana
  // si scrive sui dati che ci sono.
  startWeeklyRefresh: (monday: string) =>
    postJson<RefreshStatus>(`/api/reports/weekly/${monday}/refresh`),

  startWeeklySectionRefresh: (monday: string, section: string) =>
    postJson<RefreshStatus>(`/api/reports/weekly/${monday}/refresh/${section}`),

  // Il piano della settimana (todo 60), da `summary/05.plan/`. `null` quando
  // quella settimana non ne ha uno: le settimane prima dell'inizio del blocco
  // non ce l'hanno, e non e' un errore da annunciare.
  weekPlan: (monday: string, signal?: AbortSignal) =>
    getOrNull<WeekPlan>(`/api/weekly/${monday}/plan`, signal),

  // I lunedi' che hanno un piano (todo 88): il confine fin dove la pagina
  // Week lascia andare avanti. Una volta sola all'apertura — i file cambiano
  // quando qualcuno lancia `make week_plans`, non mentre si guarda la pagina.
  plannedWeeks: (signal?: AbortSignal) =>
    getJson<PlannedWeeks>("/api/weekly/planned", signal),

  // La seduta prevista per un giorno (todo 63), dallo stesso file. `null`
  // quando per quel giorno un piano non c'e': i giorni fuori da un blocco, e
  // le settimane il cui file e' piu' vecchio del front matter.
  dayPlan: (day: string, signal?: AbortSignal) =>
    getOrNull<DayPlan>(`/api/daily/${day}/plan`, signal),

  // I piani di `plan/`, la gara piu' vicina per prima, senza il testo.
  plans: (signal?: AbortSignal) => getJson<PlanList>("/api/plans", signal),

  // Un piano col suo testo. `null` quando lo slug non e' fra i file: capita
  // con un link vecchio, o con un piano rinominato.
  plan: (slug: string, signal?: AbortSignal) =>
    getOrNull<Plan>(`/api/plans/${encodeURIComponent(slug)}`, signal),

  // Fa di questo il goal attuale (todo 85): scrive `current: true` nel suo
  // file e lo toglie dagli altri. **Non rigenera i piani settimanali**, e
  // l'`ahead` della risposta e' quello che lo dice.
  setCurrentPlan: (slug: string) =>
    sendNoBody<PlanList>(`/api/plans/${encodeURIComponent(slug)}/current`, "PUT"),

  // Sposta il goal nel cestino (`plan/.trash/`), non lo cancella.
  deletePlan: (slug: string) =>
    sendNoBody<PlanList>(`/api/plans/${encodeURIComponent(slug)}`, "DELETE"),

  // Lo stato del lavoro in corso, di qualunque tipo: `kind` dice se e' il
  // report di un giorno o di una settimana, e le chiavi delle sezioni
  // dipendono da quello.
  refresh: (signal?: AbortSignal) =>
    getJson<RefreshStatus>("/api/refresh", signal),
};
