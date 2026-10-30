---
status: todo
---

# La pagina Home: una chat sui propri dati

Per sapere com'e' andata una seduta bisogna sapere **dove guardare**: la Day
per i numeri del giorno, la Week per la forma della settimana, il Trend per
il movimento nel tempo, lo Snap per il testo che l'allenatore ha scritto.
Tutto c'e', ma la porta d'ingresso e' un menu a due assi, e chi ha una
domanda in testa deve prima tradurla in una pagina.

La **Home** ribalta il verso: si chiede «come sono andate le ripetute di
giovedi'?» e la risposta arriva con, sotto, il grafico o la tabella che la
regge.

Il chatbot **non e' una fonte**: orchestra e spiega, ma ogni cifra viene da
un tool e ogni grafico dalla specifica Vega-Lite che l'API gia' serve. E' la
stessa regola del todo 79 — la tabella dei giri la disegna la card, non
l'agente — applicata a una pagina intera: *un modello che genera numeri
plausibili sui propri dati di salute e' esattamente la cosa da non fare*.

## Le tre decisioni gia' prese

- **Legge e agisce, ma ogni scrittura chiede conferma.** Non solo risposte:
  anche rifare una sezione di report, correggere il tipo di una corsa,
  spostare un giorno del piano — le cose fatte a mano il 30 ottobre.
- **La Home diventa la pagina di partenza.** Aprendo l'app senza parametri si
  arriva sulla chat; Day, Week e Plan restano nella barra.
- **Il motore e' l'SDK `anthropic`**, non il CLI `claude` di `refresh.py`.
  Il CLI va benissimo per i report, che nessuno sta a guardare, ma non puo'
  streammare: in una chat sarebbero decine di secondi a schermo fermo.

## Quanto costa, misurato e non stimato

Token contati con `count_tokens` su `claude-opus-5`, sui file veri del 29-30
ottobre. **Il JSON tokenizza a 1,9 caratteri/token**, non ai 3,5 della prosa:
un blocco di fatti costa quasi il doppio di quanto sembra a occhio.

| Blocco | Token |
|---|---|
| Fatti del giorno, interi e indentati (come li scrive `refresh.py`) | 6.866 |
| Gli stessi, compatti (`separators=(",",":")`) | 5.039 |
| Solo `morning` | 1.875 |
| Solo `sessions.today` | 1.933 |
| Report giornaliero, sei sezioni | 958 |
| Report settimanale | 1.378 |
| Piano della settimana | 1.574 |
| Prompt di sistema + 11 tool + domanda | 1.992 |

Con la cache dei prompt attiva e i tool che rendono **fette**: circa **4
centesimi a domanda**, cioe' **4-19 $/mese** fra le tre e le quindici domande
al giorno. Con i JSON interi si va a 7-20 centesimi, fino a 40 $/mese.

**Lo slicing e' percio' un requisito, non un'ottimizzazione**: e' la
differenza fra otto dollari al mese e quaranta.

Si parte con `claude-opus-5` ed `effort` basso o medio. Passare a
`claude-sonnet-5` (3/15 invece di 5/25, circa il 40% in meno) e' una riga in
`chat.py`: da provare dopo averla vista funzionare, non prima.

## Il lavoro, in due parti

**La seconda non si comincia finche' la prima non gira.** La chat che legge
e' utile da sola; i tool che scrivono raddoppiano la superficie di fiducia e
meritano un giro loro — e una decisione sulla tailnet (vedi i Rischi).

### Parte 1 — la chat che legge

#### 1. La dipendenza e la chiave

`anthropic` in `pyproject.toml` (`uv add anthropic`). La chiave si legge
dall'ambiente (`ANTHROPIC_API_KEY`): **mai nel repo, mai in `data.yaml`, mai
nei log**. Se manca, `/api/chat` rende 503 con un messaggio che dice cosa
esportare — il resto dell'API deve continuare a funzionare senza.

> La chiave di oggi e' finita in chiaro in un transcript il 2026-10-30:
> rigenerarla su console.anthropic.com prima di mettere in piedi questo.

#### 2. I tool — `src/training/api/chat_tools.py`

Un tool per ogni domanda che Andrea fa davvero, e ognuno **chiama il codice
che c'e' gia'**, in processo, non l'API via HTTP:

| Tool | Chiama | Note |
|---|---|---|
| `get_day(day, part)` | `daily_data.build_daily_data` | `part`: `all\|morning\|load\|recovery\|fitness\|sessions` |
| `get_week(monday, part)` | `weekly_data.build_weekly_data` | come sopra |
| `get_report(kind, date, section)` | `report_text.parse_report` | il testo gia' scritto dagli agenti |
| `list_activities(start, end, sport)` | `db.list_activities` | una riga per seduta |
| `get_activity(id, with_laps)` | `db` + `laps.session_laps` | i giri del todo 79 |
| `get_plan(day \| monday)` | `api.plans` | |
| `get_trend(measure, start, end, by)` | `daily_data.trend_data` / `week_trend_data` | |
| `show_chart(kind, ...)` | — | rende un **riferimento**, non dati |

Due regole che governano insieme il costo e la correttezza:

- **Fette, non blocchi.** La descrizione del tool dice di preferire la fetta
  piu' stretta che risponde: 1.875 token invece di 6.866.
- **JSON compatto** nei risultati dei tool: un altro 27% via.

`show_chart` non calcola niente: rende `{kind, params}` e la pagina disegna
con i componenti che esistono gia' (`RunChart`, `TrendPanels`). Il modello
sceglie **quale** grafico, mai cosa c'e' dentro.

#### 3. L'endpoint — `src/training/api/chat.py`, `app.py`

`POST /api/chat`, `StreamingResponse` con `media_type="text/event-stream"`.
Dentro, il giro dei tool scritto a mano su `client.messages.stream()`: non il
tool runner, perche' qui ogni evento va riemesso verso il browser e il giro
manuale e' piu' corto da leggere di quello con gli hook.

Eventi SSE, uno per riga: `text` (il delta), `tool` (quale tool e con che
argomenti, per poter scrivere «sto leggendo i fatti del 29»), `chart` (il
riferimento da disegnare), `done`, `error`.

- **Senza stato**: la conversazione sta nel browser e torna intera a ogni
  domanda, come fa gia' tutta l'API.
- **Cache dei prompt**: `cache_control` sull'ultimo tool, cosi' `tools` +
  `system` — che e' l'ordine in cui vengono resi — si cacheano insieme. Il
  prompt di sistema e l'elenco dei tool devono restare **identici byte per
  byte** fra una domanda e l'altra: niente data di oggi, niente nomi, niente
  interpolazioni, o la cache non prende mai.
- `thinking` adattivo con `effort` basso, e `max_tokens` con spazio per
  pensiero **piu'** risposta: su Opus 5 il tetto vale per la somma.

#### 4. Il prompt di sistema

Corto, con tre vincoli:

- ogni cifra viene da un risultato di tool; se non c'e', lo dice invece di
  stimarla;
- i report scritti dagli agenti **si citano**, non si riscrivono — se no la
  stessa domanda ha due risposte diverse, e quella della chat non ha passato
  nessuna revisione;
- i grafici si mostrano con `show_chart`, non si descrivono a parole.

#### 5. La pagina — `frontend/`

- `navigation.ts`: `Page` diventa `"home" | "day" | "week" | "plan"`,
  `VIEWS.home = []`, etichetta `Home`.
  **`pageFromUrl` e' il punto delicato**: la Home diventa la partenza, ma i
  link vecchi devono continuare ad aprire la Day. Regola: niente
  `period`/`page` **ma** c'e' un `?day=` → Day; niente di niente → Home.
- `components/HomePage.tsx`: il filo della conversazione, la casella, lo
  streaming. Il testo passa da `markdown()`; sotto le risposte, le card dei
  `chart`.
- `api/client.ts`: `api.chat(messages, onEvent, signal)` con `fetch` +
  `ReadableStream`. **Non `EventSource`**, che fa solo GET.
- `components/LapTable.tsx`: estratto da `TrainingCard.tsx`, dove dal todo 79
  e' locale, cosi' la chat puo' disegnarlo senza duplicarlo.
- `TopBar.tsx` e `styles.css`: la quarta voce e i riquadri della chat.
- `make frontend_types` dopo il modello nuovo.

### Parte 2 — i tool che scrivono

Tre scritture, scelte perche' sono esattamente le cose fatte a mano il 30
ottobre: `refresh_section`, `set_run_type`, `edit_plan` (scambiare due giorni
o riscrivere la seduta di un giorno).

**Il meccanismo della conferma, che e' il punto:**

1. Il modello chiama il tool. Il server **non lo esegue**: emette un evento
   SSE `confirm` con il nome, gli argomenti e — per `edit_plan` — il diff del
   testo nuovo, e chiude il giro.
2. La pagina mostra il riquadro: «Fallo» / «Lascia stare».
3. Su conferma, il browser rimanda la conversazione con il permesso
   esplicito; **solo allora** il server esegue e rimette il risultato nel
   giro.
4. Su rifiuto torna un `tool_result` che dice che Andrea ha detto di no, e il
   modello prosegue a parole.

Il permesso vale per **quella chiamata**, non per la sessione.

## Quello che non va toccato

- `refresh.py` e gli agenti delle sezioni: i report continuano a scriversi
  come adesso, col CLI e ai loro orari. La chat li **legge**.
- Il modo in cui l'API serve i dati: i tool chiamano le stesse funzioni delle
  rotte. Nessuna logica di calcolo nuova, o si finisce con due verita'.
- `run_chart.py` e i componenti dei grafici: `show_chart` sceglie, non
  disegna.

## Rischi

- **I dati di salute escono dalla macchina.** Oggi ci vanno i fatti del
  giorno, una volta per report, attraverso il CLI. Con la chat ci vanno fette
  a ogni domanda. Non e' un cambio di natura, ma e' un cambio di frequenza: va
  deciso prima, non scoperto dopo.
- **La tailnet, e questo va risolto prima della Parte 2.** L'API ascolta su
  127.0.0.1 senza login, ma il frontend e' esposto sulla tailnet con
  `tailscale serve` (vedi `vite.config.ts`). Finche' si legge e' un conto;
  con `edit_plan` e `refresh_section` chiunque arrivi a quella porta puo'
  riscrivere il piano. Decidere se le scritture restano a 127.0.0.1 o se
  serve un gesto in piu'.
- **Il costo cresce con la conversazione, non con la domanda**: la storia si
  rispedisce intera a ogni giro. Un filo da venti domande costa piu' del
  doppio di quattro fili da cinque. Serve un «ricomincia» ben visibile, e
  ogni risposta porta il suo costo in piccolo, cosi' il conto non arriva a
  sorpresa a fine mese.
- **Due risposte alla stessa domanda**, se il chatbot riderivasse un giudizio
  invece di citare il report. E' un vincolo del prompt, e si verifica.

## Verifica

- **I numeri non si inventano**: una domanda su un giorno di cui il tool non
  e' stato chiamato deve far dire «non ce l'ho», non una cifra. Provato
  apposta.
- **Le cifre combaciano**: chiesto il ritmo delle ripetute del 29 ottobre, la
  risposta dice 5'56" / 6'03" / 6'03" / 5'55", come la tabella dei giri.
- **Il grafico compare** sotto la risposta, nei due temi.
- **Il costo e' quello previsto**: una conversazione da cinque domande, token
  contati con `count_tokens` sul traffico vero, confrontata con la tabella
  qui sopra.
- **I link vecchi reggono**: `?day=2026-10-07` apre ancora la Day,
  `?period=week` la Week, e solo un URL nudo apre la Home.
- **Senza chiave**: `/api/chat` rende 503 e tutte le altre rotte funzionano.
- `npm run typecheck`, `npm run build`, e `make frontend_types` che non muove
  `schema.ts`.
- **Parte 2**: una scrittura rifiutata non tocca niente su disco; una
  accettata scrive, e il file cambia solo dove previsto.
