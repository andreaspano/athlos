// La barra in alto (todo 34), su due righe dal todo 55.
//
// Prima riga la **pagina** (Day, Week, Goal, Result), seconda riga **cosa se ne
// guarda**: due assi veri, mentre prima Day, Week e Activities stavano in
// fila come se fossero la stessa cosa.
//
// Le viste sono di ogni periodo e stanno in `VIEWS` (todo 59): Snap,
// Training e Trend sotto Day, Snap, Trend e Plan sotto Week. Lo Snap e' la
// prima di tutti e due, e **la stessa chiave**: cambiando periodo si resta
// sull'istantanea del nuovo (todo 67, che il Report del giorno l'ha
// rinominato cosi'). I nomi con cui
// si scrivono stanno li' accanto (`ETICHETTE`), che servono anche al titolo
// della pagina.
//
// **Goal** sta in quella prima riga, dopo Week. Un obiettivo non e' un
// periodo — non guarda indietro a un giorno o a una settimana, guarda avanti
// a una gara, e dura quanto dura il blocco — e per questo stava a destra,
// staccato. Ma staccato si trovava male: e' una delle pagine, e le pagine si
// leggono in fila. Di viste non ne ha, quindi aprendola la barra resta a una
// riga sola.
//
// **Result** le sta dopo, ed e' la coppia del Goal: quello dice dove si vuole
// arrivare, questa come sta andando il blocco che ci porta. Nemmeno lei e' un
// periodo — un blocco sono diciotto settimane, non sette giorni — e nemmeno
// lei ha delle viste.
//
// Si chiamava Plan, come la pagina e come `?period=plan`, che restano. Nella
// barra erano **due Plan**: questo e la vista della Week, che e' un'altra
// cosa — la settimana del piano, dentro la settimana. Il nome nuovo dice
// quello che la pagina mostra, cioe' la gara a cui si va e quanto manca; il
// piano e' il come, ed e' una scheda dentro.
//
// All'estremo destro, dove stava il Goal, adesso c'e' il **logo**:
// `icons/athlos.png`, servito da `/icons` come tutte le altre icone — in
// sviluppo il proxy di Vite, in produzione il mount di `app.py`. Non e' un
// collegamento, e' il nome della casa: le pagine stanno tutte a sinistra, e
// un'altra cosa da premere qui confonderebbe.
//
// **Niente voci grigie, da nessuna parte.** Month, Year e Activities si
// aggiungono quando esistono, non prima: Activities e' stata per mesi una
// pillola disattivata che non portava in nessun posto, e una voce che non si
// puo' premere e' rumore, non una promessa.
import { iconUrl } from "../api/client";
import { ETICHETTE, VIEWS, defaultView, hrefFor, type Page, type View } from "../navigation";

/** Le voci della prima riga, nell'ordine in cui si leggono. Il Goal e la
 * Result non sono periodi ma sono pagine, ed e' come pagine che stanno in
 * fila con le altre due; `VIEWS` resta il posto che dice chi ha delle viste
 * e chi no.
 *
 * L'ordine e' quello del tempo: il giorno, la settimana, la gara a cui si va
 * e come sta andando il blocco che ci porta. */
const PAGINE: { page: Page; label: string }[] = [
  { page: "day", label: "Day" },
  { page: "week", label: "Week" },
  { page: "plan", label: "Goal" },
  { page: "result", label: "Result" },
];

export function TopBar({
  current = "day",
  view = "snap",
}: {
  current?: Page;
  view?: View;
}) {
  const viste = VIEWS[current];
  // La vista si porta dietro solo dove esiste: andando sulla Day, che lo
  // Snap non ce l'ha, il collegamento torna alla prima vista di quel
  // periodo invece di lasciare nell'URL una vista che quella pagina ignora.
  const vistaSu = (page: Page): View =>
    VIEWS[page].includes(view) ? view : defaultView(page);
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="topbar-menus">
          <nav aria-label="Pages">
            {PAGINE.map(({ page, label }) => (
              <a
                key={page}
                className={page === current ? "tab active" : "tab"}
                href={hrefFor(page, vistaSu(page))}
                aria-current={page === current ? "page" : undefined}
              >
                {label}
              </a>
            ))}
          </nav>
          {viste.length > 1 && (
            <nav aria-label="Views" className="topbar-views">
              {viste.map((v) => (
                <a
                  key={v}
                  className={v === view ? "tab sub active" : "tab sub"}
                  href={hrefFor(current, v)}
                  aria-current={v === view ? "page" : undefined}
                >
                  {ETICHETTE[v]}
                </a>
              ))}
            </nav>
          )}
        </div>
        <img
          className="topbar-logo"
          src={iconUrl("athlos.png")}
          alt="Athlos"
          width={141}
          height={44}
        />
      </div>
    </header>
  );
}
