// Il calendario della pagina Week: non i giorni del mese, ma le settimane,
// scritte come nella striscia — il numero ISO e le date del lunedi' e della
// domenica. Un calendario a giorni qui chiederebbe di scegliere un giorno
// per dire una settimana, che e' un passaggio in piu' e una domanda
// diversa da quella che si sta facendo.
import { useEffect, useRef, useState } from "react";

import { addDays, isoWeek, shortDayLabel, weekMonthLabel } from "../format";

// Un anno di settimane: quanto basta per tornare indietro in una stagione
// senza fare una lista infinita. Piu' lontano si arriva con le frecce.
const WEEKS = 52;

/** Le settimane da mostrare, dalla piu' vecchia all'ultima che si puo'
 * guardare.
 *
 * L'ultima e' la corrente, o il confine del piano quando avanti si puo'
 * andare (todo 88): l'anno indietro resta un anno indietro, e in cima si
 * aggiungono le settimane previste. */
function weekList(current: string, limit: string): string[] {
  const last = limit > current ? limit : current;
  const weeks: string[] = [];
  for (let k = WEEKS - 1; k >= 0; k -= 1) weeks.push(addDays(current, -7 * k));
  for (let week = addDays(current, 7); week <= last; week = addDays(week, 7)) weeks.push(week);
  return weeks;
}

export function WeekCalendar({
  monday,
  current,
  limit,
  onSelect,
}: {
  monday: string;
  current: string;
  /** L'ultima settimana elencata: il confine del piano (todo 88). Senza, la
   * corrente. */
  limit?: string;
  onSelect: (monday: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);

  // Si chiude con Escape e cliccando fuori, come ci si aspetta da un menu
  // a discesa; il click dentro lo gestiscono i bottoni.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  // All'apertura la lista si porta sulla settimana aperta: con un anno di
  // righe, quella che interessa dev'essere gia' sotto gli occhi.
  useEffect(() => {
    if (!open) return;
    const chosen = list.current?.querySelector<HTMLElement>(
      ".week-cal-row.selected",
    );
    if (chosen && list.current) {
      list.current.scrollTop = chosen.offsetTop - list.current.clientHeight / 2;
    }
  }, [open]);

  const weeks = weekList(current, limit ?? current);
  let mese = "";

  return (
    <div className="week-cal" ref={box}>
      <button
        type="button"
        className="btn icon-btn"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label="Pick a week"
        title="Pick a week"
      >
        <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
          <rect
            x="1.5"
            y="3"
            width="13"
            height="11.5"
            rx="2"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          />
          <path
            d="M1.5 7h13M5 1.5v3M11 1.5v3"
            stroke="currentColor"
            strokeWidth="1.5"
          />
        </svg>
      </button>
      {open && (
        <div
          className="week-cal-pop"
          role="dialog"
          aria-label="Pick a week"
          ref={list}
        >
          {weeks.map((week) => {
            const intestazione = weekMonthLabel(week);
            const nuovo = intestazione !== mese;
            mese = intestazione;
            const classes = [
              "week-cal-row",
              week === monday ? "selected" : "",
              week === current ? "today" : "",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <div key={week}>
                {nuovo && <div className="week-cal-month">{intestazione}</div>}
                <button
                  type="button"
                  className={classes}
                  onClick={() => {
                    setOpen(false);
                    onSelect(week);
                  }}
                  aria-current={week === monday ? "page" : undefined}
                >
                  <span className="week-cal-number">
                    W{String(isoWeek(week)).padStart(2, "0")}
                  </span>
                  <span className="week-cal-dates">
                    {shortDayLabel(week)} – {shortDayLabel(addDays(week, 6))}
                  </span>
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
