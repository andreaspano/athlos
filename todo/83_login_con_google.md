---
status: todo
---

# Un login, per non essere l'unica difesa la tailnet

Dal todo 82 l'app sta su una porta sola e `tailscale serve` la porta sulla
tailnet. Il README dice da sempre la stessa frase: *l'API ascolta su
127.0.0.1, niente login, e chi decide che cosa esce e' `tailscale serve`*.
Finche' la tailnet e' una macchina e un telefono, e' vero e basta.

**Non e' piu' quel caso.** Oggi in tailnet c'e' anche `sdgnb722`, di
`nobilipietro@`: un'altra persona. E `tailscale serve` espone *alla tailnet*,
cioe' a chiunque ne faccia parte. Sono dati di salute, e la `POST
/api/refresh` non e' nemmeno una lettura: lancia `claude` sulla macchina.

Quindi due domande separate, e vanno decise in quest'ordine:

1. **Chiudere quello che c'e' gia' aperto** — la tailnet condivisa.
2. **Aprire quello che non c'e'** — l'app dal telefono *senza* Tailscale, che
   vuol dire `tailscale funnel`, cioe' internet.

Solo la seconda chiede davvero un login con Google. La prima potrebbe
costare molto meno, ed e' il primo passo qui sotto.

## Cosa si fa

### 0. Prima di scrivere codice: chi e' gia' dentro

Due verifiche nella admin console, nessuna delle due nel repo:

- **Le ACL.** Se una regola impedisce a `nobilipietro@` di raggiungere la
  8000 di `mutolo`, il problema 1 e' gia' chiuso e questo todo serve solo per
  il funnel. Da qui non si leggono: `tailscale serve status` dice
  `tailnet only`, che e' il default, non la regola effettiva.
- **Gli header di identita' di `serve`.** Un proxy `serve` sulla tailnet
  dovrebbe passare a monte chi ha chiesto (`Tailscale-User-Login`). **Se e'
  vero, il problema 1 si chiude in dieci righe**: si legge quell'header e si
  confronta con `andrea@spano.it`. Niente OAuth, niente cookie, niente
  segreti. Si verifica mettendo un echo su una porta a parte e un secondo
  `serve` sopra, che poi si spegne.

**Se l'header c'e' e il funnel non interessa, questo todo finisce qui** — e
finisce bene. Il resto vale per il caso pubblico, dove quell'header **non
c'e'**: le richieste dal funnel sono anonime, ed e' esattamente per questo
che serve un'identita' vera.

### 1. HTTPS, che e' il prerequisito e oggi manca

Verificato: `tailscale cert` risponde *HTTPS cert support is not
enabled/configured for your tailnet*. E' un interruttore nella admin console
(DNS), non un comando.

Serve per due motivi indipendenti:

- **Google non accetta un redirect URI in chiaro.** L'unica eccezione e'
  `http://localhost`, e `http://mutolo:8000` non lo e'. Con HTTPS acceso il
  nome diventa `https://mutolo.tailab3950.ts.net` con un certificato vero, e
  quello Google lo accetta. Google non deve raggiungerlo: il redirect avviene
  nel browser del telefono, che quel nome lo risolve.
- **Un cookie di sessione in chiaro su internet non si fa.** Sul funnel, il
  cookie e' la chiave di casa.

Poi `tailscale serve` passa alla 443 e la 8000 in chiaro si spegne.

### 2. Google, e Google solo — `api/auth.py`, nuovo

OIDC, authorization code flow con PKCE. Quattro rotte:

| Rotta | Cosa fa |
|---|---|
| `GET /auth/login` | manda a Google, con `state` e PKCE in un cookie breve |
| `GET /auth/callback` | scambia il `code`, verifica l'`id_token` (firma, `iss`, `aud`, `exp`), legge `email` e `email_verified`, controlla l'elenco, mette il cookie, torna a `/` |
| `POST /auth/logout` | cancella il cookie |
| `GET /api/me` | chi sono, per la pagina |

**Facebook no, e non e' pigrizia.** Vuole un'app Meta con privacy policy
pubblica e una revisione per uscire dalla modalita' di sviluppo, non
garantisce di dare l'email, e un secondo provider raddoppia la superficie di
una cosa che ha **un utente solo**. Se un giorno Google non bastasse, si
aggiunge allora.

L'`id_token` **non si legge e basta: si verifica**. Una libreria che lo fa
(`authlib`) invece che tre righe di `base64` — e' il punto in cui gli errori
costano tutto.

### 3. Il guardiano chiude per default — `api/app.py`

**Un middleware, non una `Depends` su ogni rotta.** La `Depends` la si
dimentica sulla rotta nuova, e il buco non si vede: nessun test fallisce,
la pagina funziona. Il middleware nega tutto tranne un elenco corto e
esplicito (`/auth/*` e poco altro), e una rotta nuova nasce protetta.

Due comportamenti diversi, perche' due clienti diversi:

- una **navigazione** non autenticata (un `GET` che accetta `text/html`) va
  a `/auth/login`, quindi a Google. **Nessuna pagina di login da
  disegnare**: non c'e' un modulo, non c'e' una password, non c'e' niente da
  fare a mano.
- una chiamata a **`/api/...`** rende `401` in JSON, cosi' la pagina puo'
  dire *sessione scaduta* invece di ricevere l'HTML di Google dentro una
  `fetch`.

Il cookie e' firmato e senza stato sul server (`SessionMiddleware` di
starlette): `HttpOnly`, `Secure`, `SameSite=Lax`, scadenza lunga — e' il
proprio telefono, non una banca.

### 4. L'elenco di chi puo' entrare

**Una email, in `user/config.yaml`.** "Ha un account Google" non e'
un'autorizzazione: senza l'elenco, chiunque su internet entra nei propri dati
di sonno. Una email verificata che non e' nell'elenco prende `403`, non
`401`: non e' che manchi la sessione, e' che non e' la persona giusta.

Nello stesso file vanno `client_id`, `client_secret` e il segreto delle
firme. Sta fuori dal repo, dove sta gia' il token di Garmin.

**Attenzione a come si aggiungono**: la configurazione non ha default e
rifiuta le chiavi che non conosce, quindi il momento in cui il validatore
impara le chiavi nuove e' anche il momento in cui **tutto si ferma finche'
non sono scritte** — compresi i giri dei report delle 08:00 e delle 21:00.
Si riempie `config.yaml` nello stesso passo, non dopo.

### 5. La pagina — `frontend/src/api/client.ts`

Le `fetch` sono tre, in un file solo: il `401` si gestisce in un posto. Sulla
risposta `401` la pagina manda a `/auth/login`.

Stessa origine, quindi il cookie viaggia da se': **niente CORS**. Anche in
sviluppo, dove vite fa da proxy verso la 8000.

### 6. Il funnel, e solo se si vuole davvero

`tailscale funnel` mette la 443 su internet. Da quel momento l'elenco del
punto 4 e' **l'unica** cosa fra il mondo e i propri dati — e fra il mondo e
un endpoint che lancia `claude`. E' un passo che si fa dopo, consapevolmente,
e si torna indietro con un comando.

## Quello che non va toccato

- **L'API resta in ascolto su 127.0.0.1.** Il login non e' il permesso di
  aprire la porta: chi espone resta Tailscale.
- `make api` e `make frontend` restano lo sviluppo. Con
  l'autenticazione spenta da una variabile d'ambiente, o lavorarci diventa un
  giro su Google a ogni ricaricamento.
- I giri dei report (todo 81) e il servizio (todo 82): girano sulla macchina e
  non passano per l'API.

## Rischi

- **Chiudersi fuori da casa propria.** Un `client_secret` sbagliato, Google
  che cambia qualcosa, un cookie che non si scrive: l'app non si apre piu' da
  nessuna parte. La via di fuga e' quella del punto "non va toccato":
  `systemctl --user stop mygarmin-api` e `make api` senza autenticazione,
  dalla macchina. **Va provata prima di servire.**
- **Il cookie e' la chiave, e sta su un telefono.** Scadenza lunga vuol dire
  che un telefono perso resta dentro. Serve poter invalidare tutto: cambiare
  il segreto delle firme butta giu' ogni sessione, e deve essere una cosa
  documentata, non una scoperta.
- **Una dipendenza nuova sul percorso critico.** Senza Google non si entra.
  Per un'app personale e' accettabile; va saputo.
- **Il login fa sembrare sicuro quello che non lo e'.** Se le ACL restano
  aperte e il middleware ha un'eccezione di troppo, si ha un login e un buco.
  Il collaudo e' **da un'altra macchina della tailnet**, non da `mutolo`: i
  tranelli di `docs/service.md` valgono anche qui.
- **`/api/refresh` e' la rotta piu' pericolosa del progetto.** Lancia un
  processo. Sul funnel merita un pensiero in piu' delle letture.

## Revert

Prima del funnel, il revert e' il revert del codice piu' il ritorno di
`tailscale serve` alla 8000 in chiaro. Dopo il funnel va spento anche quello,
**e da fuori dalla macchina**, perche' da dentro non si vede la differenza.

HTTPS acceso nella tailnet e l'app registrata su Google restano: non fanno
danno, e se il todo si riprende si riparte da li'.
