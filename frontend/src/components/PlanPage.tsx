// La pagina Goal: gli obiettivi scritti a mano in `plan/`.
//
// Gli altri piani del repo guardano indietro — il report di un giorno, quello
// di una settimana — questo guarda avanti: una gara, un bersaglio e le
// settimane che ci portano. Per questo non sta fra Day e Week nella barra ma
// a destra, staccato.
//
// La pagina non sa niente dei piani: li chiede all'API (`/api/plans`), che
// legge la cartella. Un file nuovo in `plan/` si vede ricaricando, senza
// toccare niente qui — e' il motivo per cui i numeri in cima stanno nel front
// matter del file e non nel codice.
//
// **Un elenco, non un piano per volta** (todo 84). Prima c'era un selettore e
// sotto il piano scelto: uno alla volta, e per confrontare i tre bersagli
// della stessa mezza si andava avanti e indietro. Adesso sono righe che si
// aprono e si chiudono, anche piu' d'una insieme, perche' la domanda vera e'
// *quale di questi* — e la si risponde mettendoli uno sotto l'altro.
//
// Uno e' **quello attuale**, e lo dice `current: true` nel suo front matter:
// porta la pillola e si apre da solo. Gli altri sono le alternative, che
// restano chiuse.
//
// Il testo si chiede **quando la riga si apre** e poi resta in mano: tre
// piani sono tre `GET`, e chiederli tutti all'apertura della pagina
// servirebbe testo che forse nessuno legge.
//
// L'indirizzo `?plan=<slug>` continua a valere e apre quel goal, cosi' i
// link di prima arrivano dove arrivavano. Aprire e chiudere invece **non**
// scrive nell'URL: sono gesti di lettura, e lasciarne una traccia per
// ognuno riempirebbe la cronologia di passi che il tasto indietro dovrebbe
// poi ripercorrere uno a uno.
import { useEffect, useRef, useState } from "react";

import {
  api,
  isAbort,
  type Plan,
  type PlanSummary,
} from "../api/client";
import { dayDiff, raceLabel, shortDayLabel, targetLabel, today } from "../format";
import { markdown } from "../markdown";
import { paramFromUrl } from "../navigation";
import { CardHead, Stat, WrittenAt, num } from "./Stat";
import { TopBar } from "./TopBar";

const API_DOWN = "Cannot reach the API. Is it running (make api)?";

/** Il cestino, disegnato qui e non preso da `icons/`: quelli sono le icone
 * degli sport e delle sezioni, in PNG a due dimensioni fisse. Questo e' un
 * comando, e `currentColor` lo fa seguire il tema come il testo accanto. */
function BinIcon() {
  return (
    <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" focusable="false">
      <path
        d="M6 2h4m-7 2h10M5 4l.7 9a1 1 0 0 0 1 1h2.6a1 1 0 0 0 1-1L11 4M7 6.5v5m2-5v5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  );
}
// L'icona di Next: il riquadro che dice cosa fare dopo. Un goal e' la stessa
// domanda, solo su quattro mesi invece che su domani.
const PLAN_ICON = "next.png";

/** I goal aperti quando la pagina si apre: quello chiesto dall'URL, se c'e'
 * ancora fra i file, se no quello attuale.
 *
 * Nessuno dei due e' garantito — un `plan/` senza flag e senza `?plan=` e'
 * legittimo — e allora si apre il primo, che e' la gara piu' vicina: una
 * pagina di sole righe chiuse non direbbe niente a nessuno. */
function initiallyOpen(plans: PlanSummary[]): Set<string> {
  const wanted = paramFromUrl("plan");
  if (wanted && plans.some((p) => p.slug === wanted)) return new Set([wanted]);
  const current = plans.find((p) => p.current);
  if (current) return new Set([current.slug]);
  return new Set(plans[0] ? [plans[0].slug] : []);
}

/** I numeri del goal, sopra il testo: la gara, quanto manca, il bersaglio.
 * Quelli che il front matter non ha restano un trattino, come in tutte le
 * altre pagine. */
function PlanStats({ plan, now }: { plan: PlanSummary; now: string }) {
  const toGo = plan.race ? dayDiff(now, plan.race) : null;
  const from = plan.block_start;
  return (
    <div className="stats">
      <Stat
        label="Race"
        value={plan.race ? raceLabel(plan.race) : "–"}
        sub={plan.race_name ? <span className="muted">{plan.race_name}</span> : undefined}
      />
      <Stat
        label={toGo != null && toGo < 0 ? "Days since" : "Days to go"}
        value={toGo == null ? "–" : Math.abs(toGo)}
        sub={
          plan.weeks != null ? (
            <span className="muted">
              {plan.weeks} weeks{from ? ` from ${shortDayLabel(from)}` : ""}
            </span>
          ) : undefined
        }
      />
      <Stat label="Target" value={targetLabel(plan.target_time)} />
      <Stat label="Pace" value={plan.target_pace ?? "–"} unit={plan.target_pace ? "/km" : undefined} />
      <Stat label="Speed" value={num(plan.target_speed_kmh, 2)} unit="km/h" />
      <Stat label="Peak week" value={num(plan.peak_weekly_km)} unit="km" />
    </div>
  );
}

/** Una riga dell'elenco: l'intestazione sempre visibile e, aperta, i numeri e
 * il testo.
 *
 * E' un `<details>` vero e non un pannello fatto a mano: la freccia, il
 * clic, la tastiera e la ricerca nella pagina sono del browser. `open` e
 * `onToggle` lo tengono in pari con lo stato di chi lo contiene, che e' quello
 * che sa quali testi sono stati chiesti. */
function Goal({
  plan,
  body,
  open,
  onToggle,
  onMakeCurrent,
  onDelete,
  busy,
  now,
}: {
  plan: PlanSummary;
  // `undefined` e' "non ancora arrivato", `null` e' "non c'e' piu'": sono due
  // cose diverse da dire, e dirle entrambe "niente" lascerebbe un file
  // rinominato a caricare per sempre.
  body: Plan | null | undefined;
  open: boolean;
  onToggle: (open: boolean) => void;
  onMakeCurrent: () => void;
  onDelete: () => void;
  busy: boolean;
  now: string;
}) {
  const toGo = plan.race ? dayDiff(now, plan.race) : null;
  // I comandi stanno **dentro** il `<summary>`, dove si vedono senza aprire
  // la riga. Un clic la' dentro aprirebbe e chiuderebbe il `<details>`:
  // `preventDefault` e' quello che lo trattiene, e va su ogni comando.
  const command = (what: () => void) => (event: React.MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    what();
  };
  return (
    <details
      className={plan.current ? "goal current" : "goal"}
      open={open}
      onToggle={(event) => onToggle(event.currentTarget.open)}
    >
      <summary className="goal-head">
        <span className="goal-target">{targetLabel(plan.target_time)}</span>
        <span className="goal-title">
          {plan.title}
          <br />
          <span className="muted">
            {plan.race ? raceLabel(plan.race) : "no race day"}
            {toGo != null && toGo >= 0 ? ` · ${toGo} days to go` : ""}
            {plan.target_pace ? ` · ${plan.target_pace} /km` : ""}
          </span>
        </span>
        {plan.current ? (
          <span className="goal-flag">current</span>
        ) : (
          <button
            type="button"
            className="goal-make-current"
            onClick={command(onMakeCurrent)}
            disabled={busy}
            title="Follow this goal from now on"
          >
            make current
          </button>
        )}
        <button
          type="button"
          className="goal-bin"
          onClick={command(onDelete)}
          disabled={busy}
          aria-label={`Delete ${plan.title}`}
          title="Move this goal to plan/.trash/"
        >
          <BinIcon />
        </button>
      </summary>
      <div className="goal-body">
        <PlanStats plan={plan} now={now} />
        {/* Il testo arriva dopo l'apertura: finche' non c'e', una riga che lo
            dice invece di un salto improvviso. */}
        {body === undefined && <p className="caption">Loading the plan…</p>}
        {body === null && (
          <p className="warning">
            This goal is no longer in <code>plan/</code>: the file was renamed or removed.
            Reload the page.
          </p>
        )}
        {body && (
          <>
            <div className="prose plan-prose">{markdown(body.body)}</div>
            <p className="caption plan-file">plan/{body.file}</p>
            <WrittenAt when={body.written_at} day={body.race ?? ""} />
          </>
        )}
      </div>
    </details>
  );
}

/** Le settimane gia' scritte che seguono un goal diverso da quello attuale.
 *
 * E' il seguito che il cambio di goal **non** ha: i file di
 * `summary/05.plan/` non li rigenera nessuno — non c'e' un generatore da
 * chiamare — quindi cambiare il flag li lascia dov'erano, scritti su un altro
 * bersaglio. Dirlo e' il minimo; vedi il todo 85. */
function staleWeeks(
  plans: PlanSummary[],
  ahead: { slug: string; weeks: number }[],
): { slug: string; weeks: number }[] {
  const current = plans.find((p) => p.current)?.slug ?? null;
  return ahead.filter((entry) => entry.slug !== current);
}

export function PlanPage() {
  const now = today();
  const [plans, setPlans] = useState<PlanSummary[] | null>(null);
  const [ahead, setAhead] = useState<{ slug: string; weeks: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());
  // La chiave c'e' quando l'API ha risposto; il valore e' `null` se quel
  // piano non e' fra i file.
  const [bodies, setBodies] = useState<Record<string, Plan | null>>({});
  const [error, setError] = useState<string | null>(null);

  // L'elenco dei goal. Da qui escono anche quelli da aprire subito.
  useEffect(() => {
    const controller = new AbortController();
    api
      .plans(controller.signal)
      .then((list) => {
        setPlans(list.plans);
        setAhead(list.ahead);
        setOpen(initiallyOpen(list.plans));
        setError(null);
      })
      .catch((e) => !isAbort(e) && setError(API_DOWN));
    return () => controller.abort();
  }, []);

  // Le due scritture. Rispondono con l'elenco rimasto, quindi non serve
  // richiederlo: una chiamata fa la cosa e aggiorna la pagina.
  const makeCurrent = (slug: string) => {
    setBusy(true);
    api
      .setCurrentPlan(slug)
      .then((list) => {
        setPlans(list.plans);
        setAhead(list.ahead);
        setError(null);
      })
      .catch(() => setError("Could not change the current goal."))
      .finally(() => setBusy(false));
  };

  // La conferma la chiede la pagina e non l'API: il file va nel cestino e si
  // recupera, ma un goal e' mezz'ora di scrittura e un clic per sbaglio su un
  // telefono e' facile.
  const remove = (plan: PlanSummary) => {
    const extra = plan.current ? "\n\nIt is the current goal: no goal will be current." : "";
    if (!window.confirm(`Delete "${plan.title}"?\n\nThe file moves to plan/.trash/.${extra}`)) {
      return;
    }
    setBusy(true);
    api
      .deletePlan(plan.slug)
      .then((list) => {
        setPlans(list.plans);
        setAhead(list.ahead);
        setError(null);
      })
      .catch(() => setError("Could not delete the goal."))
      .finally(() => setBusy(false));
  };

  // I testi dei goal aperti, chiesti **una volta sola**: un testo gia' in
  // mano resta, cosi' chiudere e riaprire una riga non rifa' il giro.
  //
  // Chi e' stato chiesto sta in un `ref` e non fra le dipendenze: con
  // `bodies` fra le dipendenze l'arrivo di un testo rilanciava l'effetto, e
  // la sua pulizia annullava le richieste degli altri goal aperti un istante
  // prima — che poi ripartivano da zero. Il controller e' uno e si annulla
  // solo smontando la pagina.
  const asked = useRef<Set<string>>(new Set());
  const aborter = useRef<AbortController | null>(null);
  useEffect(() => {
    aborter.current = new AbortController();
    return () => aborter.current?.abort();
  }, []);
  useEffect(() => {
    for (const slug of open) {
      if (asked.current.has(slug)) continue;
      asked.current.add(slug);
      api
        .plan(slug, aborter.current?.signal)
        .then((plan) => setBodies((had) => ({ ...had, [slug]: plan })))
        .catch((e) => {
          if (isAbort(e)) return;
          // Un testo che non e' arrivato si puo' richiedere riaprendo la
          // riga: senza questo resterebbe "Loading" per sempre.
          asked.current.delete(slug);
          setError(API_DOWN);
        });
    }
  }, [open]);

  useEffect(() => {
    document.title = "Training · Goal";
  }, []);

  const empty = plans !== null && plans.length === 0;

  const toggle = (slug: string, isOpen: boolean) =>
    setOpen((had) => {
      if (had.has(slug) === isOpen) return had;
      const next = new Set(had);
      if (isOpen) next.add(slug);
      else next.delete(slug);
      return next;
    });

  return (
    <>
      <TopBar current="plan" />
      <main className="page">
        <div className="day-header">
          <div className="day-title">
            <h1>Goal</h1>
          </div>
        </div>
        {error && <p className="warning">{error}</p>}
        {empty && (
          <p className="info">
            No goals yet. A goal is a Markdown file in <code>plan/</code>: a YAML front
            matter with the race and the target, then the text. Mark the one you are
            following with <code>current: true</code>.
          </p>
        )}
        {plans !== null && plans.length > 0 && (
        <section className="card plan-card" aria-label="Goals">
          <CardHead icon={PLAN_ICON} title="Goals" />
          {/* Le settimane che seguono un altro goal. Non e' un errore della
              pagina: e' lo stato in cui i file sono, e nessuno li riscrive. */}
          {staleWeeks(plans, ahead).map((entry) => (
            <p className="warning" key={entry.slug}>
              {entry.weeks} weekly {entry.weeks === 1 ? "plan" : "plans"} from this Monday on
              still {entry.weeks === 1 ? "follows" : "follow"} <code>{entry.slug}</code>.
              Changing the current goal does not rewrite them — nothing does yet.
            </p>
          ))}
          <div className="goal-list">
            {plans.map((plan) => (
              <Goal
                key={plan.slug}
                plan={plan}
                body={plan.slug in bodies ? bodies[plan.slug] : undefined}
                open={open.has(plan.slug)}
                onToggle={(isOpen) => toggle(plan.slug, isOpen)}
                onMakeCurrent={() => makeCurrent(plan.slug)}
                onDelete={() => remove(plan)}
                busy={busy}
                now={now}
              />
            ))}
          </div>
        </section>
        )}
      </main>
    </>
  );
}
