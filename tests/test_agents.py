"""La chiamata al modello: che cosa gli si manda e che cosa si accetta.

Qui non si chiama l'API, come non si chiama Garmin: il client e' un doppio.
Quello che si prova e' il contorno, che e' dove stanno i modi di sbagliare —
il front matter che resta attaccato al prompt, lo stile nell'ordine
sbagliato, una risposta troncata presa per buona.
"""

from pathlib import Path

import pytest

from training.api import agents


@pytest.fixture
def repo(tmp_path):
    """Un repo finto con un agente e lo stile."""
    folder = tmp_path / agents.AGENTS_DIR
    folder.mkdir(parents=True)
    (folder / "01_health.md").write_text(
        "---\nname: 01_health\ntools: Read, Write\n---\n\nTu scrivi la sezione Health.\n",
        encoding="utf-8",
    )
    (folder / "_style.md").write_text("In inglese, per un atleta.\n", encoding="utf-8")
    return tmp_path


class Fake:
    """Un client che rende quello che gli si dice, e ricorda la richiesta."""

    class _Block:
        def __init__(self, text, type="text"):
            self.text = text
            self.type = type

    class _Answer:
        def __init__(self, content, stop_reason):
            self.content = content
            self.stop_reason = stop_reason

    def __init__(self, blocks=None, stop_reason="end_turn"):
        self.blocks = blocks if blocks is not None else [Fake._Block("il testo")]
        self.stop_reason = stop_reason
        self.seen = None
        self.messages = self

    def create(self, **kwargs):
        self.seen = kwargs
        return Fake._Answer(self.blocks, self.stop_reason)


class TestSystemPrompt:
    def test_the_front_matter_does_not_reach_the_model(self, repo):
        """Era roba di Claude Code: `tools: Read, Write` in un prompt dove di
        tool non ce n'e' nessuno e' un'istruzione che non si puo' seguire."""
        system = agents.system_prompt(repo, "01_health")

        assert "tools:" not in system
        assert "name: 01_health" not in system
        assert "Tu scrivi la sezione Health." in system

    def test_the_style_comes_after_the_agent(self, repo):
        """L'ordine e' la regola: lo stile vince, e per vincere arriva dopo.
        Col sottoprocesso lo faceva `--append-system-prompt-file`."""
        system = agents.system_prompt(repo, "01_health")

        assert system.index("Tu scrivi") < system.index("In inglese")

    def test_an_agent_that_is_not_there_says_so(self, repo):
        with pytest.raises(agents.AgentError, match="could not be read"):
            agents.system_prompt(repo, "99_non_esiste")


class TestUserMessage:
    def test_the_documents_come_before_the_work(self):
        message = agents.user_message("Scrivi la sezione.", {"facts": "{}"})

        assert message.index("<facts>") < message.index("Scrivi la sezione.")

    def test_every_document_is_in_a_tag_with_its_name(self):
        message = agents.user_message("x", {"facts": "{}", "plan": "il piano"})

        assert "<facts>\n{}\n</facts>" in message
        assert "<plan>\nil piano\n</plan>" in message

    def test_no_documents_is_just_the_work(self):
        assert agents.user_message("Scrivi.", {}) == "Scrivi."


class TestWrite:
    def test_it_renders_the_text_of_the_answer(self, repo):
        client = Fake()

        text = agents.write(repo, "01_health", "Scrivi.", {"facts": "{}"}, client=client)

        assert text == "il testo"
        assert client.seen["model"] == agents.MODEL
        assert client.seen["max_tokens"] == agents.MAX_TOKENS
        assert "tools" not in client.seen, "nessun tool: non c'e' niente da chiamare"

    def test_the_blocks_without_text_do_not_count(self, repo):
        """Su questo modello la risposta porta anche i blocchi di
        ragionamento, che hanno il testo vuoto."""
        client = Fake(blocks=[Fake._Block("", "thinking"), Fake._Block("il testo")])

        assert agents.write(repo, "01_health", "x", {}, client=client) == "il testo"

    def test_an_empty_answer_is_a_failure(self, repo):
        client = Fake(blocks=[Fake._Block("   ")])

        with pytest.raises(agents.AgentError, match="answered nothing"):
            agents.write(repo, "01_health", "x", {}, client=client)

    def test_a_truncated_answer_is_a_failure(self, repo):
        """Una sezione tagliata a meta' frase ha dei blocchi dentro e
        passerebbe per testo buono."""
        client = Fake(stop_reason="max_tokens")

        with pytest.raises(agents.AgentError, match="cut off"):
            agents.write(repo, "01_health", "x", {}, client=client)

    def test_a_refusal_is_a_failure(self, repo):
        client = Fake(stop_reason="refusal")

        with pytest.raises(agents.AgentError, match="declined"):
            agents.write(repo, "01_health", "x", {}, client=client)
