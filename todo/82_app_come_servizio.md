---
status: done
---

# L'app come servizio, su una porta sola

I giri dei report girano da soli dal todo 81. **L'app no**: per averla
accesa bisognava lasciare aperti due terminali, `make api` e `make
frontend`, e il secondo era il server di sviluppo di vite — che va benissimo
per lavorarci e non ha niente a che fare con qualcosa che deve stare su.

Si vedeva: `tailscale serve` puntava a `127.0.0.1:5173`, cioe' a un processo
di sviluppo lanciato a mano. Chiuso il terminale, la tailnet non serviva piu'
niente.

## Cosa si fa

**Un servizio solo e una porta sola.** `mygarmin-api.service` e' uvicorn che
serve l'API **e** la pagina gia' compilata; vite in produzione sparisce, il
proxy non serve piu', e `tailscale serve` punta alla 8000.

### 1. L'API serve anche la pagina — `api/context.py`, `api/app.py`

`DIST_DIR` accanto a `ICONS_DIR`, e in fondo ad `app.py`:

```python
if DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="page")
```

**In fondo a tutto**, perche' un mount su `/` prende qualunque percorso e le
rotte vincono solo perche' Starlette le prova nell'ordine in cui sono
dichiarate: spostarlo piu' su oscurerebbe `/api`.

`html=True` basta e avanza: la pagina tiene il suo stato nella stringa di
ricerca (`?period=`, vedi `navigation.ts`) e non ha percorsi veri, quindi non
c'e' nessun fallback di history da gestire — e' la stessa scelta che a suo
tempo ha evitato un router di libreria.

Se `dist/` non c'e' il mount non si fa: l'API funziona lo stesso e `/` rende
404 finche' non si lancia `make frontend_build`. Un'installazione a meta' non
deve rompere le rotte.

### 2. L'unita' — `deploy/mygarmin-api.service`

`Type=exec`, `Restart=always`, `WantedBy=default.target`, su 127.0.0.1:8000.

`exec` e non `simple` perche' un errore all'avvio si veda come avvio fallito
invece che come servizio su che muore un istante dopo. Il processo principale
resta `uv`, che tiene sotto di se' uvicorn: due processi invece di uno, ed e'
il prezzo di lanciare tutto con `uv run` come fa il resto del progetto — in
cambio le dipendenze sono in pari anche dopo un `uv add`.

### 3. `make frontend_build`, e l'installazione che compila

`install_timers` diventa **`install_services`** — adesso installa un servizio
e tre timer, e il nome vecchio diceva meta' della verita'. Dipende da
`frontend_build`, cosi' la pagina servita e' sempre quella del codice
installato.

### 4. La tailnet alla 8000

`tailscale serve --bg --http=8000 http://127.0.0.1:8000`. **L'esposizione
non cambia**: prima dalla tailnet passava vite, che girava `/api` all'API,
quindi l'API era gia' raggiungibile di la'. Cambia solo chi risponde.

## Quello che non va toccato

- `make frontend` e `vite.config.ts`: restano lo sviluppo, con il
  ricaricamento a caldo e il proxy verso la 8000.
- L'API su 127.0.0.1 e senza login: chi decide che cosa esce resta
  `tailscale serve`.
- I timer del todo 81.

## Rischi

- **`dist/` che invecchia.** Il servizio serve file compilati: dopo un cambio
  al frontend serve `make frontend_build` e un `restart`, o si guarda la
  pagina di ieri convinti che sia quella di oggi. E' il prezzo di non avere
  vite in mezzo, ed e' scritto nel README.
- **`Linger` adesso serve anche all'app.** Prima riguardava solo i report;
  ora senza linger il servizio si spegne quando esci e dalla tailnet non
  risponde piu' niente.
- **La tailnet resta muta finche' non la si ripunta**, perche' il vite a cui
  puntava non c'e' piu'. Serve un comando con sudo, che non si puo' dare per
  conto di chi amministra la macchina.

## Come e' andata

Fatto. `mygarmin-api.service` e' acceso e `enabled`, e sulla 8000 rispondono
l'API, la pagina, gli asset, le icone e `/docs` — una porta sola.

### Verificato

- **Le rotte non si oscurano a vicenda**: `/api/refresh`, `/api/activities`,
  `/docs`, `/icons/...` e `/` rendono tutti 200 con il mount su `/` in fondo.
- **Si rialza da solo**: `systemctl --user restart` torna a servire, e dopo
  un `kill -9` sul processo principale `Restart=always` lo rimette su e la
  pagina risponde di nuovo.
- **`Type=exec` e `Restart=always`** sono quelli che systemd riporta.
- `npm run typecheck` pulito dopo il cambio a `vite.config.ts`.

### Due cose trovate per strada

**Il commento che avevo scritto sull'unita' era falso.** Diceva che `exec`
serviva a far restare uvicorn come processo principale; non e' vero, il
principale resta `uv`. `exec` riguarda *quando* systemd considera avviato il
servizio. Corretto nel file.

**Vite era ancora vivo.** Fermando i processi a mano avevo ucciso il wrapper
`sh -c vite` e non il processo node sotto, che continuava a servire la 5173 —
e la tailnet, puntata li', sembrava a posto. Adesso e' fermo davvero.

### Quello che resta da fare a mano, con sudo

Due comandi, tutti e due fuori dalla portata del Makefile:

```bash
sudo loginctl enable-linger andrea                        # l'app resta su senza sessione
sudo tailscale serve --bg --http=8000 http://127.0.0.1:8000   # la tailnet torna a rispondere
```

Finche' non si da' il secondo, **dalla tailnet non risponde niente**: il vite
a cui puntava e' spento.

## Revert

```bash
git revert -m 1 $(git log main --merges --grep="^Merge branch 'todo_82'$" --format=%H -1)
make uninstall_services && make install_cron
sudo tailscale serve --bg --http=5173 http://127.0.0.1:5173
```

Effetti fuori dal repo: il revert del codice **non tocca la macchina**.
`mygarmin-api.service` resta installato e acceso in `~/.config/systemd/user/`
e va tolto a mano, la tailnet resta puntata alla 8000, e `frontend/dist`
resta dov'e'. Dopo il revert l'app torna a volere due terminali.

Dopo il revert, rifare il merge di `todo_82` non riporta le modifiche (git le
considera gia' unite): per riaverle serve il revert del revert.
