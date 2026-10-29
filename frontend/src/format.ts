// Date e numeri della pagina Day.
//
// I giorni restano stringhe "YYYY-MM-DD": `new Date("2026-10-07")` li legge
// in UTC, e intorno alla mezzanotte il giorno cambierebbe. Per i conti sui
// giorni si passa da `Date.UTC`, che non dipende dal fuso. Le ore dell'API
// sono locali e senza fuso ("2026-10-07T12:28:50"): si leggono dalla stringa.

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
const DAY_MS = 24 * 60 * 60 * 1000;

function parts(day: string): [number, number, number] {
  const [y, m, d] = day.split("-").map(Number);
  return [y, m, d];
}

function utc(day: string): number {
  const [y, m, d] = parts(day);
  return Date.UTC(y, m - 1, d);
}

function fromUtc(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** Oggi, nel fuso del browser. */
export function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function addDays(day: string, days: number): string {
  return fromUtc(utc(day) + days * DAY_MS);
}

/** Quanti giorni da `from` a `to`: negativo se `to` viene prima. */
export function dayDiff(from: string, to: string): number {
  return Math.round((utc(to) - utc(from)) / DAY_MS);
}

/** I giorni da `end` a `start`, compresi, dal piu' recente. */
export function daysBetween(start: string, end: string): string[] {
  const days: string[] = [];
  for (let ms = utc(end); ms >= utc(start); ms -= DAY_MS)
    days.push(fromUtc(ms));
  return days;
}

/** Il giorno di un orario dell'API. */
export function dayOf(timestamp: string): string {
  return timestamp.slice(0, 10);
}

/** "12:28". */
export function timeOf(timestamp: string): string {
  return timestamp.slice(11, 16);
}

/** L'arrotondamento di `round` di Python: a meta' strada, al pari. Le durate
 * si leggono come quelle dei report, che passano da `round`, e `Math.round`
 * darebbe un minuto in piu' sui 30 secondi (todo 33, verifica 5). */
export function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

/** Un numero con `digits` decimali, o "-" se manca. */
export function fixed(
  value: number | null | undefined,
  digits: number,
  suffix = "",
): string {
  return value == null ? "-" : `${value.toFixed(digits)}${suffix}`;
}

const WEEKDAYS_LONG = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];
const MONTHS_LONG = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** Il giorno della settimana, 0 = domenica. */
function weekdayIndex(day: string): number {
  return new Date(utc(day)).getUTCDay();
}

/** "Wednesday 7 October", con l'anno se non e' quello di oggi. */
export function longDayLabel(day: string): string {
  const [y, m, d] = parts(day);
  const year = y === parts(today())[0] ? "" : ` ${y}`;
  return `${WEEKDAYS_LONG[weekdayIndex(day)]} ${d} ${MONTHS_LONG[m - 1]}${year}`;
}

/** "Wed". */
export function weekdayShort(day: string): string {
  return WEEKDAYS[weekdayIndex(day)];
}

/** Il numero del giorno nel mese. */
export function dayNumber(day: string): number {
  return parts(day)[2];
}

/** "25 Sep". */
export function shortDayLabel(day: string): string {
  const [, m, d] = parts(day);
  return `${d} ${MONTHS[m - 1]}`;
}

/** "28 Feb 2027". L'anno c'e' sempre: una gara sta spesso nell'anno dopo. */
export function raceLabel(day: string): string {
  return `${shortDayLabel(day)} ${day.slice(0, 4)}`;
}

/** Il bersaglio come lo si dice a voce: "2:20:00" diventa "2:20", perche' i
 * secondi tondi non sono un bersaglio, sono zeri. */
export function targetLabel(time: string | null | undefined): string {
  return time ? time.replace(/:00$/, "") : "–";
}

/** Una durata in minuti: "46 min" sotto l'ora, "2h52" sopra. */
export function durationLabel(minutes: number | null | undefined): string {
  if (minutes == null || Number.isNaN(minutes)) return "-";
  const total = roundHalfEven(minutes);
  if (total < 60) return `${total} min`;
  return `${Math.floor(total / 60)}h${String(total % 60).padStart(2, "0")}`;
}

/** I minuti di un effetto: interi, ma sotto il minuto con un decimale
 * ("0.5 min"), perche' "0 min" direbbe che non c'e' niente. */
export function effectMinutesLabel(seconds: number): string {
  const minutes = seconds / 60;
  if (minutes > 0 && minutes < 1) return `${minutes.toFixed(1)} min`;
  return `${roundHalfEven(minutes)} min`;
}

/** Il ritmo di un giro: `5'56"` dai secondi al chilometro (todo 79). E'
 * l'unico posto dove l'interfaccia parla in minuti al chilometro invece che
 * in km/h, e ci vuole: il piano chiede una fascia di ritmo e le ripetute si
 * giudicano contro quella. */
export function paceLabel(secondsPerKm: number | null | undefined): string {
  if (secondsPerKm == null || Number.isNaN(secondsPerKm) || secondsPerKm <= 0) return "-";
  const total = Math.round(secondsPerKm);
  return `${Math.floor(total / 60)}'${String(total % 60).padStart(2, "0")}"`;
}

/** La durata di un giro: `5:00`, `7:46`, minuti e secondi. `durationLabel`
 * arrotonda al minuto, e un recupero di due minuti e uno di 2'30" non
 * possono leggersi uguali. */
export function lapTimeLabel(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "-";
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** "written at 10:04", o "written 21 Oct, 00:01" quando il testo e' stato
 * scritto in un giorno diverso da quello di cui parla. Succede: la Recovery
 * del 20 ottobre e' stata riscritta a mezzanotte e un minuto. */
export function writtenLabel(timestamp: string, day: string): string {
  const when = timeOf(timestamp);
  if (dayOf(timestamp) === day) return `written at ${when}`;
  return `written ${shortDayLabel(dayOf(timestamp))}, ${when}`;
}

/** Il lunedi della settimana di `day`, secondo ISO 8601 (la settimana
 * comincia il lunedi). */
export function mondayOf(day: string): string {
  const weekday = weekdayIndex(day); // 0 = domenica
  return addDays(day, weekday === 0 ? -6 : 1 - weekday);
}

/** Il numero della settimana ISO: quella che contiene il giovedi. */
export function isoWeek(day: string): number {
  // Il giovedi della settimana decide a che anno appartiene: dal 1 gennaio
  // di quell'anno si contano le settimane.
  const thursday = addDays(mondayOf(day), 3);
  const [year] = parts(thursday);
  const firstThursday = addDays(mondayOf(`${year}-01-04`), 3);
  return Math.round((utc(thursday) - utc(firstThursday)) / (7 * DAY_MS)) + 1;
}

/** "Week 43 · October 2026": il numero ISO, e il mese del **giovedi**, che
 * e' la regola ISO per le settimane a cavallo di due mesi (la 5 del 2026 va
 * dal 26 gennaio al 1 febbraio ed e' di gennaio). */
export function weekLabel(day: string): string {
  return `Week ${String(isoWeek(day)).padStart(2, "0")} · ${weekMonthLabel(day)}`;
}

/** "October 2026": il mese di una settimana, che e' quello del giovedi'. */
export function weekMonthLabel(day: string): string {
  const [y, m] = parts(addDays(mondayOf(day), 3));
  return `${MONTHS_LONG[m - 1]} ${y}`;
}
