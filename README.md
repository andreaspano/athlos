# mygarmin

## I dati stanno fuori dal repo

Dal todo 65 il confine e' netto: **nel repo solo il codice**, e tutto quello
che riguarda l'allenamento sotto una radice sola, fuori. Prima il confine non
era stato deciso, era successo — `summary/` ignorato da git ma con dentro
tredici report tracciati da prima dell'ignore, `user/` e `plan/` tracciati, e
FIT, JSON, salute e database tutti piatti nella stessa cartella.

```
~/adrive/data/training/
  fit/       i FIT scaricati da Garmin
  health/    le metriche giornaliere, una cartella per endpoint
  json/      le correzioni (terreno, tipo di corsa) e le cache di nomi e tipi
  db/        activities.db, la cache ricostruibile dai FIT
  user/      config.yaml, profile.yaml, avatar.jpg
  summary/   i report: 01.daily, 02.weekly, ... e 05.plan
  plan/      i blocchi scritti a mano
```

Che cosa c'e' dentro ognuna, lo schema di `activities.db` e da quale file di
Garmin viene ogni colonna stanno in **[`docs/data.md`](docs/data.md)**.

**Due file di configurazione, in quest'ordine.**

`data.yaml`, nella radice del repo, dice una cosa sola — dove sta la cartella
dei dati:

```yaml
data_root: ~/adrive/data/training
```

E' l'unico file di configurazione rimasto nel repo, e **non puo' stare
altrove**: e' quello che deve trovare i dati. E' versionato perche' senza di
lui un clone pulito non parte, e il `~` lo rende valido su ogni macchina
dello stesso utente. Se la cartella che nomina non esiste il programma si
ferma: **non la crea**, che un albero vuoto nato da un refuso si scopre tre
giorni dopo guardando dei report che non arrivano.

`<radice>/user/config.yaml` ha tutto il resto: il token di login, il fuso
orario, l'inizio dello storico, la pausa fra le richieste a Garmin e le
finestre in giorni. Cosa fa ogni chiave e' scritto nei commenti del file.
Non ha piu' una chiave `data_dir`: la radice e' il puntatore.

Tutte le chiavi sono obbligatorie e non ci sono default nel codice: se il file
manca, se manca una chiave, se ce n'e' una sconosciuta o un valore e' del tipo
sbagliato, il programma si ferma all'avvio con un `ConfigError` che elenca
tutti i problemi insieme. Il puntatore si cerca sempre nella radice del repo,
qualunque sia la cartella da cui si lancia il comando.

Il trasloco dalla disposizione vecchia lo fa `tools/migrate_data.sh`, che di
suo stampa cosa farebbe e si ferma: serve `--go` per muovere i file. Si lancia
una volta.

**Le icone restano nel repo** (`icons/`): sono dell'applicazione, uguali per
tutti, e sono l'unica cosa che l'API serve da disco.

## API

Un'API (FastAPI) espone i dati della pagina Day: attivita',
dettaglio, dati e specifica Vega-Lite del grafico, traccia, i giri della
seduta, i fatti del giorno e il report giornaliero, piu' i piani di
allenamento di `plan/`. Si lancia con:

```bash
make api
```

Ascolta solo su `http://127.0.0.1:8000`: non c'e' ancora il login, e sono
dati di salute. La documentazione interattiva e' su
`http://127.0.0.1:8000/docs`, lo schema OpenAPI su `/openapi.json`. Tutto
`GET` tranne tre endpoint: il `PUT` del terreno di un'attivita' a piedi (todo
35), il `PUT` del tipo di una corsa (todo 36) e la `POST` del tasto Refresh
(todo 41), la sola che scarica da Garmin e riscrive un report.

### Il terreno delle attivita' a piedi

Corse, camminate ed escursioni hanno un terreno: `track`, `road`, `gravel`,
`trail` o `mountain`. L'API lo stima dal tipo dell'attivita' e dalla salita
per km (`src/training/interface/terrain.py`; strada quando i dati non
decidono, sterrato mai), e lo si corregge dalla vista Training della Day in
React (todo 62). Le correzioni stanno in `activity_terrain.json` nella cartella dati,
accanto a `activity_names.json`: `activities.db` non le contiene, e un
rebuild non le perde.

### Il tipo delle corse

Le corse hanno un tipo: `race`, `intervals`, `long`, `tempo` o `easy`. L'API
lo stima dall'allenamento pianificato salvato nel FIT e dalla durata
(`src/training/interface/run_type.py`): almeno due passi attivi sono ripetute,
un solo passo attivo di almeno 10 minuti e' un tempo, senza allenamento da 100
minuti in su e' una lunga, altrimenti facile. Gara non si stima mai. Lo si
corregge dalla vista Training della Day in React; le correzioni stanno in
`activity_run_type.json` nella cartella dati, accanto a
`activity_terrain.json`, e un rebuild non le perde. Il report giornaliero lo
usa nella sezione Training (todo 43): e' il metro con cui l'allenatore giudica
la seduta, perche' dice che seduta voleva essere.

### I giri di una seduta

Dal todo 79 i messaggi `lap` del FIT finiscono nella tabella `laps` di
`activities.db`: un giro per riga, con intensita', tempo, distanza, velocita'
e battiti. Servono a una cosa sola, mostrare **com'era fatta una seduta** —
il riscaldamento, le ripetute una per una, i recuperi, il defaticamento — e
la card Session ne disegna la tabella (`GET
/api/activities/{id}/laps`).

Si distingue una seduta strutturata da una corsa libera dal
`wkt_step_index` del giro, non dall'intensita': i giri di una corsa libera
sono l'auto-lap al chilometro e quel campo e' vuoto, quindi la tabella non
si disegna. Il ritmo manca dove la distanza la indovina il polso (il
nastro). I giri stanno **solo nei file**, non si ricavano dai dati gia' in
tabella: la tabella nuova si riempie con un rebuild (`LOGIC_VERSION` "9").

### Il tapis roulant e' uno sport, non una corsa

Dal todo 45 una seduta sul nastro ha `sport = treadmill`: si misurano tempo,
battito, potenza e calorie, e **non ha un concetto di distanza**. La distanza
che l'orologio registra la stima dal polso e in salita sbaglia di molto (una
seduta a 15% di pendenza torna con tre chilometri e una media da
passeggiata), quindi resta in `activities.db` ma non la mostra ne' la somma
nessuno: l'API la manda a `null` insieme alla velocita' media, i fatti del
giorno la marcano `distance_unreliable`, e il prompt dell'agente Training ha
l'ordine di non nominare ne' distanza ne' passo. Niente terreno e niente tipo
di corsa, per lo stesso motivo. Lo sport si riconosce dal `sub_sport` del FIT
(lo scrive il profilo dell'orologio) prima che dal tipo di Garmin Connect:
delle 23 sedute dello storico una sola ha un tipo su Connect.

### I file di salute di un giorno

`make update_activity`, `make backfill_health` e `make backfill` scaricano un
file per giorno e per endpoint in `health/`. Un file conta come completo solo
se e' stato salvato dopo la fine del suo giorno: uno salvato durante il
giorno non ha quello che Garmin aggiorna dopo (il VO2max e il carico dopo una
corsa della sera, il body battery piu' basso, lo stress del giorno), e si
riscarica al giro dopo (todo 39). Oggi si riscarica sempre; un giorno rimasto
a meta' piu' vecchio della finestra di `update_activity` (3 giorni) si
sistema con `make backfill_health`.

### Endurance score, hill score e soglia del lattato

Endurance e hill score si scaricano ogni giorno con il resto della salute
(`health/endurance_score/` e `health/hill_score/`); per lo storico, dopo il
primo aggiornamento, `make backfill_health` scarica solo i file che mancano
o che non sono completi (vedi sopra).
La soglia del lattato no: Garmin la da' solo il giorno in cui ne rileva una
nuova, quindi `make update_activity` tiene l'ultima in un file unico,
`health/lactate_threshold_latest.json`. La card Fitness la mostra dal giorno
in cui e' stata rilevata; prima, la frequenza di soglia salvata nei FIT. Il
report giornaliero non legge nessuna delle tre.

### La pagina Day in React

`frontend/` e' l'interfaccia (React, TypeScript, Vite), l'unica dal todo 40.
La barra in alto ha **due menu su due righe** (todo 55): sopra il periodo —
la **Day** e la **Week** — sotto che cosa se ne guarda. Sono due assi, non
una fila sola. A destra, staccato, c'e' **Goal**, che un periodo non e': un
obiettivo guarda avanti a una gara, non indietro a un giorno.

Si chiamava **Plan** come la sua pagina, e nella barra erano due: questo e la
vista Plan della Week — che dal todo 90 non c'e' piu', e il nome adesso e'
di uno solo. Goal dice quello che la pagina mostra, la gara a cui si va e
quanto manca. **L'indirizzo resta `?period=plan`**, cosi' i link scritti
prima continuano ad aprirla.

**Nella barra non ci sono voci grigie.** Month, Year e Activities si
aggiungeranno quando esisteranno, non prima: Activities e' stata per mesi una
pillola disattivata e non portava in nessun posto.

**Le viste sono di ogni periodo** (todo 59): **Snap**, **Training** e
**Trend** sotto Day, **Snap**, **Trend** e **Plan** sotto Week; la Goal, che
un periodo non e', non ne ha e apre la barra con una riga sola. Stanno in `VIEWS`
(`src/navigation.ts`) nell'ordine in cui si leggono, e **la prima e' quella
che il periodo apre da solo** — lo Snap, per tutti e due.

Lo Snap della Day si chiamava **Report** fino al todo 67. Il nome e' passato
a quello della Week per lo stesso motivo che lo aveva scelto li': quella
vista non e' un documento, e' **l'istantanea** — i numeri con le loro fasce,
e il testo dentro le card. E siccome e' la stessa chiave, cambiando periodo
si resta sull'istantanea: da Day/Snap si clicca Week e si arriva su
Week/Snap.

L'URL dice i due assi: `?period=` e `?view=`, piu' i parametri della pagina
(`?day=2026-10-07` per la Day, `?monday=2026-10-19` per la Week, `?days=90` e
`?weeks=26` per l'ampiezza dei due Trend). `?view=` si scrive solo quando non e' la vista di
partenza, quindi `?period=week` da solo apre lo Snap: i link di prima
continuano ad aprire quello che aprivano. Cambiando vista **il periodo
resta**: da Day/Snap si clicca Trend e si resta sul giorno che si stava
guardando. E **la vista si porta dietro dove esiste**: da Day/Trend si clicca
Week e si arriva sul Trend della Week, mentre da Week/Plan si torna a
Day/Snap, che il Plan la Day non ce l'ha. Senza niente si apre Day/Snap.
Niente router di libreria: `URLSearchParams` e `history.pushState`
(`src/navigation.ts`).

**Le forme vecchie non si leggono piu'.** `?page=week` valeva fino al todo
55 e ha smesso: era compatibilita' verso i link di un'app con un utente
solo, e in `summary/` e in `plan/` non ce n'era nessuno. Oggi apre Day/Snap,
che e' la ricaduta di qualunque indirizzo che non si capisce. Una chiave
sparita non ha comunque bisogno di codice: `?view=report`, la vista del
giorno fino al todo 67, ricade sulla vista di partenza perche' `view` si
valida contro `VIEWS` — e quella validazione serve a se stessa, non alla
compatibilita'.

Il **Trend** della Day (todo 55) disegna quello che lo Snap racconta: le
misure giorno per giorno nei cinque pannelli delle card, in una finestra che
si sceglie col cursore fra 5 e 365 giorni (28 di partenza, la stessa di
`BASELINE_LONG`). Un grafico **per misura** e non per pannello — dentro un
pannello le unita' non sono le stesse, e su un asse solo la linea bassa
verrebbe piatta — con la fascia di `_band` come sfondo, che si muove insieme
alla finestra. Sotto `MIN_BAND_DAYS` giorni misurati la fascia non c'e', e
la pagina lo dice; i giorni senza misura spezzano la linea invece di farle
attraversare il buco.

**Anche le tre intensita' del carico hanno la fascia di `_band`**, la stessa
che mostra la card Load: dove quel carico sta di solito, non il bersaglio di
Garmin. La domanda e' la stessa in tutta la pagina — questa misura e' nella
sua norma? — e il bersaglio rispondeva a un'altra, dove Garmin vorrebbe che
fosse. Il rapporto acuto/cronico, sempre come la card, di fascia non ne ha.

**Il mouse sul grafico accende una barra verticale grigia** sul giorno piu'
vicino, alta quanto il riquadro, e il tooltip dice quel giorno e il suo
valore. Il giorno lo sceglie una tassellatura sulla x (`nearest` nella
specifica), quindi si prende tutta la colonna: a 365 giorni, dove la linea
e' spessa due pixel e i pallini non ci sono, centrare il punto sarebbe un
gioco di mira.

**Un clic apre lo Snap di quel giorno** — lo stesso che la barra sta
indicando: il clic non guarda il segno colpito ma chiede alla scala che
giorno sia la sua x, **arrotondando al piu' vicino** come fa la barra. Il
tasto indietro torna al Trend, con la finestra di prima.

La **Week** mostra una settimana ISO (lunedi-domenica) con il suo titolo —
`Week 43 · October 2026`, dove il mese e' quello del **giovedi**, la regola
ISO per le settimane a cavallo — e una striscia di sei settimane. **Ogni card
porta il testo della sua sezione del report settimanale** (todo 53), con
l'ora e il tasto per rifarla, come nella Day.

Dal todo 68 la Week ha le **stesse viste della Day, nello stesso ordine** —
tre dal todo 90, che le ha portate da quattro a tre. Lo **Snap** e' il corpo:
il verdetto a tutta larghezza e le quattro card. La **Training** e' il lavoro:
in cima il **Plan**, cosa chiedeva la settimana (todo 71), poi l'elenco delle
sedute (un clic su una seduta apre la
Day di quel giorno, sulla sua **Training**: si e' cliccato una seduta, e la
seduta sta li') e il commento sulla forma della settimana. Le sedute
avevano sopra un grafico del lavoro per sport, tolto col todo 72.
Prima stavano tutte nello Snap, sette riquadri in fila, insieme a un **Next**
che dal todo 69 non c'e' piu'.

Il **Trend** e' la fila delle settimane (todo 78): gli stessi cinque pannelli
della Day, ma con **un punto per settimana** invece che per giorno, in una
finestra che il cursore muove da 4 a 52 settimane. Il punto e' la **media** dei
giorni misurati — la **somma** sul pannello Training, che li' si disegna a
barre, perche' i minuti di una settimana sono la loro somma e una quantita' si
legge a barre.

Due cose non sono quelle dello Snap, e sono volute. Lo Snap legge carico e
forma come **stati di fine settimana**; il Trend li media come tutto il resto,
perche' una linea i cui punti fossero stati su un pannello e medie su un altro
non si confronterebbe. E la **fascia risponde a un'altra domanda** di tutte le
altre dell'app, perche' il grafico **e' una carta di controllo**: la settimana
e' il sottogruppo, la riga tratteggiata e' la linea centrale e la fascia sono i
limiti.

- la **linea tratteggiata** e' il centro della finestra, la media delle medie
  settimanali;
- la **fascia** e' quel centro piu' e meno uno e due errori standard. Lo scarto
  tipo da cui vengono e' uno solo per la finestra — la varianza dentro ogni
  settimana, mediata su tutte, e poi la radice — e ogni settimana lo divide per
  la radice dei **suoi** giorni, quindi la fascia si allarga dove una media sta
  su meno misure;
- i **punti** sono le medie settimanali, e si guardano rispetto ai limiti e non
  a se stessi: **una settimana fuori dalla fascia e' una settimana che ha fatto
  qualcosa di diverso**.

Sotto tre giorni misurati la fascia non si disegna, e il pannello Training non
ce l'ha affatto.

Del file della settimana la pagina mostra **le sette sedute**, e basta: la
colonna le ha come **dati**, una riga per giorno, da scorrere con un'occhiata
accanto alle sedute fatte nella colonna di fianco — con `Week 3 of 18`
accanto al titolo, che dice dove si e' nel blocco senza aggiungere una riga —

```
Mon 26 Oct   Rest
             Rest. Nothing today, an easy walk if you like. 20 min of strength work.
Tue 27 Oct   Running · easy · 5 km
             Easy 5 km at 7'15"-7'40", then 6 x 20 s strides. Heart rate under 138.
Wed 28 Oct   Rest · or Cycling
             Rest, or an easy spin of 45 min.
...
```

Sotto ogni riassunto c'e' **la riga di quel giorno nella tabella del piano**
(todo 89), cioe' i ritmi, le ripetute, il tetto del battito e il perche': era
nei dati da sempre (`text`, come nella card della Day) e questa colonna la
buttava via, cosi' una qualita' e un lento si somigliavano. Il riassunto
resta sopra perche' e' lui che sta sulla riga della seduta fatta nella colonna
accanto.

— e **il resto del file non si vede piu'** (todo 91). Era una vista a parte
col documento intero (todo 60), poi una card in fondo alla Training (todo 90),
e adesso niente, perche' quello che diceva sta altrove: la tabella dei giorni
e' in queste righe col loro dettaglio (todo 89), i ritmi e le regole di
scarico sono **copiati dal blocco** — gli stessi valori di «Ritmi e
frequenze» e le stesse regole di «Quando scaricare» — e si leggono nella
pagina Goal. Quello che resta scritto per quella settimana e solo li' — a
cosa serviva, i totali, le decisioni prese strada facendo con la loro data —
**resta nel file**, che si apre anche da solo: `summary/05.plan/<lunedi>.md`.

Le sedute arrivano dal front matter (`sessions` in `WeekPlan`), **in ordine
di data e non di file**: il file di settembre 2026 ha la tabella che parte
dalla domenica, e una card che le mette in fila le vuole in fila. Quel file
pero' il front matter non ce l'ha, quindi per la sua settimana la colonna
resta vuota e senza il `Week n of N` accanto al titolo: le sedute a macchina
non ci sono, e ricavarle dalla prosa e' la strada che il todo 14 aveva
scartato.

**La Week va anche avanti** (todo 88), fin dove arriva il piano: la freccia
`›`, la fila dei riquadri e il calendario arrivano all'**ultima settimana che
ha un file** in `summary/05.plan/` — oggi la settimana di gara. Lo dice
`GET /api/weekly/planned`, i lunedi' che hanno un piano, e la pagina ne tiene
il massimo. Nessun piano vuol dire nessun avanti, che e' la risposta giusta e
non un guasto. Il confine non si ricava dal blocco del goal
(`block_start + block_weeks`): quello e' quello che il goal **dichiara**, e il
todo 86 ha mostrato che le due cose divergono — si cambia goal e le settimane
restano quelle di prima.

Camminando avanti la fila scorre con la sua regola di sempre (finisce due
settimane dopo quella guardata), quindi dalla corrente si arriva a vedere
W45..W48 un passo per volta. Il tasto `›|` resta **questa settimana**: da
gennaio la casa e' oggi.

**Una settimana che non e' cominciata non si chiede all'API.** I fatti
(`/api/weekly/<lunedi>`) rispondono **422** — *the week has not started* — e
quella risposta finirebbe nell'avviso che l'API e' giu'. Non e' giu': la
domanda e' senza senso, e a non farla e' la pagina, che di una settimana
prevista chiede **solo il piano**. Da cui tre viste con due stati:

- **Training**: la colonna del piano come sempre, e in quella delle sedute
  *The week has not started* invece di *No sessions this week* — una settimana
  finita senza sedute e una che non e' cominciata sono due cose diverse. La
  card del commento **c'e' e resta vuota**, come nella Day (todo 63): nessun
  agente scrive il verdetto di qualcosa che deve ancora succedere, e la
  cornice vuota e' la risposta. Il tasto che lo scriverebbe no, che quella
  rotta risponde 422.
- **Snap**: una riga che lo dice, e niente card. I numeri di una settimana che
  non e' cominciata non sono zero, non esistono.
- **Trend**: la finestra resta sulle settimane misurate. E' una carta di
  controllo, e dei punti che non ci sono non fanno un grafico vuoto, fanno un
  grafico sbagliato.

Anche il tasto che riscrive la settimana sparisce: `POST .../refresh` risponde
422 per scelta, ed e' la regola del todo 56 — chiudere un periodo che deve
ancora succedere vuol dire giudicarlo prima del tempo.

Un `?monday=` oltre il confine torna a questa settimana e l'indirizzo si
riscrive **senza** lasciare una voce nella cronologia: non e' un passo che
qualcuno ha fatto.

Comune a tutte e tre e' l'intestazione — titolo, frecce, calendario, il
tasto che riscrive la settimana — e il selettore: cambiando settimana la
vista resta, e tutte parlano degli stessi sette giorni.

Le fasce della Week **non sono quelle della Day**: qui il valore della
settimana si confronta con le **12 settimane precedenti** (todo 52), e ne
bastano sei misurate. Attorno a una media settimanale una fascia a 28 giorni
non direbbe niente: sette giorni oscillano molto meno di uno, e il valore
cadrebbe quasi sempre dentro. Health e Recovery sono medie dei sette giorni,
Fitness lo stato di fine settimana — la forma e' uno stato, non una cosa da
mediare.

**Nella Week ogni numero e' della settimana** (todo 54), bande comprese. La
card Load lo e' diventata per ultima: mostrava i tre carichi per effetto di
Garmin, che sono finestre di **28 giorni**, e due settimane vicine ne
condividono tre quarti — si somigliavano per forza. Adesso mostra il carico
dei sette giorni (`load_acute`, che letto alla domenica e' esattamente
lunedi-domenica) e il **tempo passato nelle tre fasce di sforzo**, contato
dalla frequenza cardiaca di ogni seduta con i confini di **quella** seduta:
una soglia alzata a settembre non riscrive i minuti di agosto. I minuti
stanno in tre colonne di `activities`, calcolate dai record a ogni `sync()`
e rifacibili con `make backfill_zones`: ricalcolarli a ogni richiesta
costerebbe un decimo di secondo per settimana.

Il carico e i minuti non raccontano sempre la stessa settimana, ed e'
voluto: le sedute senza fascia cardiaca stanno nel carico (Garmin le stima)
e non nei minuti. Quante sono lo dice `zones.sessions_without_hr`, e la card
lo scrive quando capita. Il carico cronico e il rapporto fra i due restano
nella Day, dove il mese e' il contesto giusto per un giorno.

La **Day** mostra un giorno alla volta (todo 34): la striscia della settimana,
la seduta suggerita e il verdetto del giorno, e una griglia 2x2 con Health e
Load sopra, Recovery e Fitness sotto (todo 37). Dal todo 62 l'allenamento non
sta piu' in fondo a questa colonna: ha una vista sua, **Training**, fra Snap
e Trend — la stessa card di prima, spostata di posto e non rifatta. Dal todo 63
sopra di lei c'e' la card **Plan**, la seduta che quel giorno prevedeva: prima
quello che era previsto, poi quello che si e' fatto. **La card c'e' sempre**, e
un giorno senza piano la lascia **vuota**: la cornice resta — due riquadri a
qualunque data, che uno che va e viene si legge come un errore — e dentro non
ci va niente, perche' la cornice vuota lo dice gia'.
**Tutte e quattro le card hanno la stessa forma**: le misure, ognuna
con la barra della sua fascia e il valore di oggi come tacca, e niente testo
accanto ne' sotto il numero. Qualche misura la fascia non ce l'ha, e allora e'
un numero nudo: la soglia del lattato, il rapporto di carico, la quota e il
caldo a cui sei acclimatato. La fascia pero' non vuol dire la stessa cosa
dappertutto: in Health e Recovery e' la media dei 28 giorni prima piu' e meno
uno scarto tipo (in tinta chiara piu' e meno due), e uscirne e' un segnale; in
Fitness e' la stessa media ma **sopra vuol dire che stai migliorando**; in
Load e' di nuovo la stessa media, e dice quanto di quel tipo di lavoro stai
portando rispetto al solito.
Ogni card ha il testo della sua sezione del report giornaliero, l'ora in cui
e' stato scritto e un tasto che la rifa' da sola (todo 44 e 47). In cima, a
tutta larghezza, il **Summary**: il verdetto sulle quattro, e il solo testo
del Report che non appartiene a una card.

**Sulla macchina gira da sola** (todo 82): `mygarmin-api.service` e'
uvicorn che serve l'API **e** la pagina compilata, tutto sulla 8000. Un
processo solo, niente vite acceso in produzione, niente proxy. I comandi per
gestirla sono in **[`docs/service.md`](docs/service.md)**.

```bash
cd frontend && npm ci      # la prima volta
make install_services      # compila la pagina e accende il servizio
# poi http://127.0.0.1:8000
```

Dalla tailnet ci si arriva con `tailscale serve`, una volta sola (la
configurazione resta anche dopo il riavvio):

```bash
sudo tailscale set --operator=$USER                       # una volta, per non rifare sudo
tailscale serve --bg --http=8000 http://127.0.0.1:8000    # poi http://mutolo:8000
```

L'API resta su 127.0.0.1: chi decide che cosa esce e' `tailscale serve`. Con
`tailscale serve status` si vede com'e' puntata, con `tailscale serve reset`
si spegne.

**Dopo un cambio al frontend il servizio non se ne accorge**: serve
`make frontend_build` (o `make install_services`, che lo fa) e poi
`systemctl --user restart mygarmin-api`. La pagina servita e'
`frontend/dist`, non i sorgenti.

#### Per lavorarci

In sviluppo si lascia stare il servizio e si lancia vite, che ha il
ricaricamento a caldo:

```bash
make frontend    # http://127.0.0.1:5173, con /api e /icons presi dalla 8000
```

Vite passa `/api` e `/icons` all'API, quindi non serve CORS. L'API gliela da'
il servizio: non serve piu' `make api` in un altro terminale, a meno di
volerla ricaricare a caldo anche lei.

I tipi delle risposte vengono dall'OpenAPI: dopo un cambio ai modelli
dell'API, con l'API accesa, `make frontend_types` rigenera
`frontend/src/api/schema.ts` (che non si modifica a mano).

Il tasto **Refresh** nell'intestazione (todo 41) aggiorna i dati e rifa' il
report del giorno mostrato. Dal todo 44 il report non lo scrive un agente
solo: ogni sezione ha il suo (`01_health`, `02_load`, `03_recovery`,
`04_fitness`, `05_training`, e per ultimo `07_summary`, che legge quello che
hanno concluso gli altri), e ognuno scrive il suo file in
`summary/01.daily/<giorno>/`. Il numero sei manca: era `06_next`, cancellato
col todo 66, e gli altri tengono il loro numero perche' sono anche il nome
del file. L'API li lancia **uno alla volta** con `claude -p` (il comando
`claude` deve essere nel `PATH` di `make api`), dopo aver scaricato i dati e
preparato i fatti una volta sola: un minuto e mezzo in tutto. Le regole che gli agenti condividono stanno in
`.claude/agents/_style.md`.

Ogni card ha anche **un tasto suo**, che rifa' solo quella sezione: una
sessione invece di sette quando si vuole ritoccare un testo. Una sezione che
fallisce tiene il testo che aveva e le altre si riscrivono lo stesso; il
tasto di quella sezione lo segnala.

Lo stesso lavoro si fa da terminale, senza l'API:

```bash
make daily_report                   # oggi, tutte le sezioni
make daily_report DAY=2026-10-07    # un giorno a scelta
make daily_report SECTION=health    # solo una sezione
```

Il login a Garmin non si chiede mai dal tasto: con il token scaduto il
report si scrive sui dati locali **e la pagina lo dice**, e il login si rifa'
da terminale con `make update_activity`. I report scritti prima del todo 44
stanno ancora nel file unico `summary/01.daily/<giorno>.md` e si continuano a
leggere da li'.

### I piani di allenamento

In `plan/` stanno i piani scritti a mano: un file Markdown per piano, e la
pagina **Goal** li mostra tutti, la gara piu' vicina per prima. Nessun elenco
nel codice — un file nuovo nella cartella si vede ricaricando la pagina — e
nessun agente: questi li scrive una persona, mentre `summary/` lo riscrivono
gli agenti.

**L'elenco si apre e si chiude** (todo 84): una riga per goal, e aperte
quante se ne vuole. I tre piani di una mezza sono tre bersagli della stessa
gara, e la domanda che si fa guardandoli e' *quale di questi*: una pagina che
ne mostrava uno per volta la rendeva un andare avanti e indietro.

**Uno e' quello attuale, e lo dice `current: true`** nel suo front matter:
porta la pillola e si apre da solo. Dal todo 85 si sceglie dalla pagina
(`make current` sulle righe che non lo sono) e un goal si butta col cestino:
**il file va in `plan/.trash/`, non si cancella** — un goal e' un documento
scritto a mano e l'API non ha login.

**Cambiare goal non rigenera i piani settimanali.** Dal todo 86 un
generatore c'e', ma e' un comando da lanciare (`make week_plans`, qui sotto)
e non un effetto del clic: siccome i tre piani hanno ritmi e chilometraggi
diversi, finche' non si lancia le settimane prescrivono il bersaglio vecchio —
quindi la pagina lo dice e nomina il comando: *18 weekly plans from this
Monday on still follow `half_marathon_2.20`*. Il passato non si conta e non si riscrive: le
settimane finite sono il registro di quello che era previsto allora, e i
report di allora le hanno giudicate. Prima lo si sapeva solo di rimbalzo —
le diciotto settimane di `summary/05.plan/` portano `plan: half_marathon_2.20`
— cioe' stava scritto nei file generati e non in quello scritto a mano. Il
flag e' uno o nessuno: se due file ce l'hanno, lo tiene il primo dell'elenco
e gli altri lo perdono, che due obiettivi attuali non sono una cosa da
mostrare.

Davanti al testo c'e' un front matter YAML, nello spirito del todo 14 ma per
un blocco intero invece che per una settimana: le chiavi dicono la gara, non
le sedute.

```yaml
---
race: 2027-02-28
race_name: mezza maratona (da scegliere)
distance_km: 21.097
target_time: "2:20:00"
target_pace_min_km: "6:38"
target_speed_kmh: 9.04
current: true          # il goal che si sta seguendo: uno solo fra i file
block_start: 2026-10-26
block_weeks: 18
peak_weekly_km: 46
---
```

Da quelle chiavi la pagina ricava i riquadri in cima (la gara, quanti giorni
mancano, il bersaglio, il ritmo, la velocita', la settimana piu' pesante);
tutto il resto e' il testo. **Il front matter non e' obbligatorio**: un file
che non ce l'ha si vede comunque, col solo testo e i riquadri vuoti. Un piano
invisibile perche' gli manca una chiave sarebbe peggio di un piano senza
numeri. I bersagli con i due punti vanno fra apici, se no YAML li legge come
minuti.

Il titolo non sta nel front matter: e' il primo `# ...` del testo, che la
pagina si prende per la sua intestazione e toglie dal corpo. Senza titolo
resta il nome del file.

Due endpoint, entrambi in sola lettura: `GET /api/plans` da' l'elenco senza i
testi, quello che serve al selettore, e `GET /api/plans/<slug>` un piano col
suo Markdown. Lo `slug` e' il nome del file senza `.md` (`?plan=` nell'URL), e
si cerca fra i file trovati invece di essere attaccato a un percorso: non puo'
uscire da `plan/`.

Il Markdown dei piani ha **titoli e tabelle**, che i report non hanno — un
piano e' quasi tutto tabelle, le settimane e i ritmi — e `src/markdown.tsx` li
converte come il resto, senza una libreria in piu'. Le tabelle larghe scorrono
da sole dentro il loro riquadro: scorre la tabella, non la pagina.

### Il piano dentro i report

I piani di `plan/` sono il blocco; le sedute giorno per giorno stanno in
`summary/05.plan/`, un file per settimana col nome del lunedi', col front
matter del todo 14 e la tabella dei sette giorni. Il formato e' documentato in
`summary/05.plan/README.md`, e li legge `api/plans.py` con gli stessi pezzi
dei piani di `plan/`: `WEEK_PLAN_FOLDER` e `week_plan_path` sono li', una
definizione sola per l'orchestratore e per l'API.

Dal todo 60 **si vedono anche**, nella vista Training della Week
(`GET /api/weekly/<lunedi>/plan`, 404 quella settimana non ne ha): fino al
todo 90 in una vista Plan tutta sua, poi in una card, dal todo 91 in nessuno
dei due. Delle sedute del front matter la pagina usa i campi; il testo della
tabella arriva insieme a loro, una riga per giorno, ed e' il dettaglio sotto
ogni riassunto.

Dal todo 63 **`sessions` si legge, per un giorno alla volta**:
`GET /api/daily/<giorno>/plan` rende la seduta prevista per quel giorno nei suoi
campi — sport, tipo, distanza gia' in etichetta, lo sport che un riposo ammette
comunque — piu' la riga di quel giorno presa dalla tabella, che e' dove sta il
perche'. La voce si cerca **per data e non per posizione**, che il file di
settembre 2026 ha la tabella che parte dalla domenica e otto righe. 404 quando
per quel giorno un piano non c'e', compreso il caso di un file piu' vecchio del
front matter: per chi guarda e' la stessa cosa, quel giorno non e' previsto
niente. La settimana intera resta senza `sessions`: marcare il giorno di oggi
nella tabella della Week e' ancora aperto (todo 61).

**Lo legge una sezione sola** (`_planned` in `api/refresh.py`), quando il
file della settimana esiste: **il Training del giorno** (todo 64), che
giudica. La seduta prevista per quella data e' il suo primo metro — distanza,
fascia di ritmo, tetto del battito, a cosa serviva il giorno — e il confronto
con le sedute passate **non viene sostituito, ci si somma**: cosa era
chiesto, cosa si e' fatto, e come sta rispetto al solito. Prima del todo 64
vedeva solo le sedute passate, e di "previsto" conosceva il solo allenamento
caricato sull'orologio: su un giorno con un piano scriveva «nothing was
planned» (vero di quel file) e lodava nove chilometri dove ne erano previsti
cinque.

Erano due: anche Next lo leggeva, come punto di partenza di quello che
prescriveva. **Nessuno prescrive piu'** — il Next del giorno e' andato col
todo 66, quello della settimana col 69 — e il piano si segue come e'
scritto.

Health, Recovery, Load e Fitness il piano non lo vedono: raccontano dei
numeri, e quello che era previsto non li cambia. Nemmeno il Training della
settimana, dove il confronto e' con la forma dei sette giorni, un'altra
domanda.

Nessun file, nessuna frase nel prompt: i giorni fuori da un blocco si scrivono
come prima, dalle sole sedute presenti e passate. All'agente non si dice
**ne' che un piano c'e' ne' che non c'e'**: "per questo giorno non era
previsto niente" e' peggio del silenzio, perche' si legge come un verdetto
sulla seduta.

### Le settimane si generano dal goal

Fino al todo 86 nessuno le scriveva: i diciannove file di `summary/05.plan/`
li ha scritti un giro a mano il 26 ottobre 2026, e cambiare goal li lasciava
dov'erano. Adesso c'e' `make week_plans`, cioe' `api/weekplans.py` — `plans.py`
e' chi legge, questo e' chi genera.

```
make week_plans                           # il goal attuale, da lunedi' prossimo
make week_plans DRY=1                     # cosa farebbe, senza agenti
make week_plans GOAL=half_marathon_2.10
make week_plans FROM=2026-12-07 TO=2027-01-04
```

**Le scrive un agente, una settimana per volta** (`.claude/agents/p_week.md`,
lanciato come le sezioni dei report) e non una funzione: il blocco e' prosa —
la tabella delle diciotto settimane, le tabelle di fase, i ritmi, le deroghe —
e un parser di quelle tabelle sarebbe il parser del markdown di una persona,
che si rompe sul primo blocco scritto diversamente e si rompe in silenzio. Ogni
agente riceve il blocco, l'identita' della sua settimana e **il file della
settimana prima**, che e' da dove la sua continua. Lo stile dei report
(`_style.md`) non si attacca: dice "nessun titolo, un paragrafo, niente
tabelle", e una settimana e' tutto il contrario.

**Le date non sono dell'agente.** Il lunedi', `block_week`, `block_weeks`,
`plan`, `race` e `target_time` li calcola il modulo dal front matter del blocco
e li mette nel prompt, perche' un front matter sbagliato non da' un errore:
`load_day_plan` cerca la seduta per data, quindi una data storta diventa un
giorno senza piano, e si scopre a dicembre guardando una card vuota. Quello che
l'agente scrive si **ricontrolla** (`check`): il front matter si legge,
l'identita' e' quella chiesta, `sessions` ha sette voci coi sette giorni,
`sport`/`kind`/`distance_km` sono valori che i lettori sanno leggere, e la
tabella ha una riga per ogni giorno — cercata con `_day_row`, che e' chi la
cerca davvero.

**Il file nasce in `summary/05.plan/.staging/` e arriva al suo posto solo se
passa.** Un file rotto e' peggio di un file che non c'e': quello che manca lo
gestiscono apposta tutti e tre i lettori, quello rotto gira, e il Training del
giorno ne scrive il verdetto. Una settimana scartata resta nella staging da
leggere, e al suo posto resta quella di prima.

**Si genera dal lunedi' prossimo.** Il passato non si tocca — le settimane
finite sono il registro di quello che era previsto allora, e i report di allora
le hanno giudicate — e la settimana **in corso** sta col passato: i suoi giorni
sono stati corsi e giudicati, e una settimana che cambia sotto i piedi a meta'
e' peggio di una che finisce sul piano vecchio. Per questo l'avviso della
pagina Goal, che conta da questo lunedi', resta su una settimana anche dopo una
generazione, e si spegne da se' il lunedi'.

**Quello che c'e' va in `summary/05.plan/.trash/`**, non si sovrascrive: una
settimana si puo' essere riscritta a mano avvicinandosi alla data. Generare e'
l'unico gesto distruttivo dentro `summary/`, e rilanciare il comando non e'
innocuo come rilanciare un backfill.

Il comando **prende il lock dei report** (`.refresh.lock`): due serie di
`claude` sugli stessi file non si fanno. Sono una sessione per settimana,
mezz'ora in tutto, quindi non si lancia vicino ai giri delle 8 e delle 21, che
troverebbero il lock occupato e salterebbero il report. E stampa una riga per
settimana — numero del blocco, fase, km, lungo, quante qualita': **quelle righe
sono la verifica**, da leggere accanto alla tabella del blocco, perche' i
controlli sono strutturali e non sanno niente di allenamento.

### I due giri dei timer: una pagina per giro

Dal todo 47 il report si scrive da solo due volte al giorno, e dal todo 66
**ogni giro scrive una pagina**:

| | ore | sezioni | scrive |
|---|---|---|---|
| mattina | 08:00 | health, recovery, load, fitness, summary | Day:Snap |
| sera | 21:00 | training | Day:Training |

Ogni sezione gira **una volta al giorno**. Prima i due giri si
sovrapponevano: `load` e `fitness` scritti due volte, `next` due volte, e un
verdetto con mezzo pezzo per giro.

Il prezzo del taglio, che va saputo: **Load e Fitness raccontano lo stato
prima della seduta di oggi**. Scritti alle otto includono la seduta di ieri e
non quella di oggi, quindi lo Snap dice come stai stamattina e il carico di
oggi si legge domani.

**Next non c'e' piu'** (todo 66 per il giorno, 69 per la settimana). Era
l'unica cosa che prendeva i numeri di stamattina e diceva cosa fare oggi, e
nella settimana l'unica che adattava la forma del blocco a com'era andata la
settimana prima. Le regole di deroga scritte nel piano («readiness under 40:
run it easy and move the session to Friday») adesso non le applica nessuno, e
sui giorni fuori da un blocco di suggerimenti non ce ne sono. **Le sezioni
raccontano, nessuna prescrive**: la prescrizione e' il piano, scritto a mano.

**Il verdetto del giorno e' uno** — era in due pezzi, il sole del mattino e
la luna della sera (todo 49), quando i giri erano due. Adesso e' del mattino
e ha un soggetto solo: le quattro card del corpo. La seduta la giudica il
commento della sera, nella sua pagina.

Gli agenti sanno **che giro e'** (`EVENING_FROM_HOUR` in `api/sections.py`).
Serve soprattutto al tasto della pagina, che continua a rifare **tutte** le
sezioni a qualunque ora: il momento decide come parla il testo, l'insieme
decide chi gira. Premuto alle 21:30 riscrive anche il Summary, e quello deve
sapere che la giornata e' alle spalle.

Siccome ogni sezione porta la sua ora, le card ne mostrano una sotto il
testo: dopo il giro della sera le ore sono diverse, ed e' giusto che si veda.

### Il report della settimana

Dal todo 53 anche la settimana ha il suo report, **le stesse sei sezioni del
giorno**, in `summary/02.weekly/<lunedi>/`. Le scrivono sei agenti —
`w1_health` ... `w5_training` e `w7_summary` — che sono **altri** da quelli
del giorno: i prompt del giorno
parlano di stamattina e della seduta di ieri, e non si riusano. Il ciclo che
li lancia invece e' lo stesso, parametrato su `sections.Report`
(`api/sections.py`).

**Un giro solo** (todo 68), agganciato a quello della domenica sera del
giorno:

| | quando | sezioni |
|---|---|---|
| chiusura | domenica, 21:00 | health, recovery, load, fitness, training, summary |

Erano due: il lunedi' scriveva l'apertura, un verdetto che guardava la
settimana prima, e la domenica tutto il resto. Il ragionamento era che una
settimana al primo giorno non ha numeri da commentare, e vale ancora — ma se
il verdetto e' uno, quello e' il verdetto della fine, non dell'inizio. Il
prezzo e' che **dal lunedi' al sabato la settimana non ha nessun testo**: le
card mostrano i numeri e basta. E' una scelta, scritta nel todo 68.

Il settimanale **non scarica mai**: gira in coda al giro del giorno, che ha
appena chiamato Garmin.

```bash
make weekly_report                      # la settimana di oggi
make weekly_report WEEK=2026-10-12      # un lunedi' a scelta
make weekly_report SECTION=health       # solo una sezione
```

### Riscrivere lo storico

I report vecchi non si aggiornano da soli quando le card cambiano, e dal
todo 44 in poi sono cambiate molto. `--from` (todo 50) riscrive un
intervallo invece di un periodo solo, e vale per tutti e due i comandi:

```bash
make backfill_reports FROM=2026-09-01 TO=2026-09-07    # una settimana di giorni
make backfill_reports FROM=2026-08-01                  # fino a oggi
make backfill_weeks FROM=2026-08-03                    # le settimane, FROM e TO lunedi'
```

Tre regole, e sono quelle che lo rendono ripetibile:

- **Salta le sezioni che ci sono gia'**, non i periodi: un backfill
  interrotto riprende da dove si era fermato, e rilanciarlo su un periodo
  gia' fatto costa qualche secondo. Per rifare da capo ci sono `--day` /
  `--week` con `--section`.
- **Non scarica niente**: i dati storici sono gia' su disco.
- **Se trova il lock occupato si ferma** e lo dice. I giri dei timer hanno
  la precedenza: il backfill si rilancia dopo, e riprende da li'.

I giri non sono quelli dei timer, perche' qui il periodo e' finito: il
giorno si scrive in due passate (prima la seduta con la voce della sera, poi
il corpo con quella del mattino), la settimana pure (prima la chiusura, poi
l'apertura). L'apertura di una settimana legge il report di
quella **precedente**: se non c'e' ancora, si salta e la scrive il
rilancio dopo, quando c'e'.

**Sono ore di agenti**: sei sezioni per giorno, a una ventina di secondi
l'una, fanno un paio d'ore e mezza per gli ottanta giorni da agosto; le
settimane mezz'ora. Si lancia quando non c'e' altro in corso.

### I timer di systemd

> I comandi per accendere, guardare e rimettere in piedi quello che gira
> sulla macchina stanno tutti in **[`docs/service.md`](docs/service.md)**.
> Qui c'e' il perche'.

I giri sono **timer di systemd utente**, in `deploy/`:

```bash
make install_services                      # app e timer, ripetibile
make uninstall_services                    # li toglie
systemctl --user list-timers 'mygarmin-*'  # quando girano
journalctl --user -u 'mygarmin-*' -f       # com'e' andata
systemctl --user --failed                  # cosa e' andato storto
```

Tre coppie, con gli stessi orari delle righe di cron che c'erano prima:
`mygarmin-morning` alle 8, `mygarmin-evening` alle 21 da lunedi a sabato,
`mygarmin-weekend` la domenica alle 21. La domenica e' un'unita' sola con due
`ExecStart` perche' il settimanale deve girare **dopo** il giornaliero: il
lock ne lascia passare uno alla volta e chi lo trova occupato se ne va senza
fare niente. Il `-` davanti al primo e' il `;` del crontab — se il giorno
fallisce, la settimana gira lo stesso.

Le unita' allargano il `PATH` con la cartella di `uv`, e **non basta
scrivere `uv` per intero**: dentro il lavoro c'e' un `make update_activity`
che a sua volta chiama `uv run`. I primi due giri automatici sbagliarono
proprio qui, e i report furono scritti sui dati vecchi.

#### Perche' si e' tornati ai timer (todo 81)

Il todo 47 li aveva messi, e poi erano stati sostituiti da cron con un
ragionamento giusto: su una macchina accesa sempre, recuperare un giro
saltato non vale il prezzo dei timer utente, che girano solo finche' sei
collegato.

**Quello che ha fatto cambiare idea non e' il recupero, e' la visibilita'.**
Il 21 ottobre due giri scrissero i report su dati vecchi (`uv: not found`) e
uscirono **0**: cron era contento e non se ne accorse nessuno. Adesso il
comando esce 1 anche quando lo scaricamento fallisce (todo 81), e con i timer
quell'uscita lascia l'unita' elencata da `systemctl --user --failed` finche'
non la si azzera — un guasto si vede anche passandoci davanti mezza giornata
dopo. Cron questo non lo sa fare: al massimo lascia una riga in un file che
nessuno apre.

In piu' l'output va nel journal, che ruota da solo:
`~/.local/state/mygarmin-report.log` cresceva e basta, e non c'era niente
che lo tagliasse mai. Il file vecchio resta dov'e', fermo all'ultimo giro di
cron.

#### Il prezzo: `Linger`

Resta quello di allora. I timer utente girano da quando fai l'accesso, e
senza accesso non girano:

```bash
sudo loginctl enable-linger $USER   # i timer girano anche senza sessione
```

Senza, `Persistent=true` fa comunque partire al login il giro perso — su un
fisso a cui ti colleghi e' il recupero che volevi. Ma su una macchina che
nessuno logga, **senza `enable-linger` i report non si scrivono affatto**, ed
e' peggio di cron. `make install_services` lo dice quando vede `Linger` spento.

**Dal todo 82 `Linger` serve anche all'app**: senza, il servizio che serve
la pagina si spegne quando esci, e dalla tailnet non risponde piu' niente.

#### Le righe di cron, se servisse tornarci

`deploy/crontab` resta, con `make install_cron` e `make uninstall_cron`.
`install_services` toglie le righe `# mygarmin` dal crontab, perche' i due
meccanismi insieme si ruberebbero il lock a vicenda: ogni giro troverebbe
l'altro in corso e uscirebbe senza fare niente — il silenzio che somiglia al
successo.

Un lavoro alla volta vale anche fra processi diversi, con un lock su file in
`<dati>/.refresh.lock`: se un giro parte mentre premi Refresh, il secondo se
ne va senza fare niente.
