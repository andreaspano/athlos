// "Body" (todo 97): il corpo come l'ha misurato la bilancia — peso, BMI,
// grasso, acqua, muscolo scheletrico, massa magra, osso, proteine, grasso
// viscerale e metabolismo basale. Dieci numeri nella griglia dello Snap,
// accanto alle quattro card di sempre.
//
// **Le misure del giorno, o le ultime fino a quel giorno.** Su una bilancia
// ci si sale quando si vuole, quindi un giorno senza pesata e' il caso
// normale e non un buco: la card mostra la piu' recente e dice di quando e'
// — «misurato martedi 10, un giorno prima». Mai una pesata successiva, che un
// giorno passato non racconta il futuro: la scelta la fa l'API, qui si
// disegna quello che arriva.
//
// **Una pesata sola, non il meglio di tante**: il peso di stasera e il grasso
// di stamattina sono due momenti, e cuciti insieme darebbero un corpo che non
// e' mai esistito. Di un giorno con piu' pesate l'API manda l'ultima completa.
//
// **Zero non e' un valore**: la pesata senza impedenza — calzini, piedi
// asciutti — ha il peso e il BMI e il resto `null`. I riquadri restano al
// loro posto con un trattino, e una riga lo dice, perche' un corpo disegnato
// di zeri sarebbe una bugia precisa.
//
// **Le barre qui non si leggono come nelle altre card, e la card lo scrive.**
// Altrove la fascia e' dove quella misura sta di solito, e uscirne vuol dire
// "oggi e' diverso dal solito"; qui e' l'intervallo di riferimento della
// bilancia per altezza, eta' e sesso, e uscirne vuol dire un'altra cosa. Lo
// stesso disegno con due significati e' il modo di leggere male un numero,
// quindi sotto i riquadri c'e' una riga che dice quale dei due e'.
//
// I segmenti (braccia, gambe, tronco) e le impedenze non sono qui: la
// bilancia li misura e i file li tengono, ma vogliono un disegno loro — un
// corpo con cinque valori, non una fila di riquadri.
import type { BodyComposition } from "../api/client";
import { longDayLabel, shortDayLabel, weekdayShort } from "../format";
import { CardHead, EmptyBar, RangeBar, Stat, num } from "./Stat";

/** Da quanto e' vecchia la pesata, a parole. Zero giorni non si scrive: la
 * card sta nel giorno di quella pesata, e «oggi» lo si sa. */
function agoLabel(daysAgo: number): string {
  if (daysAgo <= 0) return "";
  return daysAgo === 1 ? ", one day before" : `, ${daysAgo} days before`;
}

/** L'ora della pesata, dal suo `measured_at` (ora locale, già nel fuso di chi
 * e' salito sulla bilancia): le 10:06 di quel giorno. */
function timeLabel(measuredAt: string): string {
  return measuredAt.slice(11, 16);
}

export function BodyCard({ body, icon }: { body: BodyComposition; icon: string | null }) {
  return (
    <section className="card body-card" aria-label="Body">
      <CardHead
        icon={icon}
        title="Body"
        note={
          // Il giorno della pesata col nome del giorno della settimana, come
          // nelle righe delle sedute: in una card che mostra spesso una
          // misura di qualche giorno prima, "Tue 10 Nov" si colloca e
          // "10 Nov" va cercato sul calendario.
          <span className="muted">
            {weekdayShort(body.measured_day)} {shortDayLabel(body.measured_day)},{" "}
            {timeLabel(body.measured_at)}
            {agoLabel(body.days_ago)}
          </span>
        }
      />
      <div className="stats two">
        {body.measures.map((m) => (
          <Stat
            key={m.key}
            label={m.label}
            value={num(m.value, m.digits)}
            unit={m.unit || undefined}
            sub={
              m.band && m.value != null ? (
                <RangeBar
                  value={m.value}
                  band={m.band}
                  tick={(v) => v.toFixed(m.digits)}
                />
              ) : (
                <EmptyBar />
              )
            }
          />
        ))}
      </div>
      {/* L'eta' corporea contro quella vera: due numeri che si leggono solo
          uno accanto all'altro, quindi non sono due riquadri. */}
      {body.body_age != null && (
        <p className="caption">
          Body age {num(body.body_age)}
          {body.age != null && <> against {num(body.age)} real</>}.
        </p>
      )}
      {/* Il giorno della pesata, scritto per intero quando non e' quello che
          si sta guardando: l'intestazione lo porta in breve, ma su una card
          che mostra una misura di tre giorni prima la data merita una frase
          che non si possa leggere come "oggi". */}
      {body.days_ago > 0 && (
        <p className="caption">
          Measured on {longDayLabel(body.measured_day)} at {timeLabel(body.measured_at)}.
        </p>
      )}
      {!body.impedance && (
        <p className="caption">
          The electrodes did not read this weigh-in: the weight and the BMI are measured, the
          composition is not.
        </p>
      )}
      {/* Cosa sono le barre, detto una volta: sono l'intervallo che la
          bilancia considera normale per te, non la fascia delle altre card.
          Le misure senza barra sono quelle per cui un intervallo non arriva,
          o arriva in un'unita' che non e' quella del numero. */}
      {body.measures.some((m) => m.band) && (
        <p className="caption">
          The bands are the scale's reference range for your height, age and sex — not where
          you usually are, as on the other cards.
        </p>
      )}
    </section>
  );
}
