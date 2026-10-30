// La barra in alto (todo 34), su due righe dal todo 55.
//
// Prima riga il **periodo** (Day, Week), seconda riga **cosa se ne guarda**:
// due assi veri, mentre prima Day, Week e Activities stavano in fila come se
// fossero la stessa cosa.
//
// Le viste sono di ogni periodo e stanno in `VIEWS` (todo 59): Snap,
// Training e Trend sotto Day, Snap, Trend e Plan sotto Week. Lo Snap e' la
// prima di tutti e due, e **la stessa chiave**: cambiando periodo si resta
// sull'istantanea del nuovo (todo 67, che il Report del giorno l'ha
// rinominato cosi'). I nomi con cui
// si scrivono stanno li' accanto (`ETICHETTE`), che servono anche al titolo
// della pagina.
//
// A destra sta **Goal**, perche' un obiettivo non e' un periodo: non guarda
// indietro a un giorno o a una settimana, guarda avanti a una gara, e dura
// quanto dura il blocco. Di viste non ne ha, quindi apre la barra con una
// riga sola.
//
// Si chiamava Plan, come la pagina e come `?period=plan`, che restano. Nella
// barra erano **due Plan**: questo e la vista della Week, che e' un'altra
// cosa — la settimana del piano, dentro la settimana. Il nome nuovo dice
// quello che la pagina mostra, cioe' la gara a cui si va e quanto manca; il
// piano e' il come, ed e' una scheda dentro.
//
// **Niente voci grigie, da nessuna parte.** Month, Year e Activities si
// aggiungono quando esistono, non prima: Activities e' stata per mesi una
// pillola disattivata che non portava in nessun posto, e una voce che non si
// puo' premere e' rumore, non una promessa.
import { ETICHETTE, VIEWS, defaultView, hrefFor, type Page, type View } from "../navigation";

const PERIODI: { page: Page; label: string }[] = [
  { page: "day", label: "Day" },
  { page: "week", label: "Week" },
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
          <nav aria-label="Periods">
            {PERIODI.map(({ page, label }) => (
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
        <nav aria-label="Other pages" className="topbar-aside">
          <a
            className={current === "plan" ? "tab active" : "tab"}
            href={hrefFor("plan")}
            aria-current={current === "plan" ? "page" : undefined}
          >
            Goal
          </a>
        </nav>
      </div>
    </header>
  );
}
