"""`config.py` promette un `ConfigError` che elenca tutto quello che non va:
nessuna chiave deve poter uscire con un'altra eccezione."""

from datetime import date

import pytest

from training.garmin.config import ConfigError, load_config


def test_a_plain_date_is_accepted(config_file):
    assert load_config(config_file).history_start == date(2025, 1, 1)


def test_a_datetime_is_refused_with_a_message(config_file):
    """`datetime` e' sottoclasse di `date`: passava l'isinstance e poi rompeva
    il confronto con `date.today()` con un `TypeError` all'import, cioe' un
    traceback su ogni comando."""
    config_file.write_text(
        config_file.read_text().replace("history_start: 2025-01-01", "history_start: 2025-01-01 00:00:00"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="senza l'ora"):
        load_config(config_file)


def test_a_future_date_is_refused(config_file):
    config_file.write_text(
        config_file.read_text().replace("history_start: 2025-01-01", "history_start: 2099-01-01"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="futuro"):
        load_config(config_file)
