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
// I segmenti (braccia, gambe, tronco) e le impedenze non sono qui: la
// bilancia li misura e i file li tengono, ma vogliono un disegno loro — un
// corpo con cinque valori, non una fila di riquadri.
import type { BodyComposition } from "../api/client";
import { shortDayLabel } from "../format";
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
          <span className="muted">
            {shortDayLabel(body.measured_day)}, {timeLabel(body.measured_at)}
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
      {!body.impedance && (
        <p className="caption">
          The electrodes did not read this weigh-in: the weight and the BMI are measured, the
          composition is not.
        </p>
      )}
      {/* Perche' le barre sono vuote, finche' lo sono: la fascia vuole otto
          pesate nelle dodici settimane, e dirlo e' meglio di dieci tracce
          grigie senza spiegazione. */}
      {body.measures.every((m) => !m.band) && (
        <p className="caption">
          {body.weighings === 1
            ? "One weigh-in so far: the bands arrive at eight."
            : `${body.weighings} weigh-ins so far: the bands arrive at eight.`}
        </p>
      )}
    </section>
  );
}
