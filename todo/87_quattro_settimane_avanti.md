---
status: done
---

# Le quattro settimane che vengono, nella Training della Week

La vista Training della Week (todo 68, 73, 74, 77) risponde a due domande
affiancate: a sinistra **cosa chiedeva** la settimana — le sette sedute del
piano, una riga per giorno — e a destra **cosa e' successo**, sulla stessa
riga, col commento sopra che le giudica.

Manca la terza, che e' quella che si fa il sabato: **e dopo?** Oggi per
vederlo si cambia settimana col selettore, si guarda, si cambia di nuovo —
quattro volte per quattro settimane, e per confrontarle si tiene a mente la
prima mentre si guarda la quarta. Il piano del blocco e' scritto, le
diciassette settimane ci sono (todo 86): l'unica cosa che manca e' guardarne
quattro insieme.

## Cosa si fa

Una card nuova nella vista **Training** della Week, sotto le due colonne: le
**quattro settimane dopo quella mostrata**, ognuna coi suoi sette giorni.

### 1. Dove sta, e perche' non nella Plan

Sotto `.week-work`, a tutta larghezza, **fuori dalle due colonne**.

Le due colonne sono previsto contro fatto, allineate giorno per giorno (todo
77). Le settimane che vengono **non hanno il lato destro**: non sono state
corse. Metterle nella colonna del piano vorrebbe dire allungare la colonna
di sinistra a ventotto righe e lasciare quella di destra vuota per ventuno,
che e' esattamente il bianco che il todo 73 era andato a togliere.

**Non nella vista Plan**, che pure e' la vista dei piani: li' c'e' **il
documento** di una settimana — la tabella col perche' di ogni seduta, i
ritmi, i segnali per scaricare — e quattro documenti in fila non sono una
cosa che si legge. Qui le sedute sono **dati**, una riga per giorno, da
scorrere con un'occhiata. Lo stesso file, due domande: com'e' scritto, e cosa
chiede ogni giorno.

### 2. Quali quattro

`monday + 7`, `+14`, `+21`, `+28`: le quattro **dopo quella mostrata**, non
le quattro da oggi. Ogni numero di questa pagina e' della settimana scelta
col selettore, e una card che lo ignorasse sarebbe l'unica cosa della pagina
a farlo. Stando sulla settimana corrente — che e' come la pagina si apre —
sono le prossime quattro, che e' la domanda.

Ne viene che su una settimana passata si vedono le quattro che **l'hanno
seguita**, gia' corse. Non e' un guasto: quei file sono il registro di quello
che era previsto allora, ed e' la stessa ragione per cui nessuno li riscrive
(todo 85).

**Quattro e non un numero a scelta.** Niente `?weeks=`: quanto si guarda
avanti non e' uno stato della pagina, e un selettore in piu' su una vista che
ne ha gia' uno si paga in barra. Quattro settimane sono un mese, che e'
l'orizzonte entro cui un blocco si puo' ancora cambiare.

### 3. Cosa si vede di ogni settimana

I **sette giorni**, nella forma della riga di `WeekPlanBrief`: giorno della
settimana e data, l'icona dello sport, l'etichetta della seduta
(`sessionIcon`, `sessionLabel`, `plan-day-row`). Si riusa la riga, non la
card: `WeekPlanBrief` resta la colonna di sinistra e non cambia.

Sopra ogni gruppo di sette, **una riga sottile** che dice quale settimana e':
`Week 6 of 18 · build · 30 Nov – 6 Dec`.

Il todo 75 aveva **tolto** i numeri del blocco da `WeekPlanBrief`, e non e'
una contraddizione: li aveva tolti perche' spingevano in basso la riga del
lunedi' disallineandola dalla colonna accanto, e perche' per **una** settimana
non servono. Qui non c'e' nessuna colonna da allineare, e quattro gruppi di
sette righe senza intestazione sono un muro: senza quella riga non si sa dove
finisce una settimana e comincia l'altra. Gara e bersaglio restano fuori:
sono del blocco, non cambiano da un lunedi' all'altro, e li dice la vista
Plan.

**E il goal, ma solo quando cambia.** `WeekPlan.plan` dice da quale blocco
viene una settimana. Se una delle quattro ne dichiara uno diverso da quello
della settimana mostrata, lo si scrive sulla sua riga: e' la divergenza che
la pagina Goal avvisa (todo 85), e qui, dove si guarda avanti, sarebbe
invisibile — si leggerebbero quattro settimane coerenti senza sapere che due
vengono da un bersaglio abbandonato.

### 4. I dati: quattro chiamate a una rotta che c'e'

`GET /api/weekly/<lunedi>/plan`, quattro volte, dentro **un effetto solo con
un `AbortController` solo**, e i quattro lunedi' come dipendenza.

Niente rotta nuova. Quella che c'e' rende esattamente il piano di una
settimana, sedute comprese (todo 71), e quattro chiamate sono meno codice di
un endpoint nuovo piu' il suo modello piu' i tipi rigenerati. Lo spreco e'
il campo `body` — il testo della settimana, che questa card non mostra — e
sono un paio di chilobyte per settimana su una rete di casa.

**L'effetto non deve annullarsi da solo.** E' l'errore del todo 84: con i
risultati fra le dipendenze, l'arrivo del primo rilancia l'effetto e la sua
pulizia annulla le altre tre, che ripartono da zero. Le dipendenze sono i
lunedi', niente altro.

**404 non e' un errore**: quella settimana non ha un file — fuori dal blocco,
dopo la gara — e la sua sezione non si disegna. Verso la fine di un blocco le
quattro diventano tre, due, una.

Se **nessuna** delle quattro ha un file, la card non c'e'. E' il contrario
della regola della Day e della colonna del piano, dove la cornice resta
sempre (todo 63): quelle rispondono a una domanda che e' stata fatta — che
seduta era prevista oggi — e una cornice vuota e' la risposta. Questa e' uno
sguardo avanti, e una cornice che dice quattro volte che non c'e' niente, a
fianco di una colonna che per questa settimana lo dice gia', e' rumore.

## Quello che non va toccato

- **`WeekPlanBrief` e `WeekPlanCard`.** La colonna di sinistra resta i sette
  giorni e basta (todo 75), la vista Plan resta il documento di una settimana.
  Si riusa la riga di un giorno, non la card.
- **Le due colonne e l'allineamento** di todo 73 e 77: la card nuova sta
  sotto, e non entra in quella griglia.
- **L'URL.** Nessun parametro nuovo: ne' quante settimane, ne' da quale.
- I file di `summary/05.plan/`: questa e' una lettura. Chi li scrive e' il
  todo 86.

## Rischi

- **Cinque chiamate per una vista.** La Training della Week ne fa gia'
  parecchie; quattro piani sono letture di file piccoli con la cache
  dell'API davanti, ma sono quattro attese in piu' e quattro modi di
  arrivare in ritardo. Una che fallisce lascia la sua settimana fuori e le
  altre al loro posto: per uno sguardo avanti, un avviso rosso sarebbe
  peggio del silenzio.
- **La card puo' mostrare settimane che nessuno ha rigenerato.** Dopo un
  cambio di goal, le settimane avanti seguono il bersaglio vecchio finche'
  non si lancia `make week_plans` (todo 86). Il nome del goal sulla riga e'
  tutto quello che lo dice, ed e' una riga di testo.
- **Guardare avanti fa venir voglia di toccare**, e qui non c'e' niente con
  cui: le settimane sono file, e riscriverne una e' una cosa che si fa a mano
  o rigenerando. La card e' di sola lettura, e chi si aspetta di spostare una
  seduta trascinandola resta deluso.
- **La vista diventa lunga.** Commento, due colonne, piu' quattro settimane
  da sette righe: sul telefono e' molto da scorrere. Stanno in fondo, che e'
  il posto giusto, ma la pagina adesso e' alta.
- **Su una settimana passata la card parla al futuro di un passato.** Si
  chiama `Ahead` e mostra quattro settimane gia' corse. L'alternativa —
  sempre le prossime quattro da oggi — sarebbe l'unica cosa della pagina a
  non seguire il selettore, e si e' scelto il male minore.

## Come e' andata

Fatto. In fondo alla vista Training della Week c'e' la card **Ahead**: le
quattro settimane dopo quella mostrata, ognuna con la sua riga di
intestazione e i suoi sette giorni.

Tre cose decise strada facendo.

**La riga di un giorno e' diventata un pezzo a se'**, `PlanDayRow` in
`WeekPlanCard.tsx`, e la usano in due: la colonna del piano e questa card, che
ne mette ventotto. Era scritta dentro `WeekPlanBrief`, e copiarla avrebbe
voluto dire due posti dove cambiare il passo delle righe — lo stesso motivo
per cui `sessionLabel` sta in `PlanSession`. `WeekPlanBrief` per il resto non
cambia.

**Niente «Loading…».** Il todo aveva deciso che senza file la card non si
disegna, e mentre le quattro chiamate sono in volo non si sa ancora se un
file c'e': la card appare quando i piani arrivano. Una cornice vuota che poi
si riempie sarebbe stata la stessa cosa in due tempi.

**Una chiamata che fallisce vale `null`**, non un errore della pagina: ogni
`weekPlan` ha il suo `.catch(() => null)`, cosi' una settimana persa lascia le
altre tre al loro posto. Con un `Promise.all` secco ne bastava una per
perderle tutte e quattro.

### Verificato

Senza browser: qui `chromium-browser` e' lo stub di snap e il pacchetto non
c'e', quindi niente screenshot. Al suo posto **il componente renderizzato per
davvero**, con `react-dom/server` e `rolldown` che il frontend ha gia', sui
piani veri chiesti all'API in esecuzione (`/api/weekly/<lunedi>/plan` e
`/api/sports`):

- **quattro settimane**: quattro gruppi, intestazioni `Week 2 of 18 · base ·
  2 Nov – 8 Nov` fino a `Week 5 of 18 · base · 23 Nov – 29 Nov`, e dentro le
  righe dei giorni — `Mon 2 Nov / Rest · or Cycling`, `Tue 3 Nov / Running ·
  easy · 7 km`, con la classe `rest` sui giorni di riposo.
- **nessun file**: niente disegnato, zero caratteri. La card non c'e'.
- **due su quattro** (la seconda e la terza `null`): due gruppi, e sono la 2 e
  la 5 — i buchi non spostano le date, ogni settimana resta attaccata al suo
  lunedi'.
- **goal diverso**: su tutte e quattro compare `half_marathon_2.20` accanto
  all'intestazione, perche' la settimana mostrata era stata dichiarata del
  2.10. Con lo stesso goal non si scrive niente.

E poi: `npm run typecheck` pulito, `npm run build` ok, le classi nuove
(`weeks-ahead`, `ahead-week`) sono nel CSS e nel JS compilati, servizio
riavviato. Nessun modello dell'API cambia — la rotta e' quella del todo 60 —
quindi `schema.ts` non si rigenera.

### Quello che non ho provato

**La pagina in un browser.** Il markup e le classi ci sono, ma come la card
sta davvero nella pagina — quanto e' alta, dove cade sul telefono, se i
quattro gruppi si distinguono a occhio — non l'ho visto. E' la cosa da
guardare per prima aprendo `/?period=week&view=training`.

**Il caso della settimana fuori dal blocco** l'ho provato coi `null` a mano e
non navigando a una settimana che non ne ha: la pagina non lascia andare oltre
la settimana corrente, e all'indietro il blocco comincia il 26 ottobre.

## Revert

```bash
git revert -m 1 $(git log main --merges --grep="^Merge branch 'todo_87'$" --format=%H -1)
```

Effetti fuori dal repo: nessuno. E' una card in piu' in una vista, quattro
letture e nessuna scrittura. Resta solo la pagina compilata in
`frontend/dist/`, che si rifa' con `make frontend_build` (e il servizio la
serve da li').

Dopo il revert, rifare il merge di `todo_87` non riporta le modifiche (git le
considera gia' unite): per riaverle serve il revert del revert.
