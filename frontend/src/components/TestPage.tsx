// La pagina Test: il banco di prova.
//
// Non e' una pagina del lavoro — le tre di prima si leggono, questa si usa
// mentre si scrive — ed e' il posto dove si guarda una cosa da sola, prima di
// metterla dove va. Per questo sta per ultima nella barra, dopo Goal, e non
// ha viste: `?period=test` e basta.
//
// **A sinistra quello che ha scritto Claude, a destra quello che ha scritto il
// modello di casa**, una riga per sezione, per ogni giorno dal 26 ottobre a
// oggi, **dal piu' recente al piu' vecchio**. La griglia e' a due colonne e le card stanno a coppie: la Health di
// Claude accanto alla Health di llama, poi la Load, poi la Recovery, poi la
// Fitness. Due colonne di quattro card ciascuna si leggerebbero peggio —
// il confronto e' fra le due versioni di *una* sezione, non fra due elenchi.
//
// **La pagina non genera piu' niente**, ed e' la differenza che conta. Prima
// chiedeva a ollama a ogni apertura: sei sezioni, venti secondi di attesa, e
// quando ricaricavi il testo era un altro. Adesso legge il quaderno del banco
// (`bench/local_text.jsonl`), scritto quando il ciclo di taratura ha girato,
// quindi venticinque giorni arrivano in una richiesta e un giorno di tre
// settimane fa si rilegge uguale a com'era. Il tasto «Ask again» non c'e'
// piu': per testi nuovi si lancia il ciclo (`make bench_tune`), che li scrive
// e li misura.
//
// **Il 26 ottobre non e' una data a caso**: e' l'ultimo giorno in cui un
// prompt di Claude e' cambiato (`af2e411`, alle 18:03, e il frammento della
// Load di quel giorno e' nato alle 22:00). Prima di li' il bersaglio e' un
// altro prompt, e un bersaglio che si muove non e' un bersaglio.
//
// **Le quattro sezioni a destra sono quelle spezzate** — un modello per
// paragrafo, cucito da Python — perche' sono quelle che il ciclo tara e che
// hanno vinto il confronto con la domanda sola. Le intere restano nel
// quaderno come termine di paragone e si guardano con `grep`.
//
// I numeri, le barre e le facce restano quelli dell'API, come sulla Day: una
// richiesta per giorno a `/api/daily/{giorno}`, e il giorno si disegna quando
// la sua arriva. L'icona in testa alla card no: verrebbe dal report, che
// sarebbero altre venticinque richieste per una decorazione.
//
// **La Day non la tocca nessuno.** I frammenti in `summary/01.daily/` restano
// quelli che gli agenti di Claude hanno scritto, e quello che si vede qui a
// sinistra e' una copia di quel testo che il quaderno si e' tenuto accanto al
// suo: la colonna di destra non ha modo di arrivare da quella parte.
import { useEffect, useState } from "react";

import { api, isAbort, type BenchText, type DailyData } from "../api/client";
import { longDayLabel, today } from "../format";
import { FitnessCard } from "./FitnessCard";
import { HealthCard } from "./HealthCard";
import { LoadCard } from "./LoadCard";
import { RecoveryCard } from "./RecoveryCard";
import { SideBar } from "./SideBar";

const API_DOWN = "Cannot reach the API. Is it running (make api)?";
// Il quaderno vuoto non e' un guasto: e' un ciclo che non ha mai girato.
const NO_BENCH =
  "The bench notebook is empty. Run the tuning loop (make bench_tune) to write some texts.";

/** Il primo giorno del corpus: l'ultimo cambio a un prompt di Claude. Prima
 * di qui il bersaglio e' un altro, e `bench_tune.CORPUS_FROM` dice la stessa
 * cosa dall'altra parte. */
const FROM = "2026-10-26";

/** Le quattro sezioni, nell'ordine in cui la Day le mostra, con la chiave del
 * quaderno e quella del punteggio.
 *
 * La chiave del quaderno e' quella spezzata e quella del punteggio no: il
 * punteggio della card e' della sezione, non del modo in cui gliel'hanno
 * chiesta (`data.scores.health` vale per `health` e per `health_split`). */
const SEZIONI = [
  { key: "health_split", score: "health", Card: HealthCard, title: "Health" },
  { key: "load_split", score: "load", Card: LoadCard, title: "Load" },
  { key: "recovery_split", score: "recovery", Card: RecoveryCard, title: "Recovery" },
  { key: "fitness_split", score: "fitness", Card: FitnessCard, title: "Fitness" },
] as const;

export function TestPage() {
  const [rows, setRows] = useState<BenchText[] | null>(null);
  // I numeri, un giorno per chiave. Un giorno che non c'e' ancora e' un
  // giorno che non si disegna: meglio niente che una card con le barre vuote.
  const [data, setData] = useState<Record<string, DailyData>>({});
  const [error, setError] = useState<string | null>(null);

  // Il quaderno, in una richiesta sola per tutti i giorni.
  useEffect(() => {
    const controller = new AbortController();
    api
      .bench(FROM, today(), controller.signal)
      .then(setRows)
      .catch((e: unknown) => !isAbort(e) && setError(API_DOWN));
    return () => controller.abort();
  }, []);

  // E i numeri dei giorni che il quaderno nomina, tutti insieme: ognuno
  // riempie il suo giorno quando arriva, cosi' la pagina si popola dall'alto
  // invece di restare bianca finche' non c'e' tutto.
  useEffect(() => {
    if (!rows) return;
    const controller = new AbortController();
    const days = [...new Set(rows.map((row) => row.day))];
    for (const day of days) {
      api
        .daily(day, controller.signal)
        .then((got) => setData((had) => ({ ...had, [day]: got })))
        .catch((e: unknown) => !isAbort(e) && setError(API_DOWN));
    }
    return () => controller.abort();
  }, [rows]);

  // **Dal piu' recente al piu' vecchio.** Venticinque giorni sono una pagina
  // lunga, e la prima cosa che si vuole vedere e' come stanno le card adesso:
  // la cronologia dal 26 ottobre in avanti obbligherebbe a scorrere fino in
  // fondo per arrivare a oggi.
  const days = rows
    ? [...new Set(rows.map((row) => row.day))].sort((a, b) => b.localeCompare(a))
    : [];

  return (
    <>
      <SideBar current="test" />
      <main className="page">
        <div className="day-header">
          <div className="day-title">
            <h1>
              Test{" "}
              <span className="bench-day">
                {/* Il giorno piu' recente, che col nuovo ordine e' il primo
                    della pagina. */}
                {days.length ? `${days.length} days to ${longDayLabel(days[0])}` : "the bench"}
              </span>
            </h1>
          </div>
        </div>
        {error && <p className="warning">{error}</p>}
        {rows && !rows.length && <p className="warning">{NO_BENCH}</p>}
        {/* La legenda, una volta sola: i titoli delle card dicono di chi e'
            ogni testo, ma la riga qui sotto dice il mestiere della pagina. */}
        {days.length > 0 && (
          <p className="bench-note">
            On the left what the Claude agent wrote for that day, on the right what the model
            on this machine wrote. Nothing here is written now: both come from the bench
            notebook, as the tuning loop left them.
          </p>
        )}
        {days.map((day) => (
          <BenchDay key={day} day={day} rows={rows ?? []} data={data[day]} />
        ))}
      </main>
    </>
  );
}

/** Un giorno: il suo titolo e le otto card a coppie.
 *
 * Finche' i numeri di quel giorno non sono arrivati non si disegna niente:
 * le card leggono `data.morning` e compagnia, e mezza card e' peggio di
 * nessuna. */
function BenchDay({
  day,
  rows,
  data,
}: {
  day: string;
  rows: BenchText[];
  data: DailyData | undefined;
}) {
  const mine = rows.filter((row) => row.day === day);
  if (!data) {
    return (
      <section className="bench-block">
        <h2 className="bench-heading">{longDayLabel(day)}</h2>
        <p className="bench-note">…</p>
      </section>
    );
  }
  return (
    <section className="bench-block">
      <h2 className="bench-heading">{longDayLabel(day)}</h2>
      <div className="cards-grid">
        {SEZIONI.map(({ key, score, Card, title }) => {
          const row = mine.find((r) => r.section === key);
          if (!row) return null;
          const face = data.scores?.[score as keyof typeof data.scores] ?? null;
          // La coppia: a sinistra il bersaglio, a destra chi lo rincorre. Il
          // nome del modello sta nel titolo di destra perche' cambiarlo
          // cambia il testo, e una card senza quel nome non si sa di chi sia.
          return [
            <Card
              key={`${key}-claude`}
              data={data}
              text={row.claude ?? null}
              writtenAt={null}
              day={day}
              icon={null}
              face={face}
              title={`${title} · Claude`}
            />,
            <Card
              key={`${key}-ollama`}
              data={data}
              text={row.ollama}
              writtenAt={null}
              day={day}
              icon={null}
              face={face}
              title={`${title} · ${row.model}`}
            />,
          ];
        })}
      </div>
    </section>
  );
}
