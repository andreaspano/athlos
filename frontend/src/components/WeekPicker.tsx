// Il selettore di settimane della pagina Week (todo 53): sei bottoni, uno
// per settimana, ognuno con il numero ISO e le date del lunedi' e della
// domenica.
//
// Non e' `WeekStrip` con una bandierina: quella mostra giorni, questa
// settimane, e mescolarle complicherebbe tutte e due. La Day tiene la sua.
import { useEffect, useRef } from "react";

import { addDays, isoWeek, shortDayLabel } from "../format";

// Sei settimane: un mese e mezzo, che si guarda tutto in un colpo senza
// che la striscia diventi un muro di riquadri. Per una settimana vecchia
// la striscia finisce due settimane dopo di lei, cosi' si vede anche cosa
// e' venuto dopo.
const WEEKS = 6;
const AFTER = 2;

/** Le sei settimane da mostrare, dalla piu' vecchia, quando si guarda
 * `monday`, la settimana corrente e' `current` e avanti si arriva fino a
 * `limit`.
 *
 * Nel passato e sulla corrente la regola e' quella di sempre: la fila
 * finisce sulla settimana corrente, e per una settimana vecchia due
 * settimane dopo di lei, cosi' si vede anche cosa e' venuto dopo.
 *
 * **Avanti vale la stessa regola** (todo 88), col tetto spostato dalla
 * corrente al confine del piano: camminando con la freccia la fila scorre e
 * le settimane che vengono compaiono da se', senza una regola in piu'.
 * Senza `limit` il tetto resta la settimana corrente, cioe' la pagina di
 * prima di quel todo. */
function weeksAround(monday: string, current: string, limit?: string): string[] {
  const oldest = addDays(current, -7 * (WEEKS - 1));
  const ahead = minWeek(addDays(monday, 7 * AFTER), limit ?? current);
  const end = monday > current ? ahead : monday >= oldest ? current : minWeek(ahead, current);
  const weeks: string[] = [];
  for (let k = WEEKS - 1; k >= 0; k -= 1) weeks.push(addDays(end, -7 * k));
  return weeks;
}

const minWeek = (a: string, b: string) => (a < b ? a : b);

export function WeekPicker({
  monday,
  current,
  limit,
  onSelect,
}: {
  monday: string;
  current: string;
  /** L'ultima settimana che si puo' guardare: il confine del piano (todo 88).
   * Senza, la fila si ferma sulla settimana corrente. */
  limit?: string;
  onSelect: (monday: string) => void;
}) {
  const strip = useRef<HTMLElement>(null);
  // Sul telefono la striscia scorre: la settimana scelta si porta in vista,
  // muovendo solo la striscia e non la pagina.
  useEffect(() => {
    const chosen = strip.current?.querySelector<HTMLElement>(".strip-week.selected");
    if (chosen) strip.current?.scrollTo({ left: chosen.offsetLeft - 8 });
  }, [monday, current]);

  return (
    <nav className="week-strip" aria-label="Weeks" ref={strip}>
      {weeksAround(monday, current, limit).map((week) => {
        const chosen = week === monday;
        const classes = ["strip-week", chosen ? "selected" : "", week === current ? "today" : ""]
          .filter(Boolean)
          .join(" ");
        return (
          <button
            type="button"
            key={week}
            className={classes}
            onClick={() => onSelect(week)}
            aria-current={chosen ? "page" : undefined}
          >
            <span className="strip-number">W{String(isoWeek(week)).padStart(2, "0")}</span>
            <span className="strip-dates">
              {shortDayLabel(week)}
              <br />
              {shortDayLabel(addDays(week, 6))}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
