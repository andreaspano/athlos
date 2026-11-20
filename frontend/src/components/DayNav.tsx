// Le frecce con cui si sceglie il giorno: indietro, avanti, "oggi" e il
// calendario (todo 34, staccate dalla `DayHeader` quando la pagina Test ha
// voluto scegliere il giorno anche lei).
//
// **Stanno qui e non nella `DayHeader`** perche' quella porta con se' due
// cose che sono della Day e non della scelta del giorno: la striscia della
// settimana e il tasto Refresh, che fa girare gli agenti. Su un banco di
// prova il Refresh non ha senso — non c'e' nessun report da riscrivere — e
// un tasto che non fa niente e' peggio di un tasto che non c'e'.
//
// Il giorno piu' avanti di `maxDay` non si sceglie da nessuna parte: i
// numeri di un giorno che non e' arrivato non esistono, e l'API risponde 422.
import { addDays } from "../format";
import { DatePick } from "./DatePick";

export function DayNav({
  day,
  maxDay,
  onChange,
}: {
  day: string;
  maxDay: string;
  onChange: (day: string) => void;
}) {
  return (
    <div className="day-nav">
      <button
        type="button"
        className="btn icon-btn"
        onClick={() => onChange(addDays(day, -1))}
        aria-label="Previous day"
      >
        ‹
      </button>
      <button
        type="button"
        className="btn icon-btn"
        onClick={() => onChange(addDays(day, 1))}
        disabled={day >= maxDay}
        aria-label="Next day"
      >
        ›
      </button>
      {/* Il salto all'ultimo giorno: la freccia contro la sbarra, come
          il "vai in fondo" dei lettori. Oggi e' sempre il giorno piu'
          recente, quindi la sbarra e' la fine della fila. */}
      <button
        type="button"
        className="btn icon-btn"
        onClick={() => onChange(maxDay)}
        disabled={day === maxDay}
        aria-label="Today"
        title="Today"
      >
        <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
          <path
            d="M4.5 3.5 9 8l-4.5 4.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M11.5 3.5v9"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </button>
      <DatePick value={day} max={maxDay} onPick={onChange} label="Pick a date" />
    </div>
  );
}
