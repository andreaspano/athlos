// L'intestazione del giorno (todo 34): la data, le frecce, "Today" e la
// scelta della data. A destra, passata da `DayPage`, la striscia della
// settimana, e in fondo alla striscia il tasto Refresh (todo 41).
import { useEffect, useState, type ReactNode } from "react";

import { longDayLabel } from "../format";
import { DayNav } from "./DayNav";

/** Il tempo da `started` (ora locale dell'API, sulla stessa macchina), "m:ss". */
function elapsed(started: string, now: number): string {
  const seconds = Math.max(
    0,
    Math.floor((now - new Date(started).getTime()) / 1000),
  );
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** Il tasto Refresh, in fondo alla striscia: solo l'icona, senza scritta.
 * Mentre il lavoro gira l'icona ruota, il tasto non si clicca e da quanto va
 * avanti lo dice il tooltip, che e' anche il nome del tasto per chi legge la
 * pagina con la voce. */
function RefreshButton({
  running,
  onRefresh,
}: {
  running: string | null;
  onRefresh: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  const label = running
    ? `Refreshing… ${elapsed(running, now)}`
    : "Refresh: download new data from Garmin and rewrite this day's report (a few minutes)";
  return (
    <button
      type="button"
      className="btn icon-btn refresh-btn"
      onClick={onRefresh}
      disabled={running !== null}
      aria-busy={running !== null}
      aria-label={label}
      title={label}
    >
      <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
        <path
          d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <path
          d="M12.5 1.5v3h-3"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}

export function DayHeader({
  day,
  maxDay,
  onChange,
  refreshing,
  onRefresh,
  children,
}: {
  day: string;
  maxDay: string;
  onChange: (day: string) => void;
  // L'ora di inizio del lavoro di Refresh in corso, `null` se non ce n'e'.
  refreshing: string | null;
  onRefresh: () => void;
  children?: ReactNode;
}) {
  return (
    <section className="day-header">
      <div className="day-title">
        <h1>{longDayLabel(day)}</h1>
        <DayNav day={day} maxDay={maxDay} onChange={onChange} />
      </div>
      <div className="day-strip">
        {children}
        <RefreshButton running={refreshing} onRefresh={onRefresh} />
      </div>
    </section>
  );
}
