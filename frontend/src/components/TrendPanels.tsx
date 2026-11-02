// Il Trend della Day (todo 55): le misure giorno per giorno in una finestra
// che si sceglie col cursore, da 5 a 365 giorni.
//
// Dal todo 78 i pezzi che non guardano il calendario — il riquadro di un
// grafico, quello di un pannello, il cursore con la sua pausa — stanno qui ma
// **servono tutti e due i periodi**: `WeekTrendPanels` li importa e ci mette
// la sua copia. Il meccanismo e' lo stesso, le parole no: quelle cambiano
// abbastanza da non volere cinque ternari dentro un componente solo.
//
// Un grafico **per misura** e non per pannello: dentro un pannello le unita'
// non sono le stesse (il VO2max sta a 42, il punteggio di resistenza a
// 5000), e su un asse solo la linea bassa verrebbe piatta. I pannelli sono
// nell'ordine delle card dello Snap: le stesse cose nello stesso ordine,
// disegnate invece che raccontate.
//
// Niente conti qui dentro: le serie, le fasce e le specifiche Vega-Lite
// arrivano gia' pronte dall'API, come per `RunChart` e `WeekChart`.
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { Result, VisualizationSpec } from "vega-embed";

import {
  api,
  iconUrl,
  isAbort,
  type PanelCharts,
  type TrendChart,
  type TrendData,
} from "../api/client";
import { addDays, shortDayLabel } from "../format";
import { MAX_DAYS, MIN_DAYS, pushUrl } from "../navigation";
import type { ColorScheme } from "../useColorScheme";
import { themeConfig } from "./RunChart";

// Quanto si aspetta che il cursore stia fermo prima di chiedere: senza,
// trascinandolo partirebbe una richiesta per ogni valore attraversato.
const SETTLE_MS = 250;

const DAY_MS = 24 * 60 * 60 * 1000;

// Gli stessi cinque pannelli per la Day e per la Week, nello stesso ordine:
// quello delle card dello Snap.
export const PANELS = ["health", "recovery", "load", "fitness", "training"] as const;

/** Il primo giorno della finestra: `to` meno l'ampiezza, estremi compresi. */
function startOf(to: string, days: number): string {
  return addDays(to, -(days - 1));
}

/** Gli estremi della finestra, "28 Sep - 25 Oct". Con l'anno sul primo
 * quando la finestra lo scavalca: a 365 giorni "26 Oct - 25 Oct" sembrava
 * un intervallo di un giorno. */
export function rangeLabel(from: string, to: string): string {
  const anno = from.slice(0, 4) === to.slice(0, 4) ? "" : ` ${from.slice(0, 4)}`;
  return `${shortDayLabel(from)}${anno} \u2013 ${shortDayLabel(to)}`;
}

/** Il giorno sotto il cursore, da un clic nel grafico.
 *
 * Non si guarda **su quale segno** si e' cliccato: a 365 giorni la linea e'
 * spessa due pixel e i pallini non ci sono nemmeno, e colpirli sarebbe un
 * gioco di mira. Si prende invece la x del clic e si chiede alla scala che
 * giorno sia (`scale.invert`), cosi' vale tutta l'altezza della colonna di
 * quel giorno, a qualunque ampiezza.
 *
 * `null` se il clic cade fuori dall'area disegnata (sui numeri dell'asse,
 * nel margine) o se la scala non e' ancora pronta. */
function dayAt(view: Result["view"], box: HTMLElement, event: MouseEvent): string | null {
  const scale = view.scale("x");
  const plot = box.querySelector("svg")?.getBoundingClientRect();
  if (!scale || !plot) return null;
  const [originX] = view.origin();
  const x = event.clientX - plot.left - originX;
  const [from, to] = scale.range() as [number, number];
  if (x < from || x > to) return null;
  const value = scale.invert(x) as Date;
  if (!(value instanceof Date) || Number.isNaN(value.getTime())) return null;
  // Il giorno locale, non quello UTC: `toISOString` su una mezzanotte
  // italiana d'estate tornerebbe il giorno prima.
  //
  // E il **piu' vicino**, non quello in cui si e' caduti: la barra grigia
  // sceglie per vicinanza (`nearest` nella specifica), e un clic deve
  // aprire il giorno che la barra sta indicando, non quello prima.
  const ms = value.getTime() - value.getTimezoneOffset() * 60000;
  const giorno = new Date(Math.round(ms / DAY_MS) * DAY_MS);
  return giorno.toISOString().slice(0, 10);
}

export function OneChart({
  chart,
  theme,
  onPick,
}: {
  chart: TrendChart;
  theme: ColorScheme;
  // Il giorno su cui si e' cliccato, letto dalla scala. Dove va a finire lo
  // decide chi usa il componente: la Day apre quel giorno, la Week la
  // settimana del lunedi' piu' vicino.
  onPick: (day: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let view: Result | null = null;
    let cancelled = false;
    setFailed(false);
    void (async () => {
      try {
        const { default: embed } = await import("vega-embed");
        if (cancelled || !box.current) return;
        view = await embed(box.current, chart.spec as VisualizationSpec, {
          actions: false,
          renderer: "svg",
          config: themeConfig(theme),
        });
        if (cancelled) {
          view.finalize();
          return;
        }
        // Un clic nel grafico apre lo Snap del periodo cliccato.
        view.view.addEventListener("click", (event) => {
          if (!box.current || !view) return;
          const day = dayAt(view.view, box.current, event as MouseEvent);
          if (day) onPick(day);
        });
      } catch (error) {
        console.error(error);
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      view?.finalize();
    };
  }, [chart, theme, onPick]);

  return (
    <figure className="trend-chart">
      {failed && <p className="warning">The chart could not be drawn.</p>}
      <div ref={box} className="chart-box" />
    </figure>
  );
}

export function Panel({
  title,
  icon,
  charts,
  error,
  theme,
  onPick,
}: {
  title: string;
  icon: string | null;
  // I grafici di questo pannello, `null` finche' non sono arrivati. **Non li
  // chiede lui**: una richiesta sola per la pagina li porta tutti, e il
  // genitore li distribuisce. Chiedendoli per pannello la finestra dietro le
  // serie si calcolava cinque volte e le cinque corse di Altair si
  // contendevano il GIL nei thread del server.
  charts: TrendChart[] | null;
  error: boolean;
  theme: ColorScheme;
  onPick: (day: string) => void;
}) {
  return (
    <section className="card trend-panel" aria-label={title}>
      <div className="trend-head">
        {icon && <img src={iconUrl(icon)} alt="" width={26} height={26} />}
        <h2>{title}</h2>
      </div>
      {error && <p className="warning">The charts could not be loaded.</p>}
      {!error && charts === null && <p className="caption">Loading…</p>}
      {charts !== null && charts.length === 0 && (
        <p className="caption">Nothing measured in this window.</p>
      )}
      <div className="trend-grid">
        {(charts ?? []).map((chart) => (
          <OneChart key={chart.key} chart={chart} theme={theme} onPick={onPick} />
        ))}
      </div>
    </section>
  );
}

/** Il cursore della finestra, con la pausa prima di chiedere.
 *
 * E' il pezzo non ovvio di questa vista, e deve esistere una volta sola:
 * `pending` e' dove sta la manopola e si muove subito, `value` e' quello che
 * e' gia' stato chiesto, e fra i due c'e' `SETTLE_MS`. Senza, trascinando il
 * cursore partirebbe una richiesta per ogni valore attraversato - decine, con
 * cinque pannelli ridisegnati ogni volta.
 *
 * `onChange` deve essere stabile (`useCallback`), che sta in un effetto. */
export function TrendWindow({
  min,
  max,
  value,
  onChange,
  label,
  range,
  children,
}: {
  min: number;
  max: number;
  value: number;
  onChange: (value: number) => void;
  // Come si legge l'ampiezza ("28 days", "12 weeks") e l'intervallo sotto.
  label: (pending: number) => string;
  range: (pending: number) => string;
  // Quello che si disegna sotto il cursore, che sa gia' il valore in sospeso.
  children?: (pending: number) => ReactNode;
}) {
  const [pending, setPending] = useState(value);

  useEffect(() => setPending(value), [value]);

  useEffect(() => {
    if (pending === value) return;
    const timer = window.setTimeout(() => onChange(pending), SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [pending, value, onChange]);

  return (
    <>
      <div className="trend-window">
        <label className="trend-slider">
          <span className="caption">Window</span>
          <input
            type="range"
            min={min}
            max={max}
            value={pending}
            onChange={(e) => setPending(Number(e.target.value))}
            aria-label="Window shown"
          />
        </label>
        <p className="caption trend-range">
          <strong>{label(pending)}</strong> · {range(pending)}
        </p>
      </div>
      {children?.(pending)}
    </>
  );
}

export function TrendPanels({
  day,
  days,
  onDays,
  theme,
}: {
  day: string;
  days: number;
  onDays: (days: number) => void;
  theme: ColorScheme;
}) {
  const [data, setData] = useState<TrendData | null>(null);
  const [charts, setCharts] = useState<PanelCharts[] | null>(null);
  const [failed, setFailed] = useState(false);

  const from = startOf(day, days);

  // Un clic apre lo Snap di quel giorno. `pushUrl` avvisa chi segue l'URL,
  // quindi la pagina si scambia da sola senza ricaricare, e il tasto indietro
  // torna al Trend.
  const onPick = useCallback((picked: string) => pushUrl({ day: picked, view: null }), []);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    api
      .trend(from, day, controller.signal)
      .then(setData)
      .catch((e: unknown) => !isAbort(e) && console.error(e));
    return () => controller.abort();
  }, [from, day]);

  // I grafici di tutti e cinque i pannelli, in una richiesta.
  useEffect(() => {
    const controller = new AbortController();
    setCharts(null);
    setFailed(false);
    api
      .trendCharts(from, day, theme, controller.signal)
      .then(setCharts)
      .catch((e: unknown) => {
        if (!isAbort(e)) {
          console.error(e);
          setFailed(true);
        }
      });
    return () => controller.abort();
  }, [from, day, theme]);

  // Le fasce vogliono un minimo di giorni misurati: sotto non si disegnano,
  // e senza una riga che lo dica sembra che manchi meta' del grafico.
  const minBand = data?.min_band_days ?? 14;
  const heads = new Map((data?.panels ?? []).map((p) => [p.key, p]));
  const byPanel = new Map((charts ?? []).map((p) => [p.key, p.charts]));

  return (
    <>
      <TrendWindow
        min={MIN_DAYS}
        max={MAX_DAYS}
        value={days}
        onChange={onDays}
        label={(pending) => `${pending} days`}
        range={(pending) => rangeLabel(startOf(day, pending), day)}
      >
        {(pending) =>
          pending < minBand ? (
            <p className="caption">
              Under {minBand} measured days there is no band: the lines are drawn on their own.
            </p>
          ) : null
        }
      </TrendWindow>
      {PANELS.map((panel) => (
        <Panel
          key={panel}
          title={heads.get(panel)?.title ?? panel}
          icon={heads.get(panel)?.icon ?? null}
          charts={charts === null ? null : (byPanel.get(panel) ?? [])}
          error={failed}
          theme={theme}
          onPick={onPick}
        />
      ))}
    </>
  );
}
