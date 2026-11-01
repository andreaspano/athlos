---
status: done
---

# Una faccia su ogni card: come sta andando, in un colpo d'occhio

Le cinque icone della scala — `terrible`, `low`, `medium`, `high`, `perfect`
— sono in `icons/` e non le usa nessuno. Vanno dove servono: in cima a ogni
card, a dire **come sta andando quella cosa**, prima di leggere i numeri e
prima di leggere il testo.

Sei card, su tutte e due le pagine: **Summary, Health, Recovery, Load,
Fitness** e il **Comment** della Training.

## Da dove viene il voto

**Dai numeri, non da un'opinione** — tranne il Comment, che numeri suoi non
ne ha.

Le fasce ci sono gia' e la pagina le disegna: `low`/`high` sono una
deviazione standard attorno alla media, `outer_low`/`outer_high` sono due.
Quello che manca e' **da che parte sta il male**, che oggi e' scritto a
parole in `.claude/agents/_style.md` — nel prompt degli agenti, non nel
codice. Questo todo lo mette nel codice, dove si puo' usare.

## Cosa si fa

### 1. Le regole in un posto solo — `api/score.py`, nuovo

Una misura, la sua fascia e la direzione del bene diventano un passo da -2 a
+2:

| Dove sta il valore | Passo | Faccia |
|---|---|---|
| oltre due sigma dal lato buono | +2 | perfect |
| fra una e due sigma dal lato buono | +1 | high |
| dentro la fascia | 0 | medium |
| fra una e due sigma dal lato cattivo | -1 | low |
| oltre due sigma dal lato cattivo | -2 | terrible |

E' la stessa lettura che `_style.md` chiede agli agenti a parole: *dentro la
prima fascia e' normale, fuori merita un commento, fuori dalla seconda non e'
un cavillo*. La faccia di una card e' la **media dei passi** delle sue
misure, arrotondata; le misure senza valore o senza fascia non votano, e una
card dove non vota nessuno **non ha faccia** — l'assenza di misure non e' un
verdetto.

La direzione, dalla tabella di `_style.md`:

- **sotto e' male**: HRV, prontezza, sonno, body battery;
- **sopra e' male**: FC a riposo, respiro nel sonno, stress;
- **i punteggi di forma si leggono al contrario**: VO2max, endurance e hill
  sopra la fascia stanno ancora salendo, ed e' una buona notizia.

### 2. Il carico e' l'eccezione, e non arriva agli estremi

Per il carico **non esiste un lato buono**: tanto e' troppo e poco e' poco,
e il bene sta dove uno di solito sta. Quindi la regola e' **centrata** sulle
tre fasce mensili che la card gia' disegna (aerobico basso, aerobico alto,
anaerobico): dentro la fascia 0, fra una e due sigma -1 da qualunque parte,
oltre -2.

Da cui una cosa da dire ad alta voce: **il Load non prende mai `perfect` ne'
`terrible`**. Il massimo che quella misura sa dire e' "sei dove stai di
solito", e quella e' `high`. Fingere un `perfect` vorrebbe dire inventare un
bersaglio che i dati non hanno.

### 3. Il Summary e' la media delle quattro

Nessuna misura sua: e' il verdetto sulle altre, ed e' esattamente quello che
fa l'agente `07_summary` leggendo i frammenti. La faccia e' la media dei
passi delle quattro card che ne hanno una.

### 4. Il Comment lo dice l'agente — `verdict:` in cima al frammento

La Training non ha misure con fasce: ha una seduta e un giudizio. Quella
parola la scrive chi il giudizio lo da', cioe' l'agente.

Il frammento comincia con una riga `verdict: high`, e **chi compone la
toglie** (`_fragment_sections`): il corpo arriva alla pagina senza, e la
parola viaggia in un campo suo di `ReportSection`. Una riga `verdict:` e'
piu' facile da scrivere per un agente di un front matter, e piu' facile da
togliere per chi legge.

Si tocca il prompt di **due agenti soli**, `05_training` e `w5_training`.
Gli altri non ne hanno bisogno: il loro voto viene dai numeri.

**I report gia' scritti non ce l'hanno**, e la loro Comment resta senza
faccia finche' non si riscrivono. Va bene: una faccia inventata adesso su un
testo di ottobre sarebbe un voto che nessuno ha dato.

### 5. La faccia nella cornice — `CardHead`

Un `face` accanto al `note` del todo 91: l'icona in fondo
all'intestazione, prima del tasto che rifa' la sezione, grande come quella
della sezione (22 px), col `title` che dice la parola — `perfect`, `low` —
perche' un'icona senza nome e' un indovinello.

Sta nell'intestazione e non sopra i numeri per la ragione del todo 75: li'
non aggiunge una riga, e nessun allineamento si muove.

## Quello che non va toccato

- **Le fasce.** Sono quelle che la pagina disegna gia', e la faccia e' la
  loro lettura: se un giorno cambiano, la faccia cambia con loro e deve.
- **I testi degli agenti.** Nessuno scrive "sei a high": la faccia e' in
  cima, la prosa resta la prosa.
- **`_style.md`**: resta la fonte della direzione per chi scrive. Il codice
  la copia, e la copia porta scritto da dove viene.
- Le cinque icone (`tools/scale_icons.py`): i file ci sono gia'.

## Rischi

- **Una faccia e' un voto, e un voto si legge come una pagella.** `perfect`
  non vuol dire che va tutto bene al mondo: vuol dire **insolitamente bene
  per te**, perche' la fascia e' la storia di quella persona. Una faccia
  verde in una settimana di influenza e' possibile, se le misure di quella
  settimana stanno sopra la banda della persona malata.
- **Media di medie.** La faccia di una card media misure diverse, e il
  Summary media le card: una misura messa molto male e tre normali danno
  `medium`, cioe' la faccia nasconde proprio il numero che andava guardato.
  La card sotto ce l'ha, ma chi guarda solo le facce no.
- **Il Comment e' l'unico voto di un LLM**, e sugli stessi dati puo'
  oscillare da un giorno all'altro. Le altre cinque sono una funzione dei
  numeri e non si muovono se i numeri non si muovono.
- **Il Load non arriva agli estremi** e le altre si': cinque facce in fila
  con una che gioca con tre carte su cinque e' un'asimmetria che nessuno
  spiega guardando.
- **Una card senza faccia non e' una card che va male.** Vuol dire che non
  c'era niente da misurare, e due assenze diverse — nessun dato, nessuna
  fascia — si vedono uguali.

## Come e' andata

Fatto. Le sei card portano la faccia su tutte e due le pagine.

Due cose trovate per strada.

**La riga del voto non bastava chiederla all'agente.** Il file di
`05_training` la spiegava, e il frammento tornava senza: `_style.md` —
attaccato *dopo* il file dell'agente — dice «solo il corpo, nessun
preambolo», e quella riga sembra un preambolo. Adesso la chiede il **prompt**
dell'orchestratore (`VERDICT_LINE` in `refresh.py`), che e' l'ultima cosa che
l'agente legge ed e' anche il posto dove la riga viene tolta: le due meta'
del patto stanno nello stesso file. Provato prima e dopo, sullo stesso
giorno: senza, niente riga; con, `verdict: high` in cima.

**Il Summary media le card e non le misure.** Se mediasse tutte le misure
insieme, Health con quattro misure peserebbe quattro volte il Load che ne ha
una: la media e' sui quattro gradini gia' arrotondati.

### Verificato

Le regole, a mano: una misura sotto di molto rende -2 se sotto e' male e +2
se sotto e' bene; dentro la fascia 0; il carico dentro 0, poco fuori -1,
molto fuori -2; `verdict([])` rende `None` e non `medium`.

L'API, sui dati veri: il 31 ottobre rende `health low, recovery medium, load
low, fitness high, summary medium` — e il `low` del carico torna con
`load_balance_phrase: ANAEROBIC_SHORTAGE`, il `high` della forma col VO2max a
42.5 sopra la sua fascia. La settimana del 26 ottobre rende `fitness perfect`
(VO2max 42.5 contro una fascia 39.7-41.1, oltre anche il secondo scarto).

La catena del Comment, da un capo all'altro: rigenerata **una sola sezione**
(`--section training --no-update`, nessuna chiamata a Garmin) del 31 ottobre
e della settimana del 19; l'agente ha scritto `verdict: high`, l'API lo rende
nel campo `verdict` **e il corpo comincia dalla prima frase vera**, senza la
riga.

La pagina in un DOM, quattro viste:

| Vista | Facce |
|---|---|
| Day Snap | Summary=medium, Health=low, Load=low, Recovery=medium, Fitness=high |
| Day Training | Comment=high |
| Week Snap | Summary=medium, Health=medium, Load=medium, Recovery=medium, Fitness=perfect |
| Week Training | Comment senza faccia: quel frammento e' di ottobre e non ha la riga |

Le `src` sono i cinque file di `icons/`, e le card senza voto non hanno
immagine. `npm run typecheck` pulito, `npm run build` ok, tipi rigenerati
dall'OpenAPI, servizio riavviato.

### Quello che non ho provato

**Lo schermo**: dove cade la faccia nella cornice, se a 22 px le due
scontente si distinguono davvero nel contesto, e come sta nel Summary che ha
l'occhiello invece dell'intestazione.

**Il resto dei report**: solo due sezioni Training hanno la riga, quelle che
ho rigenerato. Le altre l'avranno quando i giri le riscrivono — stasera il
giro delle 21 per il giorno, e quello della domenica per la settimana.

## Revert

Il revert del codice basta. Effetti fuori dal repo: la riga `verdict:` resta
in cima ai frammenti `training.md` scritti nel frattempo — e senza il codice
che la toglie **si vede nel testo della card**, come prima riga. Si cancella
a mano, o si riscrive quella sezione.
