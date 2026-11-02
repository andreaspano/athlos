"""La readiness del risveglio: la prima **per ora dell'orologio**.

La lista che Garmin manda non e' ordinata nel tempo, e il risveglio puo'
esserci piu' di una volta — l'orologio rifa' il conto quando si rimette al
polso. Prendere la prima della lista sbagliava tredici giorni dell'archivio,
in media di dieci punti.
"""

from training.interface.health import _readiness_score


def entry(stamp: str, score: float, context: str = "AFTER_WAKEUP_RESET") -> dict:
    return {"timestamp": stamp, "score": score, "inputContext": context}


def test_the_earliest_wakeup_wins():
    """Il caso vero del 1 novembre: tre risvegli, il piu' presto e' terzo
    nella lista."""
    payload = [
        entry("2026-11-01T10:22:32.0", 61),
        entry("2026-11-01T12:49:10.0", 61),
        entry("2026-11-01T07:35:46.0", 77),
    ]
    assert _readiness_score(payload) == 77


def test_the_list_order_does_not_matter():
    payload = [entry("2026-10-18T07:38:00.0", 13), entry("2026-10-18T05:59:00.0", 68)]
    assert _readiness_score(payload) == 68
    assert _readiness_score(list(reversed(payload))) == 68


def test_a_single_wakeup_is_itself():
    assert _readiness_score([entry("2026-10-20T06:00:00.0", 55)]) == 55


def test_other_contexts_do_not_win_over_a_wakeup():
    """Una misura dopo l'allenamento, anche se piu' presto, non e' il
    risveglio."""
    payload = [
        entry("2026-10-20T05:00:00.0", 40, "AFTER_POST_EXERCISE_RESET"),
        entry("2026-10-20T06:30:00.0", 72),
    ]
    assert _readiness_score(payload) == 72


def test_without_a_wakeup_the_earliest_of_the_day_is_used():
    payload = [
        entry("2026-10-20T17:54:00.0", 50, "UPDATE_REALTIME_VARIABLES"),
        entry("2026-10-20T06:04:00.0", 64, "UPDATE_REALTIME_VARIABLES"),
    ]
    assert _readiness_score(payload) == 64


def test_an_entry_without_a_timestamp_goes_last():
    payload = [
        {"score": 30, "inputContext": "AFTER_WAKEUP_RESET"},
        entry("2026-10-20T06:00:00.0", 70),
    ]
    assert _readiness_score(payload) == 70


def test_entries_without_a_score_are_ignored():
    payload = [
        entry("2026-10-20T05:00:00.0", None),
        entry("2026-10-20T06:00:00.0", 66),
    ]
    assert _readiness_score(payload) == 66


def test_nothing_usable_is_none():
    assert _readiness_score([]) is None
    assert _readiness_score(None) is None
    assert _readiness_score({"score": 50}) is None
