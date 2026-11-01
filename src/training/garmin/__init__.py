"""Backup completo (non ufficiale) del proprio account Garmin Connect.

Usa la libreria open source "python-garminconnect", che replica le
chiamate dell'app mobile Garmin Connect. NON e' un'API ufficiale Garmin:
puo' rompersi se Garmin cambia i suoi endpoint interni. Le credenziali
restano sul computer dell'utente: vengono usate solo per il login e poi
viene salvato un token locale, mai inviato altrove.
"""

import sys

try:
    import garminconnect  # noqa: F401
except ImportError:
    sys.exit(
        "Manca la libreria 'garminconnect'. Installala con:\n"
        "    pip install garminconnect\n"
        "e rilancia questo script."
    )

from .activities import backfill_activity_names, update_activity
from .health import backfill_health

__all__ = ["backfill_activity_names", "backfill_health", "update_activity"]
