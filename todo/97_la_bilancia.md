---
status: done
---

# La bilancia

Da dove viene: una conversazione dell'11 novembre 2026, partita da «come
possiamo portare qui i dati della mia bilancia Renpho». La bilancia e' una a
otto elettrodi, di quelle che misurano **per segmento**, e l'app e' *Renpho
Health*.

Oggi del corpo il progetto non sa niente: in `health/` ci sono sonno, stress,
hrv, spo2, respirazione, battito a riposo, readiness, status, endurance e hill
score — nessun peso. L'unico numero in giro e' `weight_kg: 100.0` in
`user/profile.yaml`, copiato da Garmin a settembre e fermo da allora, e su
Garmin Connect ci sono **due** pesate a mano (25 agosto e 5 ottobre), entrambe
100.0 tondi. La bilancia dice 102.6.

Questo todo porta le misure della bilancia dentro i dati, le mostra in una
card della Day, e le rimanda a Garmin perche' l'orologio smetta di contare le
calorie su un peso di due mesi fa.

---

## 1. La strada: l'API di Renpho Health

Tre strade erano sul tavolo, e sono finite in quest'ordine:

1. **l'API cloud di Renpho**, cioe' quella che l'app usa. E' la scelta;
2. **Renpho → Google Health → un ponte → Garmin**, e noi leggiamo da Garmin.
   Niente credenziali nuove e il peso arriva anche all'orologio, ma sono due
   terzi in mezzo e lungo la catena la composizione si perde: passa il peso,
   non il resto. Resta la riserva se l'API cloud smette;
3. l'**export** dall'app, a mano. Non e' un flusso, ma e' l'unico modo di
   prendere uno storico piu' lungo di quello che l'API rende.

Non si reverse-engineera niente: `renpho-py` (1.3.1, uscita il 9 novembre
2026) parla col `cloud.renpho.com` di adesso — `renpho-aggregation/user/login`
con il payload cifrato AES — ed e' il seguito mantenuto di `renpho-api`.
Dipendenza nuova, nessuna dipendenza esterna sua tranne `pycryptodome`.

**Il login vuole email e password, e un account nato con Google non ne ha
una.** E' costato sei tentativi e un'ora: il server risponde `code=104, wrong
user name or password` a qualunque valore — in chiaro, MD5, SHA-1, SHA-256, e
con ogni `areaCode` — perche' non ha niente con cui confrontarlo. Si rimedia
dall'app, *Forgot password* sulla schermata di accesso: l'account prende
un'identita' email+password e si continua a entrare con Google. Due trappole
da ricordare: la password sta in **6-16 caratteri** (l'app ne taglia le piu'
lunghe a 16, e allora funziona nell'app e non nell'API), e nel `config.yaml`
va fra virgolette se contiene `#` o `:`.

Le credenziali stanno in `user/config.yaml`, `renpho_usr` e `renpho_pwd`, e
sono le prime chiavi **facoltative** di quel file: chi non ha una bilancia non
le scrive e il programma parte. Scritte prima che il file le conoscesse,
`config.py` fermava **ogni** comando con "chiavi sconosciute" — l'API in piedi
rispondeva ancora perche' la configurazione era gia' in memoria, quindi il
guasto si sarebbe visto al primo timer della notte. Da qui `_OPTIONAL`, e
`_TOGETHER` per le chiavi che stanno in coppia.

## 2. I file: `health/body_composition/<giorno>.json`

Una cartella come le altre di `health/`, un file per giorno, scritto con
`write_json` (atomico). Dentro, la **lista** delle pesate di quel giorno in
ordine di ora: l'8 novembre ce ne sono due, alle 14:39 e alle 14:42, e tenere
solo l'ultima vorrebbe dire buttare un dato vero.

Di ogni pesata si tiene quello che serve, coi nomi nostri, piu' la riga
grezza? No: **solo i campi nostri**. I 122 campi di Renpho sono quasi tutti
zeri, fasce di riferimento e impedenze, e un file di dati e' un documento che
si legge — non un dump.

**Zero non e' un valore.** La pesata delle 14:39 ha `resistance: false` e la
composizione tutta a zero: e' una pesata senza impedenza, piedi asciutti o
calzini. In quel caso il peso c'e' e il resto e' `null`, perche' una card che
disegna un corpo fatto di zeri dice una cosa falsa. E' la stessa regola delle
settimane senza corse nel blocco: una misura che non c'e' non vale zero.

## 3. La card Body, in Day · Snap

Una in piu' nella griglia delle quattro, e dieci numeri: peso, BMI, grasso %,
acqua %, muscolo scheletrico, massa magra, osso, proteine %, grasso viscerale,
metabolismo basale. Sotto, l'eta' corporea contro quella vera.

**Prende tutte e due le colonne, e i dieci numeri stanno in due righe da
cinque.** La prima versione la metteva a mezza pagina come le altre: dieci
riquadri in due colonne sono cinque righe, cioe' una card alta il doppio delle
quattro accanto, e la griglia dello Snap si leggeva sfaldata. Dieci misure
della stessa cosa vogliono una fila, non una colonna.

**Se il giorno non ha una pesata, si mostrano le ultime fino a quel giorno**,
con scritto quando sono state prese. Non l'ultima in assoluto: aprendo il 15
ottobre non si deve vedere la pesata di stamattina, o un giorno passato
racconterebbe il futuro. Nessuna scadenza oltre la quale la card smette: un
peso di sei giorni fa e' ancora il tuo peso, basta sapere di quando e'. Con
tre pesate in archivio il ripiego non e' il caso raro, e' il caso normale.

Fuori dalla prima versione: i **segmenti** (braccia, gambe, tronco, ognuno con
la sua massa grassa e muscolare) e le impedenze a 20 e 100 kHz. Meritano un
disegno loro — un corpo con cinque valori, non una fila di riquadri — e non un
angolo di card. I dati ci sono e si scaricano comunque.

### Le fasce: lo storico, e il giro che hanno fatto

Sono cambiate due volte in un pomeriggio, e il giro vale scritto.

La prima stesura disegnava la fascia di sempre — media e scarto tipo delle
pesate delle dodici settimane, minimo otto — e teneva fuori le soglie di
riferimento della bilancia per non dare due significati alla stessa barra. A
schermo erano **dieci tracce grigie**: con tre pesate in archivio non ce ne
sarebbe stata una per mesi.

Allora sono diventate le soglie di riferimento, che la bilancia manda dalla
prima pesata e sono una proprieta' della persona (verificato: le ventisei
soglie sono identiche nelle pesate dell'8 e del 10 novembre, mentre peso e
grasso erano cambiati). Il prezzo era dichiarato in una riga sotto i riquadri:
in quella card fuori dalla fascia voleva dire "fuori da dove dovresti stare" e
non "diverso dal solito".

**Sono tornate allo storico**, su richiesta, e la ragione e' buona: una barra
si impara a leggere una volta, e cinque card che dicono una cosa e la sesta
che ne dice un'altra sono un errore di lettura che aspetta di succedere.
Quindi `daily_data._band`, come tutti, con due aggiustamenti di cadenza:

- **la pesata fa parte della sua finestra.** La Day guarda i 28 giorni prima
  del giorno che giudica; qui la fascia non giudica la mattina, descrive un
  periodo, e un periodo contiene l'ultima mattina. Cosi' la fascia arriva una
  pesata prima;
- **il pavimento e' tre pesate**, contro i quattordici giorni della Day e le
  sei settimane della Week: su una bilancia ci si sale quando si vuole, e
  pretenderne sei vorrebbe dire niente fascia per mesi. Tre e' il minimo sotto
  cui uno scarto tipo non dice niente, e va letto per quello che e' —
  l'intervallo di tre mattine.

Finche' non bastano, la card scrive quante pesate ha: una traccia vuota senza
spiegazione si legge come un guasto. E una pesata senza impedenza entra nella
fascia del peso ma non in quelle della composizione, che quel grasso nessuno
l'ha misurato.

### Le due linee sulla barra

**Scura dove sei, verde dove la bilancia dice che dovresti arrivare.** La
prima e' la tacca di sempre (`range-marker`, `var(--text)`), quella che in
tutte le card dice "oggi sei qui"; la seconda e' `ideal` del riferimento, cioe'
l'unico pezzo delle soglie della bilancia che e' rimasto a schermo — ed e'
rimasto perche' un bersaglio non e' una fascia: non c'e' nessun altro disegno
con cui confonderlo.

Ce l'hanno cinque misure su dieci: peso 79.4 kg, BMI 22.0, grasso 15%, muscolo
scheletrico 38.1 kg, metabolismo 1828 kcal. Per acqua, proteine, massa magra,
grasso viscerale e osso la bilancia non propone niente, e una linea verde
inventata sarebbe un obiettivo inventato. Il BMI, che una fascia usabile non
ce l'ha, un bersaglio ce l'ha: 22.0 e' un BMI a cui mirare, 25-30 non e' un
intervallo in cui stare.

Due conseguenze pratiche:

- **la barra si disegna anche senza fascia**, purche' abbia un bersaglio: e'
  quello che la rende utile adesso, che la fascia arriva alla terza pesata e
  il bersaglio c'e' dalla prima. Un valore da solo invece non basta — una
  tacca in mezzo a una traccia vuota non dice niente;
- l'etichetta verde si scrive **solo se non finisce addosso** a quelle della
  fascia (`TICK_GAP`, un sesto della barra): in una colonna da 200 px tre
  numeri si toccano, e un'aggiunta non deve coprire quello che c'era.

Le soglie di riferimento restano **nei file** (`reference`, tutte e dieci,
anche quelle che nessuno disegna): sono dati che la bilancia manda, e il file
e' il registro. Se un giorno vorranno un disegno, ce l'avranno — loro, non la
barra di questa card.

## 4. E a Garmin

Ogni pesata nuova si rimanda a Garmin Connect con `add_body_composition`, che
`garminconnect` ha gia': peso, grasso, acqua, massa ossea, massa muscolare,
metabolismo basale, grasso viscerale, eta' metabolica e BMI. Cosi' l'orologio
conta le calorie sul peso di stamattina e non su quello di settembre, e il
peso si vede anche nell'app Garmin.

**Non si manda due volte.** Prima si chiede a Garmin cosa ha gia' in quei
giorni e si salta quello che c'e': l'ora della pesata e' la chiave, al minuto.

E si chiede con `get_weigh_ins`, non con `get_body_composition`: il secondo
rende una riga **al giorno**, quindi dell'8 novembre vedeva solo quella delle
14:42 e quella delle 14:39 ripartiva a ogni giro. Garmin non ne faceva un
doppione — riconosce il minuto e sovrascrive — ma era un file FIT caricato per
niente, ogni mattina.

Una curiosita' che sembra un difetto e non lo e': l'eta' corporea rimandata
indietro arriva come **durata**, 1893415560000 ms per sessant'anni.

## 5. Quando gira

`make update_weight` a mano, e dentro il giro del mattino con il resto: e' un
dato della salute e viaggia con la salute. Senza credenziali non e' un errore,
e' un passo che non si fa — chi non ha la bilancia non deve vedere un rosso
ogni mattina.
