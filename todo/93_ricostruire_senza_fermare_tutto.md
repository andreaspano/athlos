---
status: done
---

# Ricostruire il database senza fermare tutto

Da dove viene: un code review di `src/training/interface` del 2 novembre
2026 (`/code-review max`), che fra i rilievi tagliati dal limite metteva
`rebuild()` che cancella il database dentro una richiesta e i due `sync` che
possono scrivere lo stesso file; piu' quello che e' costato sistemare due
*altri* rilievi dello stesso review nello stesso giorno, che e' la parte che
ha reso il tema urgente.

Il 2 novembre 2026 due correzioni da poche righe sono costate **37 minuti di
API ferma ciascuna**. Non per il lavoro: per il meccanismo con cui la cache
si rifa'. Questo todo lo sistema, e non aggiunge nessuna funzione alla
pagina.

Il meccanismo di oggi, in tre righe di codice:

- `db.sync()` (riga 638) confronta `LOGIC_VERSION` con quella in
  `schema_meta` e, se non coincide, chiama `rebuild()`;
- `rebuild()` (riga 591) fa `db_path.unlink()` sul **database vivo** e poi
  rilegge tutti i 986 FIT in **una sola transazione**;
- `sync()` lo chiama chi legge, cioe' `list_activities()`, cioe'
  `api/cache.py`, cioe' **qualunque richiesta HTTP**.

Quindi: alzare una versione vuol dire che la prima persona che apre una
pagina — o il primo timer che parte — cancella il database e aspetta mezz'ora
dentro la sua richiesta.

## Che cosa va storto adesso

**Il database si cancella dentro una richiesta.** `unlink` e poi mezz'ora di
ricostruzione: in quella mezz'ora ogni altra richiesta legge un file che non
c'e' o che non e' finito. Il 2 novembre l'ho evitato fermando il servizio a
mano prima, due volte, e la seconda **non l'ho nemmeno scelto**: e' partito
un `pytest` che leggeva l'archivio.

**Una transazione sola per 986 letture.** Il WAL arriva a 70 MB e niente e'
visibile finche' non si chiude. Interrompere butta tutto e si riparte da
zero: non c'e' un "riprende da dove era".

**Due `sync` possono scrivere lo stesso file insieme.** `api/cache.py` ha un
lucchetto **per lettore** — uno per le attivita' e uno per la salute, ed e'
giusto cosi' per il tempo di attesa — ma `sync()` e `sync_health()` scrivono
lo **stesso** `activities.db`. Il docstring di `cache.py` dice che il
lucchetto serve a evitare "due `sync()` sullo stesso database", e fra i due
diversi non lo evita.

**Non c'e' niente fra "niente" e "rileggi tutti i file".** Le due correzioni
del 2 novembre erano:

| Cosa cambiava | Da dove si poteva ricalcolare | Costo pagato |
|---|---|---|
| i minuti per zona (`LOGIC_VERSION` 10) | dai `records` gia' in tabella | 37 minuti |
| la soglia prestata (`LOGIC_VERSION` 11) | dai FIT, per forza | 37 minuti |

Il primo non aveva bisogno di nessun file: `_store_zone_minutes` lavora sui
record che il database ha gia'. Il secondo si': il valore misurato delle
righe contaminate esisteva solo nei file. **Sono due casi diversi e hanno
un solo prezzo.**

E c'e' un terzo caso, che lo stesso giorno ho risolto a mano fuori dal
progetto: il conteggio dei passi di un allenamento (`fit._workout`) cambiava
**9 righe su 986**. Ho riscritto quelle nove con un `UPDATE` scritto nella
sessione, invece di rileggere 986 file per una riga che cambiava davvero.
Quella scorciatoia non deve restare un gesto da ricordare a mano.

## Cosa si fa

### 1. La ricostruzione non sta nel percorso delle richieste

`sync()` smette di chiamare `rebuild()`. Se la versione non coincide, **non
ricostruisce**: lo dice.

Lo dice come lo dice gia' lo scaricamento mancato (`api/refresh.py`, il
campo `download`): un `ok` falso con un messaggio, che la pagina mostra. Chi
legge intanto riceve **i dati che ci sono**, vecchi di una versione, con
scritto che sono vecchi — non un errore e non mezz'ora di attesa.

La ricostruzione diventa un comando: `make rebuild` (oggi non esiste, si
scrive a mano un `python -c`). Il comando ferma il servizio, ricostruisce,
lo riaccende — o meglio: non ha bisogno di fermarlo, per il punto 2.

### 2. Si costruisce a parte e si scambia alla fine

Non si cancella il database vivo. Si costruisce `activities.db.new` accanto,
e alla fine `os.replace`, che e' atomico: chi legge vede il vecchio o il
nuovo, mai un file a meta'. E' la stessa politica che `garmin/files.py`
(`write_text`) applica ai file JSON dal 2 novembre, e lo stesso motivo.

Due conseguenze buone: il servizio puo' restare accesso durante la
ricostruzione, e un'interruzione non lascia niente di rotto — il vecchio e'
ancora li', il nuovo si butta.

### 3. Si commette a pezzi, cosi' si riprende

Un commit ogni N attivita' (cento sono un decimo del lavoro). Serve a due
cose: il WAL non arriva a 70 MB, e un'interruzione lascia un file parziale
**sul lato nuovo**, che al giro dopo si puo' continuare invece di ricominciare
— i FIT gia' letti sono quelli le cui righe ci sono, ed e' lo stesso
ragionamento di `sync()`.

Con il punto 2 questo e' gratis: il file nuovo non lo legge nessuno finche'
non viene scambiato, quindi un commit parziale non si vede.

### 4. Un lucchetto per il file, non per il lettore

I due `_Cached` di `api/cache.py` tengono il loro lucchetto per non
aspettarsi a vicenda **in lettura**, e va bene. Ma la **scrittura** sul
database va serializzata: un lucchetto solo, del file, preso da `sync()` e da
`sync_health()`. Vive dove vivono loro (`interface/`), non nella cache: e' una
proprieta' del database, non del modo in cui l'API lo tiene in memoria.

E il docstring di `cache.py` va corretto: oggi promette una cosa che non fa.

### 5. Due versioni, non una

`LOGIC_VERSION` oggi vuol dire due cose insieme: "il modo di leggere i file
e' cambiato" e "una colonna derivata e' cambiata". Si separano:

- **`LOGIC_VERSION`**: quello che si ricava **dai file**. Cambiarla vuol dire
  rileggerli, e non c'e' scorciatoia.
- **`DERIVED_VERSION`** (nuova): quello che si ricava **da cio' che il
  database ha gia'** — i minuti per zona dai `records`, la soglia prestata
  dalle altre righe. Cambiarla rifa' solo quei conti, e sono secondi.

`sync()` confronta tutte e due. Al secondo caso corrisponde una funzione
che rifa' i conti derivati su tutte le righe — in pratica
`_fill_missing_thresholds` e `_fill_zone_minutes(force=True)`, che esistono
gia' e girano a ogni sync.

Il metro per sapere se e' il momento giusto: delle tre modifiche del 2
novembre, **due su tre** sarebbero costate secondi invece di 37 minuti.

## Quello che non va toccato

- **Il formato della tabella.** Questo todo cambia *quando* e *come* si
  ricostruisce, non cosa c'e' dentro.
- **`list_activities()` e `load_health_db()`**, per chi le chiama: stessa
  firma, stesso risultato. Solo non ricostruiscono piu' da sole.
- **I JSON sotto `json/`** (terreni, tipi, nomi): sono fuori dal database
  apposta, perche' `rebuild()` li perderebbe. Restano dove sono.
- **La politica del temporaneo**: quella di `garmin/files.py`, non una nuova.

## Rischi

- **Servire dati vecchi e' una bugia se non si vede.** Il punto 1 fa leggere
  una cache di una versione precedente: se il messaggio non arriva alla
  pagina, e' lo stesso silenzio sui dati stantii che `api/refresh.py` dice di
  non voler permettere. Il messaggio **e'** la meta' del lavoro, non un
  contorno.
- **Un database a parte vuol dire due volte lo spazio** per il tempo della
  ricostruzione: oggi `activities.db` e' 206 MB, quindi 412 MB di picco. Su
  questa macchina non e' un problema; va detto.
- **I commit a pezzi cambiano il significato di "il database c'e'".** Finche'
  si costruisce, il file nuovo e' incompleto: nessuno lo deve leggere, e
  l'unica garanzia e' che non e' ancora al suo posto. Se qualcuno lo apre per
  curiosita' durante la ricostruzione, vede meta' archivio.
- **Due versioni sono due cose da ricordare.** Alzare quella sbagliata e'
  silenzioso: alzare `DERIVED_VERSION` quando serviva `LOGIC_VERSION` rifa'
  i conti sui dati vecchi e non se ne accorge nessuno. Il commento sopra le
  due costanti deve dire **quale si alza quando**, con esempi.
- **Il primo avvio non ha niente da servire.** Con `sync()` che non
  ricostruisce piu', una installazione nuova resta vuota finche' qualcuno non
  lancia il comando: la pagina deve dirlo, e dire quale comando.

## Come provarlo

- Alzare `DERIVED_VERSION` e misurare: devono essere secondi, e i minuti per
  zona delle 60 sedute con le zone devono tornare identici a prima.
- Alzare `LOGIC_VERSION` con il servizio **accesso** e guardare la pagina
  durante la ricostruzione: deve rispondere, con i dati vecchi e il messaggio.
- Interrompere una ricostruzione a meta' (Ctrl+C) e verificare che il
  database vivo sia intatto e che il giro dopo riprenda invece di ricominciare.
- Lanciare `sync()` e `sync_health()` insieme da due processi e verificare che
  non si pestino: oggi il secondo trova il file sotto le mani del primo.

## Come e' andata

Fatto, tutti e cinque i punti.

**`sync()` non ricostruisce piu'.** Quando `LOGIC_VERSION` non coincide — o
la tabella e' vuota — non fa niente e rende zero: le righe che ci sono
vengono da un altro codice, e aggiungerne di nuove mescolerebbe i due. La
ricostruzione e' `make rebuild`.

**Il motivo arriva alla pagina**, sul campo `cache` di `GET /api/refresh`:
`ok` falso e il messaggio col comando da lanciare, come il campo `download`
dice uno scaricamento mancato. Le due cose viaggiano insieme perche' tutte e
due le pagine interrogano gia' quella rotta e sanno gia' mostrare un `ok`
falso. Il banner e' `CacheWarning`, e **non passa dalla guardia sul tipo**:
la cache e' una sola per la Day e per la Week.

**Si costruisce accanto e si scambia.** Il lavoro va in `activities.db.new`,
e alla fine un `os.replace` lo mette al posto del vecchio. Un commit ogni
`REBUILD_BATCH` (cento) attivita', e un file accanto rimasto a meta' si
riprende invece di ricominciare.

**Un lucchetto del file, fra processi.** `write_lock()` e' un `flock` come
quello dei lavori (`api/refresh._claim`), e lo prendono `db.sync()` e
`health_db.sync_health()`: i thread dell'API e un comando lanciato da un
terminale sono processi diversi, e un lucchetto di soli thread non li
avrebbe visti. `rebuild()` lo prende **solo per lo scambio**, non per la
mezz'ora di letture.

**Due versioni.** `LOGIC_VERSION` per quello che viene dai file,
`DERIVED_VERSION` per quello che si ricava dalle righe. `refresh_derived()`
rifa' soglie prestate e minuti per zona in **0.2 secondi su 986 attivita'**,
contro i 37 minuti di una ricostruzione: delle tre correzioni del 2
novembre, due sarebbero state secondi.

Due cose trovate per strada.

**Il messaggio non arrivava.** La prima stesura teneva il motivo in un
dizionario di modulo, scritto da `sync()`. Ma `api/cache.py` tiene il frame
in memoria per un minuto e serve senza passare da `sync()`: con la versione
storta la pagina non diceva niente. Adesso `cache_state()` guarda la tabella
ogni volta — costa una `SELECT`.

**Un giro derivato deve sapere togliere.** `_store_zone_minutes` non scrive
mai un NULL, quindi un valore che non si puo' piu' calcolare — perche' la
soglia che lo rendeva possibile non c'e' piu' — restava in tabella per
sempre. `refresh_derived()` azzera prima di rifare, ed e' idempotente: due
giri di fila danno la stessa tabella.

### Verificato

- **Versione storta col servizio accesso**: `/api/refresh` rende
  `cache: {ok: false, message: "la cache e' alla versione 10 e il codice
  vuole la 11... make rebuild"}`, e nello stesso momento `/api/activities`
  rende le sue cinque attivita' e `/api/daily/2026-11-02` la readiness 68.
  Risponde, con i dati vecchi e il messaggio.
- **Un giro derivato**: 0.2 s su 986 attivita', due volte di fila con lo
  stesso risultato (39 sedute coi minuti per zona, 28 con soglia prestata).
- **Interruzione a meta'**: il database vivo resta della stessa dimensione e
  si legge ancora; il file accanto resta e il giro dopo dice "riprendo" e
  finisce il lavoro. Due test, con FIT veri in una cartella temporanea.
- **Due processi**: uno tiene `write_lock` per 2,5 s, l'altro entra dopo
  1,9 s invece di scrivere insieme.
- 240 test (`make test`), `tsc` e `vite build` puliti, `schema.ts`
  rigenerato e stabile (due rigenerazioni, stessa impronta), i sei endpoint
  principali a 200 dal servizio vero.

### Quello che non ho provato

**Una ricostruzione intera dell'archivio** (986 FIT, mezz'ora): lo scambio e
il riprendere sono provati su una cartella temporanea con FIT veri, che e' lo
stesso codice e lo stesso `os.replace`, ma il giro completo lo fara' il primo
`make rebuild` vero.

**Lo schermo**: il banner l'ho provato per contenuto e tipi, non guardando
come sta sopra le card.

## Revert

```bash
git revert -m 1 $(git log main --merges \
  --grep="^Merge branch 'todo_93'$" --format=%H -1)
```

Effetti fuori dal repo: in `activities.db` resta la riga `derived_version`
di `schema_meta` — innocua, il codice vecchio non la legge — e accanto al
database resta `db/.activities.lock`, un file vuoto che nessuno apre piu'.
Nessun dato delle attivita' e' cambiato: questo todo tocca **quando** e
**come** si ricostruisce, non cosa c'e' in tabella.

Dopo il revert, rifare il merge di `todo_93` non riporta le modifiche (git le
considera gia' unite): per riaverle serve il revert del revert.
