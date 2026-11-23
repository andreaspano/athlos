---
status: done
---

# Il report della settimana lo scrive il modello di casa: le quattro spezzate

Da dove viene: dal **21 novembre 2026** le quattro card del corpo del giorno
le scrive llama e non piu' Claude (`sections.LOCAL_FROM`). La settimana e'
rimasta fuori, e non per una ragione: e' rimasta fuori perche' la strada e'
stata aperta un pezzo alla volta e quello e' il pezzo che non e' stato
fatto. Oggi la cosa e' scritta in un'asserzione, che e' il modo giusto di
tenere ferma una scelta e il modo sbagliato di tenerne ferma una mancanza:

```python
# api/sections.py
assert not any(s.local for s in WEEK_SECTIONS)
```

Questo todo fa per la settimana quello che il 21 novembre e' stato fatto per
il giorno: **le quattro card del corpo — Health, Load, Recovery, Fitness —
le scrive il modello di casa in pezzi, un paragrafo per misura.** La
Training e il Summary restano di Claude, come nel giorno: la prima giudica
sette giorni di sedute, il secondo legge i frammenti degli altri, e sono i
due mestieri che la spezzata non sa fare.

## Quello che non c'e' da costruire

Vale la pena dirlo prima, perche' cambia la dimensione del lavoro: **la
macchina delle misure ci serve quasi senza modifiche.**

`_measure_facts` legge di una misura **solo** `value`, `band`, `where`, il
suo `alert` e `missing`, piu' la chiave sotto cui cercarla
(`Split.measures_in`). Non tocca `avg_7d` ne' `avg_28d`. E una misura della
settimana ha quello che serve:

```json
{"card": "health", "label": "Resting heart rate", "unit": "bpm",
 "value": 51, "band": {"low": 49, "high": 51, "outer_low": 48, "outer_high": 52},
 "weeks": 12}
```

Stessa fascia a quattro bordi del giorno, quindi `_where`, `_sits` e
`_reading` funzionano come stanno. **`measures_in` e' il campo che era stato
messo esattamente per questo**: la sua docstring dice che era «la sola cosa
che impediva alla macchina delle misure di servire anche la terza sezione»,
e li' si trattava di far leggere `scores` invece di `morning`. Qui si tratta
di far leggere `measures`, ed e' lo stesso gesto.

Due altre cose ci sono gia':

- `refresh._facts(kind, subject, data_dir)` **smista gia'** fra
  `daily_payload` e `weekly_payload`. Il percorso locale non lo usa:
  `_write_local_section` chiama `daily_payload` scritto a mano, e non
  riceve nemmeno `kind`.
- ogni misura della settimana porta `card`, quindi il recinto di una
  sezione si **ricava** (`card == "health"`) invece di elencarlo a mano,
  come fa oggi `RECOVERY_MEASURES` per il giorno. Una lista in meno da
  tenere d'accordo.

## Quanti agenti, e quali

**Una chiamata al modello per misura, piu' una in cima**, come nel giorno:
non una chiamata per sezione. E' il punto di tutta la strada della spezzata e
va detto qui perche' e' la cosa che si perde traducendo: un paragrafo per
misura, **ognuno cieco agli altri**, e l'ordine e il numero li decide Python
cucendo i pezzi. Un modello da otto miliardi che riceve quattro misure
insieme ne impasta due in una frase e spiega l'una con l'altra — e' la
ragione per cui `_measure_facts` mette dentro una misura sola, ed e'
documentata li'.

Il conto, dai fatti della settimana del 16 novembre:

| Sezione | Pezzi | Chiamate | Da dove vengono i pezzi |
|---|---|---|---|
| `w1_health_split` | `resting_hr`, `hrv_last_night`, `resp_sleep_avg`, `stress_avg` | 1 + 4 = **5** | `measures` con `card == "health"` |
| `w2_load_split` | `low_aerobic`, `high_aerobic`, `anaerobic`, `carrying`, `balance` | 1 + 5 = **6** | il blocco `zones`, piu' `load` |
| `w3_recovery_split` | `readiness`, `sleep_hours`, `body_battery_wake`, `body_battery_low` | 1 + 4 = **5** | `measures` con `card == "recovery"` |
| `w4_fitness_split` | `vo2max`, `endurance`, `hill`, `threshold`, `altitude_acclimation`, `heat_acclimation` | 1 + 6 = **7** | il blocco `fitness` |

Ventitre chiamate in tutto, **le stesse ventitre** delle quattro del giorno
(5 + 6 + 5 + 7). Tutte e quattro le sezioni sono un **parallelo esatto**: gli stessi pezzi, gli stessi nomi a meno della media (`resp_sleep`
diventa `resp_sleep_avg`, `body_battery_morning` diventa
`body_battery_wake`), e un file di prompt per pezzo in
`.ollama/agents/wN_..._split/`.

**La Load legge un'altra chiave, e non e' una scelta aperta.** Il blocco
`load` della settimana non ha le tre intensita' del giorno —
`load_aerobic_low`, `load_aerobic_high`, `load_anaerobic` — e **non deve
averle**: sono il carico degli ultimi **28 giorni**, lo dice la tabella del
todo 54, e tenerle fuori e' stato chiesto in queste parole il 23 ottobre
2026 — *«le misure che voglio vedere nella settimana sono i dati di quella
settimana, non di 28 giorni»*. `WEEK_LOAD_KEYS` e' quella richiesta scritta
in codice. Allargare quel blocco vorrebbe dire disfare il todo 54: non si
fa.

La misura settimanale di quella composizione **esiste gia'** ed e' il
secondo tempo dello stesso todo 54: i **minuti per zona**, contati sulla
serie di frequenza di ogni seduta coi confini di zona di quella seduta. Nei
fatti della settimana e' il blocco `zones`, e ha la forma che la macchina
delle misure mangia — tre misure, ognuna coi suoi minuti e la sua fascia di
dodici settimane:

```json
"low_aerobic":  {"minutes": 120, "band": {"low": 258, "high": 482, ...}, "weeks": 10},
"high_aerobic": {"minutes":  68, "band": {"low":  18, "high":  54, ...}, "weeks": 10},
"anaerobic":    {"minutes":   1, "band": {"low":   0, "high":   2, ...}, "weeks": 10}
```

Quindi i cinque pezzi della Load del giorno restano cinque e cambiano
sorgente: i tre carichi diventano i tre **tempi** per zona, letti da `zones`
invece che da `load`. L'unica cura in piu' e' che il valore si chiama
`minutes` e non `value`, e che il pezzo parla di minuti: la fascia e' in
minuti, e un paragrafo che dicesse "carico" starebbe mentendo sull'unita'.

Le due parti che restano di Claude non cambiano: `w5_training` e
`w7_summary`, un agente l'uno, come oggi.

## Il lavoro

1. **Quattro splits nuovi** — `w1_health_split`, `w2_load_split`,
   `w3_recovery_split`, `w4_fitness_split` — con il loro ritaglio dei fatti
   della settimana e `measures_in="measures"`. Entrano in `ollama.SECTIONS`,
   che e' anche quello che li rende chiedibili dalla pagina Test: **e' la'
   che si guardano prima di metterli in produzione**, un giro alla volta,
   come e' stato fatto per le quattro del giorno.
2. **Le cartelle dei prompt** sotto `.ollama/agents/w1_health_split/` e
   compagnia: un file per misura, un `_measure.md` e un `_verdict.md`,
   derivati da `.claude/agents/w1_health.md` e dai fratelli. Derivati e non
   copiati: i file di `.claude/agents/` portano l'esempio in fondo, e un
   esempio llama se lo ricopia invece di guardare i numeri — e' la ragione
   per cui le due cartelle sono due, e l'esempio del sonno tolto da
   `SLEEP_READS` il 23 novembre 2026 e' la seconda volta che quella lezione
   e' costata un numero sbagliato nel report.
3. **Niente altro.** La produzione — `_write_local_section` che prende
   `kind`, l'asserzione di `sections.py` che cambia verso, le quattro
   `WEEK_SECTIONS` che prendono il loro `local=` e la data da cui vale — sta
   nel **todo 102**, insieme al banco che la deve autorizzare. Qui si
   costruisce e si guarda dalla pagina Test; il giro della domenica non si
   tocca, e nemmeno quello del mattino.

## Le due cose che il giorno non insegna

**La settimana non ha `alerts` e non ha `missing`.** I fatti della settimana
non hanno nessuna delle due chiavi: hanno `coverage`, che e' per metrica e
non per giorno — «readiness e carico Garmin li calcola anche senza
orologio al polso, le altre no». Quindi `_measure_facts` su un ritaglio
della settimana darebbe `alert: null` sempre e `missing: false` sempre,
anche su una misura che in sette giorni e' stata presa due volte. Una media
sottile va detta sottile, e la cosa che lo sa e' `coverage`: va portata nel
ritaglio al posto di `missing`, o accanto.

**E la voce e' un'altra.** Il campo `day` dei ritagli finisce nell'intestazione
del messaggio («the daily report for Monday 23 November 2026»), e per la
settimana va sostituito dai suoi due estremi — `Report.period()` li scrive
gia'. Non e' una formalita': le quattro card del giorno parlano di stamattina
e le quattro della settimana parlano di **medie su sette giorni**, e lo
`_style.md` di llama ha la riga che lo dice per Claude («a number is a
week's number»). Il prompt di ogni misura va scritto in quella voce, non
tradotto da quello del giorno.

## Dove si guarda

Dalla **pagina Test**, che e' il motivo per cui il punto 1 mette i quattro
splits in `ollama.SECTIONS`: la pagina sa chiedere una chiave e mostrare il
testo, e non salva niente. Sul disco stanno **16 settimane** scritte da
Claude, dal 3 agosto al 16 novembre: sono il termine di paragone, una
sezione alla volta.

Il confronto serio — quello che ha autorizzato il passaggio del giorno, un
mese di banco — e' il **todo 102**. Questo todo e' finito quando le quattro
sezioni si chiedono dalla pagina e il testo che ne esce sta in piedi: i
paragrafi giusti, nell'ordine giusto, ognuno sulla sua misura, i numeri
quelli dei fatti.

## Effetti fuori dal repo

**Nessuno.** La pagina Test scrive il testo e non lo salva da nessuna parte,
e nessuna delle quattro sezioni nuove e' ancora in `WEEK_SECTIONS`: i
frammenti di `summary/02.weekly/` continuano a scriverli gli agenti di
Claude, come ieri. Quello che si scrive sul disco e' materia del todo 102.

## Revert

```bash
git revert -m 1 $(git log main --merges --grep="^Merge branch 'todo_101'$" --format=%H -1)
```

Effetti fuori dal repo: **nessuno.** La pagina Test scrive il testo e non lo
salva da nessuna parte, e nessuna delle quattro spezzate nuove e' in
`WEEK_SECTIONS`: i frammenti di `summary/02.weekly/` li hanno scritti e
continuano a scriverli gli agenti di Claude, prima e dopo il revert. In
`activities.db` non si tocca niente.

L'unica cosa che il revert porta via oltre al codice e' la correzione di
`.claude/agents/w3_recovery.md`, che il todo 100 aveva lasciato indietro:
quel file diceva all'agente della Recovery della settimana di leggere
`body_battery_high`, che in `measures` non c'e' piu'. Tornando indietro torna
anche quella riga sbagliata — e la Recovery della settimana e' di Claude
fino al todo 102, quindi la riga la legge lui.

Dopo il revert, rifare il merge di `todo_101` non riporta le modifiche (git
le considera gia' unite): per riaverle serve il revert del revert.
