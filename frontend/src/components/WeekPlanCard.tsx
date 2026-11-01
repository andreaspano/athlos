// Il piano della settimana (todo 60): la card in fondo alla vista Training,
// e la colonna dei sette giorni accanto alle sedute fatte.
//
// Fino al todo 90 era **una vista a parte**, col documento intero. Non lo e'
// piu': i ritmi e le regole di scarico che quel documento porta sono quelli
// del blocco e si leggono nella pagina Goal, la tabella dei giorni e' nelle
// righe della colonna (todo 89), e quello che restava scritto solo per quella
// settimana sta in questa card, sotto le righe che spiega.
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
import { inline, markdown } from "../markdown";
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

// La prima cella di una riga di giorno, come la scrive il piano:
// `**Mon 9 Nov**`. La stessa forma che cerca `_day_row` nell'API, perche' e'
// la stessa riga — qui per **non** mostrarla, li' per mostrarla nella sua
// riga.
const DAY_CELL = /^\s*\*{0,2}\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+[A-Z][a-z]{2}/;

/** Il corpo del piano **senza la tabella dei giorni** (todo 90).
 *
 * Quella tabella si legge nelle sette righe della colonna accanto, una per
 * giorno, col dettaglio sotto il riassunto (todo 89): ripeterla qui vorrebbe
 * dire la stessa cosa due volte nella stessa vista. Quello che resta e' la
 * settimana spiegata — a cosa serve, i totali, le note, i ritmi, quando
 * scaricare.
 *
 * Si taglia **per forma e non per titolo**: si butta il blocco di righe di
 * tabella in cui una prima cella e' un giorno, e si tengono le altre tabelle
 * (i ritmi). Un filtro sul nome della sezione sarebbe fragile — le sezioni le
 * scrive un agente (todo 86), e basta che un giorno chiami «Pace» quella
 * tabella perche' il filtro mangi la cosa sbagliata.
 *
 * Le altre sezioni **non si toccano**, nemmeno quelle che ripetono il blocco:
 * «When to back off» e' quattro quinti le deroghe del goal e un quinto una
 * regola scritta per quella settimana — il 9 novembre *«if Sunday morning
 * readiness is under 50 … cut the long run to 12 km»*, che nel blocco non
 * c'e'. Buttare la sezione butterebbe anche quella. */
export function withoutDayTable(body: string): string {
  const lines = body.split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    if (!lines[i].trimStart().startsWith("|")) {
      out.push(lines[i]);
      i += 1;
      continue;
    }
    let j = i;
    while (j < lines.length && lines[j].trimStart().startsWith("|")) j += 1;
    const block = lines.slice(i, j);
    const days = block.some((line) =>
      DAY_CELL.test(line.trim().replace(/^\|/, "").split("|")[0] ?? ""),
    );
    if (!days) out.push(...block);
    i = j;
  }
  // Il buco lasciato dalla tabella non deve diventare un salto: due righe
  // vuote di fila tornano una.
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export function WeekPlanCard({
  plan,
  monday,
}: {
  plan: WeekPlan | null;
  monday: string;
}) {
  // Niente piano, niente card (todo 90): la colonna delle sedute previste,
  // qui sopra, e' gia' la cornice che lo dice — una settimana prima
  // dell'inizio del blocco non ne ha uno, e dirlo due volte nella stessa
  // vista e' dirlo male. Lo stesso mentre la chiamata e' in volo: la card
  // compare col testo.
  if (plan === null) return null;
  const prose = withoutDayTable(plan.body);
  return (
    <section className="card plan-card week-plan-card" aria-label="Weekly plan">
      <CardHead icon={PLAN_ICON} title={plan.title} />
      <WeekPlanStats plan={plan} />
      {prose && <div className="prose plan-prose">{markdown(prose)}</div>}
      <p className="caption plan-file">summary/05.plan/{plan.file}</p>
      <WrittenAt when={plan.written_at} day={monday} />
    </section>
  );
}


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
      <span className="plan-session">
        <span>{session ? sessionLabel(session, sport) : ""}</span>
        {session?.text && <span className="plan-detail">{inline(session.text)}</span>}
      </span>
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
