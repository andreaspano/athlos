"""Il testo scritto dal modello in casa, per la pagina Test.

Si prova quello che non ha bisogno di Ollama: che cosa finisce nel prompt e
che cosa ne resta fuori. La chiamata al modello no — quella vuole `ollama
serve` acceso, un modello scaricato e qualche secondo, e un test che si
appoggia a una macchina accesa non e' un test.

La cosa che vale la pena fissare e' il **recinto**: a chi scrive la Health
vanno le quattro misure della card e nient'altro. Il prompt dell'agente dice
di non guardare il sonno, la batteria e il VO2max; qui si fa in modo che non
li abbia proprio."""

import json
from datetime import date
from pathlib import Path

import pytest

from training.api import ollama

REPO_ROOT = Path(__file__).resolve().parents[1]


def measure(value, low, high, outer_low, outer_high):
    return {
        "value": value,
        "band": {"low": low, "high": high, "outer_low": outer_low, "outer_high": outer_high},
    }


@pytest.fixture
def payload():
    """Un giorno finto, con dentro anche la roba delle altre sezioni."""
    return {
        "day": "2026-11-13",
        "morning": {
            "resting_hr": measure(49.0, 47.4, 52.5, 44.8, 55.1),
            "hrv_last_night": measure(46.0, 38.8, 53.6, 31.4, 61.0),
            "resp_sleep": measure(14.0, 12.4, 15.0, 11.1, 16.2),
            "stress_avg_yesterday": measure(24.0, 20.7, 34.3, 13.9, 41.1),
            # Di Recovery e di Fitness: non devono arrivare al modello.
            "sleep_hours": measure(6.6, 6.8, 8.8, 5.7, 9.8),
            "body_battery_morning": measure(70.0, 60.0, 90.0, 50.0, 95.0),
            "readiness": measure(62.0, 50.0, 80.0, 40.0, 90.0),
        },
        "fitness": {"vo2max": 52.0},
        "alerts": ["resting_hr_up", "hrv_below_baseline"],
        "missing": ["spo2_avg", "resp_sleep"],
    }


def test_only_the_four_measures(payload):
    """Le quattro della card, e nessuna delle altre."""
    facts = ollama.health_facts(payload)
    assert set(facts["morning"]) == set(ollama.HEALTH_MEASURES)


def test_other_sections_stay_out(payload):
    """Niente VO2max e niente sonno: non sono della Health, e il modo sicuro
    di non farli commentare e' non darglieli."""
    facts = ollama.health_facts(payload)
    assert "fitness" not in facts
    for stranger in ("sleep_hours", "body_battery_morning", "readiness"):
        assert stranger not in facts["morning"]


def test_only_the_two_alerts(payload):
    """`hrv_below_baseline` e' di un'altra domanda — la media della settimana
    contro la fascia di Garmin — e `01_health.md` dice espressamente di
    lasciarlo stare."""
    facts = ollama.health_facts(payload)
    assert facts["alerts"] == ["resting_hr_up"]


def test_missing_keeps_only_its_own(payload):
    """`missing` serve (le regole di casa dicono di non commentare una misura
    che non c'e'), ma solo per le quattro."""
    facts = ollama.health_facts(payload)
    assert facts["missing"] == ["resp_sleep"]


@pytest.mark.parametrize(
    "value, expected",
    [
        (46.0, "inside its band"),
        (38.8, "inside its band"),  # gli estremi sono dentro
        (53.6, "inside its band"),
        (55.0, "above its band"),
        (35.0, "below its band"),
        (62.0, "far above its band"),
        (30.0, "far below its band"),
    ],
)
def test_where_reads_the_band(value, expected):
    """Dove sta un valore: il conto lo fa l'API, come la barra della card."""
    assert ollama._where(measure(value, 38.8, 53.6, 31.4, 61.0)) == expected


def test_where_without_a_band():
    """Una fascia nulla (troppi pochi giorni misurati) non diventa un
    giudizio inventato."""
    assert ollama._where({"value": 46.0, "band": None}) == "unknown"
    assert ollama._where({"value": None, "band": {"low": 1, "high": 2}}) == "unknown"


@pytest.mark.parametrize(
    "value, expected",
    [
        (46.0, "in the middle of its band"),
        (38.8, "in the low quarter of its band"),  # gli estremi sono dentro
        # Il confine fra il quarto e il mezzo sta a 42,5 e a 49,9: a mezzo
        # decimo da una parte e dall'altra, e quale dei due casi prenda il
        # confine esatto e' una cosa dei float e non una cosa da fissare.
        (42.0, "in the low quarter of its band"),
        (43.0, "in the middle of its band"),
        (49.5, "in the middle of its band"),
        (50.5, "in the high quarter of its band"),
        (53.6, "in the high quarter of its band"),
        (55.0, None),  # fuori dalla fascia: non c'e' un dentro da collocare
        (30.0, None),
    ],
)
def test_sits_reads_the_inside_of_the_band(value, expected):
    """Dentro la fascia erano due notizie dette con la stessa parola: la
    meta' centrale e i due quarti agli estremi. Il conto lo fa l'API, come
    quello di `_where`."""
    assert ollama._sits(measure(value, 38.8, 53.6, 31.4, 61.0)) == expected


def test_sits_without_a_band():
    """Senza fascia non c'e' un dentro, e il quarto non si inventa."""
    assert ollama._sits({"value": 46.0, "band": None}) is None
    assert ollama._sits({"value": None, "band": {"low": 1, "high": 2}}) is None


def test_sits_with_a_band_that_has_no_width():
    """Una fascia larga zero non divide per zero: il valore e' in mezzo, che
    e' il solo posto che quella fascia ha."""
    assert ollama._sits(measure(46.0, 46.0, 46.0, 46.0, 46.0)) == "in the middle of its band"


def test_front_matter_goes_away():
    """Il front matter e' di Claude Code: dice il nome dell'agente e i suoi
    attrezzi, e un modello locale di attrezzi non ne ha."""
    body = ollama._without_front_matter(
        "---\nname: 01_health\ntools: Read, Write\n---\n\nYou write the **Health** section."
    )
    assert body.startswith("You write")
    assert "tools:" not in body


def test_a_file_without_front_matter_survives():
    assert ollama._without_front_matter("Just the text.") == "Just the text."


def test_the_prompt_comes_from_the_ollama_directory():
    """Il prompt di sistema e' davvero i due file di `.ollama/agents/`, non
    una copia scritta qui che poi invecchia per conto suo."""
    system = ollama._system_prompt(REPO_ROOT, ollama.HEALTH.agent)
    assert "You write the **Health** section" in system
    assert "House rules" in system
    assert "name: 01_health" not in system


def test_llama_has_its_own_files():
    """La cartella esiste e non e' vuota: se tornasse a pescare da
    `.claude/agents/` il prompt di llama tornerebbe a essere quello di
    Claude, e nessuno se ne accorgerebbe fino a leggere la card."""
    for name in (ollama.HEALTH.agent, ollama.LOAD.agent, ollama.STYLE_FILE):
        assert ollama._prompt_file(REPO_ROOT, name).parent.name == "agents"
        assert ollama._prompt_file(REPO_ROOT, name).parent.parent.name == ".ollama"


def test_the_example_is_not_in_llamas_copy():
    """L'esempio in fondo al file di Claude llama lo ricopiava invece di
    guardare i numeri — l'HRV "al bordo basso" con un valore in mezzo alla
    fascia. La copia di `.ollama/agents/` non ce l'ha, ed e' il motivo per
    cui le due cartelle sono due."""
    assert "## Example" in (REPO_ROOT / ".claude/agents/01_health.md").read_text()
    assert "## Example" not in (REPO_ROOT / ".ollama/agents/01_health.md").read_text()


def test_a_missing_file_falls_back_to_claude(tmp_path):
    """Un file che in `.ollama/agents/` non c'e' si pesca da
    `.claude/agents/`: una differenza di una riga deve costare una riga, non
    due copie intere."""
    (tmp_path / ".ollama/agents").mkdir(parents=True)
    (tmp_path / ".claude/agents").mkdir(parents=True)
    (tmp_path / ".ollama/agents/01_health.md").write_text("mine")
    (tmp_path / ".claude/agents/_style.md").write_text("theirs")
    assert ollama._prompt_file(tmp_path, "01_health.md").read_text() == "mine"
    assert ollama._prompt_file(tmp_path, "_style.md").read_text() == "theirs"


def test_a_file_in_neither_place_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        ollama._prompt_file(tmp_path, "01_health.md")


def test_the_facts_are_in_the_message(payload):
    """L'agente di Claude i fatti li legge con Read; qui non c'e' nessun
    attrezzo, quindi devono stare nel messaggio."""
    text = ollama._user_prompt(ollama.HEALTH, date(2026, 11, 13), ollama.health_facts(payload))
    assert "hrv_last_night" in text
    assert "inside its band" in text
    assert "sleep_hours" not in text


# --- La Load: stessa pagina, un mestiere piu' difficile ---


@pytest.fixture
def load_payload():
    """Un giorno finto col carico, e dentro la roba che alla Load non va
    data: la settimana scorsa e il VO2max."""
    return {
        "day": "2026-11-13",
        "load": {
            "now": {
                "acwr": 0.8,
                "acwr_status": "OPTIMAL",
                "training_status_phrase": "PRODUCTIVE_3",
                "load_balance_phrase": "ANAEROBIC_SHORTAGE",
                "load_aerobic_low": 906.88,
                "load_aerobic_high": 817.99,
                "load_anaerobic": 130.79,
                "load_acute": 389.0,
                "load_chronic": 456.0,
            },
            "bands": {
                "load_aerobic_low": {"low": 856, "high": 1143, "outer_low": 712, "outer_high": 1287},
                "load_aerobic_high": {"low": 622, "high": 923, "outer_low": 472, "outer_high": 1074},
                "load_anaerobic": {"low": 69, "high": 120, "outer_low": 44, "outer_high": 145},
            },
            "week_ago": {"acwr": 0.8, "load_aerobic_low": 890.47},
            "vo2max_change": {"now": 43.1, "change": 1.6},
        },
        "recent": {
            "rest_days_last_7": 2,
            "days_since_last_hard_session_before_today": 1,
            "activities_last_14_days": ["una lista lunga"],
            "last_7_days": ["un'altra"],
        },
    }


WEEK = {
    "phase": "base",
    "block_week": 3,
    "block_weeks": 18,
    "sessions": [
        {"day": date(2026, 11, 9), "sport": "rest", "kind": None, "distance_label": None},
        {"day": date(2026, 11, 12), "sport": "running", "kind": "quality", "distance_label": "9 km"},
        {"day": date(2026, 11, 15), "sport": "running", "kind": "long", "distance_label": "16 km"},
    ],
}


def test_the_week_is_counted_here(load_payload):
    """Le sedute della settimana arrivano contate: quante ne chiede, quante
    dure, e quante ne restano da oggi in avanti. Date a llama le righe e
    basta, contava male — "due sedute dure ancora da fare" con una sola
    rimasta."""
    week = ollama.load_facts(load_payload, WEEK)["week"]
    assert week["asks_for"] == {"sessions": 2, "quality": 1, "long": 1, "easy": 0, "rest_days": 1}
    assert [s["kind"] for s in week["still_to_come"]] == ["long"]


def test_the_weekday_is_spelled_out(load_payload):
    """Il 15 novembre 2026 e' domenica, e un modello che deve indovinarlo
    sbaglia: aveva detto martedi'."""
    days = ollama.load_facts(load_payload, WEEK)["week"]["still_to_come"]
    assert days[0]["weekday"] == "Sunday"


def test_past_sessions_do_not_come_back(load_payload):
    """Quelle gia' passate non si mandano: la Load dice dove sta il carico
    oggi, il racconto dei giorni e' di un'altra sezione."""
    days = ollama.load_facts(load_payload, WEEK)["week"]["still_to_come"]
    assert all(d["day"] >= date(2026, 11, 13) for d in days)


def test_a_week_without_a_plan_is_not_a_fault(load_payload):
    """Fuori da un blocco la settimana non c'e', ed e' il caso normale."""
    assert ollama.load_facts(load_payload, None)["week"] is None


@pytest.mark.parametrize(
    "acwr, expected",
    [(0.6, "light"), (0.8, "lopsided"), (1.0, "lopsided"), (1.6, "heavy")],
)
def test_the_verdict_word_is_decided_here(load_payload, acwr, expected):
    """Con l'anaerobico fuori fascia e il rapporto ordinario il carico e'
    *lopsided*; sotto e sopra comandano il rapporto. La regola e' scritta nel
    prompt e llama scriveva "heavy" con un rapporto che lui stesso chiamava
    ordinario due paragrafi piu' sotto."""
    load_payload["load"]["now"]["acwr"] = acwr
    assert ollama.load_facts(load_payload)["state"]["verdict_word"] == expected


def test_load_keeps_the_three_parts(load_payload):
    facts = ollama.load_facts(load_payload)
    assert set(facts["balance"]) == set(ollama.LOAD_BALANCE)


def test_load_reads_each_part_against_its_own_band(load_payload):
    """La fascia di ogni carico e' la sua: l'anaerobico a 130.79 sta sopra la
    sua (69-120), gli altri due dentro le loro."""
    facts = ollama.load_facts(load_payload)
    assert facts["balance"]["load_anaerobic"]["where"] == "above its band"
    assert facts["balance"]["load_aerobic_low"]["where"] == "inside its band"
    assert facts["balance"]["load_aerobic_high"]["where"] == "inside its band"


def test_last_week_stays_out(load_payload):
    """`week_ago` il prompt lo nomina per dire che **non e' materiale suo** —
    questa e' una sezione su oggi. Il modo sicuro di non farlo raccontare e'
    non darglielo: chiederglielo e basta non ha funzionato con nient'altro."""
    facts = json.dumps(ollama.load_facts(load_payload))
    assert "week_ago" not in facts
    assert "890.47" not in facts


def test_vo2max_stays_out(load_payload):
    """Sta in `load` per ragioni storiche ed e' della Fitness."""
    assert "vo2max" not in json.dumps(ollama.load_facts(load_payload))


def test_rest_days_stay_out(load_payload):
    """I giorni di riposo e l'ultima seduta dura servivano a chiudere la
    sezione con un consiglio, e il consiglio e' andato via quando la sezione
    ha cominciato a leggere il piano: che cosa c'e' da fare lo dice il piano.
    Non darglieli e' il solo modo sicuro di non vederli tornare."""
    facts = json.dumps(ollama.load_facts(load_payload))
    assert "rest_days_last_7" not in facts
    assert "days_since_last_hard_session" not in facts


def test_todays_session_is_called_today(load_payload):
    """La seduta del giorno che si guarda si chiama `today` e non col nome
    del suo giorno: col nome llama lo sbagliava — la qualita' di giovedi' 12,
    guardata giovedi' 12, diventava "venerdi'"."""
    week = dict(WEEK, sessions=[
        {"day": date(2026, 11, 13), "sport": "running", "kind": "quality", "distance_label": "9 km"},
        {"day": date(2026, 11, 15), "sport": "running", "kind": "long", "distance_label": "16 km"},
    ])
    days = ollama.load_facts(load_payload, week)["week"]["still_to_come"]
    assert [d["weekday"] for d in days] == ["today", "Sunday"]


def test_garmins_codes_reach_the_writer(load_payload):
    """Le parole in maiuscolo di Garmin si danno: il prompt dice di leggerle e
    poi dire il senso da se', e per farlo bisogna averle."""
    state = ollama.load_facts(load_payload)["state"]
    assert state["acwr_status"] == "OPTIMAL"
    assert state["acwr"] == 0.8


def _prompt_names(section) -> list[str]:
    """I file di prompt di una sezione: uno per quella intera, e per quella
    spezzata quelli di ogni pezzo, l'apertura compresa."""
    if isinstance(section, ollama.Split):
        pieces = (section.opening, *section.parts)
        return [name for piece in pieces for name in piece.agent]
    return [section.agent]


def test_every_section_has_a_prompt_file():
    """Una sezione nel registro senza il suo file e' una card che risponde 503
    solo quando qualcuno la apre."""
    for section in ollama.SECTIONS.values():
        for name in _prompt_names(section):
            assert ollama._prompt_file(REPO_ROOT, name).exists()


def test_the_load_prompt_is_the_load_prompt():
    """Ogni sezione prende il **suo** file: con una chiave sbagliata nel
    registro le due card direbbero la stessa cosa, e guardando solo la Health
    non si vedrebbe."""
    system = ollama._system_prompt(REPO_ROOT, ollama.LOAD.agent)
    assert "You write the **Load** section" in system
    assert "You write the **Health** section" not in system


# --- La Health in cinque pezzi ---
#
# La sezione chiesta a cinque modelli piccoli invece che a uno: uno per
# misura, piu' uno che legge i quattro paragrafi e scrive il verdetto. Si
# prova la stessa cosa dell'altra strada — **il recinto** — ma un giro piu'
# stretto: a chi scrive dell'HRV non vanno le altre tre misure, non solo le
# altre sezioni. E si prova la forma, che e' tutto il motivo per cui questa
# strada esiste: cinque paragrafi perche' sono cinque risposte attaccate, non
# perche' il prompt l'abbia chiesto.


def part(key):
    return next(p for p in ollama.HEALTH_PARTS if p.key == key)


def owned(piece, facts, split=None):
    """Quello che tocca a un pezzo, chiesto come lo chiede `_split_text`: i
    test passano per la strada vera e non per una scorciatoia loro."""
    return piece.cut(split or ollama.HEALTH_SPLIT, piece, facts)


def asked(piece, facts, split=None, day=date(2026, 11, 13)):
    """Il messaggio di un pezzo, ritaglio compreso."""
    split = split or ollama.HEALTH_SPLIT
    return piece.asks(split, piece, day, owned(piece, facts, split))


def in_the_message(text):
    """I fatti nel messaggio di un pezzo, riletti dal JSON che ci sta
    dentro."""
    return json.loads(text[text.index("{") : text.rindex("}") + 1])


def test_the_four_parts_are_the_four_measures():
    """Le quattro della card, nel suo ordine: il testo finito e' questo
    ordine, e una card che legge le misure in un ordine e il testo in un
    altro si legge due volte."""
    assert tuple(p.key for p in ollama.HEALTH_PARTS) == ollama.HEALTH_MEASURES


def test_a_part_gets_only_its_own_measure(payload):
    """Il recinto dentro al recinto. Il prompt intero deve chiedere di non
    impastare due misure in un paragrafo e di non spiegare l'una con
    l'altra; qui le altre tre non ci sono, e una cosa che non si ha non si
    scrive."""
    facts = owned(part("hrv_last_night"), ollama.health_facts(payload))
    assert facts["value"] == 46.0
    assert facts["measure"] == "HRV of last night"
    for stranger in ("resting_hr", "resp_sleep", "stress_avg_yesterday", "sleep_hours"):
        assert stranger not in json.dumps(facts)


def test_a_part_gets_only_its_own_alert(payload):
    """`resting_hr_up` e' della frequenza e di nessun altro: un allarme in
    mano a chi non lo possiede e' un allarme che finisce nel testo."""
    facts = ollama.health_facts(payload)
    assert owned(part("resting_hr"), ollama.health_facts(payload))["alert"] == "resting_hr_up"
    assert owned(part("hrv_last_night"), ollama.health_facts(payload))["alert"] is None


def test_a_measure_that_was_not_recorded_says_so(payload):
    """`resp_sleep` e' in `missing`: chi scrive deve dirlo in una riga e non
    giudicare niente."""
    facts = owned(part("resp_sleep"), ollama.health_facts(payload))
    assert facts["missing"] is True


def test_a_measure_that_is_not_in_the_facts_is_missing_too(payload):
    """Non registrata e assente dai fatti sono la stessa cosa per chi scrive,
    e la riga da scrivere e' una sola."""
    del payload["morning"]["stress_avg_yesterday"]
    facts = owned(part("stress_avg_yesterday"), ollama.health_facts(payload))
    assert facts["missing"] is True
    assert facts["value"] is None
    assert facts["where"] == "unknown"


def test_each_part_has_its_own_prompt():
    """Ogni misura prende il **suo** file: con un nome sbagliato nel registro
    quattro paragrafi racconterebbero la stessa misura, e guardandone uno
    solo non si vedrebbe."""
    system = ollama._system_prompt(REPO_ROOT, *part("hrv_last_night").agent)
    assert "HRV of last night" in system
    assert "resting heart rate of this morning" not in system


def test_the_direction_is_written_in_the_measure_file():
    """**La cosa che si guadagna spezzando.** Il prompt intero la lasciava
    alle regole di casa, in una riga per tutte e quattro; qui ogni misura ha
    la sua, e l'HRV — la sola che si legge al contrario — ce l'ha tutta per
    se'."""
    hrv = ollama._system_prompt(REPO_ROOT, *part("hrv_last_night").agent)
    assert "the bad side of the\nband is the LOW side" in hrv
    for other in ("resting_hr", "resp_sleep", "stress_avg_yesterday"):
        text = ollama._system_prompt(REPO_ROOT, *part(other).agent)
        assert "**The bad side of the band is the high side**" in text


@pytest.mark.parametrize(
    "where, bad_when, expected",
    [
        ("inside its band", "above", "normal"),
        ("above its band", "above", "worse than usual"),
        ("far above its band", "above", "much worse than usual"),
        ("below its band", "above", "better than usual"),
        ("far below its band", "above", "much better than usual"),
        # L'HRV, la sola delle quattro che si legge al contrario.
        ("above its band", "below", "better than usual"),
        ("far above its band", "below", "much better than usual"),
        ("below its band", "below", "worse than usual"),
        ("unknown", "above", "not measured"),
    ],
)
def test_the_reading_puts_the_band_and_the_measure_together(where, bad_when, expected):
    """`_where` di proposito non giudica: dice dove sta il valore e non se
    quel posto e' una buona notizia, che per le quattro misure non e' lo
    stesso. Mettere le due cose insieme non e' giudicare, e' confrontare due
    parole — e i modelli quel confronto non lo facevano."""
    assert ollama._reading(where, bad_when) == expected


@pytest.mark.parametrize(
    "sits, bad_when, expected",
    [
        ("in the middle of its band", "above", "comfortably normal"),
        ("in the middle of its band", "below", "comfortably normal"),
        ("in the high quarter of its band", "above", "normal, but high in its range"),
        ("in the low quarter of its band", "above", "normal, and nowhere near trouble"),
        # L'HRV, che si legge al contrario anche qui dentro.
        ("in the low quarter of its band", "below", "normal, but low in its range"),
        ("in the high quarter of its band", "below", "normal, and nowhere near trouble"),
    ],
)
def test_inside_the_band_is_not_one_word(sits, bad_when, expected):
    """Il giudizio sfumato invece di quello categorico: una misura in mezzo
    alla fascia e una appoggiata all'estremo che conta sono normali tutte e
    due e non sono la stessa mattina. Da che parte della fascia stia la
    cattiva notizia lo mette qui `bad_when`, come per i valori fuori."""
    assert ollama._reading("inside its band", bad_when, sits) == expected


def test_the_fuzzy_normals_are_still_normal(payload):
    """**Nessuna delle tre conta come una misura che va male.** Il verdetto
    della mattina si conta da `reading`, e un valore dentro la fascia non
    deve poterlo spostare ne' farsi nominare dal paragrafo di apertura."""
    fuzzy = [
        ollama.NORMAL_MIDDLE,
        ollama.NORMAL_GOOD_EDGE,
        ollama.NORMAL_BAD_EDGE.format(edge="high"),
    ]
    assert ollama._health_verdict([*fuzzy, "normal"]) == "good"
    facts = verdict_facts(payload)
    assert facts["verdict"] == ollama.VERDICT_WORDS["good"]
    assert facts["what_it_rests_on"] == {"about": None, "measures": []}


def test_the_place_inside_the_band_arrives_only_in_the_reading(payload):
    """`sits` resta nell'API: in mano al modello sarebbe la posizione detta
    due volte, e llama3.1 la diceva due volte — "normal, but high in its
    range, sitting at the top end of its band"."""
    payload["morning"]["resting_hr"]["value"] = 52.0
    facts = owned(part("resting_hr"), ollama.health_facts(payload))
    assert "sits" not in facts
    assert "quarter" not in json.dumps(facts)
    assert facts["where"] == "inside its band"


def test_the_fifth_keeps_the_categorical_reading(payload):
    """`sits` e' dei quattro paragrafi e non del quinto: il paragrafo di
    apertura di fasce non parla — "no numbers, and no bands" — e un `reading`
    che dice *toward the bad edge* gli metterebbe in mano proprio quello."""
    payload["morning"]["resting_hr"]["value"] = 52.0  # dentro la fascia, in cima
    facts = ollama.health_facts(payload)
    hr = owned(part("resting_hr"), ollama.health_facts(payload))
    assert hr["reading"] == "normal, but high in its range"
    # Al quinto la stessa misura arriva normale, e basta.
    said = json.dumps(verdict_facts(payload))
    assert "in its range" not in said
    assert "comfortably" not in said


def test_the_reading_reaches_both_the_part_and_the_verdict(payload):
    """La stessa riga serve a tutti e due, e per lo stesso motivo. Il quinto
    apriva con *you are in good order* una mattina con quattro misure fuori
    dalla parte cattiva; il paragrafo dell'HRV diceva "il sistema nervoso e'
    ancora sotto carico" con un valore sopra la fascia, che per l'HRV e' una
    buona notizia."""
    facts = ollama.health_facts(payload)
    hrv = owned(part("hrv_last_night"), ollama.health_facts(payload))
    assert hrv["reading"] == "comfortably normal"
    # Tutte e quattro normali: al quinto non resta niente da nominare.
    assert verdict_facts(payload)["what_it_rests_on"] == {"about": None, "measures": []}


def test_the_shared_rules_come_after_the_measure():
    """Dal piu' stretto al piu' largo: la misura, le regole dei quattro
    paragrafi, le regole di casa. `_measure.md` dice "la misura nominata
    sopra", e sopra ci deve stare davvero."""
    system = ollama._system_prompt(REPO_ROOT, *part("resting_hr").agent)
    assert system.index("resting heart rate of this morning") < system.index(
        "One measure of the Health section"
    )
    assert system.index("One measure of the Health section") < system.index("House rules")


def test_the_verdict_gets_the_reading_of_the_measures_it_names(payload):
    """**Come si leggono, non quello che ne hanno detto.** Le frasi dei
    quattro c'erano perche' il verdetto non le contraddicesse, ed erano la
    sola prosa che avesse in mano: le ricopiava — la spiegazione del
    paragrafo che gli stava sotto, parola per parola, due centimetri sopra
    l'originale. `reading` e' la stessa verita' da cui quei paragrafi sono
    stati scritti e non e' prosa. **E solo delle misure di cui parla**: con
    tutte e quattro in mano le elencava tutte e quattro anche quando la
    seconda frase non doveva nominarne nessuna."""
    payload["morning"]["resting_hr"]["value"] = 54.0  # sopra la sua fascia
    facts = verdict_facts(payload)
    assert facts["how_they_read"] == [
        {"measure": "resting heart rate", "reading": "worse than usual"}
    ]


def test_the_verdict_never_sees_a_sentence_of_the_four(payload):
    """La firma non li prende piu': una prosa che non arriva e' una prosa
    che non si puo' ricopiare, ed e' anche la ragione per cui il quinto non
    aspetta piu' gli altri quattro (`_split_text`)."""
    import inspect

    assert "written" not in inspect.signature(ollama._health_opening_prompt).parameters


def test_the_verdict_never_sees_a_band(payload):
    """Dove sta una misura e' il mestiere dei quattro paragrafi, che gli
    stanno sotto. Dandogliela la ricopiava — *"it rests on resting heart
    rate, far above its band, HRV of last night, also far below its
    band..."* — e la riga che glielo vietava non e' servita."""
    facts = verdict_facts(payload)
    assert "band" not in json.dumps(facts)
    assert "49.0" not in json.dumps(facts)


def verdict_facts(payload):
    """I fatti nel messaggio del quinto."""
    return in_the_message(
        asked(ollama.HEALTH_SPLIT.opening, ollama.health_facts(payload))
    )


def test_the_verdict_is_told_which_way_is_bad(payload):
    """Le quattro non stanno dalla stessa parte: *sotto la fascia* in tre
    casi su quattro e' una buona notizia e nel quarto no. Il quinto quei
    file non li legge, e il confronto gli arriva fatto."""
    payload["morning"]["hrv_last_night"]["value"] = 60.0  # sopra la sua fascia
    payload["morning"]["resting_hr"]["value"] = 54.0  # sopra la sua
    why = verdict_facts(payload)["what_it_rests_on"]
    # L'HRV sopra la fascia e' una buona notizia e non porta il verdetto; la
    # frequenza sopra la sua lo porta.
    assert why["measures"] == ["resting heart rate"]


@pytest.mark.parametrize(
    "readings, expected",
    [
        (["normal"] * 4, "good"),
        (["better than usual", "much better than usual", "normal", "normal"], "good"),
        (["not measured", "normal", "normal", "normal"], "good"),
        (["worse than usual", "normal", "normal", "normal"], "niggle"),
        (["worse than usual", "worse than usual", "normal", "normal"], "off"),
        (["much worse than usual", "normal", "normal", "normal"], "off"),
        (["much worse than usual", "worse than usual", "normal", "normal"], "off"),
        (["much worse than usual", "worse than usual", "worse than usual", "normal"], "fatigue"),
        (["much worse than usual", "much worse than usual", "normal", "normal"], "fatigue"),
        (["worse than usual"] * 4, "fatigue"),
    ],
)
def test_the_verdict_is_decided_here(readings, expected):
    """La terza riga che un modello non regge, dopo `_where` e `_reading`.
    Il conto gliel'ho dato fatto e la regola scritta in tabella, e restava di
    un gradino fuori: due misure fuori, una delle quali due volte, gli
    facevano dire *a body carrying real fatigue* dove la regola dice
    *something is off*."""
    assert ollama._health_verdict(readings) == expected


def test_the_verdict_word_reaches_the_fifth(payload):
    """Deciso qui e messo nel messaggio: al quinto resta la frase.

    **E ci arriva in inglese, non come chiave.** Scriveva "your body is
    carrying a niggle this morning", che e' l'etichetta di un campo messa in
    bocca a un allenatore: un valore che in inglese sta in piedi da solo non
    ha bisogno di una riga che ne vieti la copia."""
    payload["morning"]["resting_hr"]["value"] = 54.0  # sopra la sua fascia
    assert verdict_facts(payload)["verdict"] == "broadly fine, with one measure out"
    assert set(ollama.VERDICT_WORDS) == {"good", "niggle", "off", "fatigue"}


@pytest.mark.parametrize(
    "bad, good, about, named",
    [
        (["a"], ["b"], "this one reads badly this morning", ["a"]),
        (["a", "b"], [], "these read badly this morning", ["a", "b"]),
        ([], ["b"], "nothing reads badly, and this one reads better than usual", ["b"]),
        (
            [],
            ["a", "b"],
            "nothing reads badly, and these read better than usual",
            ["a", "b"],
        ),
        # Niente su cui appoggiarsi: `about` nullo, e la seconda frase non c'e'.
        ([], [], None, []),
    ],
)
def test_the_second_sentence_knows_what_it_is_about(bad, good, about, named):
    """Erano tre casi scritti come tre regole nel prompt, e il quinto le
    mescolava: una mattina con due misure in cattivo stato chiusa con *"the
    morning is quiet, with nothing standing out as particularly positive or
    negative"*, che e' la terza regola applicata al primo caso.

    Il singolare e il plurale si contano qui per la stessa ragione: con una
    misura sola, *these read badly* gli ha fatto scrivere *"like the others
    that read badly this morning"*, e le altre non c'erano."""
    assert ollama._rests_on(bad, good) == {"about": about, "measures": named}


def test_a_quiet_morning_has_no_second_sentence(payload):
    """**La frase che non ha niente da dire se lo inventa.** Era "nothing
    reads badly, and all four sit where they should", una frase da dire senza
    nominare niente, e le mattine tranquille erano le sole che sbagliavano:
    *"it rests on a neutral balance of sleep, body battery, readiness and
    breathing rate"* — tre nomi di altre sezioni — e l'altra volta tre delle
    quattro misure che la riga di sopra gli vietava di nominare. Senza quella
    frase il paragrafo ne ha due, e non c'e' piu' niente da riempire."""
    facts = verdict_facts(payload)
    assert facts["what_it_rests_on"] == {"about": None, "measures": []}
    # E il campo che parla di quelle misure e' vuoto: non ce n'e' nessuna.
    assert facts["how_they_read"] == []


def test_the_split_uses_the_same_fence_as_the_whole():
    """Lo stesso ritaglio della sezione intera, e non una copia: due ritagli
    vorrebbero dire due recinti che divergono da soli, e il confronto fra le
    due card non direbbe piu' niente."""
    assert ollama.HEALTH_SPLIT.facts is ollama.HEALTH.facts


@pytest.mark.parametrize(
    "answered, expected",
    [
        ("One line.", "One line."),
        ("Two.\n\nParagraphs.", "Two. Paragraphs."),
        ("## Resting heart rate\n\nThe body.", "The body."),
        ('  Spaces.  ', "Spaces."),
    ],
)
def test_a_part_is_flattened_to_one_paragraph(answered, expected):
    """Una risposta con dentro una riga vuota farebbe sei paragrafi invece di
    cinque, e tanto varrebbe non aver spezzato niente."""
    assert ollama._one_paragraph(answered) == expected


def test_five_paragraphs_whatever_the_model_answers(payload, monkeypatch):
    """**La forma non e' piu' una preghiera.** Qualunque cosa rispondano i
    cinque, il testo e' il verdetto piu' i quattro paragrafi nell'ordine
    della card: non c'e' una riga di prompt che possa saltarne uno,
    impastarne due o aggiungerne un sesto. Il modello qui e' finto: la prova
    e' della cucitura, non di llama."""

    def answer(system, user):
        if "opening paragraph" in user:
            return "The body is fine.\n\n## And a heading it was not asked for.", "fake"
        measure = next(p.label for p in ollama.HEALTH_PARTS if p.label in user)
        return f"About {measure}.\n\nAnd a second paragraph.", "fake"

    monkeypatch.setattr(ollama, "_ask", answer)
    text, model = ollama._split_text(
        ollama.HEALTH_SPLIT, date(2026, 11, 13), payload, REPO_ROOT
    )
    assert model == "fake"
    assert text.split("\n\n") == [
        "The body is fine.",
        "About resting heart rate. And a second paragraph.",
        "About HRV of last night. And a second paragraph.",
        "About breathing rate in sleep. And a second paragraph.",
        "About stress yesterday. And a second paragraph.",
    ]


def test_a_silent_measure_is_the_whole_section_silent(payload, monkeypatch):
    """Una misura che non risponde e' la sezione che non risponde, come per
    la domanda sola: la pagina dice che Ollama non c'e' invece di mostrare
    una card con un buco."""

    def answer(system, user):
        raise ollama.OllamaError("Ollama is not there.")

    monkeypatch.setattr(ollama, "_ask", answer)
    with pytest.raises(ollama.OllamaError):
        ollama._split_text(ollama.HEALTH_SPLIT, date(2026, 11, 13), payload, REPO_ROOT)


# --- La Load in sei pezzi ---
#
# La seconda sezione spezzata, e la prima in cui i pezzi non sono la stessa
# domanda ripetuta: tre carichi con la loro fascia, un rapporto, il foglio
# della settimana, il verdetto in cima. Si prova quello che si provava della
# Health — **il recinto** e **la forma** — piu' la cosa nuova di questa
# sezione: che il recinto di sei pezzi diversi sia diverso per ognuno, e che
# un pezzo senza niente da dire sia un paragrafo in meno e non un buco.


def load_part(key):
    return next(p for p in ollama.LOAD_PARTS if p.key == key)


def load_owned(piece, payload, week=None):
    return owned(piece, ollama.load_facts(payload, week), ollama.LOAD_SPLIT)


def test_the_load_pieces_are_the_card_in_order(load_payload):
    """Il verdetto, i tre carichi nell'ordine in cui la card li disegna,
    quanto stai portando, che cosa la settimana chiede ancora. Il testo
    finito e' questo ordine, e una card che disegna i carichi in un ordine e
    li racconta in un altro si legge due volte."""
    assert ollama.LOAD_SPLIT.opening.key == "verdict"
    assert tuple(p.key for p in ollama.LOAD_PARTS) == (*ollama.LOAD_BALANCE, "carrying", "week")


def test_a_kind_of_work_gets_only_its_own(load_payload):
    """Il recinto dentro al recinto. Il prompt intero deve chiedere di non
    impastare due carichi in un paragrafo e di non pesare il proprio contro
    gli altri; qui gli altri due non ci sono."""
    facts = load_owned(load_part("load_anaerobic"), load_payload, WEEK)
    assert facts["value"] == 130.79
    assert facts["kind"] == "anaerobic work"
    assert facts["where"] == "above its band"
    for stranger in ("906.88", "817.99", "aerobic_low", "aerobic_high"):
        assert stranger not in json.dumps(facts)


def test_a_kind_of_work_has_no_reading(load_payload):
    """**La differenza vera con le misure della Health.** Li' la fascia ha
    una parte cattiva, ed e' della misura: `bad_when` la sa e `_reading` da'
    la notizia gia' fatta. Un carico sopra la sua fascia non e' ne' buono ne'
    cattivo finche' non si sa che settimana era, e decidere in Python quella
    riga vorrebbe dire scrivere in Python il giudizio per cui la sezione ha
    un prompt."""
    facts = load_owned(load_part("load_anaerobic"), load_payload, WEEK)
    assert "reading" not in facts
    assert all(p.bad_when is None for p in ollama.LOAD_PARTS)


def test_a_kind_of_work_gets_the_shape_of_the_week(load_payload):
    """Il carico si giudica contro quello che la settimana aveva chiesto: e'
    la prima riga in grassetto di `02_load.md`, ed e' il motivo per cui ai
    tre carichi il foglio arriva."""
    week = load_owned(load_part("load_anaerobic"), load_payload, WEEK)["week"]
    assert week["phase"] == "base"
    assert week["asks_for"]["quality"] == 1


def test_a_kind_of_work_never_gets_the_sessions_that_are_left(load_payload):
    """`still_to_come` e' il paragrafo in fondo alla sezione. Dato anche ai
    tre carichi, il lungo di domenica si leggerebbe quattro volte sulla
    stessa card."""
    facts = load_owned(load_part("load_aerobic_low"), load_payload, WEEK)
    assert "still_to_come" not in json.dumps(facts)
    assert "16 km" not in json.dumps(facts)


def test_a_kind_of_work_never_gets_the_ratio(load_payload):
    """Quanto stai portando e' il suo paragrafo, e sta sotto i tre: un
    carico che ha in mano anche il rapporto apre un conto che non e' il
    suo."""
    facts = load_owned(load_part("load_aerobic_high"), load_payload, WEEK)
    said = json.dumps(facts)
    assert "acwr" not in said
    assert "carrying" not in said
    assert "0.8" not in said


def test_a_kind_garmin_has_no_figure_for_says_so(load_payload):
    """`load_facts` i carichi che Garmin non ha non li mette in `balance`, e
    per chi scrive e' una riga sola da scrivere."""
    del load_payload["load"]["now"]["load_anaerobic"]
    facts = load_owned(load_part("load_anaerobic"), load_payload, WEEK)
    assert facts["missing"] is True
    assert facts["value"] is None
    assert facts["where"] == "unknown"


def test_the_opening_of_the_load_gets_only_the_word(load_payload):
    """**Il recinto piu' stretto del file.** Quella parola e' l'unica cosa
    della sezione che il prompt intero sbagliava a prompt pieno — *heavy* con
    un rapporto che lui stesso chiamava ordinario due paragrafi sotto — e un
    paragrafo che ha in mano una parola sola non ha niente con cui
    contraddire i cinque sotto di lui."""
    facts = in_the_message(
        asked(ollama.LOAD_SPLIT.opening, ollama.load_facts(load_payload, WEEK), ollama.LOAD_SPLIT)
    )
    # L'anaerobico sta sopra la sua fascia con un rapporto ordinario: storto.
    assert facts == {"verdict": "lopsided"}


def test_the_word_of_the_load_is_not_translated(load_payload):
    """La differenza con `VERDICT_WORDS`. Le quattro chiavi della Health
    erano etichette di un campo e in bocca a un allenatore si sentivano, e
    percio' sono state riscritte in frasi; *light*, *heavy*, *healthy* e
    *lopsided* sono aggettivi che in inglese stanno in piedi da soli.
    Ricopiato di peso, *your training load is lopsided* e' una frase."""
    load_payload["load"]["now"]["acwr"] = 1.5
    facts = load_owned(ollama.LOAD_SPLIT.opening, load_payload, WEEK)
    assert facts == {"verdict": "heavy"}


def test_no_opening_without_a_ratio(load_payload):
    """Senza il rapporto `_verdict_word` non da' nessuna parola, e
    un'apertura senza verdetto non e' un'apertura: la sezione comincia dal
    primo carico."""
    del load_payload["load"]["now"]["acwr"]
    assert load_owned(ollama.LOAD_SPLIT.opening, load_payload, WEEK) is None


def test_the_carrying_piece_gets_the_words_and_not_the_number(load_payload):
    """Il numero sta nella quarta casella della card, due centimetri sopra
    il testo, e la regola che lo vieta e' scritta nel prompt intero perche'
    il modello lo ricopiava comunque. Un pezzo che non ce l'ha non ha niente
    da ricopiare."""
    facts = load_owned(load_part("carrying"), load_payload, WEEK)
    assert facts == {"carrying": "about what you usually carry"}


def test_no_carrying_without_a_ratio(load_payload):
    """Niente rapporto, niente frase, niente paragrafo."""
    del load_payload["load"]["now"]["acwr"]
    assert load_owned(load_part("carrying"), load_payload, WEEK) is None


def test_the_week_piece_gets_only_what_is_left(load_payload):
    """La fase e i conteggi sono dei tre carichi, che contro la forma della
    settimana si giudicano. Qui c'e' la lista di chi manca, ed e' la sola
    cosa di cui questa frase parla."""
    facts = load_owned(load_part("week"), load_payload, WEEK)
    assert [s["weekday"] for s in facts["still_to_come"]] == ["Sunday"]
    assert set(facts) == {"still_to_come"}
    # `default=str` come nel messaggio vero: le date dei giorni sono date.
    said = json.dumps(facts, default=str)
    assert "asks_for" not in said
    assert "base" not in said


def test_an_empty_week_is_not_a_week_without_a_plan(load_payload):
    """Le due si somigliano abbastanza da andarci piano. **Vuota** vuol dire
    che la settimana c'e' e non chiede piu' niente — la domenica sera — e
    quella e' una frase da scrivere. **Nulla** vuol dire che quella settimana
    un foglio non ce l'ha, che e' il caso normale fuori da un blocco: li' il
    paragrafo non esiste."""
    done = {**WEEK, "sessions": [{**s, "day": date(2026, 11, 1)} for s in WEEK["sessions"]]}
    assert load_owned(load_part("week"), load_payload, done) == {"still_to_come": []}
    assert load_owned(load_part("week"), load_payload, None) is None


def test_garmins_codes_reach_nobody(load_payload):
    """Le tre parole in codice di Garmin il prompt intero le ha, e deve
    chiedere di leggerle e poi dire il significato da se' senza mai il
    codice. Nessuno dei sei pezzi le ha: il codice che non si ha non si
    ricopia, e di quello che dicono non resta fuori niente — la parola del
    verdetto e le parole del rapporto sono gia' il significato, contato
    qui."""
    facts = ollama.load_facts(load_payload, WEEK)
    pieces = (ollama.LOAD_SPLIT.opening, *ollama.LOAD_PARTS)
    said = json.dumps([owned(p, facts, ollama.LOAD_SPLIT) for p in pieces], default=str)
    for code in ("PRODUCTIVE_3", "ANAEROBIC_SHORTAGE", "OPTIMAL", "week_ago", "vo2max"):
        assert code not in said


def test_the_load_split_uses_the_same_fence_as_the_whole():
    """Lo stesso ritaglio della sezione intera, e non una copia: due ritagli
    vorrebbero dire due recinti che divergono da soli, e il confronto fra le
    due card non direbbe piu' niente."""
    assert ollama.LOAD_SPLIT.facts is ollama.LOAD.facts


def test_each_load_piece_has_its_own_prompt():
    """Ogni pezzo prende il **suo** file: con un nome sbagliato nel registro
    due paragrafi racconterebbero la stessa cosa, e guardandone uno solo non
    si vedrebbe."""
    anaerobic = ollama._system_prompt(REPO_ROOT, *load_part("load_anaerobic").agent)
    assert "efforts above threshold" in anaerobic
    assert "conversation" not in anaerobic
    week = ollama._system_prompt(REPO_ROOT, *load_part("week").agent)
    assert "still asks of him" in week


def test_the_shared_rules_come_after_the_kind_of_work():
    """Dal piu' stretto al piu' largo: il carico, le regole dei tre
    paragrafi, le regole di casa. `_part.md` dice "il tipo di lavoro nominato
    sopra", e sopra ci deve stare davvero."""
    system = ollama._system_prompt(REPO_ROOT, *load_part("load_aerobic_low").agent)
    assert system.index("easy aerobic work") < system.index(
        "One kind of work in the Load section"
    )
    assert system.index("One kind of work in the Load section") < system.index("House rules")


def fake_load_answers(system, user):
    """Un modello finto: risponde il nome del pezzo che gli e' stato chiesto,
    con dentro una riga vuota e un'intestazione che nessuno ha chiesto."""
    if "opening paragraph" in user:
        return "The load is lopsided.\n\n## And a heading nobody asked for.", "fake"
    piece = next(p.label for p in ollama.LOAD_PARTS if p.label in user)
    return f"About {piece}.\n\nAnd a second paragraph.", "fake"


def test_six_paragraphs_whatever_the_model_answers(load_payload, monkeypatch):
    """**La forma non e' piu' una preghiera.** Qualunque cosa rispondano i
    sei, il testo e' il verdetto piu' i cinque paragrafi nell'ordine della
    card. Il prompt intero quella forma la deve chiedere, e in fondo a
    `02_load.md` ci sono tre righe che la chiedono perche' tre volte non e'
    arrivata: tutti e sei scritti, il primo e' il verdetto, gli ultimi due
    non si uniscono. Qui sono sei risposte attaccate da Python."""
    monkeypatch.setattr(ollama, "_ask", fake_load_answers)
    text, model = ollama._split_text(
        ollama.LOAD_SPLIT, date(2026, 11, 13), load_payload, REPO_ROOT, WEEK
    )
    assert model == "fake"
    assert text.split("\n\n") == [
        "The load is lopsided.",
        "About easy aerobic work. And a second paragraph.",
        "About harder aerobic work. And a second paragraph.",
        "About anaerobic work. And a second paragraph.",
        "About how much you are carrying. And a second paragraph.",
        "About what the week still asks for. And a second paragraph.",
    ]


def test_a_week_without_a_plan_is_a_paragraph_in_less(load_payload, monkeypatch):
    """**Un pezzo che non ha niente non si chiede.** Fuori da un blocco la
    settimana un foglio non ce l'ha, e il prompt intero quel buco lo deve
    chiedere a parole ("e' nullo quando la settimana non ha un piano, e
    allora non c'e' niente da dirne"). Qui e' un pezzo in meno nella lista:
    cinque paragrafi, e l'ultimo non parla della settimana."""
    monkeypatch.setattr(ollama, "_ask", fake_load_answers)
    text, _ = ollama._split_text(
        ollama.LOAD_SPLIT, date(2026, 11, 13), load_payload, REPO_ROOT, None
    )
    paragraphs = text.split("\n\n")
    assert len(paragraphs) == 5
    assert "week" not in text
    assert paragraphs[-1].startswith("About how much you are carrying")


# --- La Recovery: la domanda di prima ---
#
# La terza sezione, e l'unica del banco che non si confronta con se' stessa:
# a sinistra la pagina mette il frammento che l'agente di Claude ha scritto
# davvero, a destra llama con lo stesso prompt. Quindi niente `Split` e
# niente pezzi: si prova **il recinto** — le quattro misure della card e
# nient'altro, che qui conta piu' che altrove perche' il prompt la tentazione
# se la nomina da solo — e che la copia di llama sia davvero la stessa
# domanda di quella di Claude.


@pytest.fixture
def recovery_payload():
    """Un giorno finto con la mattina della Recovery, e dentro la roba delle
    altre sezioni: quella di Health e' la tentazione vera, che una readiness
    bassa con l'HRV si spiega benissimo."""
    return {
        "day": "2026-11-19",
        "sleep_minutes": 489,
        "morning": {
            "readiness": measure(88.0, 60.2, 79.3, 50.6, 88.9),
            "sleep_hours": measure(8.2, 6.9, 8.8, 5.9, 9.8),
            "body_battery_morning": measure(80.0, 64.1, 96.4, 47.9, 100.0),
            "body_battery_low_yesterday": measure(14.0, 12.3, 31.9, 2.6, 41.6),
            # Di Health e di Load: non devono arrivare al modello.
            "resting_hr": measure(49.0, 47.4, 52.5, 44.8, 55.1),
            "hrv_last_night": measure(46.0, 38.8, 53.6, 31.4, 61.0),
            "stress_avg_yesterday": measure(24.0, 20.7, 34.3, 13.9, 41.1),
        },
        "fitness": {"vo2max": 52.0},
        "load": {"now": {"acwr": 0.8}},
        "recent": {"rest_days_last_7": 2},
        "alerts": ["short_sleep", "resting_hr_up"],
        "missing": ["spo2_avg", "body_battery_low_yesterday"],
    }


def test_only_the_four_measures_of_the_card(recovery_payload):
    """Le quattro della card Recovery, e nessuna delle altre."""
    facts = ollama.recovery_facts(recovery_payload)
    assert set(facts["morning"]) == set(ollama.RECOVERY_MEASURES)
    assert tuple(facts["morning"]) == ollama.RECOVERY_MEASURES


def test_health_stays_out_of_recovery(recovery_payload):
    """**La tentazione che il prompt si nomina da solo**: "non cercarli, nemmeno
    per spiegare una readiness scarsa, e li' la tentazione e' ovvia". Il modo
    sicuro di non vederlo fare e' non darglieli."""
    facts = ollama.recovery_facts(recovery_payload)
    assert "fitness" not in facts
    assert "load" not in facts
    assert "recent" not in facts
    for stranger in ("resting_hr", "hrv_last_night", "stress_avg_yesterday"):
        assert stranger not in facts["morning"]


def test_only_the_sleep_alert(recovery_payload):
    """`short_sleep` e' suo e lo dice `03_recovery.md`; `resting_hr_up` e' di
    Health, e un allarme in mano a chi non lo possiede finisce nel testo."""
    assert ollama.recovery_facts(recovery_payload)["alerts"] == ["short_sleep"]


def test_recovery_missing_keeps_only_its_own(recovery_payload):
    """`missing` serve — le regole di casa dicono di non commentare una misura
    che non c'e' — ma solo per le quattro."""
    assert ollama.recovery_facts(recovery_payload)["missing"] == [
        "body_battery_low_yesterday"
    ]


def test_the_night_arrives_in_both_spellings(recovery_payload):
    """La card scrive il sonno in ore e minuti e la fascia e' in ore: sono lo
    stesso fatto in due lingue, e tutti e due servono — il numero grande e la
    barra sotto di lui. Quale delle due si scrive lo dice il prompt."""
    facts = ollama.recovery_facts(recovery_payload)
    assert facts["sleep_minutes"] == 489
    assert facts["morning"]["sleep_hours"]["value"] == 8.2


def test_recovery_reads_each_measure_against_its_own_band(recovery_payload):
    """Ogni misura contro la sua fascia, come in Health: la readiness a 88 sta
    sopra la sua (60.2-79.3), il minimo di ieri a 14 dentro la sua."""
    facts = ollama.recovery_facts(recovery_payload)
    assert facts["morning"]["readiness"]["where"] == "above its band"
    assert facts["morning"]["body_battery_low_yesterday"]["where"] == "inside its band"


def test_recovery_ignores_the_week(recovery_payload):
    """Come il corpo ha dormito stanotte non dipende da che cosa c'era scritto
    sul foglio: il piano arriva e viene ignorato, come alla Health."""
    assert ollama.recovery_facts(recovery_payload, WEEK) == ollama.recovery_facts(
        recovery_payload
    )


def test_the_whole_recovery_stays_in_the_registry():
    """La sezione intera resta chiedibile anche da quando la pagina mostra
    quella spezzata: e' il termine di paragone della prima sera — la storia sta
    in `recovery_facts` — e una strada che si butta prima di aver deciso non si
    puo' piu' riguardare."""
    assert not isinstance(ollama.SECTIONS["recovery"], ollama.Split)
    assert isinstance(ollama.SECTIONS["recovery_split"], ollama.Split)


def test_llama_has_its_own_copy_of_the_recovery_prompt():
    """La copia sta in `.ollama/agents/`: se tornasse a pescare da
    `.claude/agents/` il prompt di llama tornerebbe a essere quello di Claude,
    e nessuno se ne accorgerebbe fino a leggere la card."""
    assert ollama._prompt_file(REPO_ROOT, ollama.RECOVERY.agent).parent.parent.name == (
        ".ollama"
    )


def test_the_recovery_copy_is_the_same_question_as_claudes():
    """**Fra le due card cambia chi scrive e nient'altro**, quindi la copia di
    llama deve restare la stessa domanda: la forma di Claude — il verdetto e
    poi le quattro misure in una clausola o due — e non i cinque paragrafi a
    cui le altre due sezioni sono state portate. Quello che va via e' solo
    cio' che a un modello senza attrezzi non vuol dire niente."""
    mine = ollama._prompt_file(REPO_ROOT, ollama.RECOVERY.agent).read_text()
    theirs = (REPO_ROOT / ".claude/agents/03_recovery.md").read_text()
    for shape in ("Open with the verdict", "each in a clause or two"):
        assert shape in mine and shape in theirs
    # L'esempio llama lo ricopia invece di guardare i numeri, ed e' il motivo
    # per cui le due cartelle sono due.
    assert "## Example" in theirs
    assert "## Example" not in mine
    # Gli attrezzi non ce li ha: i fatti stanno nel messaggio.
    assert "tools:" not in mine
    assert "facts file" not in mine


def test_the_recovery_facts_are_in_the_message(recovery_payload):
    """I fatti nel messaggio, che di attrezzi per leggere un file non ce n'e'
    nessuno — e solo i suoi."""
    text = ollama._user_prompt(
        ollama.RECOVERY, date(2026, 11, 19), ollama.recovery_facts(recovery_payload)
    )
    assert "Write the Recovery section" in text
    assert "body_battery_low_yesterday" in text
    assert "hrv_last_night" not in text


# --- La Recovery in cinque pezzi ---
#
# La terza spezzata, e quella che somiglia di piu' alla Health: quattro misure
# della mattina e un quinto che le legge. Si prova il recinto, come per le
# altre due, e poi le tre cose che di questa sezione sono solo sue — i due
# body battery che sono due pezzi, la misura senza parte cattiva, e il costo
# di ieri che entra nel paragrafo di apertura senza entrare nel verdetto.


def rec_part(key):
    return next(p for p in ollama.RECOVERY_PARTS if p.key == key)


def rec_owned(piece, payload):
    return owned(piece, ollama.recovery_facts(payload), ollama.RECOVERY_SPLIT)


def rec_opening(payload):
    """I fatti nel messaggio del quinto della Recovery."""
    return in_the_message(
        asked(
            ollama.RECOVERY_SPLIT.opening,
            ollama.recovery_facts(payload),
            ollama.RECOVERY_SPLIT,
            date(2026, 11, 19),
        )
    )


def test_the_recovery_pieces_are_the_card_in_order():
    """Il verdetto e poi le quattro misure nell'ordine della card: il testo
    finito e' questo ordine, e una card che mostra le misure in un ordine e le
    racconta in un altro si legge due volte."""
    assert ollama.RECOVERY_SPLIT.opening.key == "verdict"
    assert tuple(p.key for p in ollama.RECOVERY_PARTS) == ollama.RECOVERY_MEASURES


def test_a_recovery_piece_gets_only_its_own_measure(recovery_payload):
    """Il recinto dentro al recinto, come per la Health: le altre tre non ci
    sono, e una cosa che non si ha non si scrive."""
    facts = rec_owned(rec_part("readiness"), recovery_payload)
    assert facts["value"] == 88.0
    assert facts["measure"] == "readiness"
    for stranger in ("sleep", "body_battery", "hrv", "resting"):
        assert stranger not in json.dumps(facts)


def test_the_two_body_batteries_are_two_pieces(recovery_payload):
    """**Mezzo motivo per spezzare.** Sono lo stesso numero a due ore diverse,
    il prompt intero deve chiedere di non confonderli, e la prima sera llama
    li ha impastati in una frase. Due modelli che l'uno dell'altro non sanno
    niente non possono farlo."""
    wake = rec_owned(rec_part("body_battery_morning"), recovery_payload)
    low = rec_owned(rec_part("body_battery_low_yesterday"), recovery_payload)
    assert wake["value"] == 80.0
    assert low["value"] == 14.0
    assert "14.0" not in json.dumps(wake)
    assert "80.0" not in json.dumps(low)


def test_the_low_of_yesterday_has_no_reading(recovery_payload):
    """Una giornata che e' costata e' un fatto sull'allenamento e non un
    difetto del recupero: dargli una direzione vorrebbe dire far contare una
    seduta dura come una cattiva notizia sul corpo."""
    low = rec_owned(rec_part("body_battery_low_yesterday"), recovery_payload)
    assert "reading" not in low
    assert low["where"] == "inside its band"
    assert rec_part("body_battery_low_yesterday").bad_when is None


def test_the_other_three_are_read_from_below(recovery_payload):
    """Readiness, notte e batteria al risveglio: la parte cattiva e' in basso
    per tutte e tre, che e' la riga delle regole di casa."""
    counted = [p for p in ollama.RECOVERY_PARTS if p.bad_when]
    assert [p.key for p in counted] == [
        "readiness",
        "sleep_hours",
        "body_battery_morning",
    ]
    assert {p.bad_when for p in counted} == {"below"}
    # La readiness a 88 sta sopra la sua fascia, che per lei e' buona notizia.
    assert rec_owned(rec_part("readiness"), recovery_payload)["reading"] == (
        "better than usual"
    )


def test_the_night_piece_gets_the_minutes_of_the_card(recovery_payload):
    """Il fatto arriva in due scritture e tutte e due servono: i minuti sono
    il numero grande della card, le ore sono quelle che la fascia confronta."""
    night = rec_owned(rec_part("sleep_hours"), recovery_payload)
    assert night["sleep_minutes"] == 489
    assert night["value"] == 8.2


def test_the_night_piece_is_told_which_spelling_to_write(recovery_payload):
    """Senza questa riga, la prima sera llama ha scritto "almost eight hours"
    per 8h09: la scrittura sbagliata, e pure dalla parte sbagliata."""
    text = asked(
        rec_part("sleep_hours"),
        ollama.recovery_facts(recovery_payload),
        ollama.RECOVERY_SPLIT,
        date(2026, 11, 19),
    )
    assert "in hours and minutes" in text
    assert "never 8.2 hours" in text


def test_the_sleep_alert_is_the_night_piece_and_nobody_else(recovery_payload):
    """`short_sleep` parla della notte: un allarme in mano a chi non lo
    possiede e' un allarme che finisce nel testo."""
    assert rec_owned(rec_part("sleep_hours"), recovery_payload)["alert"] == "short_sleep"
    for other in ("readiness", "body_battery_morning", "body_battery_low_yesterday"):
        assert rec_owned(rec_part(other), recovery_payload)["alert"] is None


def test_each_recovery_piece_has_its_own_prompt():
    """Ogni misura prende il **suo** file: con un nome sbagliato nel registro
    due paragrafi racconterebbero la stessa misura, e guardandone uno solo non
    si vedrebbe."""
    wake = ollama._system_prompt(REPO_ROOT, *rec_part("body_battery_morning").agent)
    assert "how far the system refilled overnight" in wake
    low = ollama._system_prompt(REPO_ROOT, *rec_part("body_battery_low_yesterday").agent)
    assert "what yesterday cost you" in low
    assert "refilled overnight" not in low


def test_the_recovery_shared_rules_come_after_the_measure():
    """Dal piu' stretto al piu' largo: la misura, le regole dei quattro
    paragrafi, le regole di casa."""
    system = ollama._system_prompt(REPO_ROOT, *rec_part("readiness").agent)
    assert system.index("Your measure is **readiness**") < system.index(
        "One measure of the Recovery section"
    )
    assert system.index("One measure of the Recovery section") < system.index(
        "House rules"
    )


def test_the_measure_frame_is_shared_with_health(recovery_payload, payload):
    """**La cornice e' una.** Scrivi il paragrafo di questa misura della
    sezione tale, le altre non sono tue, rispondi col solo paragrafo: la
    stessa domanda per tutte e due le sezioni, e di quale si tratti lo dicono
    `split.title` e `part.label`. Due copie sarebbero due cose che divergono
    al primo che ne ritocca una."""
    mine = asked(
        rec_part("readiness"),
        ollama.recovery_facts(recovery_payload),
        ollama.RECOVERY_SPLIT,
        date(2026, 11, 19),
    )
    theirs = asked(part("resting_hr"), ollama.health_facts(payload))
    assert "for the Recovery section" in mine
    assert "for the Health section" in theirs
    shared = "the other three measures of the section are not yours"
    assert shared in mine and shared in theirs


@pytest.mark.parametrize(
    "readings, expected",
    [
        (["comfortably normal"] * 3, "ready"),
        (["better than usual", "normal", "normal"], "ready"),
        (["not measured", "normal", "normal"], "ready"),
        (["worse than usual", "normal", "normal"], "workable"),
        (["worse than usual", "worse than usual", "normal"], "workable"),
        (["much worse than usual", "normal", "normal"], "workable"),
        (["much worse than usual", "much worse than usual", "normal"], "flat"),
        (["worse than usual"] * 3, "flat"),
        (["much worse than usual", "worse than usual", "worse than usual"], "flat"),
    ],
)
def test_the_recovery_verdict_is_decided_here(readings, expected):
    """Il conto non e' un giudizio, e un modello piccolo lo sbaglia anche con
    la regola scritta davanti: e' la lezione di `_health_verdict`. Tre gradini
    e non quattro, che su tre misure il quarto non lo raggiungerebbe
    nessuno."""
    assert ollama._recovery_verdict(readings) == expected


def test_the_verdict_counts_three_and_not_four(recovery_payload):
    """Il minimo di ieri non entra nel conto, e si vede dal campo che lo dice:
    una giornata costata molto non deve poter spostare il verdetto sul
    corpo."""
    # Ieri e' costata molto piu' del solito, e la mattina e' buona.
    recovery_payload["morning"]["body_battery_low_yesterday"] = measure(
        1.0, 12.3, 31.9, 2.6, 41.6
    )
    facts = rec_opening(recovery_payload)
    assert facts["verdict"] == ollama.RECOVERY_VERDICT_WORDS["ready"]
    assert facts["what_yesterday_cost"] == (
        "yesterday took a great deal more out of you than a day usually does"
    )
    # E non si fa nominare fra le misure che portano il verdetto.
    assert "body battery low" not in json.dumps(facts["what_it_rests_on"])


@pytest.mark.parametrize(
    "where, expected",
    [
        ("far below its band", "yesterday took a great deal more out of you than a day usually does"),
        ("below its band", "yesterday took more out of you than a day usually does"),
        ("inside its band", "yesterday cost you about what a day usually costs"),
        ("above its band", "yesterday cost you less than a day usually does"),
        ("far above its band", "yesterday cost you less than a day usually does"),
        ("unknown", None),
    ],
)
def test_what_yesterday_cost_is_said_in_words(where, expected):
    """Stessa ragione di `_carrying` per la Load: e' aritmetica detta a parole,
    non un giudizio. `None` quando la misura non c'e', e la frase non si
    scrive invece di essere inventata."""
    assert ollama._cost_of_yesterday(where) == expected


def test_the_recovery_verdict_never_sees_a_band(recovery_payload):
    """Dove sta una misura e' il mestiere dei quattro paragrafi, che gli
    stanno sotto: dandogliela la ricopiava, ed e' la storia del quinto della
    Health."""
    facts = rec_opening(recovery_payload)
    said = json.dumps(facts)
    assert "band" not in said
    assert "88.0" not in said
    assert "489" not in said


def test_a_quiet_recovery_morning_has_no_second_sentence(recovery_payload):
    """Come per la Health: niente che vada male e niente che vada meglio del
    solito vuol dire che non c'e' una seconda frase da scrivere, e un campo
    nullo e' una risposta mentre un campo che manca e' una domanda."""
    recovery_payload["morning"]["readiness"] = measure(70.0, 60.2, 79.3, 50.6, 88.9)
    facts = rec_opening(recovery_payload)
    assert facts["what_it_rests_on"] == {"about": None, "measures": []}
    assert facts["how_they_read"] == []
    assert facts["verdict"] == ollama.RECOVERY_VERDICT_WORDS["ready"]


def test_the_recovery_split_uses_the_same_fence_as_the_whole():
    """Lo stesso ritaglio della sezione intera: due ritagli vorrebbero dire
    due recinti che divergono, e il confronto non direbbe piu' niente."""
    assert ollama.RECOVERY_SPLIT.facts is ollama.RECOVERY.facts


def test_five_paragraphs_whatever_the_model_answers(recovery_payload, monkeypatch):
    """**La forma non e' piu' una preghiera.** Qualunque cosa rispondano i
    cinque, il testo e' il verdetto piu' le quattro misure nell'ordine della
    card. Il prompt intero quella forma la deve chiedere, e la prima sera non
    e' arrivata: un paragrafo solo, col verdetto contraddetto due righe sotto
    e i due body battery impastati."""

    def answer(system, user):
        if user.startswith("Write the opening paragraph"):
            return "You woke up ready.\n\n## A heading nobody asked for.", "fake"
        measure_name = next(
            p.label for p in ollama.RECOVERY_PARTS if f"paragraph about {p.label}" in user
        )
        return f"About {measure_name}.\n\nAnd a second paragraph.", "fake"

    monkeypatch.setattr(ollama, "_ask", answer)
    text, model = ollama._split_text(
        ollama.RECOVERY_SPLIT, date(2026, 11, 19), recovery_payload, REPO_ROOT
    )
    assert model == "fake"
    assert text.split("\n\n") == [
        "You woke up ready.",
        "About readiness. And a second paragraph.",
        "About last night's sleep. And a second paragraph.",
        "About body battery at wake-up. And a second paragraph.",
        "About yesterday's body battery low. And a second paragraph.",
    ]
