// "Health" (todo 37, prima un blocco di "This morning"): frequenza a riposo,
// HRV, respiro e stress da `/api/daily/{day}`, sotto la sezione Health del
// report. Il frontend non fa conti: medie e fasce vengono dall'API.
import type { ReactNode } from "react";

import type { DailyData, Verdict } from "../api/client";
import { markdown } from "../markdown";
import { CardHead, MeasureBar, Stat, WrittenAt, num } from "./Stat";

export function HealthCard({
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
  const m = data.morning;
  // Sotto ogni numero solo la barra della sua fascia: dice da sola dove sta
  // il valore, e gli estremi sono scritti sulle tacche. Tutte e quattro le
  // fasce sono quelle dell'API (`band`): media dei 28 giorni prima piu' e
  // meno uno scarto tipo. La fascia equilibrata di Garmin (`hrv_baseline`)
  // resta nei dati e la usano il report e l'allarme dell'HRV, non la card.
  return (
    <section className="card" aria-label="Health">
      <CardHead icon={icon} title="Health" face={face} refresh={refresh} />
      <div className="stats two">
        <Stat
          label="Resting heart rate"
          value={num(m.resting_hr.value)}
          unit="bpm"
          // Sotto il numero solo la barra: la fascia dice da sola dove sta
          // il valore, e i suoi estremi sono scritti sulle tacche.
          sub={<MeasureBar measure={m.resting_hr} />}
        />
        <Stat
          label="HRV, last night"
          value={num(m.hrv_last_night.value)}
          unit="ms"
          sub={<MeasureBar measure={m.hrv_last_night} />}
        />
        <Stat
          label="Breathing in sleep"
          value={num(m.resp_sleep.value, 1)}
          unit="/min"
          sub={<MeasureBar measure={m.resp_sleep} />}
        />
        <Stat label="Stress, yesterday" value={num(m.stress_avg_yesterday.value)} sub={<MeasureBar measure={m.stress_avg_yesterday} />} />
      </div>
      {text && <div className="prose">{markdown(text)}</div>}
      <WrittenAt when={writtenAt} day={day} />
    </section>
  );
}
