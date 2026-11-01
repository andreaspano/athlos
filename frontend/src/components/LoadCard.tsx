// "Load" (todo 34, rifatta sullo stampo di Health): il carico di Garmin. Le
// tre parti del carico mensile, ognuna con la barra della **sua fascia
// storica** - media dei 28 giorni prima piu' e meno uno scarto tipo, come in
// Health e Recovery - e il valore di oggi come tacca, e il rapporto fra
// carico recente e abituale, che una fascia non ce l'ha. Sotto, il testo
// della sezione Load del report. Il VO2max e' passato alla card Fitness
// (todo 37).
//
// Niente titolo sopra i numeri e niente parole accanto: lo stato del carico
// secondo Garmin ("In a healthy range") diceva a mezze parole quello che la
// prima riga del testo dice per intero, e "above target" ripeteva a parole
// quello che la barra fa vedere.
import type { ReactNode } from "react";

import type { DailyData, Verdict } from "../api/client";
import { markdown } from "../markdown";
import { CardHead, EmptyBar, RangeBar, Stat, WrittenAt, num } from "./Stat";

type Key = "load_aerobic_low" | "load_aerobic_high" | "load_anaerobic";

const ROWS: { key: Key; label: string; help: string }[] = [
  {
    key: "load_aerobic_low",
    label: "Low aerobic",
    help: "Garmin's monthly load from easy aerobic work, against where it has sat over the last 28 days.",
  },
  {
    key: "load_aerobic_high",
    label: "High aerobic",
    help: "Garmin's monthly load from harder aerobic work, against where it has sat over the last 28 days.",
  },
  {
    key: "load_anaerobic",
    label: "Anaerobic",
    help: "Garmin's monthly load from efforts above threshold, against where it has sat over the last 28 days.",
  },
];

export function LoadCard({
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
  const now = data.load.now;
  const bands = data.load.bands;
  return (
    <section className="card load-card" aria-label="Load">
      <CardHead icon={icon} title="Load" face={face} refresh={refresh} />
      {/* La fascia e' quella di `_band`, come in Health, Recovery e Fitness:
          dove il carico sta di solito, non dove Garmin vorrebbe che stesse.
          Quindi due livelli, come le altre card. */}
      <div className="stats two">
        {ROWS.map(({ key, label, help }) => {
          const value = now?.[key] ?? null;
          const band = bands?.[key];
          return (
            <Stat
              key={key}
              label={label}
              help={help}
              value={num(value)}
              sub={
                band ? (
                  <RangeBar value={value} band={band} tick={(v) => v.toFixed(0)} />
                ) : (
                  <EmptyBar />
                )
              }
            />
          );
        })}
        <Stat
          label="Load ratio"
          value={num(now?.acwr, 1)}
          help="Garmin's acute-to-chronic load ratio: the last week of training against the last four. Around 1 means you are carrying what you usually carry."
        />
      </div>
      {text && <div className="prose">{markdown(text)}</div>}
      <WrittenAt when={writtenAt} day={day} />
    </section>
  );
}
