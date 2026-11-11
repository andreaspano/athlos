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


class TestOptionalKeys:
    """Le credenziali della bilancia: facoltative, e se ci sono stanno in
    coppia.

    Nascono da un modo di sbagliare vero: scritte in `config.yaml` quando il
    file non le conosceva, **ogni comando** si fermava all'import con
    "chiavi sconosciute" — l'API in piedi continuava a rispondere perche' la
    configurazione l'aveva gia' in memoria, quindi il guasto si sarebbe visto
    al primo timer della notte."""

    def test_without_them_the_config_is_valid(self, config_file):
        config = load_config(config_file)
        assert config.renpho_usr is None and config.renpho_pwd is None

    def test_both_written_are_read(self, config_file):
        config_file.write_text(
            config_file.read_text() + "renpho_usr: tizio@example.com\nrenpho_pwd: segreta\n",
            encoding="utf-8",
        )
        config = load_config(config_file)
        assert config.renpho_usr == "tizio@example.com"
        assert config.renpho_pwd == "segreta"

    def test_one_without_the_other_is_refused(self, config_file):
        """Mezza credenziale si vedrebbe solo al primo scarico che fallisce."""
        config_file.write_text(
            config_file.read_text() + "renpho_usr: tizio@example.com\n", encoding="utf-8"
        )
        with pytest.raises(ConfigError, match="vanno scritte insieme"):
            load_config(config_file)

    def test_an_empty_value_is_refused(self, config_file):
        config_file.write_text(
            config_file.read_text() + 'renpho_usr: ""\nrenpho_pwd: segreta\n', encoding="utf-8"
        )
        with pytest.raises(ConfigError, match="testo non vuoto"):
            load_config(config_file)

    def test_a_typo_is_still_unknown(self, config_file):
        """La porta non si e' aperta a tutti: `renpho_user` non e' una chiave,
        e va detto per nome."""
        config_file.write_text(
            config_file.read_text() + "renpho_user: tizio@example.com\n", encoding="utf-8"
        )
        with pytest.raises(ConfigError, match="chiavi sconosciute: renpho_user"):
            load_config(config_file)
