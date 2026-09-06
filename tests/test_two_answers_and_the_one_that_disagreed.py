"""The assistant used to overwrite the reference, which hid the only thing
worth asking it for.

The prescription screen had a button that asked a language model for a dose and
wrote the reply straight into the dose, the frequency and the duration. On the
same screen sits a reference with a citation under every figure, and it was
never consulted.

**The number was never the point.** A model that agrees with the book adds
nothing; a model that disagrees is the reason to stop and look. Writing the
reply into the field turned the second case into the first — the disagreement
arrived looking exactly like agreement, because the only surviving number was
the model's.

So both answers come back with their sources and **nothing is filled in**.
Three things make the comparison honest:

**The reference answers as a range.** Paracetamol is 10–15 mg/kg. A model
saying 13 is not disagreeing with anything, and reporting it as a conflict
would train the doctor to dismiss the panel.

**Over the ceiling is its own verdict.** Inside, outside, and *over the
recorded maximum* are three answers, because only the third is one where
nobody should press the button.

**And "I could not read it" is a verdict too** — never agreement. A reply in
words, or a reference with no per-kilo figure, means nothing was compared, and
saying so is the whole difference between a check and a decoration.

The second half is the other thing a model is good at and a search box is not:
turning *"الشراب بتاع الحرارة للرضيع"* into the row it means. **The model picks
the search word and the catalogue picks the answer**, so nothing can come back
that this clinic does not have.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


# --------------------------------------------------------- reading a reply

@pytest.mark.parametrize("text,expected", [
    ("500 mg", 500.0),
    ("500mg", 500.0),
    ("٥٠٠ مج", 500.0),
    ("250 mg (5 ml)", 250.0),          # the ml is the same dose, not a rival
    ("12.5 mg every 8 hours", 12.5),
    ("حسب الحاجة", None),               # words are not a number
    ("5 ml", None),                     # millilitres of *what* strength?
    ("", None),
    (None, None),
])
def test_the_number_in_a_reply_or_nothing(text, expected):
    """"5 ml" is the case this exists for: a volume with no strength beside it
    is not a dose, and treating it as one compares millilitres against
    milligrams."""
    from app.utils.rx_ai import milligrams

    assert milligrams(text) == expected


# ------------------------------------------------------ the reference's own

@pytest.fixture()
def para(clinic):
    """Paracetamol syrup at 24 mg/ml, from the seeded reference."""
    from app.models import Drug
    from app.utils.drugbook_seed import seed_drugbook

    with clinic["app"].app_context():
        seed_drugbook()
        clinic["db"].session.commit()
        row = Drug.query.filter_by(trade_name="Cetal", form="syrup",
                                   strength="120 mg/5 ml").first()
        clinic["drug"] = row.id
    return clinic


def _band(fx, weight):
    from app.models import Drug
    from app.utils.rx_ai import reference_dose

    with fx["app"].app_context():
        return reference_dose(fx["db"].session.get(Drug, fx["drug"]), weight)


def test_the_reference_answers_as_a_range(para):
    """10–15 mg/kg on a 10 kg child is 100–150 mg, and both ends are the
    answer. A point estimate would make two thirds of the correct doses in the
    book look like disagreements."""
    band = _band(para, 10)
    assert (band["low_mg"], band["high_mg"]) == (100.0, 150.0)
    assert (band["low_ml"], band["high_ml"]) == (4.2, 6.2)
    assert band["source"]


def test_the_ceiling_is_carried_beside_the_band(para):
    """A 90 kg adolescent is 900–1350 mg by weight and 1000 mg by the adult
    cap. The cap is the answer and the screen has to be able to say so."""
    band = _band(para, 90)
    assert band["capped_mg"] == 1000
    assert band["high_mg"] == 1350.0        # the band is not quietly rewritten


def test_a_weight_under_the_cap_carries_no_cap(para):
    assert "capped_mg" not in _band(para, 10)


@pytest.mark.parametrize("weight", [None, "", 0, -3, "abc"])
def test_no_weight_means_the_reference_has_nothing_to_say(para, weight):
    """And saying nothing is the point: it is the case where the assistant's
    number would otherwise stand as though something had checked it."""
    assert _band(para, weight) is None


def test_a_box_with_no_ingredient_behind_it_gets_no_band(clinic):
    from app.models import Drug
    from app.utils.rx_ai import reference_dose

    db = clinic["db"]
    with clinic["app"].app_context():
        loose = Drug(trade_name="Something", generic_name="UNKNOWN",
                     form="syrup", is_active=True)
        db.session.add(loose)
        db.session.commit()
        assert reference_dose(loose, 10) is None


# ----------------------------------------------------------- the verdicts

@pytest.mark.parametrize("reply,verdict", [
    ("120 mg", "inside"),
    ("100 mg", "inside"),          # the edges are inside
    ("150 mg", "inside"),
    ("60 mg", "under"),
    ("300 mg", "over"),
    ("1500 mg", "over_ceiling"),   # past the recorded maximum
    ("as needed", "unreadable"),
])
def test_where_the_assistants_number_falls(para, reply, verdict):
    from app.utils.rx_ai import compare

    assert compare(_band(para, 10), reply)[0] == verdict


def test_over_the_ceiling_outranks_merely_being_high(para):
    """Both are "above the band". Only one of them is a dose nobody should
    write, and collapsing them into one verdict loses that."""
    from app.utils.rx_ai import compare

    band = _band(para, 10)
    assert compare(band, "300 mg")[0] == "over"
    assert compare(band, "1500 mg")[0] == "over_ceiling"


def test_no_reference_is_unreadable_and_never_agreement(para):
    """The mistake this guards is the natural one: with nothing to compare
    against, "no conflict found" reads like a check that passed."""
    from app.utils.rx_ai import agrees, compare

    verdict, mg = compare(None, "120 mg")
    assert verdict == "unreadable" and mg == 120.0
    assert agrees(verdict) is False


def test_only_inside_is_agreement():
    from app.utils.rx_ai import VERDICTS, agrees

    assert [v for v in VERDICTS if agrees(v)] == ["inside"]


# ------------------------------------------------------------ the endpoint

@pytest.fixture()
def wired(para, monkeypatch):
    """A clinic with the assistant switched on and a scripted reply."""
    from app.models import Setting
    from app.utils import ai as ai_utils

    db = para["db"]
    with para["app"].app_context():
        for key, value in (("ai_enabled", "1"), ("ai_provider", "openai"),
                           ("ai_api_key", "test-key"), ("ai_model", "gpt-4o")):
            db.session.add(Setting(key=key, value=value))
        db.session.commit()
        assert ai_utils.is_ready()

    def scripted(messages, system=None, config=None, feature=None):
        return {"ok": True, "text": para.get("reply", "{}")}

    monkeypatch.setattr(ai_utils, "chat", scripted)
    return para


def _ask_dose(fx, reply, **body):
    fx["reply"] = reply
    payload = {"drug": "Cetal", "drug_id": fx["drug"], "weight": 10}
    payload.update(body)
    return fx["sign_in"]("doc").post("/prescriptions/ai-dose", json=payload)


def test_the_endpoint_returns_both_answers(wired):
    page = _ask_dose(wired, '{"dose": "120 mg", "frequency": "كل 6 ساعات"}')
    body = page.get_json()
    assert body["ok"] and body["dose"] == "120 mg"
    assert body["reference"]["low_mg"] == 100.0
    assert body["verdict"] == "inside"


def test_a_reply_over_the_ceiling_comes_back_as_that(wired):
    body = _ask_dose(wired, '{"dose": "1500 mg"}').get_json()
    assert body["verdict"] == "over_ceiling"
    assert body["suggested_mg"] == 1500.0


def test_without_a_weight_nothing_is_claimed_to_have_been_checked(wired):
    body = _ask_dose(wired, '{"dose": "120 mg"}', weight="").get_json()
    assert body["reference"] is None
    assert body["verdict"] == "unreadable"


def test_a_reply_that_is_not_json_still_gets_compared(wired):
    """Models return prose. The dose in it is still a dose, and refusing to
    compare it would leave the loosest replies the least checked."""
    body = _ask_dose(wired, "Give 1500 mg every 6 hours").get_json()
    assert body["verdict"] == "over_ceiling"


# ----------------------------------------------- the screen fills nothing

def test_the_screen_no_longer_writes_the_reply_into_the_fields(wired):
    """The regression this whole change is about. The old handler ran
    ``if(d.dose) l.dose=d.dose;`` — three fields written from an unchecked
    sentence — and there was no way to tell afterwards which number the
    prescription carried."""
    page = wired["sign_in"]("doc").get(
        "/prescriptions/new").get_data(as_text=True)
    handler = page.split("async aiDose(")[1].split("verdictWord(")[0]
    for forbidden in ("l.dose=d.dose", "l.frequency=d.frequency",
                      "l.duration=d.duration"):
        assert forbidden not in handler.replace(" ", ""), \
            f"the assistant still writes {forbidden} on its own"
    assert "aiCompare" in handler


def test_taking_a_figure_is_a_button_the_doctor_presses(wired):
    page = wired["sign_in"]("doc").get(
        "/prescriptions/new").get_data(as_text=True)
    assert "takeReference(line)" in page and "takeAssistant(line)" in page


def test_the_verdict_is_a_word_and_not_only_a_colour(wired):
    """A red edge with no sentence beside it is a decoration. Every verdict
    the server can return has wording on the screen."""
    from app.utils.rx_ai import VERDICTS

    page = wired["sign_in"]("doc").get(
        "/prescriptions/new").get_data(as_text=True)
    words = page.split("verdictWord(v){")[1].split("},")[0]
    for verdict in VERDICTS:
        assert verdict in words, f"{verdict} has no wording"


# ------------------------------------------- describing a drug you can't name

def test_the_rows_come_from_the_catalogue_not_from_the_model(wired):
    """The safety property of the whole feature.

    The model is asked for ingredient names and nothing else; every row shown
    is found by the same search every other screen uses. So a model that
    hallucinates "Cetal Forte 250" cannot put it on the screen — the name is
    used as a search term and finds nothing.
    """
    wired["reply"] = '{"terms": ["Paracetamol", "Cetal Forte 250"], "why": "حرارة"}'
    body = wired["sign_in"]("doc").post(
        "/prescriptions/drugs/ask", json={"q": "الشراب بتاع الحرارة للرضيع"}
    ).get_json()

    assert body["ok"] and body["results"]
    assert "Cetal Forte 250" not in [r.get("name") for r in body["results"]]
    names = " ".join((r.get("name") or "") + (r.get("generic") or "")
                     for r in body["results"]).lower()
    assert "paracetamol" in names or "باراسيتامول" in names


def test_a_description_that_names_no_medicine_returns_nothing(wired):
    wired["reply"] = '{"terms": [], "why": ""}'
    body = wired["sign_in"]("doc").post(
        "/prescriptions/drugs/ask", json={"q": "الجو حر"}).get_json()
    assert body["ok"] and body["results"] == []


def test_an_empty_question_is_not_sent_to_a_provider(wired):
    """Spending a call on an empty box is the sort of thing that shows up on
    the usage screen and nowhere else."""
    page = wired["sign_in"]("doc").post(
        "/prescriptions/drugs/ask", json={"q": "   "})
    assert page.status_code == 400
    assert page.get_json()["error"] == "no_query"


def test_the_row_says_which_word_found_it(wired):
    """Two terms can bring back the same box for different reasons, and the
    doctor is choosing between them — "found under paracetamol" is part of
    the answer."""
    wired["reply"] = '{"terms": ["Paracetamol"], "why": ""}'
    body = wired["sign_in"]("doc").post(
        "/prescriptions/drugs/ask", json={"q": "خافض حرارة"}).get_json()
    assert all(r.get("matched") == "Paracetamol" for r in body["results"])
