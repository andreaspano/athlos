---
status: todo
---

# L'importazione da MyWhoosh

Da dove viene: l'11 novembre 2026, dalla cartella `fit/mywhoosh/` comparsa a
mano. Dentro c'erano due pedalate al rullo — l'8 novembre e quella del
pomeriggio — scaricate dal portale e copiate li'. L'archivio adesso le legge
(lo scandaglio di `fit/` e' ricorsivo), ma il passo che manca e' quello
davanti: **chi le scarica**.

Oggi sono Andrea e il browser. Una pedalata al rullo e' un allenamento come
gli altri, e nessun altro allenamento si scarica a mano: le corse arrivano con
`make update_activity`, le pesate con `make update_weight` (todo 97). Questo
todo chiude il buco.

---

## 1. Cosa fa, in una riga

`make update_rides` chiede a MyWhoosh le pedalate che non abbiamo, scarica i
FIT in `fit/mywhoosh/` e lascia che l'archivio li legga come ha imparato a
fare. Nient'altro: **il FIT e' il dato**, e di convertirlo, interpretarlo o
arricchirlo se ne occupa `interface/fit.py`, che lo fa gia' per
novecentonovanta file.

## 2. La strada: l'API che usa l'app

Quattro erano sul tavolo.

1. **L'API privata di MyWhoosh.** E' la scelta. Login con email e password,
   token Bearer, elenco delle attivita', download del FIT originale. Nessun
   browser, nessun terzo in mezzo, e si incastra con il resto come
   `renpho/sync.py`: una sorgente con la sua cartella e il suo comando.
2. **MyWhoosh → Strava → Garmin, e noi leggiamo da Garmin.** MyWhoosh carica
   **solo** su Strava (non su Garmin), e Strava e Garmin si sincronizzano nei
   due versi: la catena funziona e non costa codice. Ma sono due terzi in
   mezzo, vuole un account Strava che oggi non c'e', e soprattutto **la
   pedalata arriverebbe con un id di Garmin**, cioe' come se l'avesse
   registrata l'orologio. Resta la riserva se l'API privata smette.
3. **La cache locale dell'app.** I FIT li scrive anche il gioco, sul computer
   dove si pedala. Chi monta un uploader "set and forget" parte da li'. Qui
   non serve: MyWhoosh non ha un client Linux, quindi quella cartella sta su
   un'altra macchina e servirebbe un travaso in mezzo — che e' esattamente il
   passo a mano che si vuole togliere.
4. **Il browser automatizzato** (Playwright, sessione salvata). Funziona
   quando l'API cambia, ma e' un browser intero da tenere in piedi per
   scaricare due file a settimana. No.

**Niente libreria da mettere fra le dipendenze**, a differenza del todo 97:
per Renpho c'era `renpho-py`, mantenuta e su PyPI; qui i progetti Python sono
applicazioni (uploader verso Garmin), non librerie. Il riferimento piu' preciso
e' una CLI in Go, `voydz/mywhoosh-cli`, che fa esattamente i tre passi che
servono — login, elenco, download del FIT originale — e dichiara quello che
serve sapere: *MyWhoosh non ha un'API pubblica; questi sono endpoint privati e
possono cambiare senza preavviso*. Si scrive un modulo nostro, piccolo, e si
prende da li' la forma delle chiamate.

### Quello che si sa degli endpoint

Dalla documentazione della comunita' (`mywhoosh-community/mywhoosh-api`):

| | |
|---|---|
| base | `https://services.mywhoosh.com` |
| login | `POST /http-service/api/login` |
| corpo | `{Username, Password, Platform: "Android", Action: 1001, CorrelationId: <uuid>, DeviceId: <id>}` |
| risposta | `AccessToken` (JWT), `RefreshToken`, `WhooshId` |
| poi | `Authorization: Bearer <AccessToken>` su tutto |

**L'elenco delle attivita' finite e il download del FIT non sono in quella
documentazione** — li' ci sono gli allenamenti, non le pedalate fatte — e sono
il pezzo da cavare dalla CLI in Go, che lista con `--page`/`--limit` e scarica
i byte originali. **Questo e' il rischio del todo**, e il primo passo e' una
prova: login, elenco, un file sul disco. Prima di quella non si scrive niente
intorno.

Altre due cose da verificare nella stessa prova:

- il **`.dms`**: piu' di un progetto dice di convertire `.dms` in `.fit`. I
  due file che abbiamo sono `.fit` buoni (li legge `fitparse` e sono in
  archivio), ma sono stati scaricati dal portale: se l'API rende `.dms`, va
  capito se e' un FIT col nome cambiato o qualcosa da aprire;
- la **durata del token** e se il `RefreshToken` serve: se scade in un'ora,
  un comando che gira una volta al giorno rifa' il login ogni volta e basta.

## 3. Dove finiscono i file, e con che nome

In `fit/mywhoosh/`, dove sono adesso. Il nome **cambia**: oggi i file si
chiamano come il gettone con cui li hai scaricati
(`HrnAYPiyUCixCFtArgblQVxFNFFaZFkFgetcl71x.fit`), che e' un nome di quel
download e non di quella pedalata.

Il nome diventa **l'istante di partenza**: `2026-11-11T170744.fit`. Tre
ragioni, e la seconda e' quella che conta:

1. si legge. Diciotto pedalate in una cartella si guardano in ordine;
2. **e' la chiave del "ce l'abbiamo gia'"**. L'id di un FIT senza id nel nome
   lo fa `fit._manual_activity_id`, che e' `10**12 + epoch della partenza`:
   lo stesso numero da cui viene il nome. Quindi sapere se una pedalata e' gia'
   sul disco **non richiede di aprire niente e nemmeno di interrogare il
   database** — basta guardare se il file c'e';
3. non cambia fra due giri. Un gettone si'.

I due file che ci sono si rinominano, una volta. Rinominare non raddoppia la
seduta: l'id nasce dall'istante di partenza, la riga si aggiorna col percorso
nuovo, ed e' lo stesso meccanismo provato spostandoli in `fit/mywhoosh/`
(`tests/test_manual_fit.py`).

## 4. Cosa si scarica, e cosa no

**Le pedalate che non sono sul disco**, guardando una finestra breve — le
ultime due o tre settimane — e non tutto lo storico a ogni giro. Chi vuole il
passato lancia un comando con una finestra piu' larga, come fa
`make backfill_health`.

Una pedalata **in corso** non si scarica: capita di aprire la pagina mentre si
pedala, e un FIT a meta' in archivio e' una seduta sbagliata, non una seduta
incompleta. Si guarda che sia finita (lo dice l'elenco) e nel dubbio si
aspetta il giro dopo.

Un file che l'API da' rotto si scarta **senza scriverlo**: `fit/` e' la fonte
di tutto, e un FIT troncato la' dentro e' peggio di un FIT che manca. Il
controllo e' leggerlo con `load_activity_summary` dentro un temporaneo e
spostarlo solo se risponde — la stessa regola di `files.write_json`.

## 5. Le credenziali, e il comando

`mywhoosh_usr` e `mywhoosh_pwd` in `user/config.yaml`, **facoltative e in
coppia**, dentro `_OPTIONAL` e `_TOGETHER` come quelle della bilancia (todo
97). Chi non pedala al rullo non le scrive e non cambia niente.

`make update_rides` a mano. E dentro `make update_activity`, con il `-`
davanti: se MyWhoosh e' giu', il report del mattino non diventa rosso per una
pedalata. Lo stesso trattamento della bilancia, e per lo stesso motivo.

Il momento giusto e' **prima** dello scandaglio di `fit/`: un file scaricato
adesso e letto al giro dopo vuol dire che la pedalata di stasera compare
domani. `update_activity` scarica da Garmin e poi `sync()` legge la cartella;
qui basta infilarsi prima, e la seduta e' in pagina nello stesso giro.

## 6. E a Garmin? No, e va spiegato

Tutti i progetti che si trovano in giro fanno il contrario di noi: scaricano
da MyWhoosh **per caricare su Garmin Connect**, travestendo il file da Edge
840. Il senso c'e' — Garmin vedrebbe il lavoro e lo conterebbe nel carico, nel
body battery, nello stato di allenamento.

Qui no, almeno per ora, e la ragione e' un conto che non torna: se la pedalata
va anche su Garmin, al giro dopo `make update_activity` la **riscarica** come
attivita' di Garmin, con l'id di Garmin. L'archivio si ritroverebbe due righe
per la stessa ora — una con l'id manuale (`10**12 + epoch`) e una con quello di
Connect — e due righe sono due sedute in ogni somma: carico, chilometri,
tempo per zona.

Si potrebbe risolvere (riconoscere il doppione sull'ora di partenza, e tenere
una delle due), ma e' un lavoro suo e va deciso a parte: **o il FIT sta qui, o
sta su Garmin.** Per adesso sta qui, dove nessuno lo conta due volte. Se un
giorno si vuole che Garmin faccia i suoi conti sul rullo, quello e' il todo da
scrivere, e comincia dalla deduplicazione.

## 7. Fuori da questo todo

- **i chilometri virtuali.** MyWhoosh arriva come `cycling` /
  `virtual_activity`, e i suoi chilometri li calcola il simulatore dalla
  potenza: il progetto li tratta come ciclismo su strada, mentre il tapis
  roulant e' uno sport a se' e resta fuori da ogni somma di distanza (todo 45).
  La domanda e' la stessa — un chilometro che nessuno ha misurato vale in una
  somma? — e l'11 novembre 2026 la risposta e' stata «per adesso lasciamo
  cosi'». Resta aperta, e non la apre questo todo;
- **la potenza.** Il rullo misura i watt, che per il ciclismo sono il dato
  centrale, e nell'archivio non c'e' una colonna per loro. E' un lavoro
  diverso — riguarda lo schema e le pagine, non l'importazione — e il FIT li
  porta dentro comunque, quindi quando quella colonna arrivera' lo storico
  sara' li' da rileggere.

## 8. Come si prova

- la prova del campo prima di tutto, in sola lettura: login, elenco, un file;
- i test del modulo con l'API finta (`monkeypatch`), sulle decisioni che sono
  nostre e non di MyWhoosh: quale pedalata si scarica e quale si salta, il
  nome che prende il file, il temporaneo che non diventa un FIT rotto in
  `fit/`, e il «senza credenziali non e' un errore»;
- un giro vero con le due pedalate che ci sono: devono restare **due**, non
  diventare quattro.
