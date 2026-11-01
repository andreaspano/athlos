---
status: done
---

# Via anche la card del piano: della settimana restano le sette righe

Il todo 90 aveva tolto la vista Plan e salvato la sua card — titolo, i quattro
numeri del blocco, e la prosa della settimana senza la tabella dei giorni —
mettendola in fondo alla Training. Avevo argomentato che valeva la pena: due
terzi di quel testo (1.575 caratteri su 2.284, misurati) non stanno nel
blocco, e sono il registro delle decisioni di quella settimana — *«Saturday
and Sunday were swapped on 30 Oct, at Andrea's request… readiness 69, HRV 48
and balanced»*.

Guardata nella pagina, Andrea l'ha giudicata inutile. E' il suo giudizio sulla
sua pagina: la card va via.

## Cosa si fa

Via `WeekPlanCard` da `WeekPlanCard.tsx` — il componente, i quattro numeri
(`WeekPlanStats`) e i due filtri che gli servivano, `withoutDayTable` e
`withoutOpening`. Via l'uso e l'import in `WeekPage.tsx`, e via le regole
`.week-plan-card` dal CSS.

**`.plan-prose` e `.plan-file` restano**: non erano della card, le usa la
pagina Goal per il testo di un blocco.

Restano, nel file, le due cose che servono alla colonna: `PlanDayRow` (la riga
di un giorno col suo dettaglio, todo 89) e `blockWeek`, che scrive
`Week 3 of 18` accanto al titolo della colonna.

Del documento della settimana, nella pagina, **restano le sette righe**. Dove
sta il resto: le sedute giorno per giorno sono nelle righe, coi ritmi e il
perche' nel dettaglio; i ritmi completi e le regole di scarico sono quelli del
blocco e si leggono nella pagina Goal; l'inquadramento e le decisioni restano
scritti in `summary/05.plan/<lunedi>.md`, che e' un documento e si apre anche
da solo.

## Quello che non va toccato

- **La colonna del piano** e i dettagli del todo 89: sono quello che resta, e
  sono la parte che si usa.
- **`GET /api/weekly/<lunedi>/plan`** e il `body` intero che manda: la rotta
  non cambia. La pagina ne usa meno, chi legge l'API no.
- **I file di `summary/05.plan/`** e l'agente `p_week`: continuano a scrivere
  il documento come prima. Che la pagina ne mostri una parte non e' una
  ragione per scrivere meno — il file si legge anche fuori dall'app.
- `.plan-prose`, `.plan-file`: sono della pagina Goal.

## Rischi

- **Quello che la pagina non mostra, non si legge.** Le decisioni di una
  settimana — perche' il lunedi' e' libero, perche' sabato e domenica sono
  stati scambiati, le due deroghe scritte per quella settimana — adesso si
  vedono solo aprendo il file a mano. Chi non apre i file non sa che ci sono.
- **Le deroghe della settimana non le legge piu' nessuno nella pagina.** Il
  blocco ha le sue, e quelle si vedono in Goal; quella in piu' scritta per la
  settimana no. Nessun agente le applica (il Next e' andato col todo 66), e
  adesso nemmeno una pagina le mostra.
- **La prosa delle settimane la scrive un agente che nessuno legge.** `p_week`
  continua a scrivere inquadramento, note e sezioni: resta il documento, ma il
  giro di ritorno che diceva se era scritto bene — guardarlo nella pagina —
  non c'e' piu'.

## Come e' andata

Fatto. La vista Training e' commento piu' le due colonne, e in fondo non c'e'
piu' niente.

### Verificato

La pagina in un DOM (jsdom sul bundle vero, contro l'API accesa):

- **questa settimana** e **W46, futura**: i blocchi sono `comment-card` e
  `week-work`, la card in fondo non c'e', la colonna ha la sua intestazione
  `Plan · Week 1 of 18` (e `Week 3 of 18`) e sette righe, tutte e sette col
  dettaglio;
- **la pagina Goal**: la sua prosa si disegna ancora (un blocco `.plan-prose`),
  cioe' il CSS che ho tolto era solo della card;
- nessun errore in console in nessuno dei tre casi.

`npm run typecheck` pulito, `npm run build` ok, servizio riavviato.

## Revert

```bash
git revert -m 1 $(git log main --merges --grep="^Merge branch 'todo_91'$" --format=%H -1)
```

Effetti fuori dal repo: nessuno. Resta solo la pagina compilata in
`frontend/dist/`, che si rifa' con `make frontend_build`.

Dopo il revert, rifare il merge di `todo_91` non riporta le modifiche (git le
considera gia' unite): per riaverle serve il revert del revert.
