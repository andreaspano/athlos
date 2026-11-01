---
status: done
---

# Il dettaglio del piano in ogni riga

La colonna Plan della vista Training della Week mostra sette righe cosi':

```
Mon 9 Nov    Rest · or Cycling
Tue 10 Nov   Running · easy · 8 km
Thu 12 Nov   Running · quality · 9 km
```

Dicono **quanto** e non **come**. Una qualita' da `5 x 5' a 5'55"` e un lento
da otto chilometri diventano due righe che si somigliano, e il perche' di
quella giornata — i ritmi, il tetto del battito, le ripetute, il lavoro di
forza — resta nel file.

E il file ce l'ha, e l'API lo manda da sempre: `PlannedSession.text` e' la
riga di quel giorno nella tabella del piano (`_day_row` in `api/plans.py`).
**La card della Day la mostra dal todo 63**; questa colonna la buttava via.

## Cosa si fa

In `PlanDayRow` (`WeekPlanCard.tsx`), sotto la riga corta, il testo della
tabella: `inline(session.text)`, come fa `DayPlanCard` — grassetto e corsivo
si', blocchi no, che e' mezza riga di tabella e non un documento.

**La riga corta resta sopra**, in tono pieno. E' il riassunto a macchina, e
sta sulla riga della seduta **fatta** nella colonna accanto (todo 77): quel
confronto e' fra due righe corte, e sostituirla con una frase lo
rovinerebbe. Il dettaglio sta sotto, in tono minore e piu' piccolo, perche'
li' parla il documento.

In colonna e non affiancati (`.plan-session` a griglia): il dettaglio e' una
frase, e su una riga sola spingerebbe i chilometri fuori vista.

Un giorno **senza riga nella tabella** non ha dettaglio e non lascia un buco:
il piano puo' non averlo, e il file di settembre 2026 non ce l'ha affatto.

## Quello che non va toccato

- **La vista Plan** (`WeekPlanCard`): li' c'e' il documento intero, tabella e
  prosa. Questa e' la colonna dei dati, e dal todo 71 sono due domande.
- **La griglia condivisa delle due colonne** (todo 73 e 77). E' lei che fa
  funzionare questo: una riga che si alza perche' il dettaglio va a capo alza
  anche quella di fronte, e i due giorni restano affiancati.
- `sessionLabel` e `sessionIcon`: il riassunto non cambia.
- La card della Day, che il dettaglio lo mostrava gia'.

## Rischi

- **La colonna diventa alta.** Sette dettagli sono sette frasi, e la vista
  Training era gia' lunga: sul telefono, dove le due colonne si impilano, il
  piano occupa una schermata da solo. E' il prezzo di vedere cosa chiede la
  settimana senza aprire un'altra vista.
- **Il dettaglio ripete il riassunto.** «Easy 8 km at 7'10"-7'45"» sta sotto
  «Running · easy · 8 km»: i chilometri si leggono due volte. Togliere il
  riassunto romperebbe l'allineamento con le sedute fatte, togliere il
  dettaglio e' tornare a prima.
- **Dipende da come l'agente scrive la tabella.** Il testo e' mezza riga di
  markdown scritta da `p_week` (todo 86): una riga lunga tre frasi diventa un
  paragrafo in una griglia di sette.

## Come e' andata

Fatto. Le sette righe adesso portano le parole del piano.

### Verificato

La pagina in un DOM (jsdom sul bundle vero, contro l'API accesa), due
settimane:

- **W46, prevista**: sette righe, **tutte e sette col dettaglio** —
  `Tue 10 Nov | Running · easy · 8 km | Easy 8 km at 7'10"-7'45", heart rate
  125-138, then 6 x 20 s strides…`, e `Thu 12 Nov` con `Quality: 2.5 km easy,
  then 5 x 5 min at 5'55"-6'05"…`;
- **questa settimana**: le stesse sette righe col dettaglio, e la colonna
  delle sedute fatte intatta, sette righe;
- il grassetto del markdown arriva come `<strong>` (quattro per settimana),
  non come asterischi;
- nessun errore in console.

`npm run typecheck` pulito, `npm run build` ok, servizio riavviato.

### Quello che non ho provato

**Lo schermo**: jsdom non ha motore di stile, quindi quanto si alzano le
righe e come i due giorni restano affiancati non l'ho visto. E' la cosa da
guardare, soprattutto sul telefono.

## Revert

```bash
git revert -m 1 $(git log main --merges --grep="^Merge branch 'todo_89'$" --format=%H -1)
```

Effetti fuori dal repo: nessuno. Resta solo la pagina compilata in
`frontend/dist/`, che si rifa' con `make frontend_build`.

Dopo il revert, rifare il merge di `todo_89` non riporta le modifiche (git le
considera gia' unite): per riaverle serve il revert del revert.
