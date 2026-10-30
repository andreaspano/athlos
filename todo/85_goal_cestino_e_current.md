---
status: done
---

# Cancellare un goal, e sceglierne un altro

Il todo 84 ha messo il flag `current` nel front matter e lo ha fatto leggere
alla pagina. Si leggeva e non si toccava: per cambiare obiettivo si apriva il
file con un editor, e per levarne uno si cancellava a mano. Due gesti che
riguardano la pagina e si facevano fuori da lei.

## Cosa si fa

Tre cose, e la terza e' quella che conta.

### 1. Il cestino su ogni riga — `DELETE /api/plans/{slug}`

Un'icona per riga, dentro il `<summary>` cosi' si vede senza aprirla.

**Il file va in `plan/.trash/`, non viene cancellato.** Un goal e' un
documento che una persona ha scritto a mano, l'API **non ha login** e la
pagina e' raggiungibile da tutta la tailnet — dove c'e' anche il dispositivo
di un'altra persona. Un `unlink` dal clic di quella pagina e' un modo di
perdere lavoro che non si recupera. Il nome nel cestino porta il momento,
cosi' cancellare due volte un goal riscritto nel frattempo non copre il
primo. `glob("*.md")` non scende nelle sottocartelle, quindi dal cestino
nulla ricompare nell'elenco.

La conferma la chiede la pagina, non l'API: si recupera, ma mezz'ora di
scrittura e un clic per sbaglio su un telefono sono entrambi facili.

**Cancellare il goal attuale si puo'**, e lascia nessun goal attuale. Il
contrario sarebbe un goal che non si puo' togliere perche' e' segnato, e per
levarlo bisognerebbe prima segnarne un altro.

### 2. Il goal attuale si sceglie — `PUT /api/plans/{slug}/current`

Un `make current` sulle righe che non lo sono. Scrive `current: true` nel suo
file e lo toglie dagli altri.

**Riga per riga e non con `yaml.dump`.** Un giro da YAML riordinerebbe le
chiavi, butterebbe i commenti e riscriverebbe `siblings: [a, b]` su tre
righe: questi file li scrive una persona e li rilegge, la forma e' sua, e
un'API che la rimpagina a ogni clic e' un'API che si fa odiare. Si cerca il
flag **solo dentro il front matter**: una riga `current:` nel testo, in un
esempio o in un blocco di codice, non e' la chiave.

Scrive **tutti** i file e non i due che cambiano, perche' il flag di troppo
puo' essere in un terzo: due `current: true` sono una cosa che succede, e
`_one_current` del todo 84 li nasconde in lettura senza sistemarli. Qui si
sistemano. E lo slug si controlla **prima** di toccare qualcosa: con la
verifica in mezzo si toglierebbe il flag agli altri per poi scoprire che il
nuovo non esiste, restando senza nessun goal attuale.

### 3. La cascata: dirla, perche' non si puo' farla

Qui c'e' il fatto che ha deciso il todo. **Nessuno genera i piani
settimanali.** I 19 file di `summary/05.plan/` sono stati scritti il 26
ottobre 2026 da un giro a mano — lo dice il loro README — e nel progetto non
c'e' un target `make`, non c'e' una funzione, non c'e' un agente che li
scriva. Il codice li sa solo **leggere**: `week_plan_path` per il prompt di
Next, l'API per la vista Plan della Week, `load_day_plan` per la card del
giorno.

Quindi cambiare goal **non puo'** rigenerare le settimane: non c'e' niente da
chiamare. E le settimane contano davvero — i tre piani hanno ritmi e
chilometraggi diversi (6:10 contro 7:07 al km, 50 contro 38 km nella
settimana di punta), quindi dopo uno scambio le diciotto settimane
prescrivono il bersaglio vecchio, la card Plan del giorno mostra quella
seduta, e l'agente Training giudica la corsa contro di lei.

La cosa peggiore non e' che non si rigenerino: e' che **non si veda**. Allora
si vede. `GET /api/plans` rende `ahead`, cioe' quale goal dichiarano le
settimane **da questo lunedi' in poi** e quante sono, e la pagina mette un
avviso quando non e' quello attuale: *18 weekly plans from this Monday on
still follow `half_marathon_2.20`*.

**Il passato non si conta.** Le settimane finite sono il registro di quello
che era previsto allora, e che seguano un goal vecchio e' giusto. Riscriverle
sarebbe peggio che lasciarle: i report giornalieri di ottobre hanno giudicato
le sedute contro quelle sedute, e cambiarle sotto farebbe parlare un report
di un piano che quel giorno non esisteva.

## Quello che non va toccato

- **La chiave `plan:` delle settimane.** Resta lei a dire da quale blocco
  viene una settimana. E' la meta' di cui `ahead` fa il conto.
- I piani settimanali gia' scritti, passati o futuri: questo todo non ne
  tocca nessuno.
- `?period=plan` e il nome `PlanPage.tsx`.

## Rischi

- **Un `DELETE` senza login.** E' la prima rotta distruttiva dell'API. Il
  cestino la rende recuperabile, ma chi puo' raggiungere la 8000 puo'
  svuotare l'elenco dei goal, e dalla tailnet non e' solo chi scrive questo.
  Il todo 83 vale piu' di prima.
- **Il flag diventa una bugia comoda.** Da adesso cambiarlo e' un clic, e il
  clic non fa quello che uno si aspetta: segna l'intenzione e lascia i piani
  dov'erano. L'avviso e' tutto quello che tiene insieme le due cose, ed e'
  una riga di testo — non un controllo.
- **Il seguito e' un generatore, e non esiste.** Finche' non c'e', dopo uno
  scambio di goal i piani settimanali si riscrivono come sono stati scritti
  la prima volta: a mano. E' il prossimo todo, non questo.
- **Il commento sulla riga del flag si perde.** `current: true  # ...`
  scritto a mano torna come `current: true` in fondo al front matter: quella
  riga la gestisce l'API. Il resto del file no.

## Come e' andata

Fatto. La pagina Goal ha un cestino e un `make current` su ogni riga, e
l'avviso quando le settimane non seguono il goal segnato.

### Verificato

Le scritture, **su una copia** in uno scratchpad e non sui file veri:

- `set_current` sposta il flag: nei tre file l'unica differenza e' la riga
  `current:` che va via da uno e compare nell'altro, e il corpo del markdown
  e' identico byte per byte.
- il giro di ritorno rimette l'attuale dov'era.
- `delete_plan` sposta in `.trash/half_marathon_2.30-20261030-162435.md`, e
  l'elenco scende a due.
- uno slug che non esiste alza `FileNotFoundError` **senza aver toccato
  niente**: i flag restano come erano.

Sull'API vera, senza muovere dati: `PUT /api/plans/non_esiste/current` e
`DELETE /api/plans/non_esiste` rendono 404 e i tre file non si muovono.
`GET /api/plans` rende `ahead = [{half_marathon_2.20, 18}]`.

`npm run typecheck` pulito, tipi rigenerati dall'OpenAPI, build fatta,
servizio riavviato.

### Quello che non ho provato

**Le due rotte non le ho esercitate su un goal vero**: avrebbero scambiato il
goal attuale e spostato un file nella cartella dati. Lo strato HTTP e' sottile
— un `try/except` che diventa 404 e poi l'elenco — e le funzioni sotto sono
provate, ma il primo scambio vero lo fa chi apre la pagina.

**E non ho visto la pagina.** Senza browser non ho uno screenshot: il cestino,
il `make current` e l'avviso sono nel bundle servito, ma come stanno nella
riga non l'ho guardato.

## Revert

Il revert del codice basta. Quello che resta fuori dal repo: un eventuale
`plan/.trash/` con dentro i goal cestinati, da svuotare o ripescare a mano, e
il flag `current` dove l'ultimo clic l'ha messo.
