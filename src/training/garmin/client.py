"""Wrapper per le chiamate API Garmin con gestione degli errori transitori."""

import time

from garminconnect import (
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)


def safe_call(func, *args, retries: int = 3, **kwargs):
    """Esegue una chiamata API. Restituisce `None` **soltanto** quando per quel
    giorno (o quella attivita') il dato non c'e': Garmin risponde 404 e la
    libreria alza `GarminConnectNotFoundError`. Gli errori transitori (rate
    limit, connessione) si riprovano; tutto il resto esce come eccezione,
    compreso l'errore di autenticazione.

    Prima qui c'era un `except Exception: return None` per ogni errore. Quel
    `None` diceva due cose diverse — "quel giorno non c'e' niente" e "la
    chiamata e' fallita" — e chi chiamava non poteva distinguerle: un 500 su
    `/activities` diventava "nessuna nuova attivita'", `make update_activity`
    usciva con 0 e la pagina scriveva il report su dati vecchi dichiarando che
    lo scaricamento era andato bene. Il silenzio sui dati stantii e'
    esattamente quello che il docstring di `api/refresh.py` dice di non voler
    permettere: da quando lanciano i timer non c'e' nessuno a guardare.

    Chi deve sopravvivere al singolo elemento che non si scarica (un giorno di
    salute, un'attivita') prende l'eccezione sul posto e tira avanti; chi
    scarica l'elenco su cui si basa tutto il resto la lascia uscire."""
    for attempt in range(1, retries + 1):
        try:
            return func(*args, **kwargs)
        except GarminConnectNotFoundError:
            # Deve stare prima di GarminConnectConnectionError, di cui e'
            # sottoclasse.
            return None
        except GarminConnectTooManyRequestsError:
            if attempt == retries:
                raise
            wait = 60 * attempt
            print(f"    Troppe richieste: pausa di {wait}s...")
            time.sleep(wait)
        except GarminConnectConnectionError as e:
            if attempt == retries:
                raise
            print(f"    Errore di connessione ({e}): nuovo tentativo tra 10s...")
            time.sleep(10)
    raise RuntimeError("safe_call: attempts ran out with no result")
