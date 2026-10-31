// Le quattro settimane che vengono: la card in fondo alla vista Training
// della Week (todo 87).
//
// La vista Training risponde a due domande affiancate — cosa chiedeva la
// settimana e cosa e' successo, allineate giorno per giorno (todo 73 e 77) —
// e questa e' la terza, quella che si fa il sabato: **e dopo?** Prima si
// rispondeva cambiando settimana col selettore, quattro volte, tenendo a
// mente la prima mentre si guardava la quarta.
//
// **Sta sotto le due colonne e non dentro quella del piano.** Le settimane
// che vengono non hanno il lato destro: non sono state corse. Nella colonna
// di sinistra sarebbero ventotto righe con ventuno di bianco a destra, che e'
// il bianco che il todo 73 era andato a togliere.
//
// **Non e' la vista Plan.** Li' c'e' il documento di una settimana — la
// tabella col perche' di ogni seduta, i ritmi, i segnali per scaricare — e
// quattro documenti in fila non sono una cosa che si legge. Qui le sedute
// sono dati, una riga per giorno, da scorrere con un'occhiata.
import { type WeekPlan } from "../api/client";
import { addDays, shortDayLabel } from "../format";
import type { Sport } from "./PlanSession";
import { CardHead } from "./Stat";
import { PlanDayRow } from "./WeekPlanCard";

// L'icona di Next, la stessa della card del piano: il riquadro che dice cosa
// fare dopo.
const PLAN_ICON = "next.png";

/** Quante settimane si guardano avanti.
 *
 * **Quattro, e non un numero a scelta.** Non c'e' nessun `?weeks=`: quanto si
 * guarda avanti non e' uno stato della pagina, e un selettore in piu' su una
 * vista che ne ha gia' uno si paga in barra. Quattro settimane sono un mese,
 * che e' l'orizzonte entro cui un blocco si puo' ancora cambiare. */
export const WEEKS_AHEAD = 4;

/** I lunedi' delle settimane che vengono dopo `monday`.
 *
 * Sono le quattro **dopo quella mostrata**, non le quattro da oggi: ogni
 * numero di questa pagina e' della settimana scelta col selettore, e una card
 * che lo ignorasse sarebbe l'unica a farlo. Stando sulla settimana corrente —
 * come la pagina si apre — sono le prossime quattro, che e' la domanda.
 *
 * Su una settimana passata si vedono le quattro che l'hanno seguita, gia'
 * corse: quei file sono il registro di quello che era previsto allora, ed e'
 * la stessa ragione per cui nessuno li riscrive (todo 85). */
export function mondaysAhead(monday: string): string[] {
  return Array.from({ length: WEEKS_AHEAD }, (_, i) => addDays(monday, 7 * (i + 1)));
}

/** "30 Nov – 6 Dec": da lunedi' a domenica. */
function weekRange(monday: string): string {
  return `${shortDayLabel(monday)} – ${shortDayLabel(addDays(monday, 6))}`;
}

/** Dove sta una settimana nel blocco: `Week 6 of 18 · build · 30 Nov – 6 Dec`.
 *
 * Il todo 75 aveva **tolto** i numeri del blocco dalla colonna del piano, e
 * qui tornano: li' spingevano in basso la riga del lunedi' disallineandola
 * dalla colonna accanto, e per **una** settimana non servivano. Qui non c'e'
 * nessuna colonna da allineare, e quattro gruppi di sette righe senza
 * intestazione sono un muro — senza questa riga non si sa dove finisce una
 * settimana e comincia l'altra.
 *
 * Gara e bersaglio restano fuori: sono del blocco, non cambiano da un lunedi'
 * all'altro, e li dice la vista Plan. */
function weekHead(plan: WeekPlan, monday: string): string {
  const parts = [
    plan.block_week != null && plan.block_weeks != null
      ? `Week ${plan.block_week} of ${plan.block_weeks}`
      : plan.block_week != null
        ? `Week ${plan.block_week}`
        : null,
    plan.phase,
    weekRange(monday),
  ].filter((part): part is string => Boolean(part));
  return parts.join(" · ");
}

/** Le settimane che vengono, una sotto l'altra, ognuna coi suoi sette giorni.
 *
 * `plans` ha una voce per ogni lunedi' di `mondaysAhead`, nello stesso
 * ordine, e `null` dove quella settimana non ha un file.
 *
 * **Niente file, niente sezione**: una settimana fuori dal blocco — prima che
 * cominci, dopo la gara — non e' un errore, e verso la fine di un blocco le
 * quattro diventano tre, due, una. Se non ne ha nessuna, **la card non c'e'
 * affatto**: e' il contrario della regola della Day e della colonna del piano,
 * dove la cornice resta sempre (todo 63), perche' quelle rispondono a una
 * domanda che e' stata fatta — che seduta era prevista oggi — e una cornice
 * vuota e' la risposta. Questo e' uno sguardo avanti, e una cornice che dice
 * quattro volte che non c'e' niente, accanto a una colonna che per questa
 * settimana lo dice gia', e' rumore.
 *
 * `goal` e' il blocco da cui viene la settimana mostrata, e serve a dire
 * quando una di queste viene da **un altro**: e' la divergenza che la pagina
 * Goal avvisa (todo 85), e qui, dove si guarda avanti, sarebbe invisibile —
 * si leggerebbero quattro settimane coerenti senza sapere che vengono da un
 * bersaglio abbandonato. Quando il goal e' lo stesso non si scrive: una
 * ripetizione su ogni riga non e' un'informazione. */
export function WeeksAhead({
  plans,
  monday,
  goal,
  sport,
  restIcon,
}: {
  plans: (WeekPlan | null)[];
  monday: string;
  goal: string | null;
  sport: Sport;
  restIcon: string | null;
}) {
  const mondays = mondaysAhead(monday);
  const found = mondays
    .map((week, index) => ({ week, plan: plans[index] ?? null }))
    .filter((entry): entry is { week: string; plan: WeekPlan } => entry.plan !== null);
  if (found.length === 0) return null;
  return (
    <section className="card plan-card weeks-ahead" aria-label="Ahead">
      <CardHead icon={PLAN_ICON} title="Ahead" />
      {found.map(({ week, plan }) => {
        const byDay = new Map((plan.sessions ?? []).map((s) => [s.day, s]));
        const elsewhere = plan.plan && plan.plan !== goal ? plan.plan : null;
        return (
          <div key={week} className="ahead-week">
            <p className="ahead-head">
              <span>{weekHead(plan, week)}</span>
              {/* Il goal solo quando cambia: vedi il docstring. */}
              {elsewhere && <code className="ahead-goal">{elsewhere}</code>}
            </p>
            {Array.from({ length: 7 }, (_, i) => addDays(week, i)).map((day) => (
              <PlanDayRow
                key={day}
                day={day}
                session={byDay.get(day) ?? null}
                sport={sport}
                restIcon={restIcon}
              />
            ))}
          </div>
        );
      })}
    </section>
  );
}
