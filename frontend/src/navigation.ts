// Dove si trova la pagina, nell'URL (todo 51, allargato dal todo 55).
//
// Niente router di libreria: la Day gestiva gia' il suo giorno con
// `URLSearchParams` e `history.pushState`, e per due pagine basta la stessa
// idea allargata. Lo stato sta nella stringa di ricerca e non nel percorso:
// i percorsi veri (`/week`) vorrebbero il fallback a `index.html` nel server
// di sviluppo e in quello dell'API, e non vale il prezzo.
//
// Due assi, come il menu a due righe: `?period=` dice il periodo (day o
// week), `?view=` che cosa se ne guarda. Le viste sono **di ogni periodo**
// (todo 59): `snap|training|trend`, le stesse tre per Day e Week.
//
// La Week ne aveva una quarta, **Plan**, col documento della settimana: e'
// andata col todo 90. I ritmi e le regole di scarico che portava sono quelli
// del blocco e si leggono nella pagina Goal; la tabella dei giorni e' nelle
// righe della Training (todo 89); e quello che restava scritto solo per quella
// settimana — l'inquadramento, i totali, le note — sta in una card della
// Training. Un `?view=plan` nei segnalibri ricade sullo Snap, che e' quello
// che `viewFromUrl` fa con qualunque vista che non esiste.
// Sono elencate in `VIEWS`, nell'ordine in cui stanno nel menu, e la prima
// e' quella che si apre senza `?view=`.
//
// Senza niente si apre Day/Snap, cosi' `?day=2026-10-07` basta da solo.
//
// **Le forme vecchie non si leggono piu'.** `?page=week`, che valeva fino al
// todo 55, ha smesso: era compatibilita' verso i link di un'app con un
// utente solo, e in `summary/` e in `plan/` non ce n'era nessuno. Un
// `?page=week` che sopravvive in un segnalibro adesso apre Day/Snap — la
// stessa ricaduta di qualunque indirizzo che non si capisce, non un errore.
//
// Una chiave che non c'e' piu' non ha comunque bisogno di codice: `?view=report`,
// la vista del giorno fino al todo 67, ricade sulla vista di partenza perche'
// `viewFromUrl` valida contro `VIEWS`, e quella validazione serve a se stessa.
//
// La **Plan** sta sullo stesso asse, `?period=plan`, ma non e' un periodo: i
// piani di `plan/` guardano avanti e durano quanto dura un blocco, non un
// giorno o una settimana. Per questo nella barra sta a destra, staccata, e
// non fra Day e Week; il piano aperto e' `?plan=<slug>`, cioe' il nome del
// suo file senza `.md`. Viste non ne ha.
export type Page = "day" | "week" | "plan";
export type View = "snap" | "training" | "trend";

/** Le viste di ogni periodo, nell'ordine del menu (todo 59).
 *
 * La **prima e' quella di partenza**: `hrefFor` le toglie il parametro e
 * `viewFromUrl` ci ricade: cosi' `?period=week` da solo apre lo Snap, che e'
 * quello che quel link apriva prima che le viste esistessero.
 *
 * Il Trend sta in tutte e due le liste perche' e' la stessa domanda — come
 * si muove nel tempo — e cambiando periodo la vista si porta dietro.
 *
 * Dal todo 68 anche il **Training** sta in tutte e due: nel giorno e' la
 * seduta, nella settimana le sette — il grafico, l'elenco, il commento sulla
 * forma del lavoro e la strategia di quella che viene. Prima stavano nello
 * Snap della Week, che adesso e' il solo corpo come quello del giorno. */
export const VIEWS: Record<Page, View[]> = {
  day: ["snap", "training", "trend"],
  week: ["snap", "training", "trend"],
  plan: [],
};

/** Il nome con cui ogni vista si scrive: nella riga del menu e nel titolo
 * della pagina. Sta qui e non in `TopBar` perche' e' il vocabolario di
 * `View`, e serve in tutti e due i posti; essendo un `Record<View, string>`
 * il compilatore obbliga a riempirla, quindi una vista nuova non puo'
 * restare senza nome. */
export const ETICHETTE: Record<View, string> = {
  snap: "Snap",
  training: "Training",
  trend: "Trend",
};

/** La vista che un periodo apre quando l'URL non ne chiede nessuna. */
export function defaultView(page: Page): View {
  return VIEWS[page][0] ?? "snap";
}

/** L'ampiezza della finestra del Trend: gli stessi estremi che l'API
 * accetta (`TREND_MIN_DAYS` e `TREND_MAX_DAYS` in `daily_data.py`), cosi' il
 * cursore non puo' chiedere una finestra che riceve un 422. */
export const MIN_DAYS = 5;
export const MAX_DAYS = 365;
export const DEFAULT_DAYS = 28;

/** Lo stesso per il Trend della Week (todo 78), ma in settimane:
 * `TREND_MIN_WEEKS` e `TREND_MAX_WEEKS`. Di suo le dodici su cui la Week
 * misura gia' le fasce delle sue card, cosi' il Trend si apre sugli stessi tre
 * mesi di cui quelle parlano. */
export const MIN_WEEKS = 4;
export const MAX_WEEKS = 52;
export const DEFAULT_WEEKS = 12;

function search(): URLSearchParams {
  return new URLSearchParams(window.location.search);
}

export function pageFromUrl(): Page {
  const value = search().get("period");
  if (value === "week") return "week";
  if (value === "plan") return "plan";
  return "day";
}

/** La vista chiesta dall'URL, se quel periodo ce l'ha; se no la sua prima.
 *
 * La validazione serve anche a raddrizzare i link storti: `view=report` sulla
 * Day, che il `plan` non ce l'ha, apre lo Snap invece di una pagina muta. */
export function viewFromUrl(page: Page): View {
  const value = search().get("view") as View | null;
  return value && VIEWS[page].includes(value) ? value : defaultView(page);
}

/** I giorni del Trend, riportati fra gli estremi; `DEFAULT_DAYS` se manca o
 * non e' un numero. */
export function daysFromUrl(): number {
  // Senza il controllo sul nullo `Number(null)` sarebbe 0, che e' un numero
  // finito: il cursore partiva dal minimo invece che da 28.
  const text = search().get("days");
  const value = text === null ? NaN : Number(text);
  if (!Number.isFinite(value)) return DEFAULT_DAYS;
  return Math.min(MAX_DAYS, Math.max(MIN_DAYS, Math.round(value)));
}

/** Le settimane del Trend della Week, riportate fra gli estremi;
 * `DEFAULT_WEEKS` se manca o non e' un numero. Lo stesso controllo sul nullo
 * di `daysFromUrl`, per lo stesso motivo. */
export function weeksFromUrl(): number {
  const text = search().get("weeks");
  const value = text === null ? NaN : Number(text);
  if (!Number.isFinite(value)) return DEFAULT_WEEKS;
  return Math.min(MAX_WEEKS, Math.max(MIN_WEEKS, Math.round(value)));
}

/** Il valore di un parametro dell'URL, o `null`. */
export function paramFromUrl(name: string): string | null {
  return search().get(name);
}

/** Cambia l'URL senza ricaricare, e lascia una voce nella cronologia: il
 * tasto indietro del browser torna dov'eri. `null` toglie il parametro.
 *
 * Emette anche un `popstate` finto, che il browser manda solo su avanti e
 * indietro: cosi' chi segue l'URL (`App`, e le pagine per i loro parametri)
 * si aggiorna anche quando a muoversi e' un tasto della pagina, senza che
 * nessuno debba ricaricare. */
export function pushUrl(changes: Record<string, string | null>): void {
  const url = new URL(window.location.href);
  for (const [name, value] of Object.entries(changes)) {
    if (value === null) url.searchParams.delete(name);
    else url.searchParams.set(name, value);
  }
  window.history.pushState({}, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/** L'indirizzo di una pagina, per gli `href` della barra in alto: un
 * collegamento vero, che si puo' aprire in una scheda nuova.
 *
 * Tiene il giorno, il lunedi' e l'ampiezza del Trend: passando da Snap a
 * Trend si resta sul giorno che si stava guardando, che e' il motivo per cui
 * il menu e' annidato.
 *
 * `view` lo si puo' non dire, e allora e' quella di partenza di quel
 * periodo; e il parametro si scrive solo quando serve, cioe' quando non e'
 * la prima della lista. */
export function hrefFor(page: Page, view?: View): string {
  const params = search();
  if (page === "day") params.delete("period");
  else params.set("period", page);
  const wanted = view ?? defaultView(page);
  if (wanted === defaultView(page)) params.delete("view");
  else params.set("view", wanted);
  const text = params.toString();
  return text ? `?${text}` : "?";
}
