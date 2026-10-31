// Il piano della settimana (todo 60): la vista Plan della Week.
//
// Il file e' `summary/05.plan/<lunedi>.md`, uno per settimana del blocco. Lo
// scriveva solo l'agente Next, dentro il prompt, e all'utente arrivava di
// rimbalzo nella prosa di qualcun altro: qui si legge per quello che e', le
// sette sedute della settimana con i ritmi e i segnali per scaricare.
//
// **Non e' il piano di `plan/`**, che sta nella pagina a destra: quello dura
// un blocco e parla di una gara, questo dura sette giorni e dice cosa fare.
// I numeri in cima li tiene insieme: da che blocco viene, a che settimana
// siamo, quale gara e con che bersaglio.
//
// Una settimana senza file non e' un errore — prima dell'inizio del blocco
// non ce n'e' nessuno — e la vista lo dice invece di restare muta.
import { iconUrl, type PlannedSession, type WeekPlan } from "../api/client";
import { addDays, raceLabel, shortDayLabel, targetLabel, weekdayShort } from "../format";
import { markdown } from "../markdown";
import { sessionIcon, sessionLabel, type Sport } from "./PlanSession";
import { CardHead, Stat, WrittenAt } from "./Stat";

// L'icona di Next, come nella pagina Plan: il riquadro che dice cosa fare
// dopo. Un piano e' la stessa domanda, su sette giorni invece che su domani.
const PLAN_ICON = "next.png";

/** I numeri del piano, sopra il testo: dove sta questa settimana nel blocco e
 * verso cosa. Quelli che il front matter non ha restano un trattino, come in
 * tutte le altre card.
 *
 * Tutti e quattro **su una riga sola** (`stats four`, la stessa griglia della
 * card Training): si leggono come una didascalia del titolo — fase, settimana
 * del blocco, gara, bersaglio — e su due righe la griglia a tre colonne ne
 * lasciava uno spaiato in fondo. */
function WeekPlanStats({ plan }: { plan: WeekPlan }) {
  const of =
    plan.block_week != null && plan.block_weeks != null
      ? `${plan.block_week} of ${plan.block_weeks}`
      : plan.block_week != null
        ? `${plan.block_week}`
        : "–";
  return (
    <div className="stats four">
      <Stat label="Phase" value={plan.phase ?? "–"} />
      <Stat
        label="Block week"
        value={of}
        sub={plan.plan ? <span className="muted">{plan.plan}</span> : undefined}
      />
      <Stat label="Race" value={plan.race ? raceLabel(plan.race) : "–"} />
      <Stat label="Target" value={targetLabel(plan.target_time)} />
    </div>
  );
}

export function WeekPlanCard({
  plan,
  monday,
  loading,
}: {
  plan: WeekPlan | null;
  monday: string;
  loading: boolean;
}) {
  if (plan === null) {
    // Finche' la chiamata e' in volo non si dice ancora che il piano non
    // c'e': "Loading…" e "no plan" sono due cose diverse, e scambiarle fa
    // lampeggiare un errore che non e' vero.
    if (loading) return <p className="caption">Loading…</p>;
    return (
      <p className="info">
        No plan for the week of {shortDayLabel(monday)}. The weeks of a block are files in{" "}
        <code>summary/05.plan/</code>, named after their Monday; the weeks before a block
        starts do not have one.
      </p>
    );
  }
  return (
    <section className="card plan-card week-plan-card" aria-label="Weekly plan">
      <CardHead icon={PLAN_ICON} title={plan.title} />
      <WeekPlanStats plan={plan} />
      <div className="prose plan-prose">{markdown(plan.body)}</div>
      <p className="caption plan-file">summary/05.plan/{plan.file}</p>
      <WrittenAt when={plan.written_at} day={monday} />
    </section>
  );
}


/** La riga di un giorno del piano: il giorno, l'icona dello sport e la
 * seduta in una riga di testo.
 *
 * Sta a parte perche' la vogliono in due (todo 87): la colonna del piano di
 * questa settimana, e la card delle quattro settimane che vengono, che ne
 * mette ventotto. Era scritta dentro `WeekPlanBrief`, e la seconda avrebbe
 * dovuto copiarla — lo stesso motivo per cui `sessionLabel` sta in
 * `PlanSession`.
 *
 * Un giorno **senza seduta** lascia la riga vuota col suo nome: nel piano
 * sono sette giorni sempre, e un giorno che manca dal front matter e' una
 * riga senza niente, non una riga in meno. */
export function PlanDayRow({
  day,
  session,
  sport,
  restIcon,
}: {
  day: string;
  session: PlannedSession | null;
  sport: Sport;
  restIcon: string | null;
}) {
  const icon = session ? sessionIcon(session, sport, restIcon) : null;
  return (
    <div className={`plan-day-row${session && session.sport !== "rest" ? "" : " rest"}`}>
      {/* Il giorno della settimana davanti alla data, come nell'elenco delle
          sedute: in sette righe "Mon" si legge prima del numero. */}
      <span className="plan-day">
        {weekdayShort(day)} {shortDayLabel(day)}
      </span>
      {icon && <img src={iconUrl(icon)} alt="" width={26} height={26} />}
      <span>{session ? sessionLabel(session, sport) : ""}</span>
    </div>
  );
}


/** Il piano della settimana **giorno per giorno**: la card Plan della vista
 * Training (todo 71).
 *
 * **Solo i sette giorni** (todo 75). I quattro numeri del blocco — fase,
 * settimana, gara, bersaglio — stavano in cima e sono andati via: sono del
 * blocco, non della settimana, non cambiano da un lunedi all'altro, e qui
 * spingevano in basso la riga del lunedi' disallineandola dalla prima seduta
 * della colonna accanto. Restano nella vista Plan, dove il documento li
 * vuole.
 *
 * **Non e' la card della vista Plan**, ed e' il punto. Li' c'e' il documento
 * — la tabella con il perche' di ogni seduta, i ritmi, i segnali per
 * scaricare — che si apre e si legge. Qui ci sono le sette sedute come dati,
 * una riga per giorno, da scorrere con un'occhiata accanto alle sedute che
 * hai fatto due riquadri piu' sotto. Lo stesso file, due domande: com'era
 * scritto, e cosa chiedeva ogni giorno.
 *
 * Il todo 70 ci aveva messo i **totali** — quante sedute, quanti chilometri
 * — e non era quello che si voleva: la settimana si guarda giorno per
 * giorno, che e' come e' fatta.
 *
 * La cornice c'e' sempre, come nella Day (todo 63): una settimana senza
 * piano la lascia vuota invece di far sparire un riquadro su tre. */
export function WeekPlanBrief({
  plan,
  monday,
  loading,
  sport,
  restIcon,
}: {
  plan: WeekPlan | null;
  monday: string;
  loading: boolean;
  sport: Sport;
  restIcon: string | null;
}) {
  // Lunedi' -> domenica. `daysBetween` li rende al contrario, dal piu'
  // recente, e qui l'ordine e' quello della settimana.
  const days = Array.from({ length: 7 }, (_, i) => addDays(monday, i));
  const byDay = new Map((plan?.sessions ?? []).map((s) => [s.day, s]));
  return (
    <section className="card plan-card week-days" aria-label="Plan">
      <CardHead icon={PLAN_ICON} title="Plan" />
      {plan === null
        ? loading && <p className="caption">Loading…</p>
        : plan.sessions &&
          days.map((day) => (
            <PlanDayRow
              key={day}
              day={day}
              session={byDay.get(day) ?? null}
              sport={sport}
              restIcon={restIcon}
            />
          ))}
      {plan && (
        <div className="week-days-foot">
          <WrittenAt when={plan.written_at} day={monday} />
        </div>
      )}
    </section>
  );
}
