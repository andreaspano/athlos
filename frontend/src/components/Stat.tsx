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
      {/* Col nome scritto nel `title`: un'icona senza nome e' un indovinello,
          e cinque facce che si somigliano a 22 px lo sono due volte. */}
      {face && (
        <img
          className="head-face"
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
export function RangeBar({
  value,
  band,
  tick = (v: number) => String(v),
}: {
  value: number | null;
  band: Band;
  tick?: (value: number) => string;
}) {
  const { low, high, outer_low: outerLow, outer_high: outerHigh } = band;
  const pad = (outerHigh - outerLow) * 0.12;
  // Lo stesso margine anche attorno a un valore fuori dalla fascia: senza,
  // la tacca finiva esattamente sul bordo della traccia e si vedeva a meta'
  // (il carico anaerobico, molto sotto la sua fascia).
  const min = Math.min(outerLow, value ?? outerLow) - pad;
  const max = Math.max(outerHigh, value ?? outerHigh) + pad;
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
  return (
    <div className="range-bar" aria-hidden="true">
      <div className="range-track">
        <div className="range-wide" style={span(outerLow, outerHigh)} />
        <div className="range-band" style={span(low, high)} />
        {value != null && (
          <div className="range-marker" style={{ left: at(value) }} />
        )}
      </div>
      <div className="range-ticks">
        <span style={{ left: at(low) }}>{tick(low)}</span>
        <span style={{ left: at(high) }}>{tick(high)}</span>
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
