"""`files.write_json` non deve poter lasciare un file a meta', e
`files.read_json` non deve far cadere un giro per un file rovinato."""

import json

from training.garmin.files import read_json, write_json


def test_round_trip(tmp_path):
    write_json(tmp_path / "a.json", {"b": 2})
    assert read_json(tmp_path / "a.json") == {"b": 2}


def test_missing_file_gives_the_default(tmp_path):
    assert read_json(tmp_path / "nope.json", default={}) == {}


def test_truncated_file_gives_the_default(tmp_path, capsys):
    (tmp_path / "t.json").write_text('{"a":', encoding="utf-8")
    assert read_json(tmp_path / "t.json", default={}) == {}
    assert "non si legge" in capsys.readouterr().out


def test_sort_keys(tmp_path):
    write_json(tmp_path / "s.json", {"b": 1, "a": 2}, sort_keys=True)
    assert list(json.loads((tmp_path / "s.json").read_text())) == ["a", "b"]


def test_a_failed_write_leaves_the_old_file_whole(tmp_path):
    """E' il punto di tutta la funzione: la `json.dump` che muore a meta' non
    deve portarsi via il file buono di prima."""
    target = tmp_path / "keep.json"
    write_json(target, {"buono": True})

    class Unserializable:
        def __repr__(self):
            raise RuntimeError("serializzazione fallita")

    try:
        write_json(target, {"k": Unserializable()})
    except Exception:
        pass

    assert json.loads(target.read_text()) == {"buono": True}
    assert not list(tmp_path.glob("*.tmp"))
