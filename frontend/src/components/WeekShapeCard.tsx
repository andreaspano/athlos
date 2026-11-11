// La forma del blocco, nella Training della settimana: i chilometri previsti
// e fatti settimana per settimana sull'asse di sinistra, e come si
// distribuisce la velocita' di ognuna — mediana, quartili e baffi al 5 e al
// 95 percentile — su quello di destra, con la riga del ritmo gara.
//
// **Ha girato**, e vale dire dove: era una card dentro questa stessa vista
// (todo 96, tre pannelli in percentuale del bersaglio), poi una pagina a se'
// con una card per goal, e adesso torna qui in un grafico solo. Il motivo e'
// la domanda: *sto arrivando dove il blocco voleva portarmi* la si fa
// guardando la settimana che si e' appena chiusa, e si faceva andando a
// cercarla in un'altra pagina.
//
// **C'e' solo se quella settimana sta in un blocco**, e lo decide l'API: il
// file della settimana dichiara un `plan:`, quello e' il blocco, e senza di
// lui `GET /api/weekly/<lunedi>/shape/chart/vega` risponde 404 — le settimane
// prima che il blocco cominciasse non ce l'hanno, e non e' un guasto. Un 404
// qui vuol dire "niente card", non un avviso.
//
// **Batte una volta a settimana**, come il report: il disegno e' il blocco
// com'era alla **fine della settimana aperta** — i chilometri fatti si
// fermano li', le settimane dopo tengono le sole barre del piano — e la
// settimana in corso non porta il suo punto finche' non e' finita. Il taglio
// lo fa l'API (`until`), che e' la regola del todo 52: qui dentro non si
// conta niente.
import { useEffect, useState } from "react";

import { api, isAbort, type VegaSpec } from "../api/client";
import { type ColorScheme } from "../useColorScheme";
import { CardHead } from "./Stat";
import { OneChart } from "./TrendPanels";

// L'icona del Trend: il blocco e' come si sta muovendo, su diciotto settimane
// invece che su dodici. Non quella del piano (`next.png`), che in questa vista
// ce l'ha gia' la colonna del previsto, e due riquadri di fila con lo stesso
// segno si leggono come uno solo.
const BLOCK_ICON = "trend.png";

export function WeekShape({
  monday,
  theme,
}: {
  monday: string;
  theme: ColorScheme;
}) {
  // `undefined` e' "non ancora arrivato", `null` e' "questa settimana non sta
  // in un blocco": sono due cose diverse, e la seconda non disegna niente.
  const [spec, setSpec] = useState<VegaSpec | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setSpec(undefined);
    setFailed(false);
    api
      .weekShapeChart(monday, theme, controller.signal)
      .then(setSpec)
      .catch((error: unknown) => {
        if (!isAbort(error)) setFailed(true);
      });
    return () => controller.abort();
  }, [monday, theme]);

  // Niente blocco, niente card: una cornice vuota in fondo alla vista
  // direbbe che manca qualcosa, e non manca niente — quella settimana sta
  // fuori da ogni blocco. E' la stessa scelta della colonna del piano, che
  // una settimana senza file la dice in una riga invece di disegnarla a
  // trattini, con la differenza che qui non c'e' nemmeno niente da dire.
  if (spec === null) return null;

  return (
    <section className="card week-shape" aria-label="Block">
      <CardHead icon={BLOCK_ICON} title="Block" />
      {failed && <p className="warning">The block chart could not be loaded.</p>}
      {spec === undefined && !failed && <p className="caption">Loading the block…</p>}
      {spec && <OneChart chart={{ key: monday, label: "Block", spec }} theme={theme} />}
    </section>
  );
}
