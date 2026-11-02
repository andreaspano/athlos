// Il Trend della Week (todo 78): la fila delle settimane, un punto per
// settimana ISO, in una finestra che si sceglie col cursore da 4 a 52.
//
// E' il gemello del Trend della Day, e il meccanismo e' letteralmente lo
// stesso: `OneChart`, `Panel`, `TrendWindow` e i cinque pannelli vengono da
// li'. Qui dentro sta solo quello che cambia: l'ampiezza in settimane,
// l'intervallo scritto per settimane, e dove porta un clic.
//
// Niente conti: medie, somme, fasce e specifiche Vega-Lite arrivano pronte
// dall'API, come per la Day.
import { useCallback, useEffect, useState } from "react";

import { api, isAbort, type PanelCharts, type WeekTrendData } from "../api/client";
import { addDays, isoWeek, mondayOf, shortDayLabel } from "../format";
import { MAX_WEEKS, MIN_WEEKS, pushUrl } from "../navigation";
import type { ColorScheme } from "../useColorScheme";
import { PANELS, Panel, TrendWindow } from "./TrendPanels";

/** Il lunedi' della prima settimana della finestra. */
function startOf(monday: string, weeks: number): string {
  return addDays(monday, -(weeks - 1) * 7);
}

/** Gli estremi della finestra a settimane, "W33 10 Aug - W44 26 Oct". Il
 * numero della settimana sta davanti alla sua data, che qui l'unita' e' la
 * settimana e il lunedi' e' solo il modo di nominarla. L'anno compare sul
 * primo estremo quando la finestra lo scavalca, come nella Day. */
function weekRangeLabel(from: string, to: string): string {
  const anno = from.slice(0, 4) === to.slice(0, 4) ? "" : ` ${from.slice(0, 4)}`;
  return `W${isoWeek(from)} ${shortDayLabel(from)}${anno} \u2013 W${isoWeek(to)} ${shortDayLabel(to)}`;
}

/** Il lunedi' **piu' vicino** al giorno cliccato, che e' la settimana che la
 * barra grigia sta indicando.
 *
 * Non `mondayOf`: i punti di questa vista sono lunedi' distanti sette giorni,
 * e la barra segue il punto piu' vicino (`nearest`). Cliccando da giovedi' in
 * poi `mondayOf` aprirebbe la settimana **prima** di quella evidenziata. E' lo
 * stesso motivo per cui `dayAt` arrotonda al giorno vicino invece che a quello
 * in cui il clic e' caduto. */
function nearestMonday(day: string): string {
  const monday = mondayOf(day);
  const avanti = Math.round((Date.parse(day) - Date.parse(monday)) / 86400000);
  return avanti >= 4 ? addDays(monday, 7) : monday;
}

export function WeekTrendPanels({
  monday,
  weeks,
  onWeeks,
  theme,
}: {
  monday: string;
  weeks: number;
  onWeeks: (weeks: number) => void;
  theme: ColorScheme;
}) {
  const [data, setData] = useState<WeekTrendData | null>(null);
  const [charts, setCharts] = useState<PanelCharts[] | null>(null);
  const [failed, setFailed] = useState(false);

  // Un clic apre lo Snap di quella settimana, senza ricaricare la pagina.
  // Mai oltre la settimana in corso, che l'API quella la rifiuta.
  const onPick = useCallback((day: string) => {
    const scelto = nearestMonday(day);
    const corrente = mondayOf(new Date().toISOString().slice(0, 10));
    pushUrl({ period: "week", page: null, monday: scelto > corrente ? corrente : scelto, view: null });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    api
      .weekTrend(monday, weeks, controller.signal)
      .then(setData)
      .catch((e: unknown) => !isAbort(e) && console.error(e));
    return () => controller.abort();
  }, [monday, weeks]);

  // I grafici dei cinque pannelli, in una richiesta (vedi `Panel`).
  useEffect(() => {
    const controller = new AbortController();
    setCharts(null);
    setFailed(false);
    api
      .weekTrendCharts(monday, weeks, theme, controller.signal)
      .then(setCharts)
      .catch((e: unknown) => {
        if (!isAbort(e)) {
          console.error(e);
          setFailed(true);
        }
      });
    return () => controller.abort();
  }, [monday, weeks, theme]);

  // Serve solo a dare a ogni pannello il suo titolo e la sua icona: i numeri
  // delle serie stanno nelle specifiche Vega, che arrivano gia' disegnate.
  const heads = new Map((data?.panels ?? []).map((p) => [p.key, p]));
  const byPanel = new Map((charts ?? []).map((p) => [p.key, p.charts]));

  return (
    <>
      <TrendWindow
        min={MIN_WEEKS}
        max={MAX_WEEKS}
        value={weeks}
        onChange={onWeeks}
        label={(pending) => `${pending} weeks`}
        range={(pending) => weekRangeLabel(startOf(monday, pending), monday)}
      />
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
