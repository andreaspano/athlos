---
status: done
---

# Avanti nelle settimane, fin dove arriva il piano

La pagina Week **non va avanti**. La freccia `›` e' spenta sulla settimana
corrente, la fila dei sei riquadri a destra (`WeekPicker`) finisce su di lei
— oggi W39..W44 — e un `?monday=` nel futuro viene riportato indietro.
Guardare la settimana che viene non si puo' fare: si guarda il passato, e del
futuro non c'e' niente.

Ma adesso il futuro **e' scritto**: dal todo 86 in `summary/05.plan/` ci sono
diciassette settimane fino alla gara, e ognuna dice le sue sette sedute. La
cosa naturale e' andarle a vedere dove si guardano le settimane — W45, W46,
W47, W48 — con la freccia, **una settimana per volta**, e in ogni settimana
il suo piano.

**Questo sostituisce il todo 87.** Li' avevo messo in fondo alla Training una
card con le quattro settimane che vengono, tutte insieme: risponde alla
stessa domanda nel posto sbagliato e in una forma che nessuno ha chiesto —
ventotto righe in fondo a una vista che era gia' lunga, e una pagina che non
sa comunque andare avanti. La card va via, e la risposta diventa la
navigazione. Il lavoro che resta buono e' `PlanDayRow`, la riga di un giorno
estratta: la usa ancora la colonna del piano.

## Cosa si fa

### 1. Il confine: fin dove arriva il piano — `GET /api/weekly/planned`

Andare avanti **senza limite** non ha senso: oltre il piano non c'e' niente
da vedere, e una freccia che si accende su settimane vuote fino al 2030 e'
una freccia che mente. Il confine e' **l'ultima settimana che ha un file**.

Lo dice una rotta nuova e piccola: i lunedi' di `summary/05.plan/` che hanno
un file, in ordine. La cartella la si gira gia' in `weeks_following`
(`plans.py`), quindi e' la stessa `glob` con dentro un altro conto; la
cartella `.staging/` e il cestino non si vedono, che `glob("*.md")` non scende.

La pagina ne tiene il **massimo** e lo chiama confine. Nessun piano vuol dire
nessun avanti: la pagina torna a fermarsi sulla settimana corrente, che e'
giusto — non c'e' niente da mostrare.

**Non si ricava dal blocco** (`block_start + block_weeks` di `/api/plans`):
quello e' quello che il goal **dichiara**, e il todo 86 ha mostrato che le
due cose divergono — si cambia goal e le settimane restano quelle di prima.
Il confine e' dei file che esistono, non delle intenzioni.

### 2. I cinque punti che fermano l'avanti

Sono tutti e cinque da allargare dalla settimana corrente al confine:

| Dove | Cosa fa oggi |
|---|---|
| `mondayFromUrl` (`WeekPage.tsx`) | un `?monday=` futuro torna alla settimana corrente |
| `changeWeek` | rifiuta `next > currentMonday` |
| il tasto `›` | `disabled={monday >= currentMonday}` |
| `WeekPicker.weeksAround` | la fila finisce alla settimana corrente |
| `WeekCalendar.weekList` | elenca solo settimane passate |

Il tasto `›|` resta **"questa settimana"** e non diventa "l'ultima": serve a
tornare a casa, e da una settimana di gennaio la casa e' oggi.

La fila dei sei riquadri tiene la sua regola — finisce due settimane dopo
quella guardata, col tetto spostato dalla corrente al confine — cosi'
camminando avanti con la freccia la striscia scorre e W45..W48 compaiono
senza che la regola cambi. La settimana corrente resta marcata com'e' ora
(`today`), e il piu' in la' non ha nessun segno: una settimana futura si
riconosce perche' e' dopo quella marcata.

### 3. Una settimana che non e' cominciata non si chiede all'API

Qui c'e' il guasto vero, e non e' nei bottoni. `api.weekly(monday)` si chiama
**per ogni** settimana, e per una futura l'API risponde **422** (`_check_week`:
*the week of ... has not started*). Quella `catch` finisce in `setError(API_DOWN)`:
oggi, se la navigazione si aprisse e basta, chi va su W45 si vedrebbe
l'avviso che l'API e' giu'. Non e' giu': la domanda e' senza senso, e a non
farla deve essere la pagina.

Quindi su una settimana futura la pagina **non chiede**: ne' i fatti
(`api.weekly`), ne' il report (404, non c'e'), ne' le attivita' (zero per
forza). Chiede **il piano**, che e' l'unica cosa che esiste.

E dice che cosa sta guardando, perche' una vista piena di trattini e'
indistinguibile da un guasto:

- **Training**: la colonna del piano come sempre; quella delle sedute dice
  *The week has not started* invece di *No sessions this week* — che e' la
  frase di una settimana passata in cui non si e' fatto niente, cioe' un'altra
  cosa. Il commento non c'e': nessun agente lo ha scritto e nessuno lo
  scrivera' prima del tempo.
- **Snap**: una riga che lo dice, e niente card. I numeri di una settimana
  che non e' cominciata non sono zero, non esistono.
- **Trend**: la finestra resta quella delle settimane **misurate** e non
  scorre nel futuro: una carta di controllo con dei punti che non ci sono non
  e' un grafico vuoto, e' un grafico sbagliato.
- **Plan**: funziona gia' e non cambia. E' la vista che per una settimana
  futura ha piu' senso di tutte.

### 4. Il tasto che riscrive la settimana sparisce

Sull'intestazione di una settimana futura non ci va: `POST .../refresh`
risponde **422** per scelta, ed e' la stessa regola del backfill (todo 56) —
chiudere un periodo che deve ancora succedere vuol dire giudicarlo prima del
tempo. Un tasto che c'e' e risponde 422 e' peggio di un tasto che non c'e'.

### 5. Via la card del todo 87

`WeeksAhead.tsx` si cancella, insieme al suo stato e al suo effetto in
`WeekPage.tsx` e alle sue regole di stile. Resta `PlanDayRow` in
`WeekPlanCard.tsx`, che adesso ha un utente solo ma e' il pezzo giusto da
avere separato — ed e' quello che la colonna del piano usa.

## Quello che non va toccato

- **`_check_week` e il 422.** L'API ha ragione: i fatti di una settimana che
  non e' cominciata non ci sono. A cambiare e' chi chiede, non chi risponde.
- **Il passato.** Niente di quello che si vede su una settimana finita
  cambia: le frecce indietro, la fila, il calendario, le card, il tasto.
- **La vista Plan** (todo 60) e la colonna del piano (todo 71, 75): sono
  gia' quello che serve, e sono il motivo per cui questo todo e' piccolo.
- **I file di `summary/05.plan/`**: si leggono. Chi li scrive e' il todo 86.

## Rischi

- **Una pagina che si apre su un futuro vuoto.** Se un giorno i piani non
  ci sono (blocco finito, cartella svuotata), la freccia si spegne di nuovo e
  la Week torna quella di oggi. E' il comportamento giusto, ma e' anche un
  modo di sparire senza dirlo: chi si ricorda di aver navigato avanti la
  settimana prima non capisce perche' adesso non si puo'.
- **Quattro viste, due mondi.** Da questo todo ogni vista ha due stati — la
  settimana misurata e la settimana prevista — e sono quattro posti in cui
  qualcuno potra' dimenticarsi del secondo. La prossima card che si aggiunge
  nasce con un trattino da riempire.
- **Il piano non e' un consuntivo, e la pagina si somiglia.** Guardare W47
  nella stessa cornice di W44 invita a leggere il previsto come se fosse
  successo. La riga che dice *not started* e' tutto quello che tiene separate
  le due cose.
- **Il confine e' una `glob` su una cartella.** Un file di troppo — una
  settimana scritta a mano fuori dal blocco, una copia con un nome da lunedi'
  — allunga la navigazione fin la'. Non fa danno, ma il confine e' quello che
  i file dicono, non quello che il piano dice.

## Come e' andata

Fatto. La pagina Week va avanti fino al **2027-02-22**, la settimana di gara,
e su una settimana prevista mostra il suo piano.

Tre cose decise strada facendo.

**Il confine sta in `/api/weekly/planned`, dichiarata prima di
`/api/weekly/{monday}`.** Senza quell'ordine il percorso `planned` si legge
come una data e l'API risponde 422. C'era gia' il precedente di
`/api/weekly/trend`, quindi e' la riga al posto giusto e non un trucco.

**Il lunedi' si legge dal nome del file** e non dal front matter: se il file
c'e', la settimana si puo' guardare, anche se il suo YAML e' rotto. I nomi
che non sono una data si saltano, che in quella cartella c'e' anche il README.

**`mondayFromUrl` non riporta piu' indietro, e il rimedio arriva dopo.** Il
confine lo sa l'API, cioe' un istante dopo l'apertura: la pagina parte dal
lunedi' dell'indirizzo qualunque sia, e quando il confine arriva, se e'
oltre, torna a questa settimana riscrivendo l'indirizzo **senza** lasciare
una voce nella cronologia. L'alternativa — tenere il clamp e allargarlo poi —
avrebbe fatto lampeggiare la settimana sbagliata.

### Verificato

Questa volta **la pagina intera in un DOM**, non solo il markup di un
componente: l'app impacchettata in formato classico (rolldown con il CSS
neutralizzato, che jsdom non esegue i moduli ES) e messa in jsdom contro
l'API accesa. Un buco di jsdom tappato a mano: `Element.scrollTo`, che la
fila delle settimane usa per portarsi in vista.

| Caso | Cosa esce |
|---|---|
| ora, Training | `W39 W40 W41 W42 W43 W44`, tasto riscrivi **c'e'**, commento + due colonne, 7 righe di piano |
| W46, Training | `W43 W44 W45 W46 W47 W48`, tasto riscrivi **via**, nessun commento, 7 righe di piano (`Mon 9 Nov · Rest · or Cycling`), *The week has not started* |
| W46, Snap | solo la riga *has not started: nothing is measured yet* |
| W46, Plan | la card del documento, come sempre |
| W46, Trend | i cinque pannelli, fermi sulle settimane misurate |
| `monday=2027-02-22` (ultima pianificata) | freccia avanti **spenta**, il suo piano |
| `monday=2027-04-05` (oltre il piano) | torna a `2026-10-26`, indirizzo riscritto |
| `monday=2026-11-11` (un mercoledi') | riportato al suo lunedi', W46 |

**Nessun errore in console in nessuno dei casi, e nessun avviso di API
giu'** — che era il guasto da evitare.

Poi: `GET /api/weekly/planned` rende i 19 lunedi' dal `2026-09-28` al
`2027-02-22`, e `/api/weekly/2026-10-26` e `/api/weekly/2026-10-26/plan`
rispondono ancora 200 (la rotta nuova non ruba il percorso). `import training`
e `training.api.app` ok, `npm run typecheck` pulito, `npm run build` ok, tipi
rigenerati dall'OpenAPI, servizio riavviato.

### Quello che non ho provato

**Lo schermo.** jsdom non ha un motore di stile: che il tutto stia bene in
una pagina — e come ci stia sul telefono — non l'ho visto. E **i clic**: ho
aperto gli indirizzi direttamente, non ho premuto la freccia quattro volte di
fila.

## Revert

```bash
git revert -m 1 $(git log main --merges --grep="^Merge branch 'todo_88'$" --format=%H -1)
```

Effetti fuori dal repo: nessuno — navigazione e letture. Resta solo la pagina
compilata in `frontend/dist/`, che si rifa' con `make frontend_build`.

Attenzione a **cosa riporta indietro** il revert: anche la rimozione della
card del todo 87, che tornerebbe in fondo alla Training.

Dopo il revert, rifare il merge di `todo_88` non riporta le modifiche (git le
considera gia' unite): per riaverle serve il revert del revert.
