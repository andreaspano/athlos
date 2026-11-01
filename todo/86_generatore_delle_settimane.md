---
status: done
---

# Le settimane si generano dal goal

I todo 84 e 85 hanno nominato tre volte la stessa mancanza, e nessuno dei
due l'ha colmata: **nessuno genera i piani settimanali.** I diciannove file
di `summary/05.plan/` li ha scritti un giro a mano il 26 ottobre 2026 — lo
dice il loro README — e nel progetto non c'e' un target `make`, non c'e' una
funzione, non c'e' un agente che li scriva. Il codice li sa solo leggere:
`week_plan_path` per il prompt del Training, l'API per la vista Plan della
Week, `load_day_plan` per la card del giorno.

Da questo vengono due cose che oggi sono vere insieme. La prima: il flag
`current` del todo 84 **segna un'intenzione e non muove niente** — si cambia
goal con un clic e le diciotto settimane restano scritte sul bersaglio
vecchio, coi ritmi e i chilometri di quello (6:10 contro 7:07 al km, 50
contro 38 km nella settimana di punta fra il 2.10 e il 2.30). La seconda: il
todo 85 ha potuto solo **dirlo**, con una riga di avviso sulla pagina Goal,
perche' non c'era nulla da chiamare. Quella riga finisce con *nothing does
yet*.

Questo todo e' lo `yet`.

## Cosa si fa

Un generatore: dal blocco di `plan/<slug>.md` escono i file settimanali di
`summary/05.plan/`, uno per settimana, nel formato che il todo 14 ha deciso
e che `summary/05.plan/README.md` descrive.

### 1. Lo scrive un agente, non un parser — `.claude/agents/p_week.md`

Il blocco e' **prosa**: la tabella delle diciotto settimane da' km, lungo e
qualita' riga per riga, le tre tabelle di fase danno la forma dei sette
giorni, un'altra tabella i ritmi e le frequenze, e in fondo ci sono le
deroghe e le prove di controllo. Tradurre tutto questo in sette sedute vuol
dire leggere un documento che una persona ha scritto a mano.

Un parser di quelle tabelle sarebbe **il parser del markdown di una
persona**: i tre goal di oggi hanno la stessa forma perche' li ha scritti lo
stesso giro nello stesso pomeriggio, e il prossimo blocco — una gara in
salita, un trail, un periodo senza gara — non ce l'ha. Si romperebbe sul
primo blocco scritto diversamente, e si romperebbe in silenzio: una tabella
che non si trova diventa una settimana senza sedute.

Quindi un agente, come per i report: un file in `.claude/agents/`, lanciato
con `claude -p --agent p_week` esattamente come `_write_section` lancia le
sezioni. L'impianto c'e' gia' e non va riscritto — i permessi (`Read`, piu'
un `Edit(//percorso/**)` col doppio slash), stdin chiuso, il timeout di
dieci minuti, il controllo che il file sia stato scritto **adesso** e non
dall'ultima volta.

**Lo stile dei report non si attacca.** `_style.md` dice *scrivi il corpo di
una sezione, nessun titolo, un paragrafo, pochi numeri, niente tabelle*: qui
sono tutte istruzioni sbagliate. Una settimana e' un documento con front
matter, titoli e tabelle. Quello che vale di quelle regole — l'inglese, le
date scritte per esteso — sta nel file dell'agente. Niente
`--append-system-prompt-file`.

### 2. Le date le decide Python, e Python controlla — `api/weekplans.py`

`plans.py` e' chi legge; questo e' chi genera. E genera **l'identita' della
settimana**, che all'agente si da' nel prompt e non si chiede:

- il lunedi', che e' anche il nome del file;
- `block_week` e `block_weeks`, dal `block_start` del blocco;
- `plan` (lo slug), `race`, `target_time`, copiati dal front matter del
  blocco.

Non e' pignoleria. Un agente che scrive diciassette front matter a mano ne
sbaglia uno — un lunedi' di un giorno, un `block_week` ripetuto, una data di
seduta che cade nella settimana prima — e **l'errore e' muto**:
`load_day_plan` cerca la seduta per data, quindi una data sbagliata non da'
un errore, da' un giorno senza piano. Si scoprirebbe a dicembre, guardando
una card vuota.

Poi si controlla quello che l'agente ha scritto, prima di crederci:

| Controllo | Perche' |
|---|---|
| il front matter si legge | senza, il file e' solo prosa per la pagina |
| `week` e' il lunedi' chiesto, `plan` lo slug chiesto | o il conto di `weeks_following` conta un'altra cosa |
| `block_week`, `block_weeks`, `race`, `target_time` come calcolati | sono l'identita', non un'opinione |
| `sessions` ha sette voci, una per ciascun giorno di quella settimana | e' la regola del README |
| `sport` fra i nomi di `activities.sport` piu' `rest`; `kind` fra `easy`, `quality`, `long`, `race` | un `kind: tempo` non lo mostra nessuno |
| `distance_km` un numero o due | `_distance_label` sa leggere solo questi |
| la tabella `Day \| Session` ha una riga per tutti e sette i giorni | riusando `_day_row`: e' lui che la cerca, nella forma `2 Nov`, e una tabella scritta `02/11` lo lascia a mani vuote |

**Il file nasce in `summary/05.plan/.staging/` e arriva al suo posto solo se
passa.** Un file rotto e' peggio di un file che non c'e': quello che non c'e'
lo gestiscono tutti e tre i lettori apposta (`None`, nessuna frase nel
prompt, nessuna card), quello rotto va in giro — il Training del giorno
giudica una corsa contro una seduta sbagliata, e scrive un verdetto. Nella
staging e non in `/tmp` perche' una settimana scartata si vuole leggere per
capire cosa ha scritto; `glob("*.md")` non scende nelle sottocartelle, quindi
da li' nulla si vede nell'elenco ne' nel conto di `ahead`.

### 3. Da quale settimana: **da lunedi' prossimo**

Il passato non si tocca, e il todo 85 ha gia' deciso perche': le settimane
finite sono il registro di quello che era previsto allora, i report
giornalieri di ottobre hanno giudicato le sedute contro quelle sedute, e
riscriverle farebbe parlare un report di un piano che quel giorno non
esisteva.

**La settimana in corso sta col passato**, e questa e' la decisione nuova.
Oggi e' sabato: i sei giorni passati di questa settimana sono stati corsi e
giudicati, e riscrivere il file li riscriverebbe insieme alla domenica — la
card Plan della Day, che legge il file dal vivo, mostrerebbe su mercoledi'
una seduta decisa oggi. Una settimana che cambia sotto i piedi a meta' e'
peggio di una settimana che finisce sul piano vecchio. Quindi il generatore
parte dal **lunedi' successivo a oggi** e arriva alla settimana di gara: col
2.20, da `2026-11-02` a `2027-02-22`, diciassette settimane.

Il prezzo e' un avviso che non si spegne subito: `ahead` conta da **questo**
lunedi', quindi dopo una generazione la pagina dice ancora *1 weekly plan
from this Monday on still follows ...*. E' vero — quella settimana segue
davvero il goal vecchio — e si spegne da se' il lunedi'. `weeks_following`
non si tocca.

### 4. I file che ci sono gia' vanno nel cestino

Non si sovrascrivono. Il README dice che **una settimana si puo' riscrivere a
mano** avvicinandosi alla data, sullo stato di forma del momento, e una di
quelle diciassette puo' essere mezz'ora di lavoro di una persona. Stessa
scelta del todo 85 per i goal: `summary/05.plan/.trash/<lunedi>-<momento>.md`,
col momento nel nome perche' generare due volte non copra la prima copia.

Da qui viene una cosa da dire ad alta voce: **generare e' un gesto
distruttivo**, il primo che tocca file dentro `summary/`.

### 5. Un agente per settimana, in fila, con quella prima in mano

In fila e non insieme, per i motivi che l'orchestratore scrive da se': a
parita' di lavoro i gettoni sono gli stessi, un giro che va storto si ferma
invece di bruciare le sessioni rimaste, e non si rischiano i limiti di
frequenza.

Ogni agente riceve il blocco, l'identita' della sua settimana e **il file
della settimana prima** — quella appena scritta, o quella che c'e' gia' per
la prima del giro. La progressione e' la sostanza del piano: il lungo che va
da 15 a 16, il rifornimento che entra alla settimana 7, gli ultimi
chilometri a ritmo gara dalla 10. Senza il file di prima ogni settimana
ripartirebbe dal blocco e la continuita' sarebbe una coincidenza.

### 6. Il comando — `make week_plans`

`training-week-plans`, sulla linea di `training-daily-report`:

```
make week_plans                      il goal attuale, da lunedi' prossimo
make week_plans GOAL=half_marathon_2.10
make week_plans FROM=2026-12-07 TO=2027-01-04
```

Senza `GOAL` si prende **il goal attuale**: e' la prima volta che `current`
serve a qualcosa fuori dalla pagina, e il todo 84 aveva messo fra i rischi
proprio che non servisse a niente.

Prende **lo stesso lock** del giro dei report (`.refresh.lock`, nella
cartella dei dati): due serie di `claude` sugli stessi file non si fanno, e
il lock e' l'unica cosa che lo impedisce fra processi diversi. Chi lo trova
occupato se ne va, come fanno gia' i timer.

Stampa una riga per settimana — numero del blocco, fase, km totali, lungo,
quante qualita' — perche' **quelle diciassette righe sono la verifica**: si
leggono accanto alla tabella «Le 18 settimane» del blocco, e un lungo di 21
km alla settimana 3 si vede a occhio. Il controllo del punto 2 e' strutturale,
non sa niente di allenamento.

### 7. L'avviso della pagina dice il comando

`PlanPage.tsx`: al posto di *nothing does yet*, il nome del comando da
lanciare. **Niente tasto**, e non e' per pigrizia: sono diciassette agenti e
mezz'ora col lock in mano, dietro un'API che non ha login (todo 83) e che
dalla tailnet raggiunge anche un'altra persona. Un tasto vuole uno stato da
mostrare mentre gira, e quello che c'e' — `refresh._state` — e' fatto sulle
sezioni di un report. E' il todo dopo questo.

E vanno riscritte le righe che dicono che un generatore non c'e':
`README.md` (sezione Goal) e il README di `summary/05.plan/`, che sta fuori
dal repo.

## Quello che non va toccato

- **Il formato dei file settimanali.** Lo ha deciso il todo 14, lo descrive
  `summary/05.plan/README.md`, e tre lettori ci contano. Il generatore lo
  rispetta, non lo rinegozia — compresa la regola *deve leggersi uguale a
  dicembre*: nessun «stamattina», e un motivo che e' una misura si scrive
  con la sua data.
- **La chiave `plan:`.** Resta lei a dire da quale blocco viene una
  settimana, ed e' la meta' di cui `ahead` fa il conto.
- **`weeks_following` e il suo `since`.** Vedi il punto 3.
- **Le settimane finite, e `2026-09-28.md`.** Quel file non ha il front
  matter — e' di prima che il formato l'avesse — e sta fuori da ogni blocco:
  il generatore non lo guarda.
- I report: nessun agente di `sections.py` cambia, e nessuno dei due giri
  dei timer chiama questo comando. Un piano nuovo non e' una cosa che
  succede ogni notte alle otto.

## Rischi

- **Un agente prescrive allenamenti a una persona di 100 kg.** I controlli
  del punto 2 sono strutturali: dicono che ci sono sette sedute con un
  `kind` noto, non che quelle sedute siano sensate. Niente verifica che i km
  della settimana siano quelli della tabella del blocco, e un lungo di 21 km
  scritto alla settimana 3 passerebbe ogni controllo. Il blocco e'
  l'autorita' e le diciassette righe stampate sono il modo di guardarle: va
  fatto, non e' un dettaglio del collaudo.
- **Non e' una funzione: due giri danno due piani diversi.** Rilanciare il
  comando non e' innocuo come rilanciare un backfill — riscrive settimane
  che magari andavano bene, e la copia buona e' nel cestino. Si rilancia
  sapendolo.
- **Mezz'ora di lock.** Lanciato alle 7:50 o alle 20:50, il giro dei report
  trova il lock occupato, esce 0 e quel report quella volta non si scrive. Si
  lancia quando non c'e' un giro vicino, come il `backfill_reports`.
- **Diciassette sessioni di `claude` per un comando.** Non e' niente da
  mettere in un timer.
- **Il flag e i file restano legati da una mano.** Dopo questo todo cambiare
  goal **ancora non** rigenera: c'e' un comando da lanciare, e chi non lo
  lancia ha l'avviso. Collegare le due cose — il `PUT` che genera — e' il
  todo del tasto, e porta con se' la domanda se un clic su un telefono debba
  poter riscrivere diciassette settimane.
- **Un blocco senza `block_start` o `block_weeks` non si genera.** Per la
  pagina il front matter non e' obbligatorio e un goal senza chiavi si vede
  comunque; qui no. L'errore deve dire **quale chiave manca e in quale
  file**, non fermarsi su un `None`.
- **Una settimana che si legge bene oggi e male a dicembre.** La regola del
  README e' prosa e la rispetta solo l'agente: nessun controllo la vede. E'
  l'errore che la settimana del 26 ottobre ha fatto scrivendo «this
  morning».

## Come e' andata

Fatto. `make week_plans` c'e', e con `DRY=1` dice che scriverebbe diciassette
settimane dal 2026-11-02 al 2027-02-22, 2/18 ... 18/18, dal goal attuale.

Tre cose decise strada facendo.

**`--dry-run` (`DRY=1`), che il todo non chiedeva.** Dice quali settimane
scriverebbe e quali manderebbe nel cestino, senza lanciare niente. Serviva per
provare il conto delle settimane senza spendere diciassette agenti e senza
riscrivere i file veri, e resta perche' prima di un gesto distruttivo da
mezz'ora guardare cosa fara' e' il minimo.

**Lo `sport` non si controlla contro i dati.** Il todo diceva «fra i nomi di
`activities.sport` piu' `rest`», e non lo fa: i nomi degli sport vengono dal
database, e su un database vuoto — un clone nuovo — ogni settimana sarebbe da
buttare, mentre non e' la settimana a essere sbagliata. In piu' un piano puo'
prescrivere uno sport mai fatto. Resta il controllo che ci sia e che non sia
vuoto; il `kind` invece e' un insieme chiuso e si controlla, perche' quello lo
dice il formato e non i dati. Gli sport scritti si vedono comunque nelle righe
stampate.

**Il `.staging/` tiene le scartate.** Non si svuota da se': una settimana
scartata e' l'unica traccia di cosa l'agente ha scritto, e il giro dopo la
sovrascrive da solo.

### Verificato

- **I controlli passano sui file veri**: `check` su tutti e diciassette i file
  di `summary/05.plan/` dal 2026-11-02 in poi, zero problemi — gli stessi file
  scritti a mano in ottobre, cioe' il metro giusto. E le righe stampate danno
  26, 30, 33, 26, 35, 38, 41, 31, 38, 42, 44, 34, 42, 46, 43, 38, 29, 33 km,
  che sono **esattamente** la colonna della tabella «Le 18 settimane» del
  blocco: la riga stampata e' lo strumento che doveva essere.
- **Gli otto modi di sbagliare, su copie in uno scratchpad e non sui file
  veri**: lunedi' spostato di un giorno, `plan` di un altro goal,
  `block_week` sbagliato, sei sedute invece di sette, `kind: tempo`,
  `distance_km: "sixteen"`, la riga della tabella scritta `**Tue 10/11**`, il
  front matter via. Tutti e otto dicono cosa manca, e il file buono non dice
  niente.
- **Un giro vero dell'agente**, su un albero finto in uno scratchpad: la
  settimana 4/18 del 2026-11-16, col 2026-11-09 come settimana prima e un
  2026-11-16 da sostituire. Ha scritto 26 km, lungo 12, una qualita' — la riga
  del blocco — ha ripreso dalla settimana prima («the quality session steps
  back to 4 x 5 min, the shape of week 2, after the 5 x 6 min of week 3»), ha
  tenuto la regola del sabato senza escursione, e non ha scritto nessun
  «stamattina». Il file di prima e' finito in
  `.trash/2026-11-16-20261031-153339.md`.
- **La settimana scartata non va in giro**: con un agente finto che scrive un
  file rotto, il file al suo posto resta **identico byte per byte**, la
  scartata resta nella staging, e nel cestino non entra niente.
- **Il lock**: con il lock dei report preso, `generate` rende `stopped` e non
  fa niente.
- Gli errori che fermano prima di scrivere: `FROM` nel passato (lo dice e
  dice da quando si genera), `FROM` che non e' un lunedi', un goal che non
  esiste (elenca quelli che ci sono), nessun goal attuale, un blocco senza
  `block_start` (dice quale chiave e in quale file).
- `npm run typecheck` pulito, `npm run build` ok. Nessun modello dell'API
  cambia, quindi `schema.ts` non si rigenera.

### Quello che non ho provato

**Le diciassette settimane vere non le ho generate.** E' il gesto che il todo
descrive come distruttivo: avrebbe riscritto i file di
`~/adrive/data/training/summary/05.plan/` e mandato nel cestino quelli di
ottobre, mezz'ora di agenti su dati veri. Una settimana sola, sull'albero
finto, dice che la macchina funziona; il primo giro vero lo lancia chi ha
scritto il blocco, e le righe stampate sono per lui.

**E non ho visto la pagina.** L'avviso che nomina il comando e' nel bundle
compilato, ma senza browser non l'ho guardato nella riga.

## Revert

```bash
git revert -m 1 $(git log main --merges --grep="^Merge branch 'todo_86'$" --format=%H -1)
```

Effetti fuori dal repo: i file. Le settimane generate stanno in
`summary/05.plan/` e restano, insieme a `.trash/` con dentro quelle che hanno
sostituito e a `.staging/` con le scartate: tornare indietro vuol dire
ripescare dal cestino a mano, un lunedi' per volta. Resta anche la sezione
«Who writes them» di `summary/05.plan/README.md`, che sta fuori dal repo e si
riscrive a mano.

Dopo il revert, rifare il merge di `todo_86` non riporta le modifiche (git le
considera gia' unite): per riaverle serve il revert del revert.
