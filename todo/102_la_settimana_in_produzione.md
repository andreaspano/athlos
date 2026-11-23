---
status: todo
---

# La settimana di casa in produzione, e il banco che la autorizza

Secondo tempo del **todo 101**, che costruisce le quattro spezzate della
settimana — `w1_health_split`, `w2_load_split`, `w3_recovery_split`,
`w4_fitness_split` — e si ferma alla pagina Test. Qui si decide se sono
abbastanza buone da sostituire Claude, e se si', si mettono al loro posto.

**I due pezzi stanno in quest'ordine e non nell'altro.** Il giorno e' passato
al modello di casa il 21 novembre 2026 dopo un mese di confronto cominciato
il 26 ottobre, non dopo una lettura a occhio. Fare la settimana senza quel
confronto vorrebbe dire prendere la stessa decisione con meno di quanto si
aveva per la prima. E c'e' una ragione in piu' che il giorno non aveva: **una
card della settimana sbagliata si vede per sette giorni.** Il numero sbagliato
del sonno del 23 novembre e' stato trovato in giornata perche' la Day la si
apre ogni mattina; la Week la si apre di meno, e un errore ci resta.

## 1. Il banco della settimana

Oggi il banco e' **solo del giorno**: `bench_tune._facts_of` chiama
`daily_payload`, e `CORPUS_FROM`/`CORPUS_TO` (26 ottobre - 20 novembre)
delimitano giorni di `summary/01.daily/`. Per la settimana non c'e' ne'
corpus ne' punteggio.

Il materiale c'e': sul disco stanno **16 settimane** scritte da Claude, dal
3 agosto al 16 novembre. Quattro card l'una fanno **64 testi**, lo stesso
ordine di grandezza dei 104 del giorno.

Quello che il banco della settimana vuole, e che non ha:

- `_facts_of` che smista fra giorno e settimana, come fa gia'
  `refresh._facts`;
- un corpus suo, con i suoi estremi: lunedi, non giorni;
- `bench_score` che allinea paragrafo e pezzo passa da `ollama.asked(split,
  facts)` ed e' quindi gia' generico — **da verificare, non da dare per
  buono**.

**Un buco noto, e questo e' il posto per chiuderlo.** `bench_score._numbers`
raccoglie solo le cifre: la sua docstring dice che *«quelli in parole non si
prendono: eight hours nine non si vede, e non e' un problema»*. E' il motivo
per cui il difetto del sonno del 23 novembre 2026 e' passato — quel
paragrafo e' l'unico che il suo numero lo scrive in parole, e il banco quelle
non le guarda. Adesso che `sleep_clock` sta nei fatti, un confronto per
sottostringa lo prenderebbe. **Cambia i punteggi gia' calcolati**, quindi e'
una decisione di Andrea e non dell'implementatore: se la risposta e' no, il
buco resta scritto qui.

## 2. La produzione

Solo se il banco dice di si'.

1. **`_write_local_section` prende `kind`** e chiama `_facts(kind, ...)` al
   posto di `daily_payload`. Attenzione alla ragione scritta nella sua
   docstring: **non** si rilegge il JSON temporaneo di `_prepare`, perche'
   la' le date sono passate da `_jsonable` e sono diventate stringhe.
   `_facts` rende il dizionario vivo, quindi va bene.
2. **L'asserzione cambia verso.** Oggi `sections.py` dice
   `assert not any(s.local for s in WEEK_SECTIONS)`, e le quattro
   `WEEK_SECTIONS` prendono il loro `local=`. Quella sotto — «le sezioni che
   scrive il modello di casa sono tutte del giro del mattino» — vale per il
   giorno; per la settimana l'equivalente e' che stiano nel giro unico della
   domenica.
3. **Una data, `WEEK_LOCAL_FROM`**, un lunedi, per la ragione per cui esiste
   `LOCAL_FROM` e che sta scritta accanto a lui: `backfill_reports` rifa'
   periodi passati, e senza la data un backfill di settembre riscriverebbe
   con llama le settimane che Claude ha scritto — cambiando il report a
   posteriori e **cancellando dal disco il corpus del punto 1**. La data va
   scelta dopo la fine del corpus, non prima.

## Il giro della domenica

Le quattro sezioni di casa stanno tutte nel giro unico della domenica sera
(`WEEK_MOMENT_SECTIONS`, todo 68), in coda a quello del giorno. Quattro
spezzate fanno **23 chiamate al modello** invece di quattro ad agente: con i
tempi del giorno sono un paio di minuti in piu' su un giro che gira alle 21
e non ha nessuno che lo aspetta. Non e' un problema, ma va guardato la prima
domenica.

E vale la regola del giorno: **se ollama non risponde la sezione fallisce e
si vede**, nessuna ricaduta su Claude. Il perche' sta nella docstring di
`_write_local_section` — un report completo in cui non si sa chi ha scritto
cosa e' peggio di una card che manca.

## Effetti fuori dal repo

Dal punto 2 in poi i frammenti di `summary/02.weekly/<lunedi>/` li scrive
llama. Quelli gia' sul disco restano di Claude e non si toccano: e' il
mestiere della data del punto 3, ed e' anche quello che tiene in vita il
corpus del punto 1. Un revert del codice non riscrive i frammenti che llama
avra' gia' scritto — per tornare indietro su una settimana va rifatta.
