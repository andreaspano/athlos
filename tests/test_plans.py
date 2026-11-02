"""I goal scritti a mano in `plan/`.

Sono documenti di una persona, non dati che un comando riscarica: il metro di
questi test e' che l'API non li rovini e non si fermi davanti a uno storto.
"""

import pytest

from training.api.plans import _set_current_flag, load_plans, set_current

PLAN = """---
race: 2027-02-28
race_name: mezza maratona
target_time: "2:20:00"
block_weeks: 18
# il goal che si sta seguendo (todo 84)
current: true
siblings: [a.md, b.md]
---

# Mezza maratona in 2h20

Il testo del piano.
"""


def write(folder, name, text, encoding="utf-8"):
    path = folder / name
    path.write_bytes(text.encode(encoding))
    return path


class TestUnreadableFiles:
    def test_a_latin1_plan_is_still_listed(self, tmp_path):
        """Bastava un accento salvato in latin-1 per far rispondere 500 a
        tutti e quattro gli endpoint dei goal — compresa la DELETE, cioe'
        l'unico modo di togliere il file che li rompeva."""
        write(tmp_path, "storto.md", PLAN.replace("Il testo", "Perche' si parte piano"), "latin-1")
        write(tmp_path, "buono.md", PLAN)

        plans = load_plans(tmp_path)

        assert {p["slug"] for p in plans} == {"storto", "buono"}
        assert all(p["title"] for p in plans)

    def test_a_latin1_plan_keeps_its_front_matter(self, tmp_path):
        write(tmp_path, "storto.md", PLAN.replace("Il testo", "Perche'"), "latin-1")
        plan = load_plans(tmp_path)[0]
        assert plan["target_time"] == "2:20:00"
        assert plan["weeks"] == 18


class TestWindowsLineEndings:
    def test_crlf_front_matter_is_read(self, tmp_path):
        """Con il solo `\\n` nel regex, un file salvato su Windows sembrava
        senza front matter: riquadri vuoti, e il flag scritto in un secondo
        blocco davanti al primo."""
        write(tmp_path, "crlf.md", PLAN.replace("\n", "\r\n"))
        plan = load_plans(tmp_path)[0]
        assert plan["target_time"] == "2:20:00"
        assert plan["current"] is True

    def test_setting_the_flag_on_a_crlf_file_does_not_duplicate_it(self, tmp_path):
        write(tmp_path, "crlf.md", PLAN.replace("\n", "\r\n"))
        set_current(tmp_path, "crlf")
        text = (tmp_path / "crlf.md").read_text(encoding="utf-8")
        assert text.count("---") == 2, "un front matter solo"
        assert "race: 2027-02-28" in text.replace("\r", "")


class TestSetCurrentFlag:
    def test_a_front_matter_that_cannot_be_read_is_left_alone(self, tmp_path):
        """Un file che comincia per `---` ma non si chiude: scrivergli il flag
        davanti retrocederebbe il suo front matter a testo del corpo, e con
        lui la gara, il bersaglio e le settimane del blocco."""
        broken = "---\nrace: 2027-02-28\nblock_weeks: 18\n\n# Titolo\n"
        path = write(tmp_path, "rotto.md", broken)

        with pytest.raises(ValueError, match="non si legge"):
            _set_current_flag(broken, True)
        with pytest.raises(ValueError):
            set_current(tmp_path, "rotto")
        assert path.read_text(encoding="utf-8") == broken, "il file e' intatto"

    def test_a_file_without_front_matter_gets_one(self, tmp_path):
        """Qui il blocco nuovo e' giusto: non c'e' niente da retrocedere."""
        plain = "# Un piano senza front matter\n\nSolo testo.\n"
        assert _set_current_flag(plain, True) == "---\ncurrent: true\n---\n" + plain

    def test_removing_the_key_takes_its_continuation_lines(self):
        """`current: >` su due righe: togliendo solo la prima, `  true`
        restava attaccato alla chiave di sopra e YAML leggeva
        `block_weeks: '18 true'` — da cui "manca block_weeks" su un file che
        ce l'aveva."""
        import yaml

        from training.api.plans import _front_matter

        text = "---\nblock_weeks: 18\ncurrent: >\n  true\nrace: 2027-02-28\n---\n\n# T\n"
        meta, _ = _front_matter(_set_current_flag(text, False))
        assert meta["block_weeks"] == 18
        assert "current" not in meta
        assert meta["race"] == yaml.safe_load("2027-02-28")

    def test_the_rest_of_the_file_is_untouched(self, tmp_path):
        """Il commento, l'ordine delle chiavi e `siblings` su una riga sola
        restano come li ha scritti la persona."""
        write(tmp_path, "uno.md", PLAN)
        write(tmp_path, "due.md", PLAN.replace("current: true\n", ""))

        set_current(tmp_path, "due")

        due = (tmp_path / "due.md").read_text(encoding="utf-8")
        uno = (tmp_path / "uno.md").read_text(encoding="utf-8")
        assert "# il goal che si sta seguendo (todo 84)" in due
        assert "siblings: [a.md, b.md]" in due
        assert "current: true" in due
        assert "current: true" not in uno, "il flag si toglie dagli altri"


class TestAtomicWrite:
    def test_a_failed_write_leaves_the_plan_whole(self, tmp_path, monkeypatch):
        from training.api import plans

        path = write(tmp_path, "uno.md", PLAN)

        def boom(self, *args, **kwargs):
            raise OSError("disco pieno")

        monkeypatch.setattr("pathlib.Path.write_text", boom)
        with pytest.raises(OSError):
            plans._write(path, "nuovo contenuto")

        assert path.read_text(encoding="utf-8") == PLAN
        assert not list(tmp_path.glob("*.tmp"))
