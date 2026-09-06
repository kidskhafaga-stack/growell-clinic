"""The consultant came, and the money moved in one direction only.

The last of the three ways a doctor is paid here, described in one sentence:

    «غالباً الاستشاري يا بيتحاسب من المستشفى في ساعتها، والمستشفى بتحط على
     فاتورة الأهل بعد كده وغالباً بيبقى ليها نسبة من المبلغ ده»

**Two movements, not one.** The hospital pays the consultant for the visit;
the hospital charges the family more than that and keeps the difference. Both
halves already existed — a service has a price, a doctor has a fixed
commission on it — and the only thing missing was the sentence joining them to
a round: *this consultant saw this child on Tuesday and nobody billed it.*

Nothing was invented to price it. The round is a ``Service``, so the
insurance, the contract tariff, the family discount and the tax code all
follow. The per-consultant part is the doctor–service row every other service
already uses.

**The price is the switch**, exactly as it is for a bed night — and it is also
how the resident stays out of this without a flag saying so. A house officer
walking the ward every morning has no price on their round, so their notes
stay what they have always been: clinical, and free.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """A stay, a consultant and a resident — and no price on anything yet."""
    from app.models import Admission, Service, Setting, User
    from app.models.place import Bed, Space, Unit
    from app.utils import beds as place
    from app.utils.services import ROUND_SERVICE

    db = clinic["db"]
    with clinic["app"].app_context():
        for module in ("beds", "ward", "observations"):
            Setting.set(f"mod_enabled:{module}", "1")
        code, ar, en, price, cat, ctype, cval = ROUND_SERVICE
        db.session.add(Service(code=code, name=ar, name_en=en, price=price,
                               category=cat, commission_type=ctype,
                               commission_value=cval, is_active=True))
        unit = Unit(name="الداخلي", kind="ward", is_active=True)
        db.session.add(unit)
        db.session.flush()
        space = Space(unit_id=unit.id, name="غرفة", is_active=True)
        db.session.add(space)
        db.session.flush()
        bed = Bed(space_id=space.id, name="سرير ١", is_active=True)
        db.session.add(bed)

        consultant = User(username="cons", full_name="د. استشاري",
                          role="doctor", is_active=True)
        consultant.set_password("secret")
        resident = User(username="res", full_name="د. مقيم", role="doctor",
                        is_active=True)
        resident.set_password("secret")
        db.session.add_all([consultant, resident])
        db.session.flush()

        from app.models import Patient
        child = db.session.get(Patient, clinic["ids"]["child"])
        stay = place.admit(child, bed)
        db.session.commit()
        clinic["stay"] = stay.id
        clinic["consultant"] = consultant.id
        clinic["resident"] = resident.id
    return clinic


def _price_the_round(fx, doctor_id, family_pays, doctor_gets):
    """What the clinic sets up: the family's price and the consultant's fee."""
    from app.models import DoctorServiceCommission
    from app.utils.round_billing import round_service

    db = fx["db"]
    with fx["app"].app_context():
        db.session.add(DoctorServiceCommission(
            doctor_id=doctor_id, service_id=round_service().id,
            price_override=family_pays, commission_type="fixed",
            commission_value=doctor_gets, provides=True))
        db.session.commit()


def _round(fx, doctor_id, trend="same"):
    from app.models import Admission, RoundNote

    db = fx["db"]
    with fx["app"].app_context():
        stay = db.session.get(Admission, fx["stay"])
        note = RoundNote(admission_id=stay.id, patient_id=stay.patient_id,
                         trend=trend, by_id=doctor_id, assessment="شايفه")
        db.session.add(note)
        db.session.commit()
        return note.id


def _charge(fx):
    from app.models import Admission
    from app.utils import bed_billing

    with fx["app"].app_context():
        out = bed_billing.post(fx["db"].session.get(Admission, fx["stay"]))
        fx["db"].session.commit()
        return out


# --------------------------------------------------------------- the switch

def test_a_clinic_that_prices_no_round_is_never_charged_for_one(ward):
    """The whole feature is absent until somebody puts a price on it — the
    same rule as the bed rate, and the same rule as a module that is off."""
    from app.utils.round_billing import unbilled

    _round(ward, ward["consultant"])
    with ward["app"].app_context():
        assert unbilled(admission_id=ward["stay"]) == []
    assert _charge(ward)["rounds"] == 0


def test_the_resident_walking_the_ward_is_still_free(ward):
    """No flag says "this one is billable". The price says it, and a resident
    has none — which is the arrangement rather than a rule about job titles."""
    from app.utils.round_billing import unbilled

    _price_the_round(ward, ward["consultant"], 500, 300)
    _round(ward, ward["resident"])
    with ward["app"].app_context():
        assert unbilled(admission_id=ward["stay"]) == []


# ------------------------------------------------------ the two movements

def test_the_family_pays_one_number_and_the_consultant_gets_another(ward):
    """The sentence this was built from. 500 on the bill, 300 to the doctor,
    200 to the hospital — and none of the three is written down twice."""
    from app.models import Invoice

    _price_the_round(ward, ward["consultant"], 500, 300)
    _round(ward, ward["consultant"])
    result = _charge(ward)
    assert result["rounds"] == 1

    with ward["app"].app_context():
        invoice = Invoice.query.filter_by(admission_id=ward["stay"]).first()
        line = [i for i in invoice.items if i.service.code == "SVC-ROUND"][0]
        assert line.gross == 500
        assert line.commission_amount == 300
        assert line.gross - line.commission_amount == 200


def test_the_fee_follows_the_doctor_who_came(ward):
    """Not the doctor the stay belongs to. Recorded on the line as well as
    computed from them, so repricing the bill later does not hand a visiting
    cardiologist's fee to the admitting paediatrician."""
    from app.models import Invoice

    _price_the_round(ward, ward["consultant"], 500, 300)
    _round(ward, ward["consultant"])
    _charge(ward)

    with ward["app"].app_context():
        invoice = Invoice.query.filter_by(admission_id=ward["stay"]).first()
        line = [i for i in invoice.items if i.service.code == "SVC-ROUND"][0]
        assert line.doctor_id == ward["consultant"]
        assert invoice.share_for(ward["consultant"]) == 300


def test_two_consultants_are_two_prices(ward):
    """The price is per doctor because the arrangement is per doctor."""
    from app.models import Invoice

    _price_the_round(ward, ward["consultant"], 500, 300)
    _price_the_round(ward, ward["resident"], 200, 150)
    _round(ward, ward["consultant"])
    _round(ward, ward["resident"])
    assert _charge(ward)["rounds"] == 2

    with ward["app"].app_context():
        invoice = Invoice.query.filter_by(admission_id=ward["stay"]).first()
        assert invoice.share_for(ward["consultant"]) == 300
        assert invoice.share_for(ward["resident"]) == 150


# ----------------------------------------------------------- charged once

def test_the_same_round_is_never_charged_twice(ward):
    """Asking twice charges once — the round carries the line it went onto,
    the same shape as an operation and an unbilled dose."""
    _price_the_round(ward, ward["consultant"], 500, 300)
    _round(ward, ward["consultant"])
    assert _charge(ward)["rounds"] == 1
    assert _charge(ward)["rounds"] == 0


def test_a_later_round_joins_the_same_bill(ward):
    """One account for the admission, not a bill per visit."""
    from app.models import Invoice

    _price_the_round(ward, ward["consultant"], 500, 300)
    _round(ward, ward["consultant"])
    _charge(ward)
    _round(ward, ward["consultant"])
    _charge(ward)

    with ward["app"].app_context():
        invoices = Invoice.query.filter_by(admission_id=ward["stay"]).all()
        assert len(invoices) == 1
        rounds = [i for i in invoices[0].items if i.service.code == "SVC-ROUND"]
        assert len(rounds) == 2


def test_the_line_says_who_and_when(ward):
    """What a family asks of this line: what was it, whose, and which day."""
    from app.models import Invoice

    _price_the_round(ward, ward["consultant"], 500, 300)
    _round(ward, ward["consultant"])
    _charge(ward)

    with ward["app"].app_context():
        invoice = Invoice.query.filter_by(admission_id=ward["stay"]).first()
        line = [i for i in invoice.items if i.service.code == "SVC-ROUND"][0]
        assert "د. استشاري" in line.description
        assert str(date.today().year) in line.description


# --------------------------------------------------------------- the screen

def test_the_stay_screen_shows_what_is_uncharged_before_anybody_presses(ward):
    """Money is written onto a family's account by somebody pressing
    something — never by opening a page."""
    _price_the_round(ward, ward["consultant"], 500, 300)
    _round(ward, ward["consultant"])

    page = ward["sign_in"]("boss").get(
        f"/beds/admission/{ward['stay']}").get_data(as_text=True)
    assert "data-round-due" in page
    assert "data-post-nights" in page, "nothing to press"

    from app.models import Invoice
    with ward["app"].app_context():
        assert Invoice.query.filter_by(admission_id=ward["stay"]).count() == 0


def test_a_stay_with_no_priced_round_shows_nothing_about_rounds(ward):
    """A module that is off is a module that is absent, and so is this."""
    _round(ward, ward["consultant"])
    page = ward["sign_in"]("boss").get(
        f"/beds/admission/{ward['stay']}").get_data(as_text=True)
    assert "data-round-due" not in page


def test_a_round_with_nobody_s_name_on_it_is_never_billed(ward):
    """``by_id`` is nullable — an imported history, a row written by the
    program — and a round with no author has no arrangement behind it: there
    is no doctor to read a price against and nobody to pay. Charging it would
    put a line on a family's bill at whatever the default price happened to
    be, earned by nobody.

    Found by a mutation that deleted the guard and passed anyway, because a
    second guard downstream happened to cover it. Two guards and no test is
    one accident away from none.
    """
    from app.models import Admission, Invoice, RoundNote
    from app.utils.round_billing import unbilled

    _price_the_round(ward, ward["consultant"], 500, 300)
    db = ward["db"]
    with ward["app"].app_context():
        stay = db.session.get(Admission, ward["stay"])
        db.session.add(RoundNote(admission_id=stay.id,
                                 patient_id=stay.patient_id,
                                 trend="same", by_id=None))
        db.session.commit()
        assert unbilled(admission_id=ward["stay"]) == []

    assert _charge(ward)["rounds"] == 0
    with ward["app"].app_context():
        assert Invoice.query.filter_by(admission_id=ward["stay"]).count() == 0
