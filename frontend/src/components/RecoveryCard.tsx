// "Recovery" (todo 37, rifatta dal todo 46 sullo stampo di Health):
// readiness, sonno e body battery da `/api/daily/{day}`, ognuno con la barra
// della sua fascia, e sotto la sezione Recovery del report. Il frontend non
// fa conti: valori e fasce vengono dall'API.
import type { ReactNode } from "react";

import type { DailyData, Verdict } from "../api/client";
import { durationLabel } from "../format";
import { markdown } from "../markdown";
import { CardHead, MeasureBar, Stat, WrittenAt, num } from "./Stat";

/** "8h04", dai minuti dell'API. */
function sleepValue(minutes: number | null): ReactNode {
  if (minutes == null) return "–";
  return (
    <>
      {Math.floor(minutes / 60)}
      <span className="stat-unit">h</span>
      {String(minutes % 60).padStart(2, "0")}
    </>
  );
}

export function RecoveryCard({
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
  // Sotto ogni numero solo la barra della sua fascia, come in Health: dice da
  // sola dove sta il valore, e gli estremi sono scritti sulle tacche. Le due
  // barre del body battery raccontano cose diverse — la prima quanto si e'
  // ricaricato, la seconda quanto gli ha chiesto la giornata di ieri.
  return (
    <section className="card recovery-card" aria-label="Recovery">
      <CardHead icon={icon} title="Recovery" face={face} refresh={refresh} />
      <div className="stats two">
        <Stat
          label="Readiness"
          value={num(m.readiness.value)}
          sub={<MeasureBar measure={m.readiness} />}
        />
        <Stat
          label="Sleep"
          value={sleepValue(data.sleep_minutes)}
          // La fascia e' in ore e il numero grande in ore e minuti: le tacche
          // seguono il numero, cosi' le due letture si confrontano a occhio.
          sub={
            <MeasureBar
              measure={m.sleep_hours}
              value={data.sleep_minutes != null ? data.sleep_minutes / 60 : null}
              tick={(hours) => durationLabel(hours * 60)}
            />
          }
        />
        <Stat
          label="Body battery, wake-up"
          value={num(m.body_battery_morning.value)}
          sub={<MeasureBar measure={m.body_battery_morning} />}
        />
        <Stat
          label="Body battery, yesterday's low"
          value={num(m.body_battery_low_yesterday.value)}
          sub={<MeasureBar measure={m.body_battery_low_yesterday} />}
        />
      </div>
      {text && <div className="prose">{markdown(text)}</div>}
      <WrittenAt when={writtenAt} day={day} />
    </section>
  );
}
