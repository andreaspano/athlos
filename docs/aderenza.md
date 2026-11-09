# Misurare l'andamento rispetto a un piano di allenamento

Due misure separate, da non fondere in un numero unico:

1. **Aderenza**: quanto stai seguendo il piano (l'esecuzione).
2. **Risposta**: quanto il piano sta funzionando (il risultato).

Se l'aderenza e' alta e la risposta non arriva, va cambiato il piano. Se
l'aderenza e' bassa, il piano non e' stato messo alla prova.

---

## 1. Aderenza al piano (0-100)

Si calcola per ogni seduta prevista, poi si aggrega per settimana.

### Volume

Rapporto fra fatto e previsto, sul carico (training load di Garmin) o, se
manca, sulla durata:

```
r = fatto / previsto
s_vol = max(0, 1 - |ln r| / ln 2)
```

- vale 1 se fai esattamente il previsto;
- vale 0 se fai il doppio o la meta';
- e' simmetrico in scala logaritmica: strafare pesa quanto fare meno.

| r    | s_vol |
|------|-------|
| 0.50 | 0.00  |
| 0.75 | 0.58  |
| 0.90 | 0.85  |
| 1.00 | 1.00  |
| 1.10 | 0.86  |
| 1.25 | 0.68  |
| 2.00 | 0.00  |

### Intensita'

Somiglianza fra la distribuzione del tempo nelle zone cardiache prevista e
quella fatta (frazioni che sommano a 1, zone Z1-Z5):

```
s_int = 1 - 0.5 * sum_z |previsto_z - fatto_z|
```

- vale 1 con la stessa distribuzione;
- vale 0 se non c'e' nessuna sovrapposizione.

Se il piano indica una sola zona bersaglio, `previsto_z` vale 1 su quella
zona e 0 sulle altre.

### Punteggio della seduta

```
seduta = (s_vol + s_int) / 2
```

- seduta prevista e non fatta: 0;
- seduta fatta e non prevista: nessun punteggio, ma entra nel carico
  settimanale;
- seduta di riposo prevista e rispettata: non entra nella media (non c'e'
  niente da eseguire), ma un allenamento fatto al suo posto conta come seduta
  non prevista.

### Punteggio della settimana

Media dei punteggi delle sedute, pesata sul carico previsto; le sedute chiave
(lungo, ripetute, test) hanno peso doppio:

```
peso_i = carico_previsto_i * (2 se chiave, 1 altrimenti)
aderenza = 100 * sum(peso_i * seduta_i) / sum(peso_i)
```

### Rapporto di carico

Accanto all'aderenza, sempre:

```
rapporto_carico = carico_fatto_settimana / carico_previsto_settimana
```

Comprende anche le sedute non previste. L'aderenza dice *come* hai eseguito,
il rapporto dice se sei sopra o sotto il piano (es. 1.12 = 12% in piu').

### Esempio

Previsti 45 minuti tutti in Z2; fatti 50 minuti, 40 in Z2 e 10 in Z3.

- r = 50 / 45 = 1.11, quindi s_vol = 0.85
- s_int = 1 - 0.5 * (|1.0 - 0.8| + |0.0 - 0.2|) = 0.80
- seduta = (0.85 + 0.80) / 2 = **83**

---

## 2. Risposta al piano

Per un obiettivo di mezza maratona:

- **Efficienza aerobica**: velocita' / frequenza cardiaca nelle uscite in Z2
  (o velocita' equivalente in piano, per togliere l'effetto del dislivello),
  come tendenza su 4 settimane. Collegato al todo 21 di mygarmin.
- **Tempo previsto sulla mezza** (stima di Garmin, o un modello proprio), come
  numero di sintesi da seguire nel tempo.

Lettura combinata:

| Aderenza | Risposta    | Lettura                                   |
|----------|-------------|-------------------------------------------|
| alta     | in crescita | il piano funziona                         |
| alta     | piatta      | rivedere il piano                         |
| bassa    | qualunque   | prima migliorare l'esecuzione             |

---

## Cosa serve

Il piano deve essere un dato strutturato. Per ogni seduta:

| campo          | esempio              | note                                  |
|----------------|----------------------|---------------------------------------|
| data           | 2026-11-12           |                                       |
| tipo           | corsa                | sport                                 |
| durata_min     | 45                   | o carico previsto                     |
| carico         | 80                   | facoltativo, se si pianifica in carico |
| zone           | {Z2: 1.0}            | frazioni di tempo per zona            |
| chiave         | false                | true per lungo, ripetute, test        |

I dati del fatto ci sono gia': durata e carico per attivita', tempo per zona
dai record (come per i minuti per effetto).

## Domande aperte

- Dove sta il piano: Garmin Coach o calendario di Garmin Connect, un'app
  esterna, o un file proprio?
- Come abbinare una seduta fatta a quella prevista quando cade in un altro
  giorno (finestra di +/-1 giorno?).
- Se le zone vanno valutate sui battiti (come oggi) o sul passo per le sedute
  di ripetute, dove i battiti arrivano in ritardo.
- Confronto con il todo 14 `plan_vs_done` gia' presente in mygarmin.
