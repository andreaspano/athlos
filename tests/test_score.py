"""La scala del carico. E' l'unica misura **senza un lato buono** — tanto e'
troppo e poco e' poco — e il contratto, scritto in quattro posti (docstring,
`models.py`, lo schema OpenAPI e il README), e' che non arrivi mai a `perfect`
ne' a `terrible`."""

import pytest

from training.api.score import _card_scores, body_score, centred, step, verdict

BAND = {"low": 0, "high": 27, "outer_low": -10, "outer_high": 40}


@pytest.mark.parametrize(
    "value, step, word",
    [
        (10, 1, "high"),      # dentro la fascia: «sei dove stai di solito»
        (0, 1, "high"),       # gli estremi sono dentro
        (27, 1, "high"),
        (33, 0, "medium"),    # fra una e due sigma, da sopra
        (-5, 0, "medium"),    # e da sotto
        (177, -1, "low"),     # oltre, da sopra
        (-50, -1, "low"),     # e da sotto
    ],
)
def test_the_three_steps(value, step, word):
    assert centred(value, BAND) == step
    assert verdict([centred(value, BAND)]) == word


def test_load_never_reaches_the_two_ends():
    """Il difetto era qui: i gradini erano 0/-1/-2 su una tabella che va da
    -2 a +2, quindi il carico diceva `terrible` e non passava `medium`."""
    words = {verdict([centred(v, BAND)]) for v in (-50, -5, 0, 10, 27, 33, 177)}
    assert "terrible" not in words
    assert "perfect" not in words
    assert words == {"low", "medium", "high"}


@pytest.mark.parametrize("value, band", [(None, BAND), (10, None), (10, {}), (10, {"low": 0})])
def test_no_measure_no_step(value, band):
    assert centred(value, band) is None


class TestSummary:
    def test_the_load_card_can_move_the_summary(self):
        """Con la scala tutta da una parte il Summary veniva lo stesso col
        carico al suo meglio e al suo peggio: la card non lo muoveva."""
        best = _card_scores([2, 2, 2], [2, 2, 2], [centred(10, BAND)], [2, 2, 2])
        worst = _card_scores([2, 2, 2], [2, 2, 2], [centred(177, BAND)], [2, 2, 2])
        assert best["summary"] != worst["summary"]

    def test_a_good_load_does_not_drag_the_summary_down(self):
        """E non deve nemmeno succedere il contrario: avere la misura del
        carico, al suo meglio, peggiorava il verdetto rispetto a non averla."""
        with_load = _card_scores([2, 2, 2], [2, 2, 2], [centred(10, BAND)], [2, 2, 2])
        without = _card_scores([2, 2, 2], [2, 2, 2], [None], [2, 2, 2])
        assert with_load["summary"] == without["summary"] == "perfect"


class TestWeeklyLoadVotes:
    """La card Load della Week disegna quattro barre — il carico dei sette
    giorni e i tre tempi per zona — e la faccia deve votare su quelle
    quattro, come fa il giorno con le tre di `LoadCard.tsx`."""

    def payload(self, acute, zone_minutes):
        band = {"low": 100, "high": 200, "outer_low": 50, "outer_high": 250}
        zones = {
            key: {"minutes": minutes, "band": dict(band), "weeks": 12}
            for key, minutes in zip(
                ("low_aerobic", "high_aerobic", "anaerobic"), zone_minutes
            )
        }
        # `zones` tiene anche due numeri che non sono misure: non devono votare.
        zones["sessions_without_hr"] = 0
        zones["measured_min"] = sum(zone_minutes)
        return {
            "measures": {},
            "fitness": None,
            "load": {"load_acute": acute, "band": dict(band)},
            "zones": zones,
        }

    def test_the_zones_vote(self):
        from training.api.score import weekly_scores

        # Carico fra una e due sigma (0), tutte e tre le zone dentro (+1):
        # la media e' +0.75, che arrotonda a +1.
        scores = weekly_scores(self.payload(220, (150, 150, 150)))
        assert scores["load"] == "high"

    def test_the_load_alone_no_longer_decides(self):
        from training.api.score import weekly_scores

        dentro = weekly_scores(self.payload(150, (150, 150, 150)))["load"]
        fuori = weekly_scores(self.payload(150, (400, 400, 400)))["load"]
        assert dentro != fuori, "le zone cambiano la faccia a carico uguale"

    def test_the_two_numbers_that_are_not_measures_do_not_vote(self):
        from training.api.score import WEEK_ZONE_KEYS, weekly_scores

        assert "measured_min" not in WEEK_ZONE_KEYS
        payload = self.payload(150, (150, 150, 150))
        payload["zones"]["measured_min"] = 99999
        assert weekly_scores(payload)["load"] == "high"

    def test_a_week_without_zones_still_has_a_face(self):
        from training.api.score import weekly_scores

        payload = self.payload(150, (150, 150, 150))
        payload["zones"] = {}
        assert weekly_scores(payload)["load"] == "high"


class TestBodyFace:
    """La faccia della card Body: tre misure su dieci votano, e si leggono
    contro le dodici settimane prima — non contro il bersaglio della
    bilancia."""

    @staticmethod
    def measures(**values):
        """Le dieci misure come le manda `body_on`, con la fascia solo dove
        serve al test. Il bersaglio non c'entra con la faccia, e infatti qui
        non si scrive."""
        bands = {
            "weight_kg": {"low": 102.0, "high": 104.0, "outer_low": 101.0, "outer_high": 105.0},
            "body_fat_pct": {"low": 26.0, "high": 28.0, "outer_low": 25.0, "outer_high": 29.0},
            "skeletal_muscle_kg": {
                "low": 42.0, "high": 44.0, "outer_low": 41.0, "outer_high": 45.0
            },
        }
        return [
            {"key": key, "value": values.get(key), "band": bands.get(key)}
            for key in (
                "weight_kg", "bmi", "body_fat_pct", "skeletal_muscle_kg", "bmr_kcal",
                "water_pct", "fat_free_kg", "bone_kg", "protein_pct", "visceral_fat",
            )
        ]

    def test_where_you_usually_are_is_medium(self):
        """Tutte e tre dentro la loro fascia: il corpo sta dove sta di solito,
        e non e' ne' una buona ne' una cattiva notizia — anche se dal peso
        ideale lo separano ventitre chili."""
        face = body_score(self.measures(weight_kg=102.7, body_fat_pct=27.5,
                                        skeletal_muscle_kg=42.9))
        assert face == "medium"

    def test_lighter_leaner_stronger_is_the_good_end(self):
        """Peso e grasso sotto la fascia, muscolo sopra: le tre direzioni
        tirano tutte dalla stessa parte, ed e' la parte buona."""
        face = body_score(self.measures(weight_kg=100.0, body_fat_pct=24.0,
                                        skeletal_muscle_kg=46.0))
        assert face == "perfect"

    def test_heavier_fatter_weaker_is_the_bad_end(self):
        face = body_score(self.measures(weight_kg=106.0, body_fat_pct=30.0,
                                        skeletal_muscle_kg=40.0))
        assert face == "terrible"

    def test_bmi_and_metabolism_do_not_vote(self):
        """Il BMI ripete il peso e il metabolismo e' calcolato dagli altri:
        dargli voce conterebbe due volte gli stessi fatti. Qui hanno un valore
        e una fascia **ottimi** e la faccia non si muove di un gradino."""
        plain = self.measures(weight_kg=102.7, body_fat_pct=27.5, skeletal_muscle_kg=42.9)
        loud = [
            {**m, "value": 18.0, "band": {"low": 25.0, "high": 30.0,
                                          "outer_low": 24.0, "outer_high": 31.0}}
            if m["key"] in ("bmi", "bmr_kcal") else m
            for m in plain
        ]
        assert body_score(loud) == body_score(plain) == "medium"

    def test_no_bands_no_face(self):
        """Sotto tre pesate in dodici settimane nessuna misura ha una fascia:
        la card resta senza faccia, che non e' una faccia storta."""
        naked = [
            {**m, "band": None}
            for m in self.measures(weight_kg=102.7, body_fat_pct=27.5, skeletal_muscle_kg=42.9)
        ]
        assert body_score(naked) is None
        assert body_score([]) is None

    def test_the_direction_comes_from_the_scale_table(self):
        """`step` con la direzione detta da fuori: il muscolo che sale e' un
        voto positivo, e senza quel parametro non sarebbe nemmeno un voto —
        `skeletal_muscle_kg` nelle tabelle della salute non c'e'."""
        band = {"low": 42.0, "high": 44.0, "outer_low": 41.0, "outer_high": 45.0}
        assert step(46.0, band, "skeletal_muscle_kg") is None
        assert step(46.0, band, "skeletal_muscle_kg", good_high=True) == 2
        assert step(46.0, band, "skeletal_muscle_kg", good_high=False) == -2
