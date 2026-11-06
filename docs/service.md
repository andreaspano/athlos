# I servizi sulla macchina

Quello che gira da solo su mutolo, come si accende, come si guarda e cosa
fare quando non va. Il **perche'** delle scelte sta nel README (`I timer di
systemid`) e nei todo 81 e 82; qui ci sono i comandi.

Sono **unita' utente** di systemd, in `~/.config/systemd/user/`, generate da
`deploy/` riempiendo tre segnaposto. Quindi ogni `systemctl` vuole `--user`:
senza, si sta parlando di un'altra cosa che non esiste.

## Cosa c'e'

| Unita' | Cos'e' | Quando |
|---|---|---|
| `athlos-api.service` | uvicorn: l'API **e** la pagina compilata, su `127.0.0.1:8000` | sempre su |
| `athlos-morning.timer` | le cinque sezioni del corpo (lo Snap) | ogni giorno, 08:00 |
| `athlos-evening.timer` | la Training, cioe' la seduta | lun-sab, 21:00 |
| `athlos-weekend.timer` | la Training **e poi** il report della settimana | domenica, 21:00 |
| `athlos-alert@.service` | l'avvisatore: lo lancia `OnFailure=` delle altre | solo sui guasti |

La domenica e' un'unita' sola con due `ExecStart` perche' il settimanale deve
girare **dopo** il giornaliero: il lock ne lascia passare uno alla volta e
chi lo trova occupato se ne va senza fare niente.

## Accendere e spegnere

```bash
make install_services      # compila la pagina, scrive le unita', accende tutto
make uninstall_services    # spegne e toglie le unita'
```

E' ripetibile: rilancialo dopo aver cambiato un file di `deploy/`. Toglie
anche le righe `# athlos` dal crontab, perche' i due meccanismi insieme si
ruberebbero il lock.

**Una volta sola, e vuole sudo:**

```bash
sudo loginctl enable-linger andrea                             # senza, tutto si spegne al logout
sudo tailscale set --operator=$USER                            # per non rifare sudo sui serve
sudo tailscale serve --bg --http=8000 http://127.0.0.1:8000    # la tailnet
```

Senza `enable-linger` le unita' utente girano solo finche' sei collegato:
l'app si spegne quando esci e dalla tailnet non risponde piu' niente. Si
controlla con `loginctl show-user andrea -p Linger` — deve dire `yes`.

## Guardare

```bash
systemctl --user list-units 'athlos-*.service'   # cosa gira
systemctl --user list-timers 'athlos-*'          # i prossimi giri
systemctl --user --failed                          # cosa e' andato storto
journalctl --user -u 'athlos-*' -f               # il registro, dal vivo
journalctl --user -u athlos-morning -n 50        # l'ultimo giro del mattino
```

Il registro e' nel journal, che ruota da solo. Il vecchio
`~/.local/state/athlos-report.log` e' fermo all'ultimo giro di cron del
30 ottobre 2026: non ci scrive piu' niente.

**Un guasto resta visibile.** Quando un giro esce ≠ 0 l'unita' resta
elencata da `systemctl --user --failed` finche' non la azzeri con
`systemctl --user reset-failed <unita'>`. E' la cosa che con cron mancava:
il 21 ottobre due giri scrissero i report su dati vecchi uscendo 0, e non se
ne accorse nessuno per giorni.

## Dopo aver cambiato il codice

| Cosa hai toccato | Cosa fare |
|---|---|
| Python dell'API | `systemctl --user restart athlos-api` |
| Frontend | `make frontend_build && systemctl --user restart athlos-api` |
| Un file di `deploy/` | `make install_services` |
| Dipendenze (`uv add`) | `systemctl --user restart athlos-api` — `uv run` sincronizza da solo |

**Il servizio serve `frontend/dist`, non i sorgenti.** Senza
`make frontend_build` continui a guardare la pagina di prima convinto che sia
quella di adesso. E' il prezzo di non avere vite in mezzo.

## Lavorarci

Il servizio si lascia acceso; per il frontend si lancia vite, che ha il
ricaricamento a caldo e prende `/api` dalla 8000:

```bash
make frontend      # http://127.0.0.1:5173
```

Per ricaricare a caldo anche l'API, fermare il servizio e usare `make api`
(che e' uvicorn con `--reload`):

```bash
systemctl --user stop athlos-api
make api
# ... poi
systemctl --user start athlos-api
```

## La tailnet

```bash
tailscale serve status    # com'e' puntata
```

Deve dire una cosa sola: `http://mutolo:8000` che fa da proxy a
`http://127.0.0.1:8000`. L'API resta su 127.0.0.1 — **chi decide cosa esce e'
`tailscale serve`**, non l'API, che di login non ne ha.

**Due trappole quando provi se funziona, tutte e due incontrate davvero:**

- **`curl http://mutolo:8000` dalla macchina stessa non prova la tailnet.**
  `mutolo` risolve a `127.0.1.1` da `/etc/hosts`, dove non ascolta nessuno.
- **Chiedere all'indirizzo IP da' 404**, perche' `tailscale serve` instrada
  sull'intestazione `Host` e `100.79.115.122` non e' un nome che conosce.

La prova vera, dalla macchina stessa:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  --resolve "mutolo:8000:$(tailscale ip -4)" http://mutolo:8000/
```

Da un'altra macchina della tailnet basta aprire `http://mutolo:8000`.

## Quando non va

| Sintomo | Cosa guardare |
|---|---|
| La pagina non risponde | `systemctl --user status athlos-api`; se e' spenta e non sei collegato, manca `enable-linger` |
| La pagina e' vecchia | `make frontend_build` e riavvia: stai guardando `dist/` |
| `/` da' 404 ma `/api` va | `frontend/dist` non c'e': `make frontend_build` |
| Un report non e' stato scritto | `systemctl --user --failed`, poi `journalctl --user -u athlos-<giro> -n 50` |
| Report su dati vecchi | nel registro c'e' `dati non scaricati`: login Garmin scaduto o rete. Il report **c'e' lo stesso**, scritto sui dati locali, ed e' il motivo per cui l'unita' risulta fallita |
| Un giro "non ha fatto niente" | ne stava gia' girando un altro: il lock ne lascia passare uno alla volta, e il secondo esce 0 senza lavorare |
| Dalla tailnet niente | `tailscale serve status`; e ricordati delle due trappole qui sopra prima di concludere che e' rotta |
| Tutto spento dopo il riavvio | `loginctl show-user andrea -p Linger` deve dire `yes` |

Un giro si puo' sempre rilanciare a mano, senza aspettare il timer:

```bash
systemctl --user start athlos-morning.service     # come se fossero le 8
make daily_report                                   # oppure in primo piano, per vedere
```

## Tornare al cron

Le righe stanno ancora in `deploy/crontab`:

```bash
make uninstall_services && make install_cron
```

Si perdono il recupero dei giri saltati e la visibilita' dei guasti, e
l'output torna nel file che cresce e basta. **I due meccanismi non vanno
tenuti accesi insieme.**
