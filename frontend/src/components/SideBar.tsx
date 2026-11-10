// La barra di navigazione, **a sinistra** (todo 34, su due righe in alto dal
// todo 55, in colonna da qui).
//
// Gli assi sono sempre due — la **pagina** (Day, Week, Goal, Result) e **cosa
// se ne guarda** (Snap, Training, Trend) — ma in verticale non sono due righe:
// sono un albero. Le viste stanno **sotto la pagina a cui appartengono**,
// rientrate, e si vedono solo per quella aperta; in orizzontale quel legame lo
// doveva indovinare l'occhio, che la seconda riga poteva essere di chiunque.
//
// Le viste sono di ogni periodo e stanno in `VIEWS` (todo 59). Lo Snap e' la
// prima di Day e Week, e **la stessa chiave**: cambiando periodo si resta
// sull'istantanea del nuovo (todo 67, che il Report del giorno l'ha rinominato
// cosi'). I nomi con cui si scrivono stanno li' accanto (`ETICHETTE`), che
// servono anche al titolo della pagina.
//
// **Goal** e **Result** non sono periodi ma sono pagine, e come pagine stanno
// in fila con le altre due: il Goal dice dove si vuole arrivare, la Result
// come sta andando il blocco che ci porta. Di viste non ne hanno, quindi sotto
// di loro non si apre niente.
//
// Il **logo** sta in cima alla colonna: `icons/athlos.png`, servito da
// `/icons` come tutte le altre icone — in sviluppo il proxy di Vite, in
// produzione il mount di `app.py`. Non e' un collegamento, e' il nome della
// casa.
//
// **Niente voci grigie, da nessuna parte.** Month, Year e Activities si
// aggiungono quando esistono, non prima: Activities e' stata per mesi una
// pillola disattivata che non portava in nessun posto, e una voce che non si
// puo' premere e' rumore, non una promessa.
//
// **La colonna si chiude**, col tasto a tre linee in alto a sinistra. Chiusa
// scivola fuori e lascia alla pagina tutta la larghezza, che e' quello che
// vogliono i grafici e le due colonne della Week; il tasto resta nella sua
// corsia stretta, che cosi' non finisce mai sopra il titolo della pagina.
//
// La scelta sta in `localStorage` e non in uno stato di React per un motivo
// preciso: le voci del menu sono collegamenti veri (`hrefFor`), quindi ogni
// clic **ricarica la pagina** e lo stato muore. Senza memoria la colonna si
// riaprirebbe a ogni passo, cioe' il tasto non servirebbe a niente.
//
// Sotto i 900 px la colonna torna una barra in alto: su un telefono una
// colonna fissa si mangerebbe un terzo della larghezza, e quella larghezza la
// vogliono le card.
import { Fragment, useLayoutEffect, useState } from "react";

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

/** Il tasto a tre linee: disegnato qui come il cestino della Goal, che
 * quelle in `icons/` sono le icone degli sport e delle sezioni, in PNG a due
 * dimensioni fisse. Questo e' un comando, e `currentColor` lo fa seguire il
 * tema come il testo accanto. */
function MenuIcon() {
  return (
    <svg viewBox="0 0 16 16" width="17" height="17" aria-hidden="true" focusable="false">
      <path
        d="M2.5 4h11M2.5 8h11M2.5 12h11"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

const RAIL_KEY = "athlos.rail";

/** Se la colonna e' aperta. Di suo si'; chiusa solo se lo si e' chiesto, e
 * allora lo dice `localStorage`. Si legge **prima del primo disegno**, cosi'
 * la pagina non si apre larga per poi stringersi. */
function railOpen(): boolean {
  try {
    return window.localStorage.getItem(RAIL_KEY) !== "closed";
  } catch {
    // Un browser che non lascia leggere la memoria (navigazione privata,
    // cookie di terze parti spenti) non deve restare senza menu.
    return true;
  }
}

export function SideBar({
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

  const [open, setOpen] = useState(railOpen);
  // La corsia e' un `padding-left` del `body`, quindi il corpo deve sapere
  // com'e' messa la colonna: e' l'unico posto da cui si governa la larghezza
  // di tutte e quattro le pagine senza un involucro comune.
  useLayoutEffect(() => {
    document.body.classList.toggle("rail-closed", !open);
  }, [open]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    try {
      window.localStorage.setItem(RAIL_KEY, next ? "open" : "closed");
    } catch {
      // La colonna si muove lo stesso: si dimentica al prossimo clic su una
      // voce, che e' meglio di un tasto che non fa niente.
    }
  };

  return (
    <>
      <button
        type="button"
        className="rail-toggle"
        onClick={toggle}
        aria-label={open ? "Hide the menu" : "Show the menu"}
        aria-expanded={open}
        aria-controls="rail"
      >
        <MenuIcon />
      </button>
    {/* Chiusa e' `inert`: scivola fuori ma resta nel documento per
        l'animazione, e senza questo i suoi collegamenti si raggiungerebbero
        ancora col tabulatore, cioe' si potrebbe navigare in un menu che non
        si vede. */}
    <header className={open ? "sidebar" : "sidebar closed"} id="rail" inert={!open}>
      <img
        className="sidebar-logo"
        src={iconUrl("athlos.png")}
        alt="Athlos"
        width={141}
        height={44}
      />
      <nav aria-label="Pages" className="sidebar-menu">
        {PAGINE.map(({ page, label }) => (
          <Fragment key={page}>
            <a
              className={page === current ? "tab active" : "tab"}
              href={hrefFor(page, vistaSu(page))}
              aria-current={page === current ? "page" : undefined}
            >
              {label}
            </a>
            {/* Le viste **della pagina aperta**, rientrate sotto di lei. Le
                altre pagine non le mostrano: sarebbero venti voci per dire
                dove si puo' andare, quando la domanda e' dove si e'. */}
            {page === current && viste.length > 1 && (
              <div className="sidebar-views">
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
              </div>
            )}
          </Fragment>
        ))}
      </nav>
    </header>
    </>
  );
}
