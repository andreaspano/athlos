// La pagina Test: il banco di prova.
//
// Non e' una pagina del lavoro — le tre di prima si leggono, questa si usa
// mentre si scrive — ed e' il posto dove si guarda una cosa da sola, prima di
// metterla dove va. Per questo sta per ultima nella barra, dopo Goal, e non
// ha viste: `?period=test` e basta.
//
// Dentro ci sono la **Health**, la **Load**, la **Recovery** e la **Fitness**
// del giorno, le stesse card dello Snap della Day, con una differenza sola e
// che e' tutto il punto: **il testo non lo scrive Claude, lo scrive il modello che gira su
// questa macchina**. I numeri, le icone e le facce restano quelli dell'API,
// come sulla Day; i testi arrivano da `/api/test/local/<sezione>/<giorno>`,
// che da' a llama lo stesso prompt dell'agente di quella sezione e gli chiede
// la stessa cosa.
//
// **Quattro e non una** perche' una card sola non dice se il modello sa
// scrivere o se quel prompt gli era venuto bene: la Health giudica quattro
// misure che si somigliano, la Load tre carichi, un rapporto e due parole in
// codice di Garmin da tradurre, la Recovery quattro misure di cui due sono lo
// stesso numero a due ore diverse, la Fitness tre punteggi letti al contrario
// — sopra la fascia e' buono — piu' una soglia senza fascia e due
// acclimatamenti che per quasi tutto l'anno sono zero. Sono quattro mestieri
// diversi.
//
// **E ognuna delle due e' due volte**, affiancata a se' stessa. La seconda
// card di una sezione e' la stessa sezione chiesta in un altro modo: non a un
// modello che tiene in mano tutti i numeri e tutti i paragrafi, ma a un
// modello piccolo per paragrafo, che degli altri non sa niente, piu' uno che
// apre la sezione. Il testo finito lo cuce Python, quindi i paragrafi ci sono
// sempre e nell'ordine della card: la forma smette di essere una cosa che il
// prompt deve chiedere.
//
// Due delle tre sono cosi'. La Health e' in cinque — un paragrafo per misura
// e il verdetto in cima — e
// la Load in sei, che spezzandola si scopre fatta di mestieri diversi: i tre
// carichi con la loro fascia, quanto stai portando, che cosa la settimana
// chiede ancora, e la parola in cima. **E li' si vede la cosa che una card
// sola non puo' fare**: fuori da un blocco la settimana un foglio non ce
// l'ha, e quel paragrafo non esiste invece di essere un buco che il prompt
// deve ricordarsi di lasciare.
//
// Le due di una sezione stanno **una accanto all'altra sugli stessi numeri**
// perche' e' l'unico modo di deciderle: quale delle due strade scriva meglio
// non lo dice il ragionamento, lo dice il giorno storto che si va a cercare
// con le frecce. Se vince quella spezzata, l'altra va via allora e non
// adesso.
//
// **La Day non la tocca nessuno.** Quei testi non si scrivono da nessuna
// parte: nascono quando questa pagina li chiede e muoiono con la risposta. I
// frammenti in `summary/01.daily/<giorno>/` restano quelli che gli agenti di
// Claude hanno scritto, e lo Snap continua a leggere quelli: le card si
// guardano una accanto all'altra, in due schede del browser, ed e' per quello
// che questa pagina esiste.
//
// **Il giorno si sceglie**, con le stesse frecce della Day (`DayNav`): un
// banco di prova che guarda solo oggi non serve a niente, perche' oggi e'
// quasi sempre una mattina normale — quattro misure dentro la loro fascia —
// e su una mattina normale si somigliano tutti. Le differenze fra chi scrive
// si vedono su un giorno storto, e quel giorno bisogna poterlo andare a
// cercare.
//
// Il giorno sta nell'URL (`?day=2026-10-07`) come sulla Day e con la stessa
// `dayFromUrl`, quindi `?period=test&day=...` e la stessa data sulla Day si
// aprono fianco a fianco in due schede, che e' il modo in cui questa pagina
// si legge. Il tasto indietro torna al giorno di prima.
//
// Della `DayHeader` prende solo le frecce: la striscia della settimana e il
// Refresh sono della Day — qui non c'e' nessun report da riscrivere.
//
// **La Recovery e' affiancata a un'altra cosa**, e il paragrafo di sopra non
// vale per lei. La sua card di sinistra non e' llama chiesto in un altro modo:
// e' il frammento che l'agente di Claude ha scritto davvero, quello che la Day
// legge, con la sua data in fondo. A destra c'e' il modello di casa, e fra le
// due cambia chi scrive e nient'altro.
//
// E' la domanda che viene **prima** di quella delle altre due: non come
// chiedere una sezione al modello di casa, ma se il modello di casa quella
// sezione la sappia scrivere.
//
// **La prima sera ha risposto no, e tre volte.** Col prompt di Claude llama ha
// aperto con un verdetto che due righe sotto contraddiceva, ha scritto la notte
// in una scrittura che sulla card non c'e', e ha impastato i due body battery
// in una frase — che e' il paragrafo in grassetto del suo prompt, letto e non
// applicato. Sono le tre righe che avevano gia' fatto spezzare le altre due
// sezioni, e la Recovery e' andata dove sono andate loro: la card di destra e'
// in cinque pezzi, e quelle tre cose non sono piu' cose che possano succedere.
// Il confronto a sinistra pero' resta quello di prima, che e' quello che conta:
// non quale dei due modi di chiedere, ma se a questo punto regga Claude.
//
// **La Fitness sta come la Recovery**: a sinistra il frammento di Claude, a
// destra il modello di casa in pezzi. E' la coppia giusta per una sezione
// nuova, ed e' anche quella che la prima sera ha dato il divario piu' netto —
// il prompt intero, in un paragrafo, ha scritto una fila di quattro numeri
// senza nessun verdetto e ha chiuso con "non sei acclimatato a nessuna quota
// ne' al caldo", che e' esattamente la frase che quel prompt dice di non
// scrivere. La sezione intera resta chiedibile all'API, che e' il termine di
// paragone.
//
// Le sei richieste si fanno **insieme**, non una dopo l'altra: sono
// indipendenti e Ollama le mette in fila da se'. Ognuna riempie la sua card
// quando arriva, cosi' la Health non aspetta la Load.
//
// La riga in fondo dice **quanto ci ha messo ognuna**, ed e' meta' del
// confronto: una sezione spezzata sono cinque o sei domande invece di una, e
// si paga. Quanto, lo dice quel numero e non un preventivo.
//
// Sotto c'e' chi le ha scritte e quanto ci ha messo, e un tasto per
// richiederle. **Non e' un dado**: il modello gira a temperatura zero (il
// perche' sta in `api/ollama.py`), quindi con gli stessi numeri le risposte
// sono le stesse. Il tasto serve a riprovare quando Ollama era spento e lo si
// e' acceso adesso, che e' il guasto normale di questa pagina.
import { useCallback, useEffect, useState } from "react";

import { ApiError, api, isAbort, type DailyData, type LocalText, type Report } from "../api/client";
import { longDayLabel, today } from "../format";
import { sectionBody, sectionIcon, sectionWrittenAt } from "../markdown";
import { dayFromUrl, pushUrl } from "../navigation";
import { DayNav } from "./DayNav";
import { HealthCard } from "./HealthCard";
import { LoadCard } from "./LoadCard";
import { FitnessCard } from "./FitnessCard";
import { RecoveryCard } from "./RecoveryCard";
import { SideBar } from "./SideBar";

const API_DOWN = "Cannot reach the API. Is it running (make api)?";
// Il 503 dell'endpoint: Ollama spento, o il modello non scaricato. E' il
// guasto normale di questa pagina, e vale la pena dire come si ripara.
const NO_MODEL =
  "The local model did not answer. Is Ollama running (ollama serve), and is the model pulled (ollama list)?";
// Il 404: l'API quella sezione non ce l'ha. **Non e' un guasto, e' una
// versione.** La pagina compilata sta in `frontend/dist` e la serve lo
// stesso processo dell'API, quindi un `make frontend_build` senza
// riavviare lascia la pagina nuova davanti all'API di prima: la card
// chiede una sezione che quel processo non conosce e si prende un 404.
// E' successo il giorno in cui `health_split` e' nato, e per un po' ha
// avuto la faccia di "l'API non risponde" — che mandava a guardare la
// cosa sbagliata, perche' l'API rispondeva benissimo.
const OLD_API = (sezione: string) =>
  `The API does not know the "${sezione}" section: it is running code older than this page. Restart it (systemctl --user restart athlos-api, or make api).`;

/** Le sezioni sul banco, nell'ordine in cui vanno sulla pagina. Le chiavi
 * sono quelle dell'API, non nomi nuovi.
 *
 * Sono **due sezioni scritte in due modi ciascuna**, e l'ordine le mette a
 * coppie: la griglia e' a due colonne, quindi la Health intera e la Health
 * spezzata stanno sulla prima riga e le due Load sulla seconda. Una accanto
 * all'altra sugli stessi numeri e' il solo modo di vedere quale delle due
 * strade scrive meglio, e una coppia per riga e' il solo modo di non
 * confrontare la Health con la Load. */
const SEZIONI = [
  "health",
  "health_split",
  "load",
  "load_split",
  "recovery_split",
  "fitness_split",
] as const;
// La Recovery e' una chiave sola e la sua riga ha due card: a sinistra non
// c'e' un'altra domanda a llama, c'e' il frammento che l'agente di Claude ha
// scritto davvero, lo stesso che la Day legge. Quindi niente da chiedere e
// niente da aspettare, per quella meta'.
//
// E a destra c'e' `recovery_split` e non `recovery`: la sezione intera resta
// nel registro dell'API — si chiede a mano, ed e' il termine di paragone della
// prima sera — ma sulla pagina quel posto adesso e' della strada in cinque
// pezzi, che e' quello che la prima sera ha fatto vedere di servire.
type Sezione = (typeof SEZIONI)[number];

export function TestPage() {
  const now = today();
  const [day, setDay] = useState(() => dayFromUrl(now));
  const [data, setData] = useState<DailyData | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  // I testi locali, uno per sezione. Una chiave che non c'e' vuol dire "non
  // e' ancora arrivato", che sulla card e' una cosa diversa da "non
  // arrivera'": quella la dice `error`.
  const [local, setLocal] = useState<Partial<Record<Sezione, LocalText>>>({});
  const [writing, setWriting] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Il giorno scelto va nell'URL, con una voce nella cronologia: il tasto
  // indietro torna al giorno di prima, come sulla Day. `pushUrl` manda anche
  // un `popstate` finto, che l'ascoltatore qui sotto raccoglie — cosi' c'e'
  // una strada sola per cambiare giorno, che lo chieda una freccia o il
  // browser.
  const changeDay = (next: string) => {
    if (next === day || next > now) return;
    pushUrl({ day: next });
  };

  useEffect(() => {
    const onPop = () => setDay(dayFromUrl(today()));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // I numeri e le icone, come li chiede la Day. Del report servono le icone
  // delle sezioni — e **un testo solo**, quello della Recovery.
  //
  // Per le altre due i testi di Claude non si mostrano: le loro due card sono
  // la stessa domanda fatta a llama in due modi, e metterci in mezzo anche
  // Claude vorrebbe dire tre testi su una riga da due. La Recovery invece e'
  // proprio quel confronto — il frammento vero a sinistra, llama a destra —
  // ed e' la domanda che viene prima: non come chiederglielo, ma se lo sappia
  // scrivere.
  useEffect(() => {
    const controller = new AbortController();
    api
      .daily(day, controller.signal)
      .then(setData)
      .catch((e: unknown) => !isAbort(e) && setError(API_DOWN));
    api
      .dailyReport(day, controller.signal)
      .then(setReport)
      .catch((e: unknown) => !isAbort(e) && setError(API_DOWN));
    return () => controller.abort();
  }, [day]);

  // I testi. In una funzione sua e non dentro l'effetto perche' la chiama
  // anche il tasto: le richieste sono le stesse, cambia chi le fa partire.
  const write = useCallback(
    (signal?: AbortSignal) => {
      setWriting(true);
      // Via i testi del giorno prima: restare sotto i numeri di un altro
      // giorno per i due secondi della scrittura e' un verdetto sbagliato
      // sulla card, non un'attesa.
      setLocal({});
      Promise.all(
        SEZIONI.map((sezione) =>
          api
            .localText(sezione, day, signal)
            // Ogni card si riempie appena il suo testo arriva, senza
            // aspettare l'altra.
            .then((written) => setLocal((had) => ({ ...had, [sezione]: written })))
            .catch((e: unknown) => {
              if (isAbort(e)) return;
              // I tre guasti di questa pagina sono tre cose diverse da
              // riparare, e dirli tutti e tre "l'API non risponde" vuol
              // dire mandare a guardare la cosa sbagliata.
              if (!(e instanceof ApiError)) return setError(API_DOWN);
              if (e.status === 503) return setError(NO_MODEL);
              if (e.status === 404) return setError(OLD_API(sezione));
              setError(API_DOWN);
            }),
        ),
      ).finally(() => setWriting(false));
    },
    [day],
  );

  useEffect(() => {
    const controller = new AbortController();
    write(controller.signal);
    return () => controller.abort();
  }, [write]);

  const again = () => {
    setError(null);
    setLocal({});
    write();
  };

  // Quanto ci ha messo ognuna, per la riga in fondo. Il modello e' lo stesso
  // per tutte e due: lo dice la prima che risponde.
  const scritte = SEZIONI.map((s) => local[s]).filter((x): x is LocalText => Boolean(x));
  const tempi = scritte.map((x) => `${x.section} in ${x.seconds}s`).join(", ");

  return (
    <>
      <SideBar current="test" />
      <main className="page">
        <div className="day-header">
          <div className="day-title">
            {/* Il nome della pagina e il giorno che le card raccontano: sulla
                Day il titolo e' la data, qui la data da sola non direbbe che
                si sta guardando il banco di prova. */}
            <h1>
              Test <span className="bench-day">{longDayLabel(day)}</span>
            </h1>
            <DayNav day={day} maxDay={now} onChange={changeDay} />
          </div>
        </div>
        {error && <p className="warning">{error}</p>}
        {data && (
          <>
            <div className="cards-grid">
              <HealthCard
                data={data}
                text={local.health?.text ?? null}
                // Non c'e' niente da datare: i testi non sono file, sono
                // appena nati. Quando e da chi lo dice la riga qui sotto.
                writtenAt={null}
                day={day}
                icon={sectionIcon(report, "Health")}
                face={data.scores.health}
              />
              {/* La stessa Health, chiesta a cinque modelli piccoli invece
                  che a uno: un paragrafo per misura — e nessuno dei quattro
                  sa degli altri tre — piu' un quinto che legge quei quattro
                  e scrive il verdetto in cima. I numeri sono gli stessi
                  della card accanto, l'icona e la faccia pure: l'unica cosa
                  che cambia e' il testo, che e' quello che si sta
                  guardando. */}
              <HealthCard
                data={data}
                text={local.health_split?.text ?? null}
                writtenAt={null}
                day={day}
                icon={sectionIcon(report, "Health")}
                face={data.scores.health}
                title="Health, in five"
              />
              <LoadCard
                data={data}
                text={local.load?.text ?? null}
                writtenAt={null}
                day={day}
                icon={sectionIcon(report, "Load")}
                face={data.scores.load}
              />
              {/* La stessa Load, chiesta a sei modelli piccoli invece che a
                  uno: un paragrafo per carico — e nessuno dei tre sa degli
                  altri due — uno per quanto stai portando, uno per quello
                  che la settimana chiede ancora, e uno che scrive la parola
                  in cima. I numeri sono gli stessi della card accanto,
                  l'icona e la faccia pure: l'unica cosa che cambia e' il
                  testo, che e' quello che si sta guardando. */}
              <LoadCard
                data={data}
                text={local.load_split?.text ?? null}
                writtenAt={null}
                day={day}
                icon={sectionIcon(report, "Load")}
                face={data.scores.load}
                title="Load, in six"
              />
              {/* **La Recovery come la legge la Day**: gli stessi quattro
                  numeri e il frammento che l'agente di Claude ha scritto,
                  `summary/01.daily/<giorno>/`, con la data in fondo alla card
                  perche' quel testo una data ce l'ha — e' un file, scritto la
                  mattina in cui il report e' girato. Le altre card del banco
                  non ce l'hanno: nascono adesso. */}
              <RecoveryCard
                data={data}
                text={sectionBody(report, "Recovery")}
                writtenAt={sectionWrittenAt(report, "Recovery")}
                day={day}
                icon={sectionIcon(report, "Recovery")}
                face={data.scores.recovery}
                title="Recovery, by Claude"
              />
              {/* La stessa card, gli stessi quattro numeri, e il testo del
                  modello di casa — chiesto in cinque pezzi, uno per misura,
                  piu' il quinto che li legge e dice quanto il corpo era
                  pronto.

                  **Non e' piu' lo stesso prompt di Claude**, e la prima sera
                  ha detto perche': il verdetto contraddetto due righe sotto,
                  la notte scritta nella scrittura sbagliata, i due body
                  battery impastati in una frase. Tre righe del prompt lette e
                  non applicate, e sono le tre che la strada in pezzi rende
                  impossibili — il verdetto lo conta Python, la scrittura la
                  dice la riga del pezzo, e i due body battery sono due
                  modelli che l'uno dell'altro non sanno niente. La sezione
                  intera resta chiedibile all'API, che e' il termine di
                  paragone. */}
              <RecoveryCard
                data={data}
                text={local.recovery_split?.text ?? null}
                writtenAt={null}
                day={day}
                icon={sectionIcon(report, "Recovery")}
                face={data.scores.recovery}
                title="Recovery, in five"
              />
              {/* **La Fitness come la legge la Day**, col frammento vero e la
                  sua data, e accanto quella in pezzi: e' la coppia della
                  Recovery, sulla sezione piu' varia che ci sia. */}
              <FitnessCard
                data={data}
                text={sectionBody(report, "Fitness")}
                writtenAt={sectionWrittenAt(report, "Fitness")}
                day={day}
                icon={sectionIcon(report, "Fitness")}
                face={data.scores.fitness}
                title="Fitness, by Claude"
              />
              {/* La stessa card, gli stessi numeri, e il modello di casa in
                  pezzi: uno per punteggio, uno per la soglia, uno per ogni
                  acclimatamento **che non sia zero**, e il verdetto in cima.

                  Qui il paragrafo che non c'e' e' la regola e non
                  l'eccezione: d'inverno i due acclimatamenti sono zero e la
                  sezione viene di cinque paragrafi, nelle settimane in
                  montagna di sei o sette. Il prompt intero quel buco lo deve
                  chiedere a parole, e la prima sera non l'ha fatto — ha
                  scritto "you are not acclimatised to any altitude or heat",
                  che e' esattamente la frase che il suo prompt dice di non
                  scrivere. */}
              <FitnessCard
                data={data}
                text={local.fitness_split?.text ?? null}
                writtenAt={null}
                day={day}
                icon={sectionIcon(report, "Fitness")}
                face={data.scores.fitness}
                title="Fitness, in pieces"
              />
            </div>
            <p className="bench-note">
              {writing
                ? "The local model is writing…"
                : scritte.length
                  ? `Written here by ${scritte[0].model} — ${tempi}. The Day page still shows what Claude wrote.`
                  : "No text."}{" "}
              <button type="button" className="goal-make-current" onClick={again} disabled={writing}>
                Ask again
              </button>
            </p>
          </>
        )}
      </main>
    </>
  );
}
