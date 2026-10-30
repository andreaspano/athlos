"""L'utente di una richiesta: da quale cartella dati e da quale cartella dei
report leggere.

Ogni endpoint lo riceve da `get_user_context()`, una dipendenza FastAPI.
Oggi l'utente e' uno solo e la dipendenza rende sempre le stesse cartelle;
con il login cambiera' solo lei, non gli endpoint."""

from dataclasses import dataclass
from pathlib import Path

from training.garmin.config import DATA_DIR, PLAN_DIR, SUMMARY_DIR

# La radice del repo e non la cartella corrente: l'API non deve dipendere
# dalla cartella da cui si lancia. Serve ancora per le icone e per il `cwd`
# dei sottoprocessi, non piu' per i dati.
REPO_ROOT = Path(__file__).resolve().parents[3]
# I report e i piani stanno nella cartella dei dati dal todo 65, con tutto il
# resto che riguarda l'allenamento: `config.py` li nomina, qui si importano.
# Prima venivano dal repo, e il confine fra codice e dati passava in mezzo
# alla stessa cartella.
#
# Le icone no: sono dell'applicazione, uguali per tutti, e sono l'unica cosa
# che l'API serve da disco (`StaticFiles` in `app.py`).
ICONS_DIR = REPO_ROOT / "icons"
# La pagina compilata (`npm run build`). In sviluppo non si usa — ci pensa
# vite su 5173 — ma il servizio di systemd la serve da qui, cosi' la
# macchina ha un processo solo e una porta sola (todo 82).
DIST_DIR = REPO_ROOT / "frontend" / "dist"


@dataclass(frozen=True)
class UserContext:
    data_dir: Path
    summary_dir: Path
    plan_dir: Path


def get_user_context() -> UserContext:
    return UserContext(data_dir=DATA_DIR, summary_dir=SUMMARY_DIR, plan_dir=PLAN_DIR)
