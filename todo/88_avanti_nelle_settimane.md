---
status: todo
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

## Revert

Il revert del codice basta. Effetti fuori dal repo: nessuno — e' navigazione
e letture. Resta solo la pagina compilata in `frontend/dist/`, che si rifa'
con `make frontend_build`.
