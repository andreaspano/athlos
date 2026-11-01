"""`safe_call` deve distinguere "quel giorno non c'e' il dato" da "la chiamata
e' fallita": prima rispondeva `None` a entrambi, e un 500 diventava una
giornata vuota."""

import time

import pytest
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

from training.garmin.client import safe_call


def raising(exc):
    def call():
        raise exc
    return call


def test_not_found_is_a_day_without_data():
    assert safe_call(raising(GarminConnectNotFoundError("no data"))) is None


def test_a_value_passes_through():
    assert safe_call(lambda: {"a": 1}) == {"a": 1}


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("kwarg rinominato dalla libreria"),
        TypeError("firma cambiata"),
        RuntimeError("500 inatteso"),
        GarminConnectAuthenticationError("401"),
    ],
)
def test_real_errors_come_out(exc):
    with pytest.raises(type(exc)):
        safe_call(raising(exc))


@pytest.fixture
def no_waiting(monkeypatch):
    """Registra le pause invece di dormirle."""
    slept = []
    monkeypatch.setattr(time, "sleep", slept.append)
    return slept


def test_connection_error_raises_once_the_retries_are_spent(no_waiting):
    with pytest.raises(GarminConnectConnectionError):
        safe_call(raising(GarminConnectConnectionError("boom")), retries=3)


def test_no_wait_after_the_last_attempt(no_waiting):
    """Con tre tentativi le pause sono due: la terza non serviva a niente e
    durante un backfill costava tre minuti per chiamata."""
    with pytest.raises(GarminConnectTooManyRequestsError):
        safe_call(raising(GarminConnectTooManyRequestsError("429")), retries=3)
    assert no_waiting == [60, 120]


def test_transient_then_success(no_waiting):
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise GarminConnectConnectionError("transitorio")
        return "ok"

    assert safe_call(flaky) == "ok"
    assert attempts["n"] == 3
