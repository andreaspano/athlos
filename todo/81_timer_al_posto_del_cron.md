---
status: done
---

# I timer di systemd al posto del cron

I tre giri automatici (todo 47 per il giorno, 53 per la settimana) stanno in
cron dal 21 ottobre. Funzionano, ma il registro di quelle prime giornate
mostra tre cose che cron non sa fare, e una quarta che e' un refuso.

**Quello che il log ha gia' raccontato.** Il 21 ottobre due giri hanno
scritto i report su dati vecchi:

```
dati     non scaricati  /bin/sh: 1: uv: not found
make: *** [Makefile:4: update_activity] Error 127
```

e il comando e' uscito **0**. Cron era contento, nessuno si e' accorto di
niente, e i report di quel giorno parlano di dati di prima. Che lo
scaricamento fallito non fermi il lavoro e' una scelta voluta e resta
(`_prepare`: meglio un report sui dati locali che nessun report), ma
**l'esito finisce solo in `download`, che si vede sulla pagina**, e alle otto
del mattino nessuno guarda la pagina.

## Cosa si sistema

### 1. Il codice di uscita dice la verita' — `api/refresh.py`

`_cli` esce 1 quando una sezione fallisce, ma non quando fallisce lo
scaricamento. Adesso esce 1 anche li': il report e' scritto, ma e' scritto su
dati che non sono quelli di oggi, e questo e' un fatto che chi lancia deve
sapere. Con `--no-update` non c'e' scaricamento e non cambia niente.

E' una riga, ed e' quella che da' senso a tutto il resto: senza un codice di
uscita onesto, nessun meccanismo di avviso puo' accorgersi di niente.

### 2. I timer, con il recupero — `deploy/*.timer`, `deploy/*.service`

Cron non recupera: se la macchina e' spenta alle 8, quel giro non esiste piu'
e non lo dice nessuno. `Persistent=true` invece se lo ricorda e lo lancia
appena puo'.

Tre coppie, una per riga di crontab, con gli stessi orari:

| Unita' | Quando | Cosa lancia |
|---|---|---|
| `mygarmin-morning` | `*-*-* 08:00` | `training-daily-report --moment morning` |
| `mygarmin-evening` | `Mon..Sat *-*-* 21:00` | `training-daily-report --moment evening` |
| `mygarmin-weekend` | `Sun *-*-* 21:00` | il giorno, **poi** la settimana |

La domenica resta una unita' sola con due `ExecStart`, per lo stesso motivo
per cui nel crontab erano una riga sola con il `;`: il lock ne lascia passare
uno alla volta, e chi lo trova occupato se ne va senza fare niente, quindi
devono essere in fila. Il primo ha il prefisso `-`, che e' il `;` di systemd:
se il giorno fallisce la settimana gira lo stesso.

**Gli orari non cambiano.** Le 21 restano strette — il 29 ottobre la corsa e'
finita alle 20:38, ventidue minuti di margine perche' l'orologio
sincronizzasse — ma e' una questione a parte e non si tocca qui.

### 3. L'avviso quando qualcosa va storto — `deploy/mygarmin-alert@.service`

`OnFailure=` su tutte e tre le unita'. Quando una esce ≠ 0 parte
l'avvisatore, che scrive una riga forte nel journal e, se c'e' una sessione
grafica, manda un `notify-send`. Senza desktop resta la riga, piu'
`systemctl --user --failed`, che dopo un guasto elenca l'unita' finche' non
la si azzera: **il guasto resta visibile anche a chi passa di li' mezza
giornata dopo**, che e' la cosa che con cron mancava.

### 4. La rotazione: il file sparisce, resta il journal

`~/.local/state/mygarmin-report.log` cresce e basta — oggi 3 KB, ma non c'e'
niente che lo tagli mai, ed e' l'unica traccia che hai. Invece di aggiungere
un `logrotate` da installare, le unita' scrivono nel **journal**, che ruota
da solo e qui e' persistente (`/var/log/journal` c'e'). Il `tail -f` diventa:

```bash
journalctl --user -u 'mygarmin-*' -f
```

Il file vecchio non si cancella: resta li' com'e', e il README dice dov'e'
finito il seguito.

### 5. Il doppio slash — `Makefile`

Le righe installate dicono `/home/andrea//.local/bin/uv`. Non e' il
segnaposto riempito male: e' il tuo `PATH`, che ha `/home/andrea//.local/bin`,
e `command -v uv` lo rende com'e'. Si normalizza con `$(abspath ...)`.

### 6. L'installazione — `Makefile`

`install_timers` e `uninstall_timers` accanto a quelli del cron. Riempie i
segnaposto dei file di `deploy/`, li scrive in `~/.config/systemd/user`, fa
`daemon-reload` e `enable --now` delle tre.

**Toglie anche le righe `# mygarmin` dal crontab**: i due meccanismi non
devono girare insieme, o ogni giro trova il lock occupato dall'altro e se ne
va senza fare niente — un guasto che si legge come silenzio.

`uninstall_cron` resta, perche' serve a chi ha ancora le righe vecchie.

**Su `Linger`, che va detto e non nascosto.** I timer utente girano quando il
gestore utente gira, cioe' dal login. `Persistent=true` fa partire al login
il giro perso — su un fisso a cui si fa l'accesso e' esattamente il recupero
che si vuole. Per una macchina che nessuno logga serve
`sudo loginctl enable-linger andrea`, e `install_timers` lo **dice** quando
vede `Linger=no`, senza chiedere la password per conto suo.

## Quello che non va toccato

- Gli orari dei giri, e la scelta di andare avanti con i dati locali quando
  Garmin non risponde: cambia solo il codice di uscita, non il
  comportamento.
- `deploy/crontab`: resta nel repo come documentazione di dove si veniva, e
  perche' chi ha ancora quelle righe possa toglierle.
- Il lock di `refresh.py` e il modo in cui le sezioni girano.

## Rischi

- **Due meccanismi insieme.** Se restassero sia il cron sia i timer, ogni
  giro troverebbe il lock occupato e uscirebbe 0 senza fare niente: il
  silenzio peggiore, perche' somiglia al successo. Per questo
  `install_timers` disinstalla il cron, e la verifica lo controlla.
- **`Linger=no`.** Senza accesso, niente giri. Oggi e' cosi' anche con cron
  solo in parte (cron gira comunque): e' l'unica cosa che si perde passando
  ai timer, ed e' il motivo del messaggio in installazione.
- **Il codice di uscita piu' severo.** Da adesso un login Garmin scaduto fa
  risultare l'unita' fallita. E' il punto, ma la prima volta che capita
  bisogna ricordarsi che il report c'e' lo stesso.

## Verifica

- `systemctl --user list-timers 'mygarmin-*'` elenca le tre con il prossimo
  orario giusto: 08:00 domani, 21:00 oggi se e' lun-sab, domenica per
  l'ultima.
- **Il recupero**: con l'orologio spostato indietro, o fermando e
  riavviando il gestore utente dopo un orario passato, il giro perso parte
  da solo.
- **Il codice di uscita**: `training-daily-report` con una rete finta o un
  `make update_activity` che fallisce esce 1 e lascia l'unita' `failed`.
- **L'avviso**: l'unita' fallita compare in `systemctl --user --failed` e la
  riga forte sta nel journal.
- **Il crontab e' vuoto** di righe `# mygarmin` dopo `install_timers`.
- **Il doppio slash non c'e' piu'** nei file installati.
- `uv run python -c "import training"` e i moduli toccati.

## Come e' andata

Fatto, e installato. I tre timer sono accesi:

```
NEXT                        LEFT         UNIT
Fri 2026-10-30 21:00:00 CET 7h left      mygarmin-evening.timer
Sat 2026-10-31 08:00:00 CET 18h left     mygarmin-morning.timer
Sun 2026-11-01 21:00:00 CET 2 days left  mygarmin-weekend.timer
```

Il crontab e' rimasto con la sola riga che non c'entra
(`@reboot insync-headless`), e `Persistent=yes` su tutte e tre.

### Il README diceva che i timer erano gia' stati provati, e tolti

Scrivendo la documentazione e' saltato fuori che **il todo 47 i timer li
aveva messi, e poi erano stati sostituiti da cron apposta**, con questo
ragionamento: su una macchina accesa sempre, recuperare un giro saltato non
vale il prezzo dei timer utente, che girano solo finche' sei collegato.

Il ragionamento era giusto allora e resta giusto adesso sul **recupero**.
Quello che lo ribalta e' un'altra cosa, che allora non si sapeva: il 21
ottobre due giri hanno scritto sui dati vecchi uscendo 0, e non se n'e'
accorto nessuno per giorni. Con il codice di uscita onesto (punto 1) e
`OnFailure`, un guasto resta elencato da `systemctl --user --failed` finche'
non lo azzeri. **Cron questo non lo sa fare in nessun modo**: al massimo
lascia una riga in un file che nessuno apre.

Quindi il motivo per cui si torna ai timer non e' il recupero del todo 81,
e' la visibilita'. Il recupero viene in regalo.

**Il prezzo di allora resta tale e quale**, ed e' scritto nel README e detto
da `install_timers`: con `Linger=no` i timer girano da quando fai l'accesso.
Su un fisso a cui ti colleghi, `Persistent=true` fa partire al login il giro
perso ed e' esattamente quello che serve; su una macchina che nessuno logga
**serve `sudo loginctl enable-linger andrea`, o i report non si scrivono
affatto**. Non l'ho lanciato io: vuole la password ed e' una scelta di chi
amministra la macchina.

### Il notificatore e' stato tolto dopo averlo provato

L'avvisatore nasceva con un `notify-send` accanto alla riga nel journal. Alla
prova ci metteva **cinque secondi secchi** e non notificava niente: su questa
macchina non c'e' nessun demone di notifiche (`org.freedesktop.Notifications`
risponde `false`, le sessioni sono tty e ssh), e la chiamata restava appesa
sul timeout di D-Bus — proprio mentre si sta gestendo un guasto. Un
`timeout 5` davanti lo limitava ma non lo rendeva utile, quindi e' via:
restano la riga nel journal (15 ms) e l'unita' fra le fallite. Se un giorno
ci fosse un desktop, e' una riga da rimettere.

### Come e' stato verificato

- **Il codice di uscita**, sui cinque casi che la riga nuova deve
  distinguere: niente scaricamento (`--no-update`) → 0, scaricamento riuscito
  → 0, **scaricamento fallito → 1** (il caso del 21 ottobre), sezione fallita
  → 1, tutti e due → 1.
- **La catena del guasto, per davvero**: un'unita' che fallisce apposta fa
  partire l'avvisatore, che scrive `GUASTO in mygarmin-provaguasto.service`
  nel journal, e l'unita' resta elencata da `--failed` finche' non la si
  azzera. (`systemd-run` non serve per questa prova: non espande `%n` nelle
  proprieta' transitorie. Ci vuole un file.)
- **`OnFailure` si risolve** in
  `mygarmin-alert@mygarmin-morning.service.service`, che e' la forma giusta.
- **Il comando dell'unita' gira** nell'ambiente dell'unita' (PATH e cartella
  di lavoro di systemd, niente del resto).
- **Il doppio slash non c'e' piu'** in nessuna riga installata. Non veniva
  dal segnaposto: `$HOME` **e** `$PATH` qui finiscono con uno slash di
  troppo, quindi `abspath` serve su tutti e due, non solo su `uv`.
- **Il crontab** non ha piu' righe `# mygarmin`, e la riga di insync e'
  intatta.
- `import training`, `from training.api import refresh`, e i tre target del
  Makefile che si espandono.

Quello che **non** ho provato: il recupero vero di un giro perso. Vorrebbe
spostare l'orologio o fermare il gestore utente, e si vedra' da solo la prima
volta che la macchina e' spenta alle 8.

## Revert

```bash
git revert -m 1 $(git log main --merges --grep="^Merge branch 'todo_81'$" --format=%H -1)
make uninstall_timers && make install_cron
```

Effetti fuori dal repo: il revert del codice **non tocca la macchina**. I
timer restano installati e accesi in `~/.config/systemd/user/` e il crontab
resta senza le sue righe, quindi dopo il revert vanno rifatti a mano i due
comandi qui sopra — se no non gira piu' niente. Il vecchio
`~/.local/state/mygarmin-report.log` e' rimasto dov'era, fermo all'ultimo
giro di cron del 30 ottobre.

Dopo il revert, rifare il merge di `todo_81` non riporta le modifiche (git le
considera gia' unite): per riaverle serve il revert del revert.
