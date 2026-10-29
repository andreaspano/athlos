---
status: done
---

# La tabella dei giri nella card Session

Il 29 ottobre e' tornata la qualita': 2 km piano, 4 x 5 min a 5'55"-6'05",
2 min di recupero, 1,5 km piano. Il report l'ha raccontata bene, ma per
sapere **come sono andate le quattro ripetute** una per una non c'era niente
da leggere: la card Session da' i totali della seduta (7,6 km, 58 min, 131
bpm medi) e il grafico da' la traccia istante per istante, e fra i due manca
il pezzo che serve a chi ha corso delle ripetute — quanto e' andata la prima,
quanto l'ultima, se il recupero ha recuperato.

Quel pezzo **l'orologio l'ha gia' scritto**. Il FIT del 29 ottobre porta
dodici messaggi `lap`, e non sono i giri automatici al chilometro: ognuno ha
il suo `wkt_step_index`, cioe' il passo dell'allenamento che l'orologio stava
seguendo.

```
#   intensity  trigger   time_s  dist_m    kmh   ahr  mhr  wkt
1   warmup     distance     466    1000   7.73   113  146   0
2   warmup     distance     440    1000   8.18   126  130   0
3   active     time         300     842  10.10   140  147   1
4   recovery   time         120     268   8.04   130  140   2
5   active     time         300     827   9.93   140  145   1
6   recovery   time         120     229   6.88   124  142   2
7   active     time         300     827   9.92   139  146   1
8   recovery   time         120     249   7.47   132  146   2
9   active     time         300     844  10.12   141  145   1
10  cooldown   distance     425    1000   8.47   134  143   4
11  cooldown   distance     205     500   8.77   135  138   4
12  cooldown   session_end    7      15   8.09   138  139   None
```

Le quattro ripetute sono li', 300 secondi esatti ognuna: 5'56", 6'03",
6'03", 5'56" a 140, 140, 139, 141 bpm. **Questi numeri oggi si buttano**:
`fit.py` legge solo i messaggi `record`, e i `lap` non entrano nel database.

## Cosa si fa

I giri si leggono, si tengono nel database, e **la card Session ne disegna la
tabella** sotto la barra degli effetti e sopra il grafico — prima i totali,
poi com'era fatta la seduta, poi la traccia.

### 1. I giri dal FIT — `interface/fit.py`

`load_activity_laps(path)`, accanto a `load_activity_records`: una riga per
messaggio `lap`, con `message_index`, `intensity`, `lap_trigger`,
`total_timer_time`, `total_distance`, `enhanced_avg_speed` (o `avg_speed`),
`avg_heart_rate`, `max_heart_rate`, `avg_running_cadence`, `total_ascent` e
`wkt_step_index`.

L'`intensity` va mappata a mano: il profilo di fitparse conosce i primi
quattro valori dell'enum e rende le stringhe `active`, `rest`, `warmup`,
`cooldown`, ma gli altri li lascia interi — nel FIT del 29 ottobre i
recuperi sono `4` (recovery) e in una corsa libera **tutti** i giri sono `5`
(interval). La mappa copre 0-6 e chi non la conosce resta com'e'.

### 2. Il database — `interface/db.py`

Tabella `laps` dentro `_SCHEMA` (`activity_id` + `lap_index` come chiave,
`ON DELETE CASCADE` come `records`), un `_insert_laps` chiamato da
`_parse_and_store`, e `load_activity_laps(activity_id)` per rileggerli.

`LOGIC_VERSION` da `"8"` a `"9"`: la tabella nuova nasce vuota, e i giri
delle 980 sedute di prima si trovano solo rileggendo i FIT. E' un `rebuild`
intero, e **non e' una colonna da aggiungere a mano** come quelle di
`_ADDED_COLUMNS` (todo 54): quelle si ricavavano dai record gia' in tabella,
questi no, stanno solo nel file. Tutto in locale, nessuna chiamata a Garmin.

### 3. Strutturata o no — la regola

Una seduta ha una tabella **solo se almeno un giro porta un
`wkt_step_index`**: allora l'orologio stava seguendo un allenamento, e i giri
sono i pezzi di cui era fatto. Senza, i giri sono l'auto-lap al chilometro
(`lap_trigger` `distance`, `intensity` 5, `wkt_step_index` vuoto) e la
tabella non si disegna: su una corsa libera sarebbero nove righe di numeri
che nessuno ha chiesto, su ogni corsa dell'anno.

I nomi delle righe li decide l'API e non il browser, cosi' il testo del
report e la tabella dicono la stessa cosa: `warmup` → "Warm-up", `cooldown`
→ "Cool-down", `active` → "Rep 1", "Rep 2", ... contando gli attivi,
`rest`/`recovery` → "Recovery". L'ultimo giro chiuso da `session_end` di
pochi secondi (sette, il 29 ottobre) **non e' un giro**: sotto i trenta
secondi, e con la seduta che finisce, non va in tabella.

### 4. L'API — `api/models.py`, `api/app.py`

`GET /api/activities/{activity_id}/laps` → `{structured: bool, laps: [...]}`,
accanto a `/chart` e `/route`, che e' il posto dove la card va a prendersi il
resto. Una seduta non strutturata rende `structured: false` e la lista vuota.

Il campo `pace_s_per_km` lo calcola l'API dai metri e dai secondi del giro,
e **sul tapis roulant non c'e'** (`distance_unreliable`, todo 45): la
distanza la indovina il polso, e un ritmo costruito su quella sarebbe
inventato. Li' restano tempo, battiti e cadenza.

### 5. La card — `frontend/`

- `api/client.ts`: `api.laps(id)`, e `schema.ts` rigenerato (`make
  frontend_types`, con l'API accesa).
- `components/TrainingCard.tsx`: un `LapTable` fra `EffectsBar` e
  `RunChart`, disegnato solo se `structured`. Colonne: numero, cosa era,
  tempo, distanza, ritmo, battiti medi e massimi.
- `format.ts`: `paceLabel(seconds)` → `5'56"`. **E' la prima volta che
  l'interfaccia parla in minuti al chilometro** — finora tutto era in km/h —
  e qui ci vuole: il piano chiede una fascia di ritmo, le ripetute si
  giudicano contro quella, e nessuno corre guardando i km/h.
- `styles.css`: la tabella in `.lap-table`, stretta e allineata a destra sui
  numeri, e dentro `.table-scroll` come le tabelle dei piani.

### 6. Il report — `.claude/agents/05_training.md`

I giri entrano anche nei fatti (`sessions.today.laps`, da
`daily_data._session`), ma **solo perche' l'agente possa citarli nel
discorso** — "5'56", 6'03", 6'03", 5'56": sette secondi su quattro
ripetute" e' una frase che prima non poteva scrivere. La tabella la disegna
la card: all'agente si dice di non farne una, che sarebbe la stessa cosa due
volte, con la differenza che la sua l'avrebbe ricopiata a mano.

## Quello che non va toccato

- Il grafico (`run_chart.py`, `RunChart.tsx`): i giri sono un'altra cosa, e
  le fasce a tre colori restano come sono.
- `records`: la tabella nuova gli sta accanto, nessuna colonna cambia.
- Il terreno e il tipo di corsa scelti a mano: stanno nei json di
  `data_dir` (`_add_terrain`, `_add_run_type`) e **il rebuild non li
  tocca**. Va verificato dopo, non dato per scontato.

## Rischi

- **Il rebuild.** `LOGIC_VERSION` nuovo e il primo `sync()` rilegge 980 file
  FIT. Va misurato, e va lanciato quando non gira un refresh: il lock di
  `refresh.py` sta in `data_dir`, e un rebuild a metta' di un report
  giornaliero non si sa cosa lascia.
- **I giri che non ci sono.** Le sedute vecchie, la bici, la palestra: zero
  `lap` o uno solo, `structured: false`, nessuna tabella. Non e' un errore ed
  e' il caso piu' comune.
- **`wkt_step_index` senza allenamento.** Se qualche FIT lo portasse pieno su
  una corsa libera, uscirebbe una tabella di nove chilometri. Da guardare
  sullo storico: quante sedute risultano strutturate, e se sono quelle giuste.

## Verifica

- Il 29 ottobre (24897459315): tabella con warm-up, le quattro ripetute a
  5'56"/6'03"/6'03"/5'56", i tre recuperi, il cool-down. Undici righe, non
  dodici: i sette secondi finali non entrano.
- Il 27 ottobre (24873771445, corsa libera, dieci giri automatici): nessuna
  tabella.
- L'indoor cycling del 28 (24884401594, un giro solo): nessuna tabella.
- Una seduta sul tapis roulant: se strutturata, tabella senza distanza e
  senza ritmo.
- Quante sedute dello storico risultano strutturate, con il conto a mano.
- Il terreno e il tipo scelti a mano ci sono ancora dopo il rebuild.
- `npm run typecheck` e `npm run build` puliti, nei due temi.

## Come e' andata

Fatto. La tabella sta nella card Session, fra la barra degli effetti e il
grafico, e sul 29 ottobre legge undici righe:

| | tempo | distanza | ritmo | bpm |
|---|---|---|---|---|
| Warm-up | 7:46 | 1,00 km | 7'46" | 113 |
| Warm-up | 7:20 | 1,00 km | 7'20" | 126 |
| **Rep 1** | **5:00** | **0,84 km** | **5'56"** | **140** |
| Recovery | 2:00 | 0,27 km | 7'28" | 130 |
| **Rep 2** | **5:00** | **0,83 km** | **6'03"** | **140** |
| Recovery | 2:00 | 0,23 km | 8'44" | 124 |
| **Rep 3** | **5:00** | **0,83 km** | **6'03"** | **139** |
| Recovery | 2:00 | 0,25 km | 8'02" | 132 |
| **Rep 4** | **5:00** | **0,84 km** | **5'55"** | **141** |
| Cool-down | 7:05 | 1,00 km | 7'05" | 134 |
| Cool-down | 3:25 | 0,50 km | 6'50" | 135 |

Le ripetute in grassetto, il resto in grigio: si guarda la tabella per
quelle, e sette secondi di differenza fra la prima e l'ultima si leggono
senza cercarli.

### Due cose che lo storico ha smentito, e che erano scritte qui sopra

**`wkt_step_index` da solo non basta.** Il todo diceva che un giro con un
passo dell'allenamento e' un pezzo di una seduta strutturata. Sulle 985
sedute non e' vero: tre portano `workout_step` a **zero su tutti i giri**,
che sono l'auto-lap al chilometro e nient'altro — una corsa del 28 settembre
2025, e la "Base" sul nastro del 20 ottobre, dove i "giri" durano 12 e 19
minuti. Il segnale vero e' che i passi siano **piu' di uno**: l'orologio e'
passato da un pezzo al successivo. Con la regola stretta, e almeno un giro
attivo, le sedute strutturate dello storico sono **sei**, e sono le sei
`Rip_*`. Con la regola del todo erano otto, due delle quali fasulle.

**L'intensita' non dice come si chiama un giro.** Nelle ripetute del 15
ottobre i recuperi fra una ripetuta e l'altra sono scritti `cooldown`, lo
stesso valore del defaticamento vero in fondo: a dar retta all'intensita'
quella seduta finiva cinque volte. Il nome adesso lo da' il **posto** —
prima del primo giro di lavoro e' riscaldamento, dopo l'ultimo e'
defaticamento, in mezzo e' recupero — e l'intensita' serve solo a
riconoscere il giro di lavoro. Sul 15 ottobre escono tre Warm-up, cinque
ripetute da 4 minuti con quattro Recovery, due Cool-down.

Il nome dell'allenamento, intanto, non e' una fonte: "Rip_4x5" sono cinque
ripetute da quattro minuti, "Rip_5min4T" sono quattro da cinque. I giri
dicono quello che e' successo, il nome quello che Andrea aveva in mente.

### Il rebuild

2112 secondi, 35 minuti, 985 sedute: 2,7 milioni di record e **6243 giri**,
983 sedute su 985 ne hanno almeno uno. Un terzo in piu' del solito perche'
`load_activity_laps` apre il FIT una terza volta, dopo il sommario e i
record — tre passate invece di due. Si poteva aprirlo una volta sola per
tutti e tre, ma avrebbe voluto dire riscrivere il giro di
`_parse_and_store`, e il rebuild e' una cosa che capita a ogni
`LOGIC_VERSION` e basta.

**Una trappola da ricordare, se capita di rifarlo:** a rebuild finito il
database sembrava **vuoto** — zero attivita', zero giri — con un WAL da 197
MB accanto. Non era vuoto: l'API accesa (`make api`) teneva una connessione
aperta, il checkpoint non poteva passare, e quel che si leggeva era il file
principale ancora alla pagina uno. Spento uvicorn, SQLite ha fatto il
checkpoint da solo e i 205 MB sono comparsi. **Chi lancia un rebuild spenga
prima l'API**, e non si spaventi per un conteggio a zero finche' c'e' un
`-wal` grosso nella cartella.

### Come e' stato verificato

- **Il 29 ottobre**: undici righe, quattro ripetute a 5'56", 6'03", 6'03",
  5'55", i sette secondi finali fuori dalla tabella. Visto nella pagina, nei
  due temi.
- **Il 15 ottobre**, la seduta con i recuperi scritti `cooldown`: quattordici
  righe, cinque ripetute, quattro Recovery in mezzo e due Cool-down in fondo.
- **La corsa libera del 27** (dieci giri automatici), **l'indoor cycling del
  28** (un giro), **la corsa del settembre 2025** e **la "Base" sul nastro**
  (passo sempre zero): nessuna tabella.
- **Il nastro**: nessuna seduta strutturata nello storico, quindi provato a
  mano con dei giri finti — distanza e ritmo spariscono, restano tempo e
  battiti, e la card toglie le due colonne.
- **Sei sedute strutturate** su 985, contate sul database ricostruito.
- **Il terreno e il tipo scelti a mano**: il 27 ottobre e' ancora
  `terrain_source: user`, `run_type_source: user` dopo il rebuild.
- `training-daily-data` sul 29 ottobre porta gli undici giri nei fatti;
  `training-weekly-data` gira.
- `npm run typecheck` e `npm run build` puliti, `make frontend_types` non
  muove piu' `schema.ts`.

## Revert

```bash
git revert -m 1 $(git log main --merges --grep="^Merge branch 'todo_79'$" --format=%H -1)
```

Effetti fuori dal repo: la tabella `laps` resta in `activities.db` con i suoi
6243 giri, e `logic_version` resta a "9". Sono innocui, il codice vecchio non
li legge — ma il codice vecchio ha `LOGIC_VERSION = "8"`, quindi il primo
`sync()` dopo il revert trova la versione diversa e **rifa il rebuild**: altri
35 minuti, una volta sola.

Dopo il revert, rifare il merge di `todo_79` non riporta le modifiche (git le
considera gia' unite): per riaverle serve il revert del revert.
