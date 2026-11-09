// Il piano della settimana (todo 60): la colonna dei sette giorni accanto
// alle sedute fatte, nella vista Training.
//
// **Del documento della settimana resta questa colonna, e basta.** Era una
// vista a parte col file intero (todo 60), poi una card in fondo alla Training
// (todo 90), e adesso niente: i ritmi e le regole di scarico che portava sono
// quelli del blocco e si leggono nella pagina Goal, le sedute giorno per
// giorno sono in queste righe col loro dettaglio (todo 89), e il resto — a
// cosa serviva quella settimana, le decisioni prese strada facendo — resta
// scritto nei file di `summary/05.plan/`, che si aprono anche da soli.
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
import {
  iconUrl,
  type Adherence,
  type AdherenceSession,
  type PlannedSession,
  type WeekPlan,
} from "../api/client";
import { addDays, shortDayLabel, weekdayShort } from "../format";
import { inline } from "../markdown";
import { sessionIcon, sessionLabel, type Sport } from "./PlanSession";
import { CardHead, WrittenAt } from "./Stat";

// L'icona di Next, come nella pagina Plan: il riquadro che dice cosa fare
// dopo. Un piano e' la stessa domanda, su sette giorni invece che su domani.
const PLAN_ICON = "next.png";

/** La riga di un giorno del piano: il giorno, l'icona dello sport, la seduta
 * in una riga di testo e **sotto, quello che il piano chiede davvero**.
 *
 * Sta a parte perche' la vogliono in due (todo 87): la colonna del piano di
 * questa settimana, e la card delle quattro settimane che vengono, che ne
 * mette ventotto. Era scritta dentro `WeekPlanBrief`, e la seconda avrebbe
 * dovuto copiarla — lo stesso motivo per cui `sessionLabel` sta in
 * `PlanSession`.
 *
 * Un giorno **senza seduta** lascia la riga vuota col suo nome: nel piano
 * sono sette giorni sempre, e un giorno che manca dal front matter e' una
 * riga senza niente, non una riga in meno.
 *
 * **Il dettaglio e' la riga della tabella del piano** (`text`, todo 89), cioe'
 * le parole con cui la settimana e' scritta: i ritmi, le ripetute, il tetto
 * del battito, il lavoro di forza, il perche'. Era gia' nei dati — la card
 * della Day lo mostra dal todo 63 — e qui si fermava a
 * `Running · easy · 8 km`, che dice *quanto* e non *come*: una qualita' da
 * 5 x 5' a 5'55" e un lento da 8 km diventavano due righe che si somigliano.
 *
 * La riga corta **resta** sopra, in tono pieno: e' il riassunto a macchina,
 * e sta sulla riga della seduta fatta nella colonna accanto (todo 77), dove
 * il confronto e' fra due righe corte. Il dettaglio sta sotto, in tono
 * minore, perche' e' il documento che parla. Un giorno senza riga nella
 * tabella non ha il dettaglio e non lascia un buco: il piano puo' non
 * averlo. */
function PlanDayRow({
  day,
  session,
  sport,
  restIcon,
  score,
}: {
  day: string;
  session: PlannedSession | null;
  sport: Sport;
  restIcon: string | null;
  /** Come e' stata eseguita quella seduta (todo 96), se il piano ne chiedeva
   * una. Sta sulla riga del giorno perche' li' c'e' gia' scritto cosa
   * chiedeva: previsto, fatto e punteggio si leggono in una riga sola. */
  score?: AdherenceSession | null;
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
      <span className="plan-session">
        <span>{session ? sessionLabel(session, sport) : ""}</span>
        {session?.text && <span className="plan-detail">{inline(session.text)}</span>}
      </span>
      {score && <PlanDayScore score={score} />}
    </div>
  );
}


/** Il punteggio di una seduta: quanto e' stata eseguita come chiedeva.
 *
 * Il numero e' `s_vol`, da zero a cento, e accanto ci sono i chilometri da
 * cui viene — una percentuale senza il numero che la produce non si verifica
 * a occhio. Una seduta non fatta vale zero ed e' il caso in cui serve di
 * piu'; una fatta ma senza una distanza confrontabile non ha punteggio e qui
 * non compare. */
function PlanDayScore({ score }: { score: AdherenceSession }) {
  if (score.score == null) return null;
  const done = score.done_km;
  return (
    <span
      className="plan-score"
      title={
        done == null
          ? "Not done: this session scores zero."
          : `${done} km done against ${score.planned_km} asked` +
            (score.moved_to ? `, run on ${score.moved_to}` : "") +
            (score.key ? " · counts double" : "")
      }
    >
      {Math.round(score.score * 100)}
      <span className="muted">{done == null ? "not done" : `${done} km`}</span>
    </span>
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
/** `Week 3 of 18`, o niente quando il piano non lo dice: il file di settembre
 * 2026 non ha front matter, e un riquadro di contesto che dice «Week – of –»
 * e' peggio di un riquadro senza contesto. */
function blockWeek(plan: WeekPlan | null): string | null {
  if (plan?.block_week == null) return null;
  return plan.block_weeks != null
    ? `Week ${plan.block_week} of ${plan.block_weeks}`
    : `Week ${plan.block_week}`;
}

export function WeekPlanBrief({
  plan,
  monday,
  loading,
  sport,
  restIcon,
  adherence,
}: {
  plan: WeekPlan | null;
  monday: string;
  loading: boolean;
  sport: Sport;
  restIcon: string | null;
  /** L'aderenza della settimana (todo 96), o `null` se non c'e'. */
  adherence?: Adherence | null;
}) {
  // Lunedi' -> domenica. `daysBetween` li rende al contrario, dal piu'
  // recente, e qui l'ordine e' quello della settimana.
  const days = Array.from({ length: 7 }, (_, i) => addDays(monday, i));
  const byDay = new Map((plan?.sessions ?? []).map((s) => [s.day, s]));
  const scoreOf = new Map((adherence?.sessions ?? []).map((s) => [s.day, s]));
  return (
    <section className="card plan-card week-days" aria-label="Plan">
      {/* Dove sta questa settimana nel blocco, accanto al titolo.
          Il todo 75 aveva tolto i **quattro** numeri del blocco da qui perche'
          stavano in una riga loro e spingevano in basso il lunedi',
          disallineandolo dalla prima seduta della colonna accanto. Questo sta
          **dentro l'intestazione**, che c'era gia': non aggiunge una riga,
          quindi l'allineamento non si muove. Gara e bersaglio restano fuori —
          non cambiano da un lunedi' all'altro, e li dice la card in fondo. */}
      <CardHead icon={PLAN_ICON} title="Plan" note={blockWeek(plan)} />
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
              score={scoreOf.get(day) ?? null}
            />
          ))}
      {plan && (
        <div className="week-days-foot">
          {/* L'aderenza **in fondo e non in cima** (todo 96). In cima sarebbe
              una riga in piu' davanti al lunedi', e spingerebbe le sette
              righe in basso disallineandole dalle sedute della colonna
              accanto: e' esattamente quello che il todo 75 aveva tolto da
              qui, e il 77 ha messo in riga. In fondo c'e' gia' una riga sua,
              e un verdetto sull'esecuzione si legge dopo i sette giorni.
              Due numeri e non uno: l'aderenza dice **come** hai eseguito, il
              rapporto se sei stato sopra o sotto. 82 con 1.21 e 82 con 0.83
              sono settimane opposte. */}
          {adherence?.volume_adherence != null && (
            <p className="plan-adherence">
              <span>
                Volume adherence <strong>{Math.round(adherence.volume_adherence)}</strong>
              </span>
              {adherence.ratio != null && (
                <span>
                  Done / planned <strong>{adherence.ratio.toFixed(2)}</strong>
                  <span className="muted">
                    {adherence.done_km} of {adherence.planned_km} km
                  </span>
                </span>
              )}
              <span className="muted">
                Volume only: the plan does not carry the intensity half yet.
              </span>
            </p>
          )}
          <WrittenAt when={plan.written_at} day={monday} />
        </div>
      )}
    </section>
  );
}
