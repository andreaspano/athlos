// Il giudizio sulla seduta (todo 66): la terza card della vista Training.
//
// E' il testo della sezione Training del report, che fino a ieri stava
// **dentro** la card della seduta, nella colonna di destra accanto ai menu.
// Li' era una didascalia dei numeri; qui e' quello che e': il verdetto
// dell'allenatore, che dal todo 64 guarda sia il piano del giorno sia come
// l'hai eseguito. Lo scrive il giro della sera, alle nove.
//
// La cornice c'e' sempre, anche senza testo: la vista Training ha tre
// riquadri a qualunque data, e uno che va e viene si legge come un errore.
// Lo stesso ragionamento della card Plan (todo 63), e come quella un giorno
// senza testo resta vuoto invece di spiegare perche'.
import type { ReactNode } from "react";

import { markdown } from "../markdown";
import { CardHead, WrittenAt } from "./Stat";
import type { Verdict } from "../api/client";

// Un fumetto, non il manubrio della sezione Training: fino a ieri la card
// prendeva l'icona del report, la stessa della card della seduta che ha
// subito sopra, e due riquadri di fila con lo stesso segno si leggevano come
// uno solo. Qui l'icona e' fissa come quella di Plan (`PLAN_ICON`), perche'
// anche questa dice cosa e' il riquadro, non di che sezione e' figlio.
const COMMENT_ICON = "comment.png";

export function TrainingCommentCard({
  comment,
  writtenAt,
  day,
  face,
  refresh,
}: {
  comment: string | null;
  /** Il voto dell'agente (todo 92): questa card non ha misure, ha un
   * giudizio, e la parola la scrive chi il giudizio lo da'. */
  face: Verdict | null;
  writtenAt: string | null;
  day: string;
  refresh?: ReactNode;
}) {
  return (
    <section className="card comment-card" aria-label="Comment">
      <CardHead icon={COMMENT_ICON} title="Comment" face={face} refresh={refresh} />
      {comment && <div className="prose">{markdown(comment)}</div>}
      <WrittenAt when={writtenAt} day={day} />
    </section>
  );
}
