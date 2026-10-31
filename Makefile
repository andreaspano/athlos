.PHONY: install_services uninstall_services frontend_build install_cron uninstall_cron daily_report weekly_report backfill_zones backfill_reports backfill_weeks update_activity backfill_activity_names backfill_health backfill fitness_status api frontend frontend_types weekly_data daily_data week_plans

update_activity:
	uv run python -c "from training.garmin import update_activity; update_activity()"

backfill_activity_names:
	uv run python -c "from training.garmin import backfill_activity_names; backfill_activity_names()"

# Lo storico delle metriche di salute, da history_start (user/config.yaml) a
# oggi: 30-45 minuti di chiamate a Garmin per ogni anno. Si puo' interrompere
# con Ctrl+C e rilanciare, riprende da dove era arrivato.
backfill_health:
	uv run python -c "from training.garmin import backfill_health; backfill_health()"

# Attivita' e metriche di salute di un intervallo a scelta, estremi inclusi:
#   make backfill FROM=2024-01-01 TO=2024-12-31
# Un anno di salute sono circa 4.000 chiamate, undici al giorno (30-45
# minuti). Come
# backfill_health, si interrompe con Ctrl+C e riprende dai giorni mancanti.
backfill:
	@test -n "$(FROM)" -a -n "$(TO)" || { echo "Uso: make backfill FROM=YYYY-MM-DD TO=YYYY-MM-DD"; exit 2; }
	uv run python -c "\
	from datetime import date; \
	from training.garmin.auth import init_api; \
	from training.garmin.config import DATA_DIR; \
	from training.garmin.activities import download_activities_between; \
	from training.garmin.health import export_daily_health; \
	start, end = date.fromisoformat('$(FROM)'), date.fromisoformat('$(TO)'); \
	assert start <= end, 'FROM deve venire prima di TO'; \
	api = init_api(); \
	download_activities_between(api, start.isoformat(), end.isoformat()); \
	export_daily_health(api, DATA_DIR, start, end)"

fitness_status:
	uv run training-fitness-status

# L'API, solo su 127.0.0.1 (niente login): letture, piu' il terreno, il tipo di
# corsa e il tasto Refresh (todo 41), che lancia `claude`. Documentazione su
# http://127.0.0.1:8000/docs
#
# Questo e' per lavorarci: ha `--reload` e vuole la porta libera. Quella che
# gira sulla macchina e' `mygarmin-api.service` (todo 82, vedi
# docs/service.md), che serve anche la pagina compilata: per usare questo,
# prima `systemctl --user stop mygarmin-api`.
api:
	uv run uvicorn training.api.app:app --host 127.0.0.1 --port 8000 --reload

# La pagina Day in React (todo 33 e 34), su http://127.0.0.1:5173. Chiede i dati
# all'API: prima make api. La prima volta: cd frontend && npm ci
frontend:
	cd frontend && npm run dev

# La pagina compilata in frontend/dist, che e' quella servita dal servizio
# (todo 82). In sviluppo non serve: `make frontend` e' vite, con il
# ricaricamento a caldo. **Dopo un cambio al frontend va rilanciata**, o il
# servizio continua a servire la pagina di prima.
frontend_build:
	cd frontend && npm run build

# Rigenera i tipi TypeScript (frontend/src/api/schema.ts) dall'OpenAPI, dopo
# ogni cambio ai modelli dell'API. Con l'API accesa (make api).
frontend_types:
	cd frontend && npm run gen:api


# I fatti di una settimana in JSON, per il report settimanale. Solo dati
# locali: per la settimana aggiornata, prima make update_activity.
#   make weekly_data                   (l'ultima settimana chiusa)
#   make weekly_data WEEK=2026-09-21   (un lunedi')
weekly_data:
	uv run training-weekly-data $(if $(WEEK),--week $(WEEK))

# Il report giornaliero, scritto dai sette agenti uno alla volta (todo 44).
# Lo stesso lavoro del tasto Refresh, ma da terminale: scarica i dati nuovi,
# prepara i fatti una volta sola e lancia gli agenti in fila.
#   make daily_report                        (oggi, tutte le sezioni)
#   make daily_report DAY=2026-10-07         (un giorno a scelta)
#   make daily_report SECTION=health         (solo una sezione)
daily_report:
	uv run training-daily-report $(if $(DAY),--day $(DAY)) $(if $(SECTION),--section $(SECTION))

# Riscrive i report vecchi nella forma di oggi (todo 50): salta le sezioni
# che ci sono gia' e non scarica niente da Garmin.
#
# **Sono ore di agenti**: i giorni sono otto sezioni l'uno (79 giorni da
# agosto fanno circa tre ore e mezza), le settimane otto a settimana. Si
# lancia quando non c'e' altro in corso: se il giro delle 10 o delle 22
# prende il lock, il ciclo si ferma e lo dice, e si rilancia dopo.
#   make backfill_reports FROM=2026-08-01                 (TO di default oggi)
#   make backfill_reports FROM=2026-09-01 TO=2026-09-07   (una settimana)
backfill_reports:
	@test -n "$(FROM)" || { echo "serve FROM=YYYY-MM-DD"; exit 1; }
	uv run training-daily-report --from $(FROM) $(if $(TO),--to $(TO))

# Lo stesso per le settimane: FROM e TO sono lunedi'.
#   make backfill_weeks FROM=2026-08-03
backfill_weeks:
	@test -n "$(FROM)" || { echo "serve FROM=YYYY-MM-DD (un lunedi')"; exit 1; }
	uv run training-weekly-report --from $(FROM) $(if $(TO),--to $(TO))

# Ricalcola i minuti per zona delle sedute (todo 54), dai record gia' in
# tabella: nessuna chiamata a Garmin, nessun file FIT riletto. Lo fa da se'
# anche ogni sync, su quelle che non li hanno; qui serve a rifarli tutti
# quando cambia il modo di contarli.
#   make backfill_zones
#   make backfill_zones FORCE=1    (anche quelle che li hanno gia')
backfill_zones:
	uv run python -c "from training.interface.db import fill_zone_minutes; \
	  fatte, senza = fill_zone_minutes(force=bool('$(FORCE)')); \
	  print(f'minuti per zona: {fatte} sedute calcolate, {senza} senza (nessuna soglia o nessun battito)')"

# Il report settimanale, scritto dagli otto agenti uno alla volta (todo 53).
# Non scarica niente: la settimana si scrive sui dati che ci sono.
#   make weekly_report                       (l'ultima settimana chiusa)
#   make weekly_report WEEK=2026-10-12       (un lunedi' a scelta)
#   make weekly_report SECTION=health        (solo una sezione)
weekly_report:
	uv run training-weekly-report $(if $(WEEK),--week $(WEEK)) $(if $(SECTION),--section $(SECTION))

# I fatti di un giorno in JSON, per il report giornaliero. Solo dati locali:
# per il giorno aggiornato, prima make update_activity.
#   make daily_data                  (oggi)
#   make daily_data DAY=2026-10-07   (un giorno a scelta)
daily_data:
	uv run training-daily-data $(if $(DAY),--day $(DAY))

# I piani settimanali di summary/05.plan/, generati dal blocco di un goal
# (todo 86). Li scrive un agente per settimana, uno alla volta, e il file
# arriva al suo posto solo se passa i controlli.
#
# **Genera dal lunedi' prossimo**: il passato e la settimana in corso non si
# riscrivono. Le settimane che ci sono gia' finiscono in
# summary/05.plan/.trash/ — una puo' essere stata riscritta a mano.
#
# Sono una sessione di `claude` per settimana e mezz'ora col lock in mano,
# lo stesso dei report: non si lancia vicino ai giri delle 8 e delle 21, che
# troverebbero il lock occupato e salterebbero il report.
#   make week_plans                        (il goal attuale, da lunedi' prossimo)
#   make week_plans DRY=1                  (dice cosa farebbe, senza agenti)
#   make week_plans GOAL=half_marathon_2.10
#   make week_plans FROM=2026-12-07 TO=2027-01-04
week_plans:
	uv run training-week-plans $(if $(GOAL),--goal $(GOAL)) $(if $(FROM),--from $(FROM)) $(if $(TO),--to $(TO)) $(if $(DRY),--dry-run)

# I giri che scrivono i report da soli (todo 47 per il giorno, 53 per la
# settimana). Le unita' stanno in deploy/ con tre segnaposto, perche' systemd
# non espande niente e il repo puo' stare dove vuole.
#
# `abspath` normalizza i percorsi: qui dentro sia `$PATH` sia `$HOME`
# finiscono con uno slash di troppo (`/home/andrea//.local/bin`), e senza
# questo il doppio slash finiva in tutte le righe installate (todo 81).
UV := $(abspath $(shell command -v uv))
# La cartella di uv entra nel PATH delle unita': il percorso assoluto basta a
# lanciare il comando, non a `make update_activity` che dentro chiama un
# altro `uv run`.
UV_DIR := $(dir $(UV))
CRON_LOG := $(abspath $(HOME)/.local/state/mygarmin-report.log)
UNIT_DIR := $(abspath $(HOME)/.config/systemd/user)
TIMERS := mygarmin-morning mygarmin-evening mygarmin-weekend
SERVICES := mygarmin-api

# Tutto quello che gira da solo sulla macchina: l'app (todo 82) e i tre giri
# dei report (todo 81).
#
# L'app e' un servizio solo — uvicorn che serve l'API e la pagina compilata —
# e per questo `install_services` prima compila. I giri sono timer, che
# rispetto a cron recuperano quello perso (`Persistent=true`) e lasciano un
# guasto visibile (`OnFailure=` e `systemctl --user --failed`).
#
# Ripetibile: riscrive le unita' e le riabilita. **Toglie anche le righe del
# crontab**, perche' i due meccanismi insieme si ruberebbero il lock a
# vicenda e ogni giro uscirebbe senza fare niente.
install_services: frontend_build
	@test -n "$(UV)" || { echo "uv non e' nel PATH"; exit 1; }
	@mkdir -p $(UNIT_DIR)
	@for f in deploy/mygarmin-*.service deploy/mygarmin-*.timer; do \
	   sed -e 's|__REPO__|$(CURDIR)|g' -e 's|__UV__|$(UV)|g' \
	       -e 's|__UVDIR__|$(UV_DIR:/=)|g' "$$f" > "$(UNIT_DIR)/$$(basename $$f)"; \
	 done
	@systemctl --user daemon-reload
	@for t in $(TIMERS); do systemctl --user enable --now $$t.timer >/dev/null; done
	@for s in $(SERVICES); do systemctl --user enable --now $$s.service >/dev/null; \
	   systemctl --user restart $$s.service; done
	@{ crontab -l 2>/dev/null | grep -v '# mygarmin$$' || true; } | crontab - 2>/dev/null || true
	@echo "Installati. L'app:"
	@systemctl --user --no-pager --no-legend list-units 'mygarmin-*.service' | head -3
	@echo "  http://127.0.0.1:8000"
	@echo "I prossimi giri:"
	@systemctl --user list-timers 'mygarmin-*' --no-pager
	@echo "Il registro: journalctl --user -u 'mygarmin-*' -f"
	@test "$$(loginctl show-user $$USER -p Linger --value 2>/dev/null)" = yes || { \
	   echo; \
	   echo "Nota: Linger e' spento, quindi i timer girano da quando fai"; \
	   echo "l'accesso e un giro perso parte al login. Per una macchina che"; \
	   echo "nessuno logga: sudo loginctl enable-linger $$USER"; }

# Toglie l'app e i timer, e lascia il resto in pace. Il cron non lo rimette:
# per quello c'e' install_cron.
uninstall_services:
	@for s in $(SERVICES); do systemctl --user disable --now $$s.service >/dev/null 2>&1 || true; done
	@for t in $(TIMERS); do systemctl --user disable --now $$t.timer >/dev/null 2>&1 || true; done
	@rm -f $(UNIT_DIR)/mygarmin-*.service $(UNIT_DIR)/mygarmin-*.timer
	@systemctl --user daemon-reload
	@echo "Tolti."

# Le righe di cron: il modo vecchio (todo 47), prima dei timer del todo 81.
# Resta perche' chi le ha ancora possa toglierle, e per poterci tornare.
#
# L'installazione e' ripetibile: toglie le righe `# mygarmin` che ci sono gia'
# e rimette queste, senza toccare il resto del tuo crontab.
install_cron:
	@test -n "$(UV)" || { echo "uv non e' nel PATH"; exit 1; }
	@mkdir -p $(dir $(CRON_LOG))
	@{ crontab -l 2>/dev/null | grep -v '# mygarmin$$' || true; \
	   sed -e 's|__REPO__|$(CURDIR)|g' -e 's|__UV__|$(UV)|g' -e 's|__UVDIR__|$(UV_DIR:/=)|g' \
	       -e 's|__LOG__|$(CRON_LOG)|g' \
	       deploy/crontab | grep '# mygarmin$$'; } | crontab -
	@echo "Installato. Il crontab adesso:"
	@crontab -l | grep '# mygarmin$$'
	@echo "Il registro dei giri: $(CRON_LOG)"

# Toglie i due giri e lascia il resto del crontab com'e'.
uninstall_cron:
	@{ crontab -l 2>/dev/null | grep -v '# mygarmin$$' || true; } | crontab -
	@echo "Tolti. Il crontab adesso:"
	@crontab -l 2>/dev/null || echo "  (vuoto)"
