---
status: todo
---

# Una sezione sola, i dati di tutti

Da dove viene: il report del **23 novembre 2026**, che sulla stessa mattina
diceva «body battery al risveglio molto peggio del solito» e «frequenza
cardiaca a riposo molto sopra la sua banda», e chiudeva con *keep it easy*,
mentre i dati di quella mattina erano i migliori delle due settimane prima —
46 di riposo, la piu' bassa in dodici giorni, body battery a 99 dopo averne
caricati 73 nella notte, readiness 71 con il tempo di recupero a un minuto.
Il piano della settimana e' stato riscritto quel giorno **contro** il testo
del report, non grazie a lui.

Il guasto non e' nei numeri e non e' nel modello. E' nel giro: **un refresh di
una sezione sola riscarica i dati di tutti e riscrive il testo di uno.**

## Cosa e' successo quel giorno

Lo stato in memoria dell'API (`GET /api/refresh`) lo teneva ancora:

```
day: 2026-11-23   moment: morning
started 09:21:09  finished 09:21:34   download: ok
sections.health:  09:21:19 -> 09:21:34   "written by llama3.1:8b"
sections.load / recovery / fitness / training / summary:  2026-11-21 12:24
```

1. **08:16** — il giro del timer del mattino scrive le cinque sezioni del
   corpo (`load.md` 08:16:25, `recovery.md` 08:16:34, `health.md` e
   `fitness.md` 08:16:44, `summary.md` 08:16:52), su una sincronizzazione
   Garmin che della giornata non aveva ancora niente di fermo. Lo dice il
   file di quel giorno stesso: l'evento body battery delle 07:34 e'
   `feedbackLongType: EARLY_MORNING_NO_DATA`, ventisei minuti prima del giro.
   Il sonno di quel giro risulta «non misurato»; rifatto a freddo e' otto ore
   e nove minuti.
2. **09:21** — un refresh della sola Health
   (`POST /api/reports/daily/{day}/refresh/health`, il tasto della card).
   **Riscarica tutto** — `health/stats/`, `training_readiness/` e
   `resting_heart_rate/` del 23 novembre hanno tutti mtime 09:21:11-14 — e
   poi riscrive **solo** `health.md` (09:21:34).

Da li' in avanti nella cartella del giorno c'erano due verita': `health.md`
parlava dei dati delle 09:21 e aveva ragione, le altre quattro parlavano di
quelli delle 08:16. La peggiore e' il Summary, perche' il suo unico ingresso
sono i frammenti degli altri: ha letto una Health che un'ora dopo e' stata
buttata, e ha continuato a citarla.

I numeri, ricostruiti sui dati fermi:

| misura | valore | banda | lettura | cosa diceva il frammento |
|---|---|---|---|---|
| `body_battery_morning` | 99.0 | 62.6-96.5 | **sopra** | «far below its band» |
| `resting_hr` | 46.0 | 47.2-51.4 | sotto, cioe' bene | `health.md` giusto, `summary.md` «far above its range» |
| `body_battery_low_yesterday` | 10.0 | min 12.2 | sotto | «below its band», giusto |

Le due sbagliate sono le due che alle 08:16 stavano ancora arrivando. Quella
che era gia' ferma e' uscita giusta. Non c'e' una banda invertita da nessuna
parte: c'e' un giro lanciato troppo presto e un frammento mai rifatto.

**Perche' adesso.** `sections.LOCAL_FROM` e' il 21 novembre: le quattro card
del corpo le scrive il modello di casa da tre giorni. Il Summary e' il solo
che le vede tutte e quattro ed e' il solo che potrebbe accorgersi di una card
sbagliata — ed e' esattamente quello che non rigira quando una card viene
corretta.

Quello che **non** si puo' dimostrare: il file dei fatti vive in una cartella
temporanea (`refresh.py:306`) e la `health.md` delle 08:16 e' stata
sovrascritta, quindi non si sa se il Summary abbia girato male un frammento
giusto o riportato bene un frammento sbagliato. I tre pezzi qui sotto
servono in entrambi i casi; la differenza la misura il banco, non questo
todo.

---

## 1. Chi legge i frammenti rigira con chi li scrive

`start()` filtra `kind.run_order` sulle chiavi chieste
(`refresh.py:181`), e `summary` e' dichiarato `reads_fragments=True`
(`sections.py:66`). Chiedere una sezione sola gli cambia tutto l'ingresso
sotto i piedi e non lo rifa'.

Il pezzo da cambiare e' `section_keys()` (`refresh.py:694`), o `start()`
subito dopo: **quando fra le chiavi chieste c'e' una sezione che non e' un
verdetto, aggiungere i verdetti di quel `kind`.** L'invariante di `_ordered`
— i verdetti in coda, con l'assert che lo tiene — li mette gia' al posto
giusto nel giro, quindi non serve altro ordine.

Vale per il giorno e per la settimana, che le chiavi sono le stesse.

Attenzione a non allargare oltre: `training` **non** legge i frammenti
(`reads_fragments=False`), scrive un verdetto suo e in un giro del mattino
non c'entra. Chi chiede `health` deve ritrovarsi `health` + `summary`, non
la seduta riscritta.

C'e' una simmetria da notare, perche' meta' del lavoro e' gia' fatta.
`TestSummaryGate` (`tests/test_refresh.py:221`) guarda **la forma per
fallimento** dello stesso pericolo, e il suo docstring lo dice meglio di
qui: «se in questo giro qualcuno e' fallito, dei suoi leggerebbe il testo
del giro prima». La forma per giro parziale e' lo stesso pericolo e non la
guarda nessuno. Il test nuovo sta accanto a quello: chiesta una sezione
sola, nel giro ci finisce anche il Summary.

## 2. `health_data_up_to` lo legge qualcuno

Si calcola in `daily_data.py:992`, e' dichiarato in `models.py:779`, e
**non lo legge nessuno** — nessuna sezione, nessun prompt di agente. Il
timer delle otto su una giornata Garmin non ancora ferma e' il caso per cui
era stato messo.

Due strade, e vanno decise insieme perche' la seconda rende la prima quasi
inutile:

- **Dirlo agli agenti.** Il campo entra nei fatti e il prompt dice che di
  quello che viene dopo quella data si scrive «non misurato», come si fa
  oggi per il sonno mancante. Funziona, ma lascia scritto un report che del
  mattino non dice niente.
- **Non scrivere un report su una giornata non ferma.** Il giro del mattino
  controlla la completezza e, se manca, riprova piu' tardi invece di
  scrivere un numero sicuro su una sincronizzazione parziale. E' la strada
  giusta: il valore del report del mattino e' che sia **del mattino**, e un
  «non misurato» su tre misure su cinque non e' un report.

In mezzo c'e' la domanda vera, che e' l'ora del timer: le otto erano
un'ipotesi e il 23 novembre dice che sono presto. Spostarlo non e' una
correzione, e' una misura da fare — per qualche giorno, a che ora
`health_data_up_to` arriva a oggi.

## 3. Ogni frammento dice da quali dati e' stato scritto

Oggi un frammento non porta traccia dei dati su cui e' stato scritto, e
l'incoerenza del 23 novembre si vede solo confrontando gli mtime dei
frammenti con quelli dei file sotto `health/`. A schermo non si vede
affatto: la pagina mostra cinque card e non sa dire che una e' di un'ora
dopo le altre.

Due righe di front matter in ogni frammento — i dati fino a quando, scritto
quando — e la pagina puo' dire quello che adesso non puo': **questo Summary
e' piu' vecchio delle card che riassume.** Che e' anche la rete sotto il
pezzo 1, per il giorno in cui il giro parziale lo lancia qualcosa che non
passa da `section_keys()`.
