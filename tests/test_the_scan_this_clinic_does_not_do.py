"""Where a test is going to be done, and the one list it changes.

> «لو المريض هيعملها فى المكان … لو مش هيعملها فى المكان الركويست يطلع على
> الروشته ويروح للمكان. طلب ايكو المكان مفهوش ايكو يبقى المريض هيعمله بره، أو
> طلب ايكو المكان فيه ايكو بس المريض عايز يعمله برده»

**Most of this was already built**, and the point of this file is to keep it
that way. An order written in the room already prints on the prescription,
already stays on the child's file, already takes its result when the family
brings the report back — `results_inbox` was written for exactly that journey
— and was already never billed, because `labs.unbilled` reads `collected_at`,
*drawn* and not merely ordered.

One thing was missing and one thing was wrong. The missing thing: nowhere to
say **where**. The wrong thing: the clinic's own bench listed every open
order, including the ones nobody in the building was ever going to touch.

Two facts, deliberately kept apart:

* **`Investigation.in_house`** — a fact about the *place*, said once on the
  catalogue screen. «المكان مفهوش إيكو» is not a question to re-ask at every
  order.
* **`VisitInvestigation.done_outside`** — a fact about *this order*. It
  defaults from the catalogue, so in the ordinary case nobody is asked
  anything; and it flips, because the family decides after the order is
  written as often as before it.

And it is **not a fourth status**: `labs.py` records what a fourth state
costs, and «بره» is not a stage an order passes through.

**The other half of this question is already answered elsewhere**, and the two
are not rivals. `test_the_clinic_that_sends_its_tests_out` covers the clinic
that has no lab at all — one switch, no bench anywhere in their copy. This
file is the centre that *has* one: a place with a lab and no echo machine, and
a family who would rather take this one scan to the hospital down the road.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    """A clinic with a lab, a child, and two tests: one it does and one it
    does not."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import (Investigation, Patient, Setting, User, Visit)
        from app.utils.clock import local_today

        Setting.set("mod_enabled:labs", "1")
        Setting.set("mod_enabled:visits", "1")
        boss = User(username="boss", full_name="المدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        db.session.add(boss)
        cbc = Investigation(name_ar="صورة دم", kind="lab", is_active=True,
                            in_house=True)
        echo = Investigation(name_ar="إيكو", kind="imaging", is_active=True,
                             in_house=False)
        db.session.add_all([cbc, echo])
        db.session.flush()
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      is_active=True, date_of_birth=local_today())
        db.session.add(kid)
        db.session.flush()
        visit = Visit(patient_id=kid.id, doctor_id=boss.id,
                      visit_date=local_today())
        db.session.add(visit)
        db.session.commit()
        ids = {"cbc": cbc.id, "echo": echo.id, "kid": kid.id,
               "visit": visit.id, "boss": boss.id}

    def sign_in():
        client = app.test_client()
        client.post("/login", data={"username": "boss", "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _order(clinic, test_id, **extra):
    data = {"investigation_id": test_id, "csrf_token": "x"}
    data.update(extra)
    return clinic["sign_in"]().post(
        "/visits/%s/investigations" % clinic["ids"]["visit"],
        data=data, follow_redirects=True)


def _only_order(clinic):
    from app.models import VisitInvestigation

    return VisitInvestigation.query.one()


# ------------------------------------- the clinic's own answer, said once --
def test_a_test_the_clinic_does_not_do_is_marked_without_anybody_asking(clinic):
    """«الطبيب ميكتبش كتير» — the catalogue answered this already."""
    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["echo"])
        assert _only_order(clinic).done_outside is True


def test_a_test_the_clinic_does_is_not(clinic):
    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["cbc"])
        assert _only_order(clinic).done_outside is False


def test_the_family_can_still_take_it_elsewhere(clinic):
    """«المكان فيه إيكو بس المريض عايز يعمله بره» — one press, and it beats
    the catalogue."""
    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["cbc"], done_outside="1")
        assert _only_order(clinic).done_outside is True


def test_and_the_other_way_round(clinic):
    """A test the clinic normally sends out, done here this once."""
    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["echo"], done_outside="0")
        assert _only_order(clinic).done_outside is False


def test_a_typed_name_with_no_catalogue_entry_is_done_here(clinic):
    """Nothing is known about it, and «here» is what every order in this
    program has meant until now."""
    with clinic["app"].app_context():
        clinic["sign_in"]().post(
            "/visits/%s/investigations" % clinic["ids"]["visit"],
            data={"name": "تحليل غريب"}, follow_redirects=True)
        assert _only_order(clinic).done_outside is False


# ---------------------------------------------- what it actually changes ---
def test_the_bench_does_not_list_what_it_will_never_touch(clinic):
    from app.utils import labs

    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["cbc"])
        _order(clinic, clinic["ids"]["echo"])
        names = [r.name for r in labs.worklist()]

    assert names == ["صورة دم"]


def test_and_the_counts_agree_with_the_list(clinic):
    """Two numbers on a button and a list underneath it that disagree is how
    somebody learns to trust neither."""
    from app.utils import labs

    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["cbc"])
        _order(clinic, clinic["ids"]["echo"])
        counted = labs.counts()

    assert counted["to_collect"] == 1


def test_an_unanswered_catalogue_entry_means_here(clinic):
    """**The upgrade rule, and the direction both halves fail in.**

    «Nobody has said» has to read as «here», never as «outside» — a clinic
    that upgrades must see exactly what it saw yesterday, and the safe side
    of this question is the one where an order shows up on a bench somebody
    then ignores, not the one where it silently never appears.

    So both halves ask it in the negative: `goes_outside` tests
    ``in_house is False`` rather than ``not in_house``, and the bench's own
    filter tests ``done_outside.is_not(True)`` rather than ``== False``.
    """
    from app.utils import labs

    class Unanswered:
        in_house = None

    assert labs.goes_outside(Unanswered()) is False
    assert labs.goes_outside(None) is False


# ------------------------------------------- and everything that must not --
def test_it_is_not_a_fourth_status(clinic):
    """`status` says how far the order has got; this says where it is going,
    and the two are independent. A word inside `status` would have made it a
    stage of the same pipeline — and `labs.py` already records what that
    costs."""
    from app.models.visit import INVESTIGATION_STATUSES

    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["echo"])
        row = _only_order(clinic)

    assert row.status == "requested"
    assert "outside" not in INVESTIGATION_STATUSES


def test_the_order_is_still_on_the_childs_file(clinic):
    """It is a real order. The only list it leaves is this building's bench."""
    from app.models import Visit

    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["echo"])
        visit = clinic["db"].session.get(Visit, clinic["ids"]["visit"])
        assert [x.name for x in visit.investigations] == ["إيكو"]


def test_its_result_still_lands_on_the_same_row(clinic):
    """The mother photographs the report and sends it. That journey already
    worked — `results_inbox` was written for it — and this must not have
    broken it."""
    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["echo"])
        row = _only_order(clinic)
        clinic["sign_in"]().post("/visits/investigations/%s/result" % row.id,
                                 data={"result_text": "طبيعي"},
                                 follow_redirects=True)
        again = _only_order(clinic)

    assert again.result_text == "طبيعي"
    assert again.status == "resulted"


def test_nothing_done_elsewhere_reaches_a_bill(clinic):
    """And it never could: `unbilled` reads `collected_at` — **drawn**, not
    merely ordered — so a test nobody drew here was already free. Pinned
    because it is the thing that would hurt most if it ever changed."""
    from app.utils import labs

    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["echo"])
        assert labs.unbilled(visit_id=clinic["ids"]["visit"]) == []


# ------------------------------------------- said after the order exists ---
def test_the_family_changes_its_mind_after_the_order_was_written(clinic):
    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["cbc"])
        row = _only_order(clinic)
        clinic["sign_in"]().post(
            "/visits/investigations/%s/where" % row.id,
            data={"done_outside": "1", "outside_place": "معمل النيل"},
            follow_redirects=True)
        again = _only_order(clinic)

    assert again.done_outside is True
    assert again.outside_place == "معمل النيل"


def test_and_changes_it_back(clinic):
    """**And the place goes with it.** A lab's name left behind on a test
    drawn in this building would print somebody else's name on our own
    work."""
    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["echo"])
        row = _only_order(clinic)
        client = clinic["sign_in"]()
        client.post("/visits/investigations/%s/where" % row.id,
                    data={"done_outside": "1", "outside_place": "معمل النيل"},
                    follow_redirects=True)
        client.post("/visits/investigations/%s/where" % row.id,
                    data={"done_outside": "0"}, follow_redirects=True)
        again = _only_order(clinic)

    assert again.done_outside is False
    assert again.outside_place is None


def test_too_late_once_there_is_an_answer(clinic):
    """Where an answered test was done is part of what happened, not a plan
    to revise — and moving it would put a finished order back on a bench with
    nothing left to do with it."""
    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["cbc"])
        row = _only_order(clinic)
        client = clinic["sign_in"]()
        client.post("/visits/investigations/%s/result" % row.id,
                    data={"result_text": "طبيعي"}, follow_redirects=True)
        client.post("/visits/investigations/%s/where" % row.id,
                    data={"done_outside": "1"}, follow_redirects=True)

        assert _only_order(clinic).done_outside is False


# --------------------------------------------------- the clinic says once --
def test_the_catalogue_is_where_the_place_answers(clinic):
    from app.models import Investigation

    with clinic["app"].app_context():
        client = clinic["sign_in"]()
        client.post("/labs/tests/%s" % clinic["ids"]["cbc"],
                    data={"name_ar": "صورة دم", "is_active": "1"},
                    follow_redirects=True)
        assert clinic["db"].session.get(
            Investigation, clinic["ids"]["cbc"]).in_house is False

        client.post("/labs/tests/%s" % clinic["ids"]["cbc"],
                    data={"name_ar": "صورة دم", "is_active": "1",
                          "in_house": "1"}, follow_redirects=True)
        assert clinic["db"].session.get(
            Investigation, clinic["ids"]["cbc"]).in_house is True


def test_it_is_a_different_question_from_whether_it_is_offered(clinic):
    """A test the clinic sends out still belongs in the doctor's search,
    because the **order** is written here whoever performs it. Reading one off
    the other would be one empty value standing for two facts."""
    with clinic["app"].app_context():
        found = clinic["sign_in"]().get(
            "/visits/investigations/search?q=إيكو").get_json()

    assert [r["name"] for r in found] == ["إيكو"]
    assert found[0]["in_house"] is False


def test_the_price_is_not_the_answer_either(clinic):
    """`service_id` says whether the clinic charges for it. A clinic that does
    echoes and does not bill them separately has no service — and calling that
    "we do not do echoes" would send every one of its own scans out of the
    building."""
    from app.models import Investigation

    with clinic["app"].app_context():
        cbc = clinic["db"].session.get(Investigation, clinic["ids"]["cbc"])
        assert cbc.service_id is None
        assert cbc.in_house is True


# --------------------------------------------- and the paper says where ---
def test_the_prescription_carries_it_over(clinic):
    """What the doctor ordered in the room is what prints, and it prints
    saying where it is going."""
    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["echo"])
        page = clinic["sign_in"]().get(
            "/prescriptions/new?patient_id=%s&visit_id=%s"
            % (clinic["ids"]["kid"], clinic["ids"]["visit"])
        ).get_data(as_text=True)

    assert '"outside": true' in page.replace("&#34;", '"') \
        or '&#34;outside&#34;: true' in page


def test_the_printed_line_says_so(clinic):
    from app.models import Prescription
    from app.models.prescription import PrescriptionInvestigation

    with clinic["app"].app_context():
        rx = Prescription(patient_id=clinic["ids"]["kid"],
                          doctor_id=clinic["ids"]["boss"])
        rx.investigations.append(PrescriptionInvestigation(
            kind="imaging", name="إيكو", done_outside=True))
        clinic["db"].session.add(rx)
        clinic["db"].session.commit()

        from app.i18n import _load_translations, _lookup
        page = clinic["sign_in"]().get(
            "/prescriptions/%s" % rx.id).get_data(as_text=True)
        said = _lookup(_load_translations(), "ar", "rx.inv_outside_short")

    assert "إيكو" in page
    assert said in page


def test_a_place_is_not_stored_on_something_done_here(clinic):
    """A lab's name on a test drawn in this building would print somebody
    else's name on our own work — and it is the field a stale value survives
    in longest, because nothing on the screen shows it once the order reads
    «here»."""
    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["cbc"], done_outside="0",
               outside_place="معمل النيل")
        assert _only_order(clinic).outside_place is None


def test_and_a_place_posted_while_bringing_it_back_is_dropped(clinic):
    """The same rule on the way in. A form that carries both — «هيتعمل هنا»
    and a lab's name — is answering one question twice, and the answer that
    counts is where it is being done."""
    with clinic["app"].app_context():
        _order(clinic, clinic["ids"]["echo"])
        row = _only_order(clinic)
        clinic["sign_in"]().post(
            "/visits/investigations/%s/where" % row.id,
            data={"done_outside": "0", "outside_place": "معمل النيل"},
            follow_redirects=True)
        again = _only_order(clinic)

    assert again.done_outside is False
    assert again.outside_place is None


def test_a_clinic_can_add_a_test_it_does_not_do(clinic):
    """«ضيف الإيكو في القايمة علشان الدكتور يطلبه، بس إحنا مش بنعمله» — the
    catalogue is what the doctor searches, and it is not a list of this
    building's machines."""
    from app.models import Investigation

    with clinic["app"].app_context():
        client = clinic["sign_in"]()
        client.post("/labs/tests/add",
                    data={"name_ar": "رنين", "kind": "imaging"},
                    follow_redirects=True)
        sent_out = Investigation.query.filter_by(name_ar="رنين").one()

        client.post("/labs/tests/add",
                    data={"name_ar": "أشعة صدر", "kind": "imaging",
                          "in_house": "1"}, follow_redirects=True)
        ours = Investigation.query.filter_by(name_ar="أشعة صدر").one()

    assert sent_out.in_house is False
    assert ours.in_house is True


# ------------------------------- and the third kind the routes could not see
def test_a_diagnostic_order_is_not_filed_as_a_lab(clinic):
    """**The dropdown offered a word the route threw away.** Three screens
    grew an «تشخيصي» option when the third kind arrived, and five places went
    on checking `("lab", "imaging")` — so a doctor who picked it got the order
    filed as a lab, and the echo landed back on the bench that the third kind
    was added to get it off.

    The fix is not a longer tuple: it is `INVESTIGATION_KINDS`, the same list
    the dropdowns are built from, so the next kind cannot come apart the same
    way.
    """
    with clinic["app"].app_context():
        clinic["sign_in"]().post(
            "/visits/%s/investigations" % clinic["ids"]["visit"],
            data={"name": "إيكو على القلب", "kind": "diagnostic"},
            follow_redirects=True)

        assert _only_order(clinic).kind == "diagnostic"


def test_a_word_that_is_not_a_kind_still_falls_back_to_the_lab(clinic):
    with clinic["app"].app_context():
        clinic["sign_in"]().post(
            "/visits/%s/investigations" % clinic["ids"]["visit"],
            data={"name": "حاجة", "kind": "ultrasound-ish"},
            follow_redirects=True)

        assert _only_order(clinic).kind == "lab"


def test_the_search_can_be_narrowed_to_the_third_kind_too(clinic):
    from app.models import Investigation

    with clinic["app"].app_context():
        clinic["db"].session.add(Investigation(
            name_ar="رسم قلب", kind="diagnostic", is_active=True))
        clinic["db"].session.commit()
        found = clinic["sign_in"]().get(
            "/visits/investigations/search?q=رسم&kind=diagnostic").get_json()

    assert [r["name"] for r in found] == ["رسم قلب"]
