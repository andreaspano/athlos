---
status: done
---

# La batteria al risveglio e' un altro numero

Da dove viene: il todo 99, che su questo si e' fermato. Il report del 23
novembre 2026 diceva «body battery al risveglio molto peggio del solito» su
una mattina in cui la batteria al risveglio era 99 — il massimo della
finestra. Il todo 99 ha dato la colpa al giro delle 08:15 lanciato su una
sincronizzazione parziale, e il giro c'entra, ma la causa prima e' un'altra
e sta in una riga sola:

```python
# interface/daily_data.py
"body_battery_morning": ("body_battery_high", 0),
# interface/health.py
"body_battery_high": _number(_dig(payloads["stats"], "bodyBatteryHighestValue")),
```

**`body_battery_morning` non legge la batteria al risveglio. Legge il
massimo della giornata.** Che e' un numero diverso, e lo e' in due modi.

## I due modi in cui e' diverso

**Di mattina e' un massimo parziale.** Alle 08:15 «il massimo di oggi» e' il
massimo delle due ore passate dal risveglio, e se la notte non e' ancora
salita su Garmin e' il massimo di niente. Alle 21:00 lo stesso campo da' il
valore giusto, perche' da li' in poi la batteria cala e il massimo resta
quello del risveglio. E' un numero che diventa vero col passare delle ore:
per il giro della sera va bene, per quello del mattino no. Questo e' il
pezzo che il todo 99 ha visto.

**E un pisolino lo sposta comunque.** Anche a giornata finita, il massimo
non e' il risveglio se durante il giorno la batteria e' risalita piu' in
alto. Garmin il valore vero ce l'ha e si chiama **`bodyBatteryAtWakeTime`**;
sta nello stesso `stats`, accanto a quello che leggiamo.

Sui dati che abbiamo, il conto e' questo:

| | |
|---|---|
| giorni con tutti e due i campi | 241 |
| in cui coincidono | 194 |
| in cui il massimo e' **piu' alto** del risveglio | 47 |
| in cui il risveglio e' piu' alto del massimo | **0** |
| scarto massimo | 7 punti (8 novembre: risveglio 38, massimo 45) |
| scarto medio | 0.26 punti |

Zero su 241 nell'altro verso, come dev'essere: il valore del risveglio e'
uno dei valori della giornata, quindi il massimo non puo' stargli sotto.
Non e' rumore che si compensa: **e' una misura che sbaglia sempre nello
stesso verso**, e quel verso e' «meglio del vero». Il 23 novembre ha
sbagliato nell'altro solo perche' la giornata non era ancora cominciata.

## Il lavoro

Il campo nuovo non sostituisce quello vecchio: **sono due misure diverse e
servono tutte e due.** Oggi una colonna sola fa due mestieri, e in un posto
e' pure etichettata giusta.

1. **Una colonna nuova**, `body_battery_wake`, da `bodyBatteryAtWakeTime`,
   accanto a `body_battery_high` in `interface/health.py`. Tutti i 6170 file
   di `health/stats/` hanno la chiave.
2. **`body_battery_morning` legge quella** (`interface/daily_data.py`), ed
   e' la misura che finisce nella Recovery del giorno e nei fatti degli
   agenti (`api/ollama.py`, dove si chiama «body battery at wake-up»).
3. **La settimana pure**: `weekly_data.py` ha
   `("recovery", "body_battery_high", "Body battery, wake-up", "", 0)` —
   stessa etichetta sbagliata sullo stesso campo.
4. **`body_battery_high` resta dov'e' etichettato bene**: nello Snap del
   giorno e' «Body battery high» (`daily_data.py`), ed e' giusto — li' il
   massimo della giornata e' proprio quello che si vuole dire.
5. Le fasce si ricalcolano da se': sono 28 giorni della stessa serie, quindi
   si spostano insieme ai valori. Lo scarto medio di 0.26 dice che si
   spostano di pochissimo, e i 47 giorni che cambiano cambiano **dentro**
   una fascia che si e' mossa meno di loro.

## La decisione: da quando

Questa e' la parte da decidere prima di scrivere il codice, perche' cambia
un numero gia' scritto.

La proposta e': **vale per tutti, all'indietro compreso.** Le ragioni:

- non e' un cambio di opinione su una misura, e' una misura che leggeva il
  campo sbagliato. Il valore vecchio non e' «come la pensavamo a ottobre»,
  e' un errore, e lasciarlo per rispetto della storia vuol dire tenere 47
  giorni che dicono una cosa falsa;
- le card gia' scritte **non cambiano**: sono testo su disco. Cambia il
  numero che la pagina mostra accanto, e cambia quello che gli agenti
  leggerebbero riscrivendo. Una Recovery di ottobre che dice «90» accanto a
  una card che mostra 89 e' il prezzo, ed e' un punto;
- lo scarto e' un punto sul 98% dei giorni che si muovono.

L'alternativa e' una data come `LOCAL_FROM`, cioe' campo nuovo da qui in
avanti e vecchio prima. Ha senso solo se il corpus del banco
(`bench/local_text.jsonl`, i 104 testi) va tenuto confrontabile al numero: in
quel caso la data va scelta **dopo** `bench_tune.CORPUS_TO`, non prima.

Chi implementa questo todo segua la proposta, salvo che Andrea abbia
scritto qui il contrario.

## Effetti fuori dal repo

`make rebuild` rifa' `activities.db` dai file che ci sono gia' — niente
rete, niente Garmin — e serve perche' la colonna nuova prima non c'era.
Finche' non lo si lancia, `body_battery_wake` non esiste nel database e la
Recovery del giorno resta senza quella misura.

## Revert

```bash
git revert -m 1 $(git log main --merges --grep="^Merge branch 'todo_100'$" --format=%H -1)
```

Effetti fuori dal repo: **si risistemano da soli, ma non subito.** In
`activities.db` la tabella `health_daily` adesso ha la colonna
`body_battery_wake` ed e' stata ricostruita dai JSON con
`HEALTH_LOGIC_VERSION` a "4". Il revert riporta quel numero a "3", e al
primo `sync_health()` — cioe' alla prima richiesta dell'API o al primo giro
di un report — la versione sul disco non corrisponde piu', la tabella viene
buttata e rifatta con il parsing vecchio. Da quel momento la colonna non
c'e' piu' e i 47 giorni tornano a leggere il massimo del giorno. Nel
frattempo la colonna resta li' e non la guarda nessuno.

Niente di scritto in `summary/`: i testi gia' scritti non cambiano ne' col
merge ne' col revert. Quello che cambia e' il **numero accanto** — nella
Recovery della Day e nella barra "Body battery, wake-up" della Week — e lo
fa in tutte e due le direzioni.

Dopo il revert, rifare il merge di `todo_100` non riporta le modifiche (git
le considera gia' unite): per riaverle serve il revert del revert.
