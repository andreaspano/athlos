// La pagina Result: come **sta andando** il blocco, cioe' se il piano sta
// funzionando.
//
// Non e' l'aderenza, che dice quanto lo stai seguendo: le due misure stanno
// separate, e `docs/aderenza.md` spiega perche'. E non e' nemmeno il Goal,
// che e' il bersaglio scritto a mano: li' c'e' quello che si vuole, qui
// quello che fin qui e' successo.
//
// **Una card per goal**, come nella Goal, e dentro il blocco di quel goal in
// un grafico solo: i chilometri previsti e fatti settimana per settimana, e
// come si distribuisce la velocita' di ognuna. Un goal che blocco non ce
// l'ha — nessuna settimana scritta lo dichiara — tiene la sua card e lo dice
// in una riga: e' lo stato di un'alternativa che non si sta seguendo, non un
// guasto.
//
// Sta in prima riga nella barra, dopo Goal, e non e' una vista di Week per
// una ragione di orizzonte: una vista della Week risponde su sette giorni,
// il risultato si legge su un blocco intero — diciotto settimane, dalla
// prima al giorno di gara. La card Block era nata dentro la Week Training
// proprio per questo e da li' e' uscita (todo 96).
//
// Di viste non ne ha, quindi aprendola la barra resta a una riga sola, come
// per la Goal. Niente conti qui dentro: la specifica Vega-Lite arriva pronta
// dall'API, che e' la regola del todo 52.
import { useEffect, useState } from "react";

import { api, isAbort, type PlanSummary, type VegaSpec } from "../api/client";
import { raceLabel } from "../format";
import { useColorScheme, type ColorScheme } from "../useColorScheme";
import { CardHead } from "./Stat";
import { TopBar } from "./TopBar";
import { OneChart } from "./TrendPanels";

const API_DOWN = "Cannot reach the API. Is it running (make api)?";

// La stessa icona della Goal: la pagina risponde sulla stessa cosa, da
// un'altra parte.
const RESULT_ICON = "next.png";

/** La card di un goal: l'intestazione e il grafico del suo blocco.
 *
 * Il grafico si chiede per card e non tutti insieme all'apertura: sono
 * richieste indipendenti, e una che tarda non tiene ferme le altre. */
function GoalBlock({ plan, theme }: { plan: PlanSummary; theme: ColorScheme }) {
  // `undefined` e' "non ancora arrivato", `null` e' "questo goal non ha un
  // blocco": sono due cose diverse da dire.
  const [spec, setSpec] = useState<VegaSpec | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setSpec(undefined);
    setFailed(false);
    api
      .blockShapeChart(plan.slug, theme, controller.signal)
      .then(setSpec)
      .catch((error: unknown) => {
        if (!isAbort(error)) setFailed(true);
      });
    return () => controller.abort();
  }, [plan.slug, theme]);

  return (
    <section className="card" aria-label={plan.title}>
      <CardHead
        icon={RESULT_ICON}
        title={plan.title}
        note={
          <span className="muted">
            {plan.race ? raceLabel(plan.race) : "no race day"}
            {plan.current ? " · current" : ""}
          </span>
        }
      />
      {failed && <p className="warning">{API_DOWN}</p>}
      {spec === undefined && !failed && <p className="caption">Loading the block…</p>}
      {spec === null && (
        <p className="caption">
          No block yet: no written week in <code>summary/05.plan/</code> declares this goal.
        </p>
      )}
      {spec && (
        <OneChart chart={{ key: plan.slug, label: plan.title, spec }} theme={theme} />
      )}
    </section>
  );
}

export function ResultPage() {
  const theme = useColorScheme();
  const [plans, setPlans] = useState<PlanSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .plans(controller.signal)
      .then((list) => setPlans(list.plans))
      .catch((caught: unknown) => {
        if (!isAbort(caught)) setError(API_DOWN);
      });
    return () => controller.abort();
  }, []);

  return (
    <>
      <TopBar current="result" />
      <main className="page">
        <div className="day-header">
          <div className="day-title">
            <h1>Result</h1>
          </div>
        </div>
        {error && <p className="warning">{error}</p>}
        {plans !== null && plans.length === 0 && (
          <p className="info">
            No goals yet. A block is the weeks of <code>summary/05.plan/</code> that declare a
            goal of <code>plan/</code>: without a goal there is nothing to measure against.
          </p>
        )}
        {plans?.map((plan) => (
          <GoalBlock key={plan.slug} plan={plan} theme={theme} />
        ))}
      </main>
    </>
  );
}
