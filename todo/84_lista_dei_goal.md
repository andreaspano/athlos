---
status: done
---

# I goal come elenco, e uno e' quello attuale

La pagina Goal — che fino a poco prima si chiamava Plan — mostrava **un
piano per volta**: un selettore in cima e sotto quello scelto. Per i tre
piani che ci sono adesso e' il modo sbagliato: `half_marathon_2.10`, `2.20` e
`2.30` sono **tre bersagli della stessa gara**, ambizioso, realistico e
prudente, e la domanda che si fa guardandoli e' *quale di questi*. Con uno
per volta si risponde andando avanti e indietro e tenendo a mente i numeri
dell'altro.

E c'era una cosa che il progetto sapeva e la pagina no. Le diciotto settimane
di `summary/05.plan/` portano tutte la chiave `plan: half_marathon_2.20`:
**il goal attuale esisteva gia'**, scritto nei file generati, e il file
scritto a mano non lo diceva. Chi apriva la pagina vedeva tre piani pari fra
loro e nessun modo di sapere quale si stesse seguendo.

## Cosa si fa

### 1. Il flag nel front matter — `api/plans.py`

`current: true`, nel file del goal che si sta seguendo. Sta li' e non in un
posto nel codice per lo stesso motivo di tutte le altre chiavi: i goal li
scrive una persona a mano, e il file e' dove si decide.

`_plan()` lo legge con `meta.get("current") is True` — il flag e' uno o
nessuno, non un valore da interpretare.

**Due file col flag e' una cosa che succede**: si scrive il goal nuovo e si
dimentica di togliere il vecchio. `_one_current()` ne lascia uno, il primo
nell'ordine di `load_plans` (gara piu' vicina, poi bersaglio piu' veloce), che
e' deterministico. Mostrarne due sarebbe peggio di mostrarne uno magari
sbagliato: il flag c'e' proprio per rispondere a *quale*.

**L'ordine dell'elenco non cambia**: l'attuale non va in cima. La lista e' il
calendario di quello che si vuole fare, e `current` e' una pillola su una
delle sue righe, non una posizione.

### 2. `current` nell'API — `api/models.py`

Un `bool` in `PlanSummary`, quindi anche in `Plan` e nei tipi TypeScript
rigenerati da `make frontend_types`.

### 3. L'elenco che si apre — `components/PlanPage.tsx`

Via il selettore, via il piano unico. Ogni goal e' un `<details>` vero e non
un pannello fatto a mano: la freccia, il clic, la tastiera e la ricerca nella
pagina sono del browser.

- l'intestazione, sempre visibile: il bersaglio grande, il titolo, la gara e
  quanto manca, e la pillola `current` dove va;
- aperta: i riquadri dei numeri e il testo del piano;
- **l'attuale e' aperto all'arrivo**, gli altri chiusi. `?plan=<slug>` vince
  su di lui, cosi' i link di prima aprono ancora quello che aprivano;
- **il testo si chiede quando la riga si apre**, e poi resta in mano: tre
  piani sono tre `GET`, e chiederli tutti all'apertura della pagina
  servirebbe testo che forse nessuno legge.

Aprire e chiudere **non** scrive nell'URL. Sono gesti di lettura, e lasciarne
una traccia per ognuno riempirebbe la cronologia di passi che il tasto
indietro dovrebbe poi ripercorrere uno a uno.

Il titolo della pagina torna a essere `Goal` e non il titolo del piano
aperto: di piani aperti adesso ce ne puo' essere piu' d'uno.

### 4. Il flag sul 2.20 — `plan/half_marathon_2.20.md`

Il goal attuale non si decide qui: si scrive quello che le diciotto settimane
dicono gia'.

## Quello che non va toccato

- **La chiave `plan:` delle settimane di `summary/05.plan/`.** Resta lei a
  dire da quale blocco viene una settimana. Vedi i rischi.
- `?period=plan`, il tipo `Page` e il nome del file `PlanPage.tsx`: il nome
  visibile e' cambiato col rename a Goal, l'indirizzo no, e i link scritti
  prima devono continuare ad aprire la pagina.
- Il front matter non obbligatorio: un goal senza `current` e senza niente
  si vede comunque, coi riquadri vuoti.

## Rischi

- **Due fonti per la stessa verita'.** Da adesso il goal attuale sta scritto
  in due posti: `current: true` nel file del goal, e `plan:` in ognuna delle
  diciotto settimane. Oggi dicono la stessa cosa perche' il flag l'ho messo
  dove le settimane puntavano, ma **niente lo verifica**, e cambiare goal
  senza rigenerare le settimane le fa divergere in silenzio. La via d'uscita
  e' una sola fonte: o la pagina ricava l'attuale dalle settimane, o chi
  genera le settimane legge il flag. E' il seguito naturale di questo todo e
  **non l'ho fatto**: toccherebbe come nascono i piani settimanali, che e'
  un'altra storia.
- **`current` non fa ancora niente oltre la pagina.** Non lo leggono gli
  agenti ne' i report: e' una pillola e una riga aperta. Chi si aspetta che
  cambiare flag cambi quello che il report giudica resterebbe deluso.
- **Il testo a richiesta si vede.** Aprendo una riga il corpo appare un
  istante dopo, e nel frattempo c'e' una riga che lo dice. Con tre piani in
  locale e' quasi invisibile; dalla tailnet un po' meno.

## Come e' andata

Fatto. La pagina Goal e' un elenco di tre righe, la 2.20 porta la pillola ed
e' quella aperta.

### Verificato

- `GET /api/plans` rende `current = true` sul solo `half_marathon_2.20`, e
  `false` sugli altri due.
- `GET /api/plans/half_marathon_2.20` rende il testo (8.354 caratteri) e il
  flag.
- `npm run typecheck` pulito, `make frontend_types` rigenerato dall'OpenAPI,
  `make frontend_build` ok, servizio riavviato, `/?period=plan` rende 200.

### Due cose trovate per strada

**`api.plan()` puo' rendere `null`**, non solo un piano: e' un 404 tradotto,
e capita con un file rinominato. La prima versione lo trattava come "testo
non ancora arrivato" e quella riga sarebbe restata a *Loading* per sempre.
Adesso sono tre stati distinti — `undefined` non ancora chiesto, `null` non
c'e' piu', e il piano — e il secondo lo dice.

**L'effetto che chiedeva i testi si annullava da solo.** Aveva `bodies` fra
le dipendenze, quindi l'arrivo di un testo lo rilanciava e la sua pulizia
annullava le richieste dei goal aperti un istante prima, che ripartivano da
zero. Chi e' stato chiesto sta in un `ref`, e il controller e' uno, annullato
solo smontando la pagina.

## Revert

Il revert del codice basta: `current: true` resta nel front matter del 2.20 e
non fa danno a nessuno — prima di questo todo nessuno leggeva quella chiave.
