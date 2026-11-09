// La card Block (todo 96): la **risposta**, cioe' quanto il piano sta
// funzionando — che non e' l'aderenza, cioe' quanto lo stai seguendo. Le due
// misure stanno separate anche a schermo, come dice `docs/aderenza.md`:
// l'aderenza sono due numeri in cima alla card del piano, questa e' un
// grafico in fondo alla vista.
//
// Tre pannelli, uno per KPI — quanto corri, quanto a lungo, quanto in fretta
// — sulla stessa scala, da zero a quello che la gara chiede. Ogni settimana
// porta la sua barra (previsto a contorno, fatto piena) e sopra corrono la
// linea del migliore finora e il tratteggio del tempo trascorso.
//
// Niente conti qui dentro: percentuali, cricchetti e specifiche Vega-Lite
// arrivano pronti dall'API, che e' la regola del todo 52.
import { useEffect, useState } from "react";

import { api, isAbort, type BlockProgress, type TrendChart } from "../api/client";
import type { ColorScheme } from "../useColorScheme";
import { CardHead } from "./Stat";
import { OneChart } from "./TrendPanels";

export function WeekBlockCard({
  monday,
  theme,
  icon,
}: {
  monday: string;
  theme: ColorScheme;
  icon: string | null;
}) {
  const [data, setData] = useState<BlockProgress | null>(null);
  const [charts, setCharts] = useState<TrendChart[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setData(null);
    setCharts(null);
    Promise.all([
      api.block(monday, controller.signal),
      api.blockCharts(monday, theme, controller.signal),
    ])
      .then(([found, specs]) => {
        setData(found);
        setCharts(specs);
        setLoading(false);
      })
      .catch((error) => {
        // Il 404 non arriva qui: `getOrNull` lo rende `null`, che qui vuol
        // dire "questa settimana non sta in un blocco" e non "non si e'
        // potuto chiedere". Resta l'API giu', e di quella se ne occupa gia'
        // l'avviso in cima alla pagina.
        if (isAbort(error)) return;
        setLoading(false);
      });
    return () => controller.abort();
  }, [monday, theme]);

  // Fuori da un blocco la card non c'e': una settimana prima che cominciasse
  // non ha niente da mostrare, e una cornice vuota si legge come un guasto.
  if (loading || !data || !charts) return null;

  const week = data.weeks.find((w) => w.block_week === data.block_week);
  return (
    <section className="card block-card" aria-label="Block">
      <CardHead icon={icon} title="Block" />
      <p className="caption block-week-note">
        Week <strong>{data.block_week}</strong> of {data.block_weeks}
        {week?.phase ? ` · ${week.phase}` : ""}
        {data.title ? ` · ${data.title}` : ""}
      </p>
      <div className="block-panels">
        {charts.map((chart) => (
          <OneChart key={chart.key} chart={chart} theme={theme} />
        ))}
      </div>
      <p className="caption">
        Bars are one week each: outline is what the plan asked for, filled is what was
        done. The line is the best reached so far, so it never falls when a cutback week
        does. The dashed line is elapsed time, from the start line to the race — the
        plan's own climb is steeper than it, and finishes before the race.
      </p>
    </section>
  );
}
