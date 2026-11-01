---
status: done
---

# Via la vista Plan della Week: il doppione era di due generi

La Week aveva quattro viste, e la quarta — **Plan** (todo 60) — era il
documento della settimana: i quattro numeri del blocco in cima, la tabella
dei sette giorni col perche' di ognuno, i totali, i ritmi, e quando
scaricare.

Da due todo non era piu' al suo posto, e per due ragioni diverse.

**La tabella dei giorni e' la stessa cosa detta due volte.** Dal todo 89 ogni
riga della colonna Plan della Training porta la riga di quel giorno nella
tabella del file: *Easy 8 km at 7'10"-7'45", heart rate 125-138, then 6 x 20 s
strides*. La tabella della vista Plan dice quelle sette righe, e sono nella
stessa vista a un riquadro di distanza.

**I ritmi e le deroghe sono copiati dal blocco.** Verificato sui file, non a
memoria: la tabella `Paces` della settimana del 9 novembre ha **gli stessi
valori** di «Ritmi e frequenze» di `plan/half_marathon_2.20.md` — 7'10"-7'45"
/ 125-138, 5'55"-6'10" / 150-156, tutto — senza la colonna «Quanto» e senza
gli allunghi. Le prime quattro regole di `When to back off` sono la
traduzione di «Quando scaricare, senza chiedere» del blocco, una per una. E i
totali (33 km · lungo 16 · 1 qualita') sono la riga di quella settimana nella
tabella «Le 18 settimane». Tutto questo si legge nella pagina Goal.

Quindi la vista mostrava, in un posto suo, cose che stanno in altri due
posti. Va via.

## Cosa si fa

### 1. La Week ha tre viste — `navigation.ts`

`VIEWS.week` diventa `snap | training | trend`, le stesse della Day, e il
tipo `View` perde `"plan"` — nessun periodo ce l'ha piu'. Un `?view=plan` nei
segnalibri **ricade sullo Snap**, che e' quello che `viewFromUrl` fa con
qualunque vista che non esiste: quella validazione serve a se stessa, e non
serve codice per i link vecchi.

### 2. Quello che era solo li' va sotto le righe che spiega — `WeekPlanCard`

La card non muore: cambia posto. Sta in fondo alla **Training**, a tutta
larghezza sotto le due colonne, e tiene l'intestazione col titolo della
settimana, i quattro numeri del blocco e la prosa.

**I quattro numeri restano** — fase, settimana N di M, gara, bersaglio. Sono
ricavabili dal blocco, ma non per *questa* settimana senza contare le righe
della sua tabella, e in una card a tutta larghezza non hanno il problema di
allineamento per cui il todo 75 li aveva tolti dalla colonna.

**Niente piano, niente card.** La colonna delle sedute previste, due riquadri
sopra, e' gia' la cornice che lo dice; dirlo due volte nella stessa vista e'
dirlo male. Via anche il messaggio *No plan for the week of…*, che era la
risposta di una vista che non c'e' piu'.

### 3. La tabella dei giorni si taglia **per forma, non per nome**

`withoutDayTable`: si butta il blocco di righe di tabella in cui una prima
cella e' un giorno (`**Mon 9 Nov**`, la stessa forma che `_day_row` cerca
nell'API), e si tengono le altre tabelle — i ritmi.

Un filtro sul **titolo** della sezione sarebbe fragile: le sezioni le scrive
un agente (todo 86), e basta che un giorno chiami «Pace» quella tabella
perche' il filtro mangi la cosa sbagliata.

**Le altre sezioni non si toccano, nemmeno quelle che ripetono il blocco.**
`When to back off` del 9 novembre ha una **quinta regola che nel blocco non
c'e'** — *«If Sunday morning readiness is under 50, or breathing in sleep is
15 or more, cut the long run to 12 km rather than moving it»* — scritta per
quella settimana. Buttare la sezione perche' quattro quinti sono copiati
butterebbe anche quella. Si taglia solo quello che e' **sicuramente** detto
due volte nella stessa vista.

## Quello che non va toccato

- **`GET /api/weekly/<lunedi>/plan`** e il modello `WeekPlan`: la rotta resta,
  e resta il `body` intero. Il taglio e' una scelta di questa card, non del
  dato — e chi legge l'API continua a vedere il documento com'e' scritto.
- **La colonna del piano** (`WeekPlanBrief`, `PlanDayRow`) e i suoi dettagli
  del todo 89.
- **I file di `summary/05.plan/`**: nessuno li riscrive. Che la settimana
  ricopi i ritmi del blocco e' giusto — e' un documento che si legge da solo,
  anche fuori dall'app.
- `?period=plan`, la pagina Goal: e' l'altra cosa che si chiamava Plan, e
  adesso e' la sola.

## Rischi

- **La Training si allunga ancora.** Commento, due colonne di sette righe col
  dettaglio, e adesso la settimana spiegata: sul telefono, dove le colonne si
  impilano, sono parecchie schermate. E' la vista che fa tutto, ed e' il
  prezzo di averne una in meno.
- **Il documento non si legge piu' intero in nessun posto dell'app.** Chi
  voleva «il file della settimana» aveva una vista che glielo dava; adesso ha
  una card senza la tabella dei giorni, e per la tabella guarda le righe
  accanto. Il file intero resta sul disco.
- **Il taglio per forma puo' sbagliare.** Una tabella che non sia dei giorni
  ma abbia in prima cella qualcosa come `Mon 9 Nov` verrebbe buttata, e una
  tabella dei giorni scritta in un'altra forma (`09/11`) resterebbe —
  diventando il doppione che si voleva togliere. In compenso non si rompe mai
  in modo rumoroso: si vede una tabella in piu' o in meno.
- **Un `?view=plan` vecchio non dice niente.** Ricade sullo Snap senza
  spiegare perche'. Per un'app con un utente solo e' il comportamento di
  qualunque indirizzo che non si capisce piu'.

## Come e' andata

Fatto. La Week ha tre viste e la settimana spiegata sta in fondo alla
Training.

### Verificato

La pagina in un DOM (jsdom sul bundle vero, contro l'API accesa):

- **questa settimana, Training**: menu `Snap Training Trend`, la card c'e' col
  titolo `Week 1 of 18 - 26 October - 1 November 2026`, i quattro numeri
  (`Phase base`, `Block week 1 of 18 half_marathon_2.20`, `Race 28 Feb 2027`,
  `Target 2:20`), **una sola tabella nella prosa** — i ritmi — e **zero righe
  di giorno** dentro la card: il taglio funziona. Le sezioni `Paces` e `When
  to back off` ci sono, e la prosa comincia da *«The week back in, and it
  starts with a day off»*. Le sette righe del piano restano nella colonna.
- **W46, una settimana futura**: la stessa cosa, con la sua prosa — *«Three
  kilometres more than last week, and the last climbing week before the
  cutback»*.
- **un vecchio `?view=plan`**: ricade sullo Snap, nessun errore.
- nessun errore in console in nessuno dei tre casi.

`npm run typecheck` pulito, `npm run build` ok, servizio riavviato.

### Quello che non ho provato

**Lo schermo**, come sempre senza browser: quanto e' lunga la Training
adesso, e come la card sta sotto le due colonne, non l'ho visto.

## Revert

```bash
git revert -m 1 $(git log main --merges --grep="^Merge branch 'todo_90'$" --format=%H -1)
```

Effetti fuori dal repo: nessuno. Resta solo la pagina compilata in
`frontend/dist/`, che si rifa' con `make frontend_build`.

Dopo il revert, rifare il merge di `todo_90` non riporta le modifiche (git le
considera gia' unite): per riaverle serve il revert del revert.
