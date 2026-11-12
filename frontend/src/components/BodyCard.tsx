// "Body" (todo 97): il corpo come l'ha misurato la bilancia — peso, BMI,
// grasso, muscolo scheletrico, metabolismo basale, acqua, massa magra, osso,
// proteine e grasso viscerale.
//
// **Dieci numeri in due righe da cinque, e la card prende tutta la
// larghezza**: a mezza pagina in due colonne erano cinque righe, cioe' una
// card alta il doppio delle altre quattro che le stanno accanto, e la griglia
// dello Snap si sfaldava. Dieci misure vogliono una fila, non una colonna.
//
// **La prima riga sono le cinque misure con un bersaglio** — peso, BMI,
// grasso, muscolo scheletrico, metabolismo — e la seconda le cinque senza.
// L'ordine lo decide `MEASURES` in `body_data.py`, qui si disegna quello che
// arriva: la card non sa quali sono le cinque, le mette in fila e la griglia
// va a capo da se'. Serve a far coincidere la riga di sopra con le barre che
// hanno la linea del bersaglio, cosi' la distanza da coprire si legge tutta
// insieme invece di stare sparsa fra le due righe.
//
// Le cinque colonne sono `stats five`, una regola che c'era gia' — il numero
// piu' piccolo e senza andare a capo, e sotto i 900 px tre per riga — e che
// da un po' nessuno usava: le card dei numeri di una seduta sono passate a
// due colonne, questa ne ha dieci e se la riprende invece di scriverne
// un'altra identica.
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
// **Le barre sono quelle di sempre**: dove quella misura sta di solito, cioe'
// la media delle pesate delle dodici settimane con il suo scarto tipo. Per un
// momento sono state le fasce di riferimento della bilancia — dove il numero
// *dovrebbe* stare per altezza, eta' e sesso — e arrivavano subito invece di
// aspettare uno storico; sono tornate indietro perche' davano allo stesso
// disegno un secondo significato, e una barra si impara a leggere una volta.
// I riferimenti restano nei file, se un giorno vorranno un disegno loro.
//
// **Due linee verticali su ogni barra** (e vanno spiegate, o sono un
// disegno): quella alta e' il valore di adesso — la tacca di sempre, che in
// tutte le card dice "oggi sei qui" — e quella bassa il **bersaglio che la
// bilancia propone** per altezza, eta' e sesso. Sono dello stesso nero, e si
// distinguono per altezza: il bersaglio e' stato verde per un po', e il verde
// e' caduto perche' dava alla barra un secondo colore da imparare quando
// bastava una seconda altezza. Il bersaglio ce l'hanno cinque misure su
// dieci: peso 79.4 kg, BMI 22, grasso 15%, muscolo scheletrico 38.1 kg,
// metabolismo 1828 kcal. Le altre cinque non lo hanno, e una linea inventata
// sarebbe un obiettivo inventato.
//
// E' anche quello che rende la barra utile **adesso**: la fascia dello storico
// arriva alla terza pesata, il bersaglio c'e' dalla prima, e fra le due linee
// si legge la distanza da coprire.
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
      <div className="stats five">
        {body.measures.map((m) => (
          <Stat
            key={m.key}
            label={m.label}
            value={num(m.value, m.digits)}
            unit={m.unit || undefined}
            sub={
              // La barra si disegna se ha qualcosa da dire: la fascia, o il
              // bersaglio della bilancia. Un valore da solo non basta — una
              // tacca in mezzo a una traccia vuota non dice niente, e allora
              // resta la traccia, allineata con le altre righe.
              m.band || m.target != null ? (
                <RangeBar
                  value={m.value}
                  band={m.band}
                  target={m.target}
                  beatsTarget={m.beats_target}
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
      {/* Cosa sono le due linee, detto una volta: due righe verticali sulla
          stessa barra vanno spiegate, o si leggono come un disegno. La frase
          nomina l'altezza — "la piu' corta" — e non il colore, che adesso il
          colore vuol dire un'altra cosa: era "the green one", e il verde se
          l'e' preso la tacca del valore per dire che il bersaglio e' battuto.
          **Il verde e il rosso si spiegano qui o non si spiegano**: un colore
          con un significato che la pagina non dice e' una decorazione che
          sembra un dato. */}
      {body.measures.some((m) => m.target != null) && (
        <p className="caption">
          On the bars, the taller line is where you are and the{" "}
          <span className="target-word">shorter one</span> the goal the scale proposes for your
          height, age and sex. The taller line turns{" "}
          <span className="word-good">green</span> when you are on the better side of that goal
          and <span className="word-bad">red</span> when you are not — down for weight, BMI and
          body fat, up for skeletal muscle and basal metabolism.
        </p>
      )}
      {/* Perche' le fasce non ci sono, finche' non ci sono: tre pesate e' il
          pavimento sotto cui uno scarto tipo non dice niente, e una traccia
          senza una riga che la spieghi si legge come un guasto. */}
      {body.measures.every((m) => !m.band) && (
        <p className="caption">
          {body.weighings === 1
            ? "One weigh-in in the last twelve weeks: the bands of where you usually are arrive at three."
            : `${body.weighings} weigh-ins in the last twelve weeks: the bands of where you usually are arrive at three.`}
        </p>
      )}
    </section>
  );
}
