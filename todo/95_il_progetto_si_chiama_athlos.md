---
status: done
---

# Il progetto si chiama athlos

Da dove viene: una decisione del 6 novembre 2026. «mygarmin» dice da dove
arrivano i dati; il progetto ormai e' un'altra cosa — i report, il piano, i
goal — e Garmin e' solo la sorgente. Il nome nuovo e' **athlos**.

Questo todo rinomina **quello che sta nel repo e le unita' di systemd**. La
cartella del repo e il remote su GitHub sono gesti fuori dal repo e li fa
una persona a mano: stanno in fondo, sotto «Quello che resta da fare a
mano».

**Il pacchetto Python non si tocca**: si chiama `training`, non `mygarmin`
(`pyproject.toml:2`). Nessun import cambia, nessun comando (`training-daily-
report`, `training-week-plans`) cambia, e `data.yaml` punta a
`~/adrive/data/training`, che resta dov'e'. Il nome vecchio e' nei **nomi
dei file di deploy** e in una manciata di stringhe.

## Dove sta il nome

23 file lo nominano. Si dividono in tre mucchi, e solo i primi due si
toccano:

| mucchio | file | che cosa c'e' dentro |
|---|---|---|
| **i nomi dei file** | `deploy/*.service`, `deploy/*.timer` | 8 file da rinominare |
| **le stringhe** | `Makefile` (16), `docs/service.md` (19), `README.md` (9), `deploy/crontab` (4), `tests/test_refresh.py` (2) | nomi di unita' nei comandi e nella prosa |
| **il registro** | otto file di `todo/` (17, 41, 47, 56, 81, 82, 83, 94) | **non si toccano**: raccontano com'era allora |

## Cosa si fa

### 1. Gli otto file di `deploy/`

`git mv`, uno per uno:

```
mygarmin-api.service      → athlos-api.service
mygarmin-morning.service  → athlos-morning.service
mygarmin-morning.timer    → athlos-morning.timer
mygarmin-evening.service  → athlos-evening.service
mygarmin-evening.timer    → athlos-evening.timer
mygarmin-weekend.service  → athlos-weekend.service
mygarmin-weekend.timer    → athlos-weekend.timer
mygarmin-alert@.service   → athlos-alert@.service
```

Dentro i file cambiano due righe: `OnFailure=mygarmin-alert@%n.service` dei
tre giri, che diventa `athlos-alert@%n.service`, e la `Description=` di
tutte e otto, che e' il nome che `systemctl status` stampa. Il resto —
`WorkingDirectory`, `ExecStart`, i segnaposto `__REPO__` e `__UV__` — non
nomina il progetto.

### 2. Il `Makefile`

- `TIMERS` (riga 172) e `SERVICES` (173): i nomi nuovi;
- il glob di `install_services` (189): `deploy/athlos-*.service` e
  `deploy/athlos-*.timer`;
- i due `systemctl ... 'mygarmin-*'` del riepilogo (199 e 202);
- `CRON_LOG` (170): `~/.local/state/athlos-report.log`. **Il file vecchio
  resta su disco** — vedi «Quello che resta da fare a mano»;
- il commento del bersaglio `api` (55-57), che dice di fermare
  `mygarmin-api` prima di lavorarci.

### 3. La prosa: `README.md`, `docs/service.md`, `deploy/crontab`

Sostituzione dei nomi di unita' e dei comandi (`systemctl --user restart`,
`list-timers 'athlos-*'`, `journalctl --user -u 'athlos-*'`). Il titolo del
README (`# mygarmin`, riga 1) diventa `# athlos`.

**Una frase da scrivere, non da sostituire**: da qualche parte in cima al
README va detto **perche'** il progetto si chiama cosi' e che i dati
vengono da Garmin. Chi arriva al repo col nome nuovo non ha piu' quel
pezzo di informazione gratis, e il README e' l'unico posto dove cercarlo.

### 4. I due test

`tests/test_refresh.py:255` e `:279` nominano `OnFailure=mygarmin-alert@`
dentro i docstring. Sono prosa, non asserzioni: si aggiornano perche' un
commento che nomina un'unita' che non esiste manda fuori strada.

### 5. Le unita' installate

Quelle in `~/.config/systemd/user/` hanno ancora i nomi vecchi, e
`install_services` **non** le toglie: installerebbe le nuove accanto, e due
serie di timer sugli stessi file si ruberebbero il lock. Quindi, in
quest'ordine:

```bash
make uninstall_services     # con i nomi VECCHI, cioe' prima del merge
# ... merge ...
make install_services       # con i nomi nuovi
```

**Da cui il vincolo**: `uninstall_services` va lanciato **prima** di
mergiare, o il suo elenco di unita' da spegnere e' gia' quello nuovo e le
vecchie restano accese e orfane. Se succede si rimedia a mano:

```bash
systemctl --user disable --now mygarmin-{api,morning,evening,weekend}.{service,timer} 2>/dev/null
rm -f ~/.config/systemd/user/mygarmin-*
systemctl --user daemon-reload
```

L'API resta giu' il tempo del merge, cioe' meno di un minuto. I timer si
riaccendono con `install_services`, e il prossimo giro e' quello previsto:
non si recupera niente di saltato, perche' non salta niente.

## Quello che non va toccato

- **Il pacchetto `training`** e i suoi comandi.
- **`~/adrive/data/training`**: i dati, i report, i goal. Il puntatore in
  `data.yaml` non nomina il progetto.
- **I todo che lo nominano** (17, 41, 47, 56, 81, 82, 83, 94): sono il
  registro di com'era, e «mygarmin» li' e' giusto.
- **Il nome del database, delle cartelle dei report, dei frammenti**:
  niente di tutto questo nomina il progetto.

## Rischi

**Il momento dello spegnimento.** E' l'unica cosa che puo' andare storta:
`uninstall_services` prima del merge, `install_services` dopo. Invertirli
lascia otto unita' orfane accese. Il comando per rimediare e' qui sopra.

**Il nome e' in una stringa di `journalctl`.** Chi ha un alias o uno script
fuori dal repo che guarda `mygarmin-*` smette di vedere niente — e **senza
errore**, perche' un filtro che non trova unita' e' un filtro vuoto, non un
guasto. Vale la pena cercarli prima: `grep -rl "mygarmin" ~/.bashrc
~/.bash_aliases ~/bin 2>/dev/null`.

**Il resto e' solo testo.** Nessun comportamento cambia, nessun dato si
muove, e i test non toccano systemd.

## Come si verifica

1. `git grep -il mygarmin` rende **otto file sotto `todo/`** (17, 41, 47,
   56, 81, 82, 83, 94 — tutti registro, tutti fermi) **piu' una riga del
   `README.md`**, che e' la frase messa apposta: «Si chiamava `mygarmin`».
   Niente altro.
2. `uv run pytest -q`: 240 passati (nessun test guarda i nomi delle unita',
   quindi il numero non cambia).
3. `make install_services` e poi `systemctl --user list-timers 'athlos-*'`:
   tre timer, con il prossimo giro negli orari di sempre (8:00, 21:00,
   domenica 21:00).
4. `systemctl --user list-units 'mygarmin-*'` non rende niente.
5. La pagina su `http://127.0.0.1:8000` si apre e mostra il report di oggi.
6. Un guasto finto per provare l'avvisatore nuovo: `systemctl --user start
   athlos-alert@prova.service` e poi `journalctl --user -u
   'athlos-alert@prova' -n 5` — deve stampare la riga del guasto.

## Quello che resta da fare a mano

Fuori dal repo, dopo il merge. Nessuno di questi e' urgente e nessuno
rompe niente se si rimanda:

- **La cartella del repo**: `mv ~/dev/mygarmin ~/dev/athlos`, poi
  `make install_services` di nuovo, che riscrive `WorkingDirectory` e
  `ExecStart` col percorso nuovo (li riempie da `$(CURDIR)`). Da sapere:
  le sessioni di Claude Code di questo progetto vivono in
  `~/.claude/projects/-home-andrea-dev-mygarmin`, e con la cartella nuova
  il progetto riparte da zero — i transcript e la memoria restano li',
  orfani ma leggibili.
- **Il remote**: rinominare il repo su GitHub e poi
  `git remote set-url origin git@github.com:andreaspano/athlos.git`.
  GitHub tiene il redirect, quindi non si rompe niente nel frattempo.
- **Il registro del cron**: `~/.local/state/mygarmin-report.log` (3,3 KB,
  fermo al 30 ottobre, da quando i timer scrivono nel journal). Si
  rinomina o si butta; il nome nuovo lo scrive solo `install_cron`, che non
  si usa piu'.

## Come e' andata

## Revert

```bash
git revert -m 1 $(git log main --merges \
  --grep="^Merge branch 'todo_95'$" --format=%H -1)
```

Effetti fuori dal repo: le unita' installate restano quelle con i nomi
**nuovi** — il revert riporta i file di `deploy/`, non quello che sta in
`~/.config/systemd/user/`. Per tornare indietro davvero serve lo stesso
giro al contrario: `make uninstall_services` prima del revert e
`make install_services` dopo. Se la cartella del repo e il remote sono gia'
stati rinominati a mano, il revert non li tocca.

Dopo il revert, rifare il merge di `todo_95` non riporta le modifiche (git
le considera gia' unite): per riaverle serve il revert del revert.
