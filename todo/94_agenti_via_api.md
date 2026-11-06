---
status: done
---

# Gli agenti via API invece che per sottoprocesso

Da dove viene: una domanda del 6 novembre 2026 — quanto costerebbe al mese
questa app pagando Claude via API invece che dall'abbonamento — e la misura
fatta per rispondere, che ha trovato dove vanno i token. La risposta e' 38
dollari al mese; la parte interessante e' che il testo che si legge sulle
card e' l'1% di quello che si pagherebbe.

Oggi ogni sezione e' un processo `claude -p` (`_write_section` in
`api/refresh.py`, riga 551), cioe' una sessione intera di Claude Code: il suo
prompt di sistema, le definizioni dei suoi tool, e il giro di agente che
legge e scrive file. Questo todo la fa diventare **una chiamata sola al
modello**: i fatti nel messaggio, il testo nella risposta, il file lo scrive
l'orchestratore. Niente cambia di quello che si vede sulla pagina.

## Che cosa costa adesso

Misurato sui transcript di Claude Code in
`~/.claude/projects/-home-andrea-dev-mygarmin/`, su 1020 giri di agente di
sezione veri (tutti su `claude-opus-5`):

| agente | run | cache write | cache read | uscita | richieste al modello |
|---|---|---|---|---|---|
| `01_health` | 116 | 17.500 | 29.600 | 1.568 | 5,6 |
| `02_load` | 114 | 16.800 | 25.300 | 1.459 | 5,1 |
| `03_recovery` | 107 | 16.600 | 25.800 | 1.740 | 5,3 |
| `04_fitness` | 116 | 17.200 | 27.200 | 1.849 | 5,2 |
| `05_training` | 120 | 19.900 | 33.400 | 2.023 | 5,9 |
| `07_summary` | 19 | 18.500 | 21.100 | 3.039 | 8,7 |
| `p_week` | 18 | 27.100 | 30.000 | 9.347 | 7,1 |

Al mese, con i giri dei timer (mattina cinque sezioni ogni giorno, sera il
Training ogni giorno, la settimana la domenica): **3,86 MTok scritti in
cache, 5,83 MTok letti, 0,45 MTok di uscita**. Col listino di Opus 5 — 5 e 25
dollari per MTok, scrittura in cache 1,25x, lettura 0,1x — sono 38,32 dollari
al mese, di cui 25,77 solo il giro della mattina.

**Quei token non sono il lavoro.** Sono il prompt di sistema di Claude Code
piu' le definizioni dei tool, ricaricati a ogni giro di agente, per cinque o
sei richieste al modello che producono 1.500 token di testo.

**E il giro di agente non serve.** Sempre dai transcript, un agente di
sezione chiama in media 3,9 tool, di cui 2,83 `Read`. Che cosa legge:

| che cosa | per run |
|---|---|
| frammenti dello **stesso** periodo (le sezioni accanto) | 1,73 |
| il file dei fatti che l'orchestratore gli ha appena scritto | 0,74 |
| un periodo **passato** | 0,09 |

Niente che l'orchestratore non abbia gia' in mano. Il modulo prepara i fatti,
li scrive in un file temporaneo, e poi si paga il modello perche' vada a
leggerli.

Con una chiamata sola l'ingresso diventa il prompt dell'agente piu'
`_style.md` piu' i fatti. Contati con `count_tokens` su `claude-opus-5`:
fatti del giorno 5.511 token, della settimana 4.592; `_style.md` 1.308; i
file di agente da 901 (`01_health`) a 2.818 (`05_training`); una sezione
scritta 173 token (`health.md` del 6 novembre). Cioe' **circa 7.700 token in
ingresso e 300 in uscita per sezione**, contro i 46.000 di adesso: **11,36
dollari al mese**, un terzo.

Il resto che sparisce: `claude` che deve stare nel PATH, i glob dei permessi
col doppio slash, il controllo che il frammento sia stato scritto *adesso*, i
venti minuti di timeout del sottoprocesso.

## Cosa si fa

### 1. La chiamata al modello in un posto solo — `api/agents.py`, nuovo

Un modulo con una funzione: prende il nome dell'agente, il prompt e quello
che l'agente deve avere sotto gli occhi, e rende il testo. Niente tool,
niente file, niente sottoprocesso.

Il blocco di sistema e' il corpo del file dell'agente (il front matter di
Claude Code — `name`, `description`, `tools` — si toglie) **e poi**
`_style.md`, **in quest'ordine**. L'ordine non e' un dettaglio: il commento
sopra `VERDICT_LINE` (`api/refresh.py`, riga 514) dice che la riga del voto
sta nel prompt proprio perche' lo stile arriva *dopo* il file dell'agente, e
che col solo file dell'agente il frammento tornava senza. Invertirlo per
guadagnare un po' di cache non vale il rischio di rompere una cosa provata.

Come si chiama il modello, dalla skill `claude-api`:

- `model="claude-opus-5"`, che e' quello su cui gli agenti girano gia' (lo
  dicono i transcript): non e' una scelta nuova, e' la stessa.
- `max_tokens` largo, **8000**, per una sezione da 300 token. Non e' spreco:
  su Opus 5 il ragionamento e' **acceso per difetto** e `max_tokens` e' il
  tetto di ragionamento *piu'* testo. Con un tetto stretto la sezione si
  tronca a meta'.
- `thinking` si lascia come sta (adattivo). **Non si spegne**: con il
  ragionamento spento Opus 5 a volte scrive una chiamata a un tool dentro il
  testo visibile, o lascia uscire tag `<thinking>` — e qui di tool non ce ne
  sono comunque.
- `output_config={"effort": ...}` e' la leva del costo e della qualita': si
  parte dal valore per difetto e si prova a scendere, misurando. Non si
  decide a tavolino.
- Nessun `tools`, quindi nessun glob di permessi da scrivere.

### 2. I fatti nel messaggio, non su disco

`_prepare` (riga 404) scrive i fatti in un JSON temporaneo e il prompt ne da'
il percorso. I fatti vanno nel messaggio utente, e il file temporaneo
sparisce con la riga 304 che lo crea. `make daily_data` e `make weekly_data`
sono comandi a parte e continuano a scrivere il loro file: quello e' per
guardarci dentro, e resta.

La frase del prompt che dice **«The facts are in {facts}: read that file, do
not run anything»** va riscritta: non c'e' piu' un file da leggere.

### 3. I frammenti accanto, per chi li legge

Le sezioni con `reads_fragments` — il Summary del giorno e della settimana —
oggi leggono i cinque frammenti dalla cartella. Glieli passa l'orchestratore,
nel messaggio, **quelli che in quel momento ci sono**: e' esattamente quello
che il filesystem gli da' oggi, e quindi non cambia niente nemmeno quando una
sezione e' fallita e il suo frammento e' quello di prima.

### 4. Il piano settimanale — `api/weekplans.py`

Stessa cosa per `_write_week` (riga 390). Quello che il suo prompt nomina —
il blocco in `plan/` (il 2h20 e' 3.700 token), la settimana prima (1.946), il
README del formato — va nel messaggio. Il file lo scrive l'orchestratore in
`.staging/`, dove lo scrive adesso, e la validazione che c'e' gia' non si
tocca.

### 5. Che cosa si cancella

- `_allowed_tools` (riga 91) con il suo commento sul doppio slash;
- `shutil.which("claude")` in `refresh.py` e in `weekplans.py`;
- il controllo «il frammento esiste, e' di adesso, non e' vuoto» (righe
  586-590) diventa «il modello ha reso del testo non vuoto»: piu' semplice e
  piu' diretto, perche' il file lo scrive chi controlla;
- il `TIMEOUT_SECONDS` del sottoprocesso, al suo posto il timeout e i
  tentativi dell'SDK (`max_retries`, che per difetto riprova 429 e 5xx).

### 6. La chiave

`ANTHROPIC_API_KEY` deve arrivare al servizio e ai timer, che sono unita di
systemd (`deploy/mygarmin-api.service`, `mygarmin-morning.service`,
`mygarmin-evening.service`, `mygarmin-weekend.service`): un
`EnvironmentFile=` che punta a un file **fuori dal repo**, a 600. La chiave
assente deve fallire con un messaggio che si legge nel banner — in inglese,
come tutti gli altri dal todo di `english_messages` — e non con un traceback.

## Quello che non va toccato

- **Il contenuto dei file di agente.** Sono il prompt, e restano quello che
  sono: si toglie il front matter, non una parola del corpo.
- **La forma dei frammenti**: un file per sezione, i nomi delle cartelle, la
  riga `verdict:` in cima al Training.
- **Il lucchetto, la macchina degli stati, i banner, il tasto Refresh.**
  Questo todo cambia *come* si chiama il modello, non quando ne' che cosa si
  vede.
- **La CLI `claude` resta**: e' quella con cui ci lavoro a mano, e `/atodo`,
  `/code-review` e il resto non c'entrano niente con questo. Cambia solo come
  l'app chiama il modello da se'.

## Rischi

**I prompt sono scritti per un agente, non per una chiamata.** Non e' solo la
frase dei fatti: i tredici file di agente possono dare per scontato di poter
guardare in giro. Vanno riletti tutti prima di fidarsi, e il modo di
accorgersene e' la prova del punto successivo, non la lettura.

**Una chiamata sola non ha una seconda occhiata.** Oggi un agente a cui i
numeri sembrano strani puo' andare a leggere un altro file. Misurato: lo fa
0,09 volte per run, cioe' una volta su undici. La strada di mezzo esiste —
lasciare `Read` fra i tool e pagare il giro solo quando serve — e se la prova
dice che qualcosa si perde, e' quella da prendere invece di tornare indietro.

**La qualita' e' la cosa, il costo no.** 27 dollari al mese risparmiati non
comprano niente se le sezioni diventano peggiori: `_style.md` chiede un
giudizio da allenatore, ed e' il lavoro in cui il modo di lavorare conta. La
prova sta sotto, e viene prima del resto.

**La stima e' una stima.** 11,36 dollari al mese assume 300 token di uscita e
nessuna cache. Il `usage` vero della prima settimana lo dice; se e' molto piu'
alto, il motivo sara' il ragionamento, che in questo conto non c'e'.

**La cache, qui, non serve quasi a niente**, e va detto per non andarla a
cercare: una richiesta sola per sezione, un prefisso diverso per agente e
dodici ore fra un giro e l'altro. Il conto di sopra non la conta, ed e'
giusto cosi'.

## Come si verifica

**La prova che conta, e prima di tutto il resto**: lo stesso giorno scritto
nei due modi. `make daily_report DAY=<un giorno passato>` col codice di adesso
e col nuovo, sui *medesimi* fatti, e i frammenti a confronto — non per
vedere se sono uguali, che non lo saranno, ma se dicono le stesse cose e se
una delle due versioni e' peggiore. Da fare su qualche giorno diverso fra
loro: uno con una seduta dura, uno di riposo, una domenica con la settimana.

Poi:

- il `usage` vero di una settimana, sommato, contro gli 11,36 dollari al mese
  stimati qui;
- `test_write_section_refuses_an_empty_file` (`tests/test_refresh.py`, riga
  118) e' l'unico test che passa dal vero `_write_section`: diventa «il
  modello non ha reso niente». Gli altri sostituiscono `_write_section` e non
  cambiano;
- un doppio del client nei test. La regola della suite — non tocca Garmin ne'
  il data root vero, e si lancia sempre, anche senza rete — vale per l'API
  esattamente come per Garmin: nessun test deve chiamarla.

## Come e' andata

**La prova che conta.** Tre periodi scritti nei due modi, sugli stessi fatti,
in una cartella di prova (`summary_dir` temporanea, `update=False`, i report
veri non toccati): il 3 novembre, che e' una seduta corsa troppo lunga e
troppo forte; il 4 novembre, che e' un riposo; e la settimana del 26 ottobre
intera. Diciotto sezioni, nessuna fallita.

I verdetti sono gli stessi — `low` sul 3, `high` sul 4 — e i fatti citati
sono gli stessi: i dieci chilometri dove il piano diceva sette, i venti
secondi al km sotto la banda, i 2,5 minuti sopra Z3, il confronto con i 7,3
km delle uscite facili. In qualche punto la versione nuova dice **qualcosa in
piu'**: la velocita' all'andata e al ritorno nella Training del 3, i tre
giorni di riposo su sette in quella del 4, lo scarto sulle ore nella Load
della settimana. Niente che somigli a un calo.

**I tempi**: da 2 a 14 secondi per sezione, contro il minuto che ci voleva ad
avviare una sessione di Claude Code. Un giro della mattina sta sotto il
mezzo minuto.

**Quello che non ho misurato**: il costo vero. La stima del todo sono 11,36
dollari al mese, e per confermarla serve il `usage` di una settimana di giri
veri — questi diciotto li ho contati a occhio, non sommati. Chi guarda la
bolletta la prima settimana ha la risposta.

**Quello che non ho fatto**, perche' non e' mio da fare: scrivere la chiave
in `~/.config/mygarmin/api.env`. Finche' non c'e', il servizio riavviato
scrive nel banner *«The Anthropic client could not be built»* e nessuna
sezione si riscrive — che e' il comportamento voluto, non un guasto. Il
comando sta in `docs/service.md`.

**Una cosa che e' venuta meglio del previsto.** Il controllo «il file c'e',
e' di adesso, non e' vuoto» non e' stato sostituito da un controllo
equivalente: e' **sparito**. Adesso o il modello rende un testo o rende un
motivo, e il file lo scrive chi controlla. Con lui sono sparite tre
possibilita' di guasto muto che il todo non aveva nemmeno contato.

## Revert

```bash
git revert -m 1 $(git log main --merges \
  --grep="^Merge branch 'todo_94'$" --format=%H -1)
```

Effetti fuori dal repo: il file con `ANTHROPIC_API_KEY` resta su disco e le
unita' di systemd vanno reinstallate (`make install_services`) perche'
tornino a quelle senza `EnvironmentFile`. Niente dati cambiano: i frammenti
scritti nel frattempo restano quelli che sono, e il codice di prima li legge
senza accorgersi di chi li ha scritti.
