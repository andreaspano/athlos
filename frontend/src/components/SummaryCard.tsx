// Il riquadro "Summary": fondo scuro e un accento suo, il viola, nato per
// stare accanto all'arancio di Next — che non c'e' piu', ne' nel giorno
// (todo 66) ne' nella settimana (todo 69).
//
// **Un pezzo, adesso, in tutti e due i periodi**: un giro scrive il
// verdetto, e il verdetto e' uno. Il giorno ne aveva due fino al todo 66 (il
// sole del mattino e la luna della sera, todo 49) e la settimana fino al 68
// (l'apertura del lunedi e la chiusura della domenica). La forma a due pezzi
// resta nel codice — `evening` opzionale — perche' costa due righe e un
// giorno potrebbe tornare utile.
//
// Senza `evening` la card e' un pezzo solo e l'occhiello dice "Summary"
// senza aggiungere altro: non c'e' niente da cui distinguerlo.
import type { ReactNode } from "react";

import { iconUrl, type Verdict } from "../api/client";
import { markdown } from "../markdown";
import { WrittenAt } from "./Stat";

export type SummaryPart = {
  body: string | null;
  writtenAt: string | null;
  refresh?: ReactNode;
};

function Part({
  part,
  day,
  glyph,
  when,
  tone,
  face,
}: {
  part: SummaryPart;
  day: string;
  glyph: string;
  when: string;
  tone?: string;
  face?: Verdict | null;
}) {
  if (!part.body) return null;
  return (
    <div className="next-main">
      <span
        className={tone ? `next-icon ${tone}` : "next-icon"}
        aria-hidden="true"
      >
        {glyph}
      </span>
      <div>
        <div className="eyebrow">
          Summary{when && ` · ${when}`}
          {/* La faccia del verdetto (todo 92): la media delle quattro card
              sotto, che e' quello che questo testo riassume. */}
          {face && (
            <img
              className="head-face"
              src={iconUrl(`${face}.png`)}
              alt={face}
              title={face}
              width={20}
              height={20}
            />
          )}
          {part.refresh}
        </div>
        <div className="next-reason">{markdown(part.body)}</div>
        <WrittenAt when={part.writtenAt} day={day} />
      </div>
    </div>
  );
}

export function SummaryCard({
  morning,
  evening,
  day,
  week,
  face,
}: {
  morning: SummaryPart;
  // Senza di lui la card e' un pezzo solo: e' il caso del giorno (todo 66).
  evening?: SummaryPart;
  day: string;
  // Il verdetto della settimana (todo 53): gli stessi due blocchi, e anche
  // qui il primo e' di mattina (il lunedi) e il secondo di sera (la
  // domenica), quindi i due glifi restano il sole e la luna.
  week?: boolean;
  /** La faccia del verdetto (todo 92): la media delle quattro card. Sta sul
   * primo pezzo, che e' quello che c'e' sempre. */
  face?: Verdict | null;
}) {
  return (
    <section className="next-card summary-card" aria-label="Summary">
      <Part
        part={morning}
        day={day}
        glyph="☀"
        when={evening ? (week ? "week start" : "morning") : ""}
        face={face}
      />
      {evening && (
        <Part
          part={evening}
          day={day}
          glyph="☾"
          when={week ? "week end" : "evening"}
          tone="moon"
        />
      )}
      {!morning.body && !evening?.body && (
        <div className="next-main">
          <span className="next-icon" aria-hidden="true">
            ≡
          </span>
          <div>
            <div className="eyebrow">Summary</div>
            <p className="next-reason">
              {week ? "No summary for this week." : "No summary for this day."}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
