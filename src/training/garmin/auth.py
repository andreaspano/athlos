"""Login a Garmin Connect, riusando un token salvato quando possibile."""

import getpass
import sys

from garminconnect import Garmin, GarminConnectAuthenticationError

from .config import TOKEN_STORE


def _ask_mfa_code() -> str:
    return input("Codice MFA/one-time inviato da Garmin: ").strip()


def init_api() -> Garmin:
    """Prova a riusare un token salvato; se non c'e' o non e' piu' valido,
    chiede email e password e fa un login completo.

    Il login completo ha bisogno di qualcuno davanti alla tastiera (password e
    codice MFA), e non sempre c'e': `api/refresh.py` lancia
    `make update_activity` con lo stdin chiuso, e cosi' fanno i timer. Prima
    qui un `except Exception` prendeva tutto e andava comunque a chiedere la
    password: senza stdin l'`input()` alzava `EOFError`, e in pagina arrivava
    la coda di un traceback invece di "il login e' scaduto". Lo stesso
    `except` scambiava per token scaduto anche un errore di rete passeggero
    (dopo aver caricato il token, la libreria chiede il profilo), buttando via
    un token buono.

    Quindi: solo l'errore di autenticazione porta al login completo, e solo se
    c'e' un terminale. Gli errori di rete escono come sono, cosi' chi ha
    chiamato riprova piu' tardi."""
    try:
        api = Garmin()
        api.login(TOKEN_STORE)
        print("Login effettuato riusando il token salvato.")
        return api
    except (GarminConnectAuthenticationError, FileNotFoundError) as exc:
        if not sys.stdin.isatty():
            raise GarminConnectAuthenticationError(
                "Il token Garmin non c'e' piu' o e' scaduto, e qui non c'e' "
                "nessuno a cui chiedere la password (stdin chiuso). Lancia "
                "`make update_activity` da un terminale per rifare il login: "
                "servono password e codice MFA. Poi i timer riprendono da "
                f"soli. ({exc})"
            ) from exc
        print("Nessun token valido trovato: serve un login completo.\n")

    email = input("Email Garmin: ").strip()
    password = getpass.getpass("Password Garmin (non verra' mostrata): ")
    api = Garmin(email=email, password=password, prompt_mfa=_ask_mfa_code)
    api.login(TOKEN_STORE)
    print("Login riuscito. Il token e' stato salvato per i prossimi avvii.\n")
    return api
