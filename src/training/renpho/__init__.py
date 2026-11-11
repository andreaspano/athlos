"""La bilancia (todo 97): le misure del corpo, da Renpho Health.

Un pacchetto a se' accanto a `garmin`, e per la stessa ragione per cui quello
esiste: e' una **sorgente**, cioe' un posto da cui i dati arrivano. Parla con
il cloud di Renpho attraverso `renpho-py`, scrive i suoi file sotto
`health/body_composition/` come `garmin.health` scrive i suoi, e non sa niente
di chi poi li legge.

Come `garmin`, non e' un'API ufficiale: `renpho-py` replica le chiamate
dell'app Renpho Health e puo' rompersi se Renpho cambia i suoi endpoint. Le
credenziali restano sulla macchina, in `user/config.yaml`.
"""

from .sync import update_weight

__all__ = ["update_weight"]
