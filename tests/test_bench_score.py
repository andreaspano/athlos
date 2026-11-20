"""I controlli sul testo del modello di casa.

**I casi sono quelli veri.** Ogni guasto che qui viene provato l'ho visto con
gli occhi tarando i prompt a mano, e il testo del test e' quello che il modello
aveva scritto davvero: il verdetto che si contraddice, *almost eight hours* per
un sonno di 8h09, i due body battery impastati in una frase, *my body came
back*, *yesterday cost him*, *this rests on*, *only readiness was measured*. Un
controllo che non prende il guasto che l'ha fatto nascere non serve a niente.

**E la meta' dei test e' sui falsi positivi**, che e' il modo in cui una
metrica cosi' muore. Tutti e tre quelli che ci sono stati li ha trovati il
corpus di Claude, non il ragionamento: il passo `5:53` letto come due numeri,
l'`I` dell'allenatore (che `01_health.md` autorizza) preso per la prima
persona dell'atleta, e il conto dei numeri per paragrafo applicato a una
sezione intera, dove un paragrafo copre quattro misure.
"""

from datetime import date

import pytest

from training.api import bench_score, ollama
from training.api.context import REPO_ROOT

DAY = date(2026, 11, 19)


def measure(value, low, high, outer_low, outer_high):
    return {
        "value": value,
        "band": {"low": low, "high": high, "outer_low": outer_low, "outer_high": outer_high},
    }


# I fatti si costruiscono **passando dai ritagli veri** e non a mano: sono
# loro che aggiungono il `where` di ogni misura, e senza quello ogni lettura
# viene "not measured" e i controlli che la guardano non provano niente. La
# prima versione di questo file li scriveva a mano e un test passava per il
# motivo sbagliato.
@pytest.fixture
def payload():
    return {
        "day": "2026-11-19",
        "sleep_minutes": 489,
        "morning": {
            "resting_hr": measure(50.0, 47.4, 52.5, 44.8, 55.1),
            "hrv_last_night": measure(45.0, 38.8, 53.6, 31.4, 61.0),
            "resp_sleep": measure(14.0, 12.4, 15.0, 11.1, 16.2),
            "stress_avg_yesterday": measure(24.0, 20.7, 34.3, 13.9, 41.1),
            "readiness": measure(88.0, 60.2, 79.3, 50.6, 88.9),
            "sleep_hours": measure(8.2, 6.9, 8.8, 5.9, 9.8),
            "body_battery_morning": measure(80.0, 64.1, 96.4, 47.9, 100.0),
            "body_battery_low_yesterday": measure(14.0, 12.3, 31.9, 2.6, 41.6),
        },
        "alerts": [],
        "missing": [],
    }


@pytest.fixture
def health_facts(payload):
    return ollama.health_facts(payload)


@pytest.fixture
def recovery_facts(payload):
    return ollama.recovery_facts(payload)


# --- I numeri inventati ---


def test_a_number_from_the_facts_is_not_invented(health_facts):
    """**Il falso positivo e' il modo in cui questa metrica muore**, e il primo
    test e' che un numero legittimo passi."""
    text = "Resting heart rate is 50 beats per minute, comfortably normal."
    assert bench_score.invented_numbers(text, health_facts) == []


def test_a_band_edge_is_not_invented(health_facts):
    """Gli estremi della fascia gliel'hanno dati: nominarli e' permesso dai
    prompt, quindi non e' un'invenzione."""
    assert bench_score.invented_numbers("between 47.4 and 52.5", health_facts) == []


def test_a_rounded_number_is_not_invented(recovery_facts):
    """Arrotondare e' scrivere lo stesso numero: 8.2 ore si possono dire
    otto."""
    assert bench_score.invented_numbers("readiness at 88", recovery_facts) == []


def test_a_number_nobody_gave_him_is_invented(health_facts):
    """Il guasto vero: il 2 novembre il frammento di Claude ha scritto «81 at
    wake-up» con i fatti che dicevano 100."""
    assert bench_score.invented_numbers("you woke at 81", health_facts) == ["81"]


def test_a_pace_in_the_facts_is_not_invented():
    """**Il falso positivo che ha fatto sembrare sbagliati otto frammenti della
    Fitness di Claude di fila.** `5:43` e' due numeri per un regex ingenuo, e
    nei fatti il passo sta scritto proprio cosi' perche' il conto lo fa
    Python."""
    facts = {"threshold": {"heart_rate": 151, "pace": "5:43 per kilometre"}}
    assert bench_score.invented_numbers("about 5:43 per kilometre", facts) == []


def test_a_pace_in_seconds_is_not_invented():
    """E se i fatti il passo lo tengono in secondi, si confronta in secondi."""
    facts = {"threshold": {"pace_s_per_km": 343}}
    assert bench_score.invented_numbers("about 5:43 per kilometre", facts) == []


def test_a_pace_nobody_gave_him_is_invented():
    """Il guasto vero dell'altra meta': per diciassette giorni i fatti avevano
    `lactate_threshold: null` — nessun passo — e l'agente ne ha scritto uno."""
    facts = {"threshold": {"measure": "the threshold heart rate", "heart_rate": 153, "pace": None}}
    assert bench_score.invented_numbers("153, about 5:53 per kilometre", facts) == ["5:53"]


def test_a_date_in_the_facts_is_not_invented():
    """Le date nei fatti arrivano come oggetti `date`, e un paragrafo che
    nomina il giorno di una lettura ne usa un pezzo."""
    facts = {"threshold": {"read_on": date(2026, 11, 12)}}
    assert bench_score.invented_numbers("read on 12 November", facts) == []


def test_small_numbers_in_prose_are_not_invented(health_facts):
    """«Una delle quattro», «due o tre frasi»: in prosa sono conteggi, non
    cifre, e il bersaglio di questo controllo sono le cifre specifiche."""
    assert bench_score.invented_numbers("one of the four measures", health_facts) == []


# --- La persona ---


def test_the_coachs_first_person_is_allowed():
    """**`01_health.md` la chiede espressamente** («in a coach's voice: *I do
    not like that one*»), e Claude la usa trentotto volte sul corpus. La prima
    versione del controllo le dava tutte per errori."""
    assert bench_score.wrong_person("Breathing in sleep is the one I like least.") == []
    assert bench_score.wrong_person("What we do have is stark: you woke at 17.") == []


def test_the_athletes_first_person_is_a_fault():
    """I guasti veri di llama: il corpo dell'atleta raccontato come se fosse di
    chi scrive."""
    assert bench_score.wrong_person("my body came back further than usual")
    assert bench_score.wrong_person("we're doing about as much of this work as usual")
    assert bench_score.wrong_person("which means we usually do more")


def test_the_third_person_is_a_fault():
    """Claude non la usa mai in tutto il corpus, e llama ci scivola."""
    assert bench_score.wrong_person("yesterday cost him about what a day costs")
    assert bench_score.wrong_person("this shape lets him tackle tough workouts")


def test_the_second_person_is_what_is_wanted():
    assert bench_score.wrong_person("You woke up ready. Your readiness reads better than usual.") == []


# --- Le letture contraddette ---


def test_a_paragraph_that_contradicts_its_reading(recovery_facts):
    """**Il guasto che mi ha fatto ripristinare una modifica a mano**: una
    mattina con due buone notizie in cui il paragrafo ha scritto *much worse
    than usual* su una lettura che diceva il contrario."""
    split = ollama.SECTIONS["recovery_split"]
    text = "\n\n".join(
        [
            "You woke up ready.",
            "Your readiness is much worse than usual today.",
            "Last night's sleep was eight hours nine minutes, comfortably normal.",
            "Body battery at wake-up is comfortably normal.",
            "Yesterday cost about what a day costs.",
        ]
    )
    found = bench_score.contradicted_readings(split, text, recovery_facts)
    assert any("readiness" in f for f in found)


def test_a_paragraph_that_agrees_with_its_reading(recovery_facts):
    split = ollama.SECTIONS["recovery_split"]
    text = "\n\n".join(
        [
            "You woke up ready.",
            "Your readiness reads better than usual today.",
            "Last night's sleep was eight hours nine minutes, comfortably normal.",
            "Body battery at wake-up is comfortably normal.",
            "Yesterday cost about what a day costs.",
        ]
    )
    assert bench_score.contradicted_readings(split, text, recovery_facts) == []


def test_the_paragraphs_align_with_the_pieces(recovery_facts):
    """L'allineamento viene da `ollama.asked`, la stessa funzione con cui il
    testo viene cucito: il paragrafo *i* e' del pezzo *i*. Se i conti non
    tornano si lascia perdere invece di dare la colpa al paragrafo
    sbagliato."""
    split = ollama.SECTIONS["recovery_split"]
    assert bench_score._paragraphs(split, "uno\n\ndue", recovery_facts) == []


# --- Le misure degli altri ---


def test_a_paragraph_that_names_another_sections_measure(recovery_facts):
    """Il guasto vero: un'apertura della Fitness che ha scritto «your training
    load is well within a healthy range», che e' roba della Load."""
    split = ollama.SECTIONS["recovery_split"]
    text = "\n\n".join(
        [
            "You woke up ready.",
            "Your readiness reads better than usual, and the hill score agrees.",
            "Last night's sleep was long.",
            "Body battery at wake-up is normal.",
            "Yesterday cost about what a day costs.",
        ]
    )
    assert any("hill score" in f for f in bench_score.foreign_measures(split, text, recovery_facts))


def test_the_two_body_batteries_do_not_accuse_each_other(recovery_facts):
    """**Un'etichetta che e' pezzo dell'altra non conta**: *body battery* dentro
    *body battery at wake-up* prenderebbe il paragrafo giusto per il motivo
    sbagliato."""
    split = ollama.SECTIONS["recovery_split"]
    text = "\n\n".join(
        [
            "You woke up ready.",
            "Your readiness reads better than usual.",
            "Last night's sleep was long.",
            "Body battery at wake-up is comfortably normal.",
            "Yesterday's body battery low sat inside its band.",
        ]
    )
    assert bench_score.foreign_measures(split, text, recovery_facts) == []


# --- I codici di Garmin ---


@pytest.mark.parametrize(
    "code", ["ACCLIMATIZING", "ANAEROBIC_SHORTAGE", "PRODUCTIVE_3", "OPTIMAL", "ABOVE_TARGET"]
)
def test_a_garmin_code_is_a_fault(code):
    """`_style.md` li vieta in due righe, e il controllo riconosce la forma
    invece di elencarli: un codice nuovo si prende da se'."""
    assert bench_score.garmin_codes(f"the trend is {code} today") == [code]


def test_a_name_in_capitals_is_not_a_code():
    assert bench_score.garmin_codes("VO2max is up and HRV is normal") == []


# --- L'impalcatura, e la lunghezza ---


def test_a_sentence_about_its_own_workings(health_facts):
    """Il guasto vero sulle mattine tranquille: una frase sul campo che non
    c'era."""
    split = ollama.SECTIONS["health_split"]
    text = "The body is fine. There are no measures that say otherwise. It's a good morning."
    assert any("no measures" in f for f in bench_score.soft_faults(split, text, health_facts))


def test_prose_that_dismisses_a_measure_is_not_scaffolding(health_facts):
    """«nothing to say about it» **non e' un errore**: Claude la usa nove volte
    sul corpus per liquidare una misura normale, ed e' prosa d'allenatore."""
    split = ollama.SECTIONS["health_split"]
    text = "Breathing in sleep plain middle of the range, nothing to say about it."
    assert not any("parla di se'" in f for f in bench_score.soft_faults(split, text, health_facts))


def test_a_split_has_no_length_to_check():
    """Il conto di parole di una sezione spezzata non sta scritto in nessun
    file, e inventarlo dava un errore su ogni testo della Recovery."""
    assert bench_score.wanted_words(REPO_ROOT, ollama.SECTIONS["recovery_split"], claude=False) is None


def test_a_whole_section_reads_its_length_from_its_own_prompt():
    """Due file diversi per la stessa sezione chiedono lunghezze diverse, e
    misurare un testo contro il conto dell'altro e' un errore inventato."""
    section = ollama.SECTIONS["load"]
    assert bench_score.wanted_words(REPO_ROOT, section, claude=True) == 80
    assert bench_score.wanted_words(REPO_ROOT, section, claude=False) == 180


def test_numbers_in_one_paragraph_only_count_for_a_split(health_facts):
    """**Il terzo falso positivo trovato dal corpus**: in una sezione intera un
    paragrafo copre quattro misure e due o tre numeri ci stanno di diritto.
    Contarli dava ventisette errori sui testi di Claude."""
    whole = ollama.SECTIONS["health"]
    text = "Resting heart rate 50, HRV 45.0, breathing 14.0 and stress 24 — all ordinary."
    assert not any("stesso paragrafo" in f for f in bench_score.soft_faults(whole, text, health_facts))


# --- La distanza e il punteggio ---


def test_a_text_is_identical_to_itself():
    assert bench_score.distance("the body is fine", "the body is fine") == 0.0


def test_two_different_texts_are_somewhere_in_between():
    gap = bench_score.distance("the body is fine", "the shape is slipping")
    assert 0.0 < gap < 1.0


def test_no_target_is_no_distance():
    assert bench_score.distance("qualcosa", None) == 0.0


def test_a_clean_text_scores_zero(health_facts):
    whole = ollama.SECTIONS["health"]
    marks = bench_score.score(whole, health_facts, "Resting heart rate 50, and that is ordinary.")
    assert marks["faults"] == []
    assert marks["score"] == 0.0


def test_the_distance_is_not_counted_against_a_faulty_target(health_facts):
    """**La riga che impedisce al ciclo di imparare gli sbagli del bersaglio.**
    Se il frammento di Claude ha un errore grave, su quel giorno e quella
    sezione non e' un bersaglio: il termine va a zero."""
    whole = ollama.SECTIONS["health"]
    marks = bench_score.score(
        whole,
        health_facts,
        "Resting heart rate 50, and that is ordinary.",
        "You woke at 81, which nobody measured.",
    )
    assert marks["target_faults"]
    assert marks["distance"] == 0.0
    assert marks["score"] == 0.0


def test_the_distance_is_measured_but_not_scored(health_facts):
    """**La scelta, fissata in un test.** Un testo pulito prende zero anche se
    dista dal bersaglio: la distanza e' lessicale, e il modo piu' corto di
    farla scendere e' imitare la voce di Claude. Si misura, si guarda, e non
    entra nel punteggio su cui il ciclo decide.

    Col peso che le avevo dato il confronto con Claude era impossibile da
    vincere: nel punteggio di llama c'erano 0,246 di distanza che il bersaglio,
    contro se stesso, per costruzione non ha."""
    whole = ollama.SECTIONS["health"]
    marks = bench_score.score(
        whole,
        health_facts,
        "Resting heart rate 50, and that is ordinary.",
        "Your resting heart rate sits at 50 and there is nothing in it.",
    )
    assert marks["target_faults"] == []
    assert marks["distance"] > 0
    assert marks["score"] == 0.0


def test_the_athletes_name_is_third_person():
    """**Il buco che questo controllo ha avuto per due giorni.** Cercavo i
    pronomi e non il nome, quindi dieci testi su centocinquanta dicevano
    *«Andrea's nervous system»* e il punteggio non ne sapeva niente. E lo
    dicevano perche' lo diceva la riga del compito dei miei prompt."""
    assert bench_score.wrong_person("Andrea's nervous system spent the night under load")
    assert bench_score.wrong_person("this is good news for Andrea")


def test_the_prompts_do_not_name_him_in_the_task_line():
    """La causa, non il sintomo: il nome stava nella frase piu' letta del
    prompt — *«one paragraph of Andrea's daily report»* — in dieci file su
    tredici. I prompt di Claude quella riga non ce l'hanno, e Claude il nome
    non lo scrive mai. Resta solo in `_style.md`, che ha la stessa forma di
    quello di Claude e non perde."""
    from pathlib import Path

    colpevoli = [
        str(path.relative_to(REPO_ROOT / ".ollama/agents"))
        for path in (REPO_ROOT / ".ollama/agents").rglob("*.md")
        if path.name != "_style.md" and "Andrea" in path.read_text(encoding="utf-8")
    ]
    assert colpevoli == [], f"il nome e' tornato in {colpevoli}"


def test_an_ordinary_word_is_not_another_section_s_measure(recovery_facts):
    """**Il falso positivo che mi ha fatto ritoccare due prompt per niente.**
    *«which is good news for your morning readiness»* e *«a good place for
    recovery after last night's sleep»* sono prosa inglese, non riferimenti
    alla misura di un'altra sezione: cercare l'etichetta come sottostringa
    dava undici errori su centoquattro testi."""
    split = ollama.SECTIONS["recovery_split"]
    text = "\n\n".join(
        [
            "You woke up ready.",
            "Your readiness reads better than usual.",
            "Last night's sleep was long.",
            "Your body battery at wake-up came back fully, which is good news for your "
            "morning readiness.",
            "Yesterday cost about what a day costs.",
        ]
    )
    assert bench_score.foreign_measures(split, text, recovery_facts) == []


def test_a_distinctive_measure_name_is_still_caught(recovery_facts):
    """Il prezzo e' solo sulle parole comuni: *hill score* in un paragrafo
    della Recovery resta un errore, che in una frase non ci capita per caso."""
    split = ollama.SECTIONS["recovery_split"]
    text = "\n\n".join(
        [
            "You woke up ready.",
            "Your readiness reads better than usual, and the hill score agrees.",
            "Last night's sleep was long.",
            "Body battery at wake-up is normal.",
            "Yesterday cost about what a day costs.",
        ]
    )
    assert any("hill score" in f for f in bench_score.foreign_measures(split, text, recovery_facts))
