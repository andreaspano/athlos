"""Il login completo vuole qualcuno alla tastiera. Sotto `api/refresh.py` e
sotto i timer non c'e': prima si arrivava a un `EOFError` in pagina."""

import pytest
from garminconnect import GarminConnectAuthenticationError, GarminConnectConnectionError

from training.garmin import auth


class NotATty:
    def isatty(self):
        return False

    def readline(self):
        raise EOFError("stdin chiuso")


def fake_garmin(exc):
    class Fake:
        def __init__(self, *args, **kwargs): ...

        def login(self, *args, **kwargs):
            raise exc

    return Fake


def test_expired_token_without_a_tty_says_what_to_do(monkeypatch):
    monkeypatch.setattr(auth, "Garmin", fake_garmin(GarminConnectAuthenticationError("scaduto")))
    monkeypatch.setattr("sys.stdin", NotATty())
    with pytest.raises(GarminConnectAuthenticationError, match="make update_activity"):
        auth.init_api()


def test_a_network_error_is_not_an_expired_token(monkeypatch):
    """Dopo aver caricato il token la libreria chiede il profilo: un errore di
    rete li' non deve far buttare via un token buono."""
    monkeypatch.setattr(auth, "Garmin", fake_garmin(GarminConnectConnectionError("Login failed: rete")))
    monkeypatch.setattr("sys.stdin", NotATty())
    with pytest.raises(GarminConnectConnectionError):
        auth.init_api()
