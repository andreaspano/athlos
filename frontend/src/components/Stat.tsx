// Un numero con etichetta, unita' e riga sotto, e la barra della fascia che
// gli sta sotto: lo usano Recovery, Health e Fitness (todo 37, prima stava
// in "This morning"; le barre erano in HealthCard fino al todo 46).
import type { ReactNode } from "react";

import { iconUrl, type Band, type Measure, type Verdict } from "../api/client";
import { writtenLabel } from "../format";

export function num(value: number | null | undefined, digits = 0): string {
  return value == null ? "–" : value.toFixed(digits);
}

export function Stat({
  label,
  value,
  unit,
  sub,
  help,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  sub?: ReactNode;
  /** La spiegazione nel tooltip del riquadro. */
  help?: string;
}) {
  return (
    <div className="stat" title={help}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value}
        {unit && <span className="stat-unit"> {unit}</span>}
      </div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

/** Il titolo piccolo di un riquadro, con l'icona della sua sezione del report
 * e, in fondo a destra, il tasto che rifa' solo quella sezione (todo 44).
 *
 * `note` e' un pezzo di contesto accanto al titolo, in tono minore: quanto
 * basta a dire *di che* parla questo riquadro senza aggiungergli una riga
 * sotto. La usa la colonna del piano per la settimana del blocco. */
export function CardHead({
  icon,
  title,
  note,
  face,
  refresh,
}: {
  icon: string | null;
  title: string;
  note?: ReactNode;
  /** Come sta andando quello che la card mostra (todo 92): una delle cinque
   * parole della scala, e la faccia in fondo all'intestazione. `null` o
   * assente vuol dire **niente da misurare**, non un voto basso: la card
   * resta senza. */
  face?: Verdict | null;
  refresh?: ReactNode;
}) {
  return (
    <div className="block-head">
      {icon && <img src={iconUrl(icon)} alt="" width={22} height={22} />}
      <span>{title}</span>
      {note && <span className="head-note">{note}</span>}
      {/* La faccia sta **in fondo a destra della card**, non qui: la
          scrive l'intestazione perche' e' lei che ha la prop, e il CSS la
          porta nell'angolo (`.card-face`, posizionata sulla cornice). Col
          nome nel `title`: un'icona senza nome e' un indovinello, e cinque
          facce che si somigliano a 22 px lo sono due volte. */}
      {face && (
        <img
          className="card-face"
          src={iconUrl(`${face}.png`)}
          alt={face}
          title={face}
          width={22}
          height={22}
        />
      )}
      {refresh}
    </div>
  );
}

/** Una fascia e il valore di oggi dentro: la media dei 28 giorni prima piu'
 * e meno uno scarto tipo (la parte piena), e piu' e meno due (la parte
 * chiara). La scala va un po' oltre la fascia, per vedere anche un valore
 * fuori. `tick` scrive gli estremi quando il numero crudo non basta: il
 * sonno li vuole in ore e minuti, come il valore grande sopra. */
/** Quanto vicine possono stare due etichette sotto la barra prima di
 * sovrapporsi, in frazione della larghezza. Sotto i 200 px di una colonna
 * della card Body due numeri a meno di un sesto l'uno dall'altro si toccano. */
const TICK_GAP = 0.17;

export function RangeBar({
  value,
  band,
  target,
  tick = (v: number) => String(v),
}: {
  value: number | null;
  /** La fascia, se c'e': senza di lei la barra si disegna comunque, purche'
   * abbia qualcosa da mostrare (un valore, un bersaglio). */
  band?: Band | null;
  /** Il bersaglio, la linea verde (la card Body, todo 97): dove quella misura
   * **dovrebbe** arrivare. Le altre card non ne hanno uno e non la disegnano. */
  target?: number | null;
  tick?: (value: number) => string;
}) {
  // I punti che la barra deve contenere: la fascia se c'e', il valore, il
  // bersaglio. Senza nessuno non c'e' niente da disegnare.
  const points = [
    band?.outer_low,
    band?.outer_high,
    value,
    target,
  ].filter((n): n is number => n != null);
  if (points.length === 0) return <EmptyBar />;
  const lowest = Math.min(...points);
  const highest = Math.max(...points);
  // Il margine resta quello di sempre **quando la fascia c'e'**: cambiarlo
  // avrebbe spostato di un pelo le barre di Health, Recovery, Load e
  // Fitness, che di questo codice sono le prime inquiline. Senza fascia lo
  // si prende dalla distanza fra i punti, e se cadono tutti nello stesso
  // posto da un soffio attorno, che una barra larga zero non si disegna.
  const pad = band
    ? (band.outer_high - band.outer_low) * 0.12
    : (highest - lowest || Math.abs(highest) * 0.1 || 1) * 0.12;
  // Lo stesso margine anche attorno a un valore fuori dalla fascia: senza,
  // la tacca finiva esattamente sul bordo della traccia e si vedeva a meta'
  // (il carico anaerobico, molto sotto la sua fascia).
  const min = lowest - pad;
  const max = highest + pad;
  // Una misura ferma sullo stesso valore per tutta la finestra ha scarto
  // tipo zero: fascia e valore cadono tutti nello stesso punto e la scala
  // sarebbe larga zero (una divisione per zero, e il CSS con "NaN%" dentro
  // non si applica). Capita al carico anaerobico di chi non supera mai la
  // soglia: in quel caso la barra e' tutta nel mezzo.
  const at = (v: number) =>
    max === min ? "50%" : `${((v - min) / (max - min)) * 100}%`;
  const span = (a: number, b: number) => ({
    left: at(a),
    width: `calc(${at(b)} - ${at(a)})`,
  });
  // Dove cade un valore, in frazione della barra: serve a decidere se due
  // etichette si pestano i piedi.
  const frac = (v: number) => (max === min ? 0.5 : (v - min) / (max - min));
  // L'etichetta del bersaglio si scrive se non finisce addosso a quelle della
  // fascia: il numero verde e' un'aggiunta, e un'aggiunta non deve coprire
  // quello che c'era.
  const targetTick =
    target != null &&
    (!band ||
      (Math.abs(frac(target) - frac(band.low)) > TICK_GAP &&
        Math.abs(frac(target) - frac(band.high)) > TICK_GAP));
  return (
    <div className="range-bar" aria-hidden="true">
      <div className="range-track">
        {band && <div className="range-wide" style={span(band.outer_low, band.outer_high)} />}
        {band && <div className="range-band" style={span(band.low, band.high)} />}
        {/* Il bersaglio sotto la tacca del valore: quando i due coincidono —
            cioe' quando ci sei arrivato — e' il valore che si vede. */}
        {target != null && (
          <div className="range-target" style={{ left: at(target) }} />
        )}
        {value != null && (
          <div className="range-marker" style={{ left: at(value) }} />
        )}
      </div>
      <div className="range-ticks">
        {band && <span style={{ left: at(band.low) }}>{tick(band.low)}</span>}
        {band && <span style={{ left: at(band.high) }}>{tick(band.high)}</span>}
        {targetTick && (
          <span className="tick-target" style={{ left: at(target) }}>
            {tick(target)}
          </span>
        )}
      </div>
    </div>
  );
}

/** Il posto di una barra che non si puo' disegnare: la misura una fascia
 * ce l'ha, ma i giorni misurati non bastano a calcolarla. Una traccia
 * grigia e vuota, perche' "non lo so ancora" e "qui non ha senso" non sono
 * la stessa cosa e non devono somigliarsi — e le righe restano allineate
 * con quelle che la barra ce l'hanno. Dove una fascia non e' prevista (la
 * soglia, gli acclimatamenti, il rapporto di carico) non va messo niente. */
export function EmptyBar() {
  return (
    <div className="range-bar" aria-hidden="true">
      <div className="range-track" />
      <div className="range-ticks" />
    </div>
  );
}

/** La barra della fascia di una misura, o la traccia vuota se la fascia non
 * c'e' (pochi giorni misurati). `value` sostituisce quello della misura dove
 * il numero buono sta altrove (il sonno, che la pagina ha in minuti). */
export function MeasureBar({
  measure,
  value,
  tick,
}: {
  measure: Measure;
  value?: number | null;
  tick?: (value: number) => string;
}) {
  if (!measure.band) return <EmptyBar />;
  return (
    <RangeBar
      value={value === undefined ? measure.value : value}
      band={measure.band}
      tick={tick}
    />
  );
}

/** La riga che dice quando e' stato scritto il testo di una card (todo 47).
 *
 * Niente quando l'ora non c'e', che e' anche il caso della card senza testo:
 * l'API manda `written_at` solo per le sezioni scritte, quindi la guardia
 * sta tutta qui e nessuna card se la ripete. Dentro i riquadri scuri (Next,
 * Summary) prende il loro grigio. */
export function WrittenAt({ when, day }: { when: string | null; day: string }) {
  if (!when) return null;
  return <p className="written-at">{writtenLabel(when, day)}</p>;
}
