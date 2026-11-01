// "Fitness" (todo 37 e 38, rifatta dal 48 sullo stampo di Health): cosa
// Andrea e' capace di fare, che cambia piano nelle settimane. VO2max (prima
// in fondo a "Load"), endurance e hill score di Garmin e la soglia del
// lattato (o, prima che Garmin ne rilevi una, la frequenza di soglia del
// FIT), da `fitness` di `/api/daily/{day}`. Il testo lo scrive l'agente
// `04_fitness` (todo 44). Un valore che manca e' "–", la card resta.
//
// Accanto al numero non va niente: la variazione in 28 giorni ("+1.2 in 28
// days") raccontava un andamento, e queste card dicono com'e' oggi. Dove sta
// la misura lo fa vedere la barra.
//
// I due acclimatamenti stanno in fondo accanto alla soglia: non sono
// capacita' che crescono, sono dove il corpo si trova adesso. Zero per quasi
// tutto l'anno, 1400 m nelle settimane in montagna e 58% di caldo in un
// settembre.
import type { ReactNode } from "react";

import type { DailyData, Verdict } from "../api/client";
import { markdown } from "../markdown";
import { CardHead, EmptyBar, RangeBar, Stat, WrittenAt, num } from "./Stat";

export function FitnessCard({
  data,
  text,
  writtenAt,
  day,
  icon,
  face,
  refresh,
}: {
  data: DailyData;
  text: string | null;
  writtenAt: string | null;
  day: string;
  icon: string | null;
  /** La faccia della card (todo 92). */
  face: Verdict | null;
  refresh?: ReactNode;
}) {
  const vo2 = data.fitness.vo2max;
  const endurance = data.fitness.endurance;
  const hill = data.fitness.hill;
  const lactate = data.fitness.lactate_threshold;
  const threshold = data.fitness.threshold_hr;
  const altitude = data.fitness.altitude_acclimation;
  const heat = data.fitness.heat_acclimation;
  // Sotto ogni numero solo la barra della sua fascia, come in Health e
  // Recovery. Qui pero' **sopra la fascia e' buono**: queste misure si
  // muovono in settimane, e stare sopra l'ultimo mese vuol dire che stanno
  // ancora salendo. La soglia non ha fascia (e' un valore solo, rilevato di
  // rado) e resta un numero nudo.
  return (
    <section className="card fitness-card" aria-label="Fitness">
      <CardHead icon={icon} title="Fitness" face={face} refresh={refresh} />
      {/* Tre colonne e non due: i punteggi con la loro barra sulla prima
          riga, e sulla seconda la soglia e la quota a cui il corpo e'
          acclimatato, i due numeri nudi. */}
      <div className="stats">
        <Stat
          label="VO2max"
          value={num(vo2?.now, 1)}
          sub={
            vo2?.band ? (
              <RangeBar value={vo2.now} band={vo2.band} />
            ) : (
              <EmptyBar />
            )
          }
        />
        <Stat
          label="Endurance score"
          value={num(endurance?.now)}
          sub={
            endurance?.band ? (
              <RangeBar value={endurance.now} band={endurance.band} />
            ) : (
              <EmptyBar />
            )
          }
        />
        <Stat
          label="Hill score"
          value={num(hill?.now)}
          sub={
            hill?.band ? (
              <RangeBar value={hill.now} band={hill.band} />
            ) : (
              <EmptyBar />
            )
          }
        />
        {lactate ? (
          <Stat
            label="Lactate threshold"
            value={num(lactate.heart_rate)}
            unit="bpm"
          />
        ) : (
          <Stat
            label="Threshold heart rate"
            value={num(threshold?.value)}
            unit="bpm"
          />
        )}
        <Stat
          label="Altitude acclimation"
          value={num(altitude?.metres)}
          unit="m"
          help="How high Garmin reckons your body is acclimatised to, from where you have been training. It builds over days spent high up and is lost just as fast; zero at home."
        />
        <Stat
          label="Heat acclimation"
          value={num(heat?.percent)}
          unit="%"
          help="How far Garmin reckons your body has adapted to training in the heat, from the temperature of your activities. A week of hot sessions builds it and ten cool days undo it; zero in winter."
        />
      </div>
      {text && <div className="prose">{markdown(text)}</div>}
      <WrittenAt when={writtenAt} day={day} />
    </section>
  );
}
