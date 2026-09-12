"""What a case costs, and who the theatre owes — by the kind of case it was.

Reported twice, from two sides of one fact:

> «فيه تسعيرين للعملية اذا كانت خاصة او مستشفى او طوارئ»

> «واتعاب الجراح برده علشان الحالات الخاصة وحالات الطوارئ وحالات المستشفى»

and once more about the second person in the room:

> «سعر الجراح والمخدر مختلف وبيختلف بين طبيب وطبيب»

Before this the program had one price, one fee, and one person. The
anaesthetist gassed the child and the bill said nothing about it — their
share was whatever the surgeon's service happened to pay, on a line recorded
as the surgeon's.

Four things these hold:

**The nearest rate set wins**: this doctor's rate for this kind of case, then
their ordinary rate, then the service's own. The same fallback the bed rates
use, and for the same reason — a clinic sets the exceptions it has, not a full
grid.

**Blank is not zero, and "none" is not blank.** A case rate that names a price
and nothing else leaves the commission where it was. A column that could not
tell those apart would stop paying a surgeon the day somebody typed an
emergency price.

**A case nobody classified prices exactly as it always did.** Every operation
booked before the kind existed has none, and that is a real answer, not
"private with the label missing".

**And one price, resolved in one place.** The two doors used to disagree: the
desk billed a day case at the surgeon's rate and the ward billed the same
operation at the list price.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def theatre(clinic):
    """A theatre, two doctors in it, and an operation priced two ways."""
    from app.models import Service, Setting, Theatre, User
    from app.utils.case_types import ensure_seeded

    with clinic["app"].app_context():
        for module in ("theatres", "beds", "ward"):
            Setting.set(f"mod_enabled:{module}", "1")
        Setting.set("require_shift_to_collect", "0")
        ensure_seeded()

        op_svc = Service(name="عملية لوز", code="SVC-TONS", price=3000,
                         category="procedure", commission_type="percent",
                         commission_value=30, is_active=True)
        anaes = Service(name="تخدير", code="SVC-ANAES", price=500,
                        category="procedure", commission_type="percent",
                        commission_value=40, is_active=True)
        clinic["db"].session.add_all([op_svc, anaes])

        surgeon = User(username="surg", full_name="د. جرّاح", role="doctor",
                       is_active=True)
        surgeon.set_password("secret")
        gasman = User(username="gas", full_name="د. مخدّر", role="doctor",
                      is_active=True)
        gasman.set_password("secret")
        clinic["db"].session.add_all([surgeon, gasman])

        room = Theatre(name="غرفة ١", is_active=True)
        clinic["db"].session.add(room)
        clinic["db"].session.commit()
        clinic["ids"] = {"op_svc": op_svc.id, "anaes": anaes.id,
                         "surgeon": surgeon.id, "gasman": gasman.id,
                         "room": room.id}
    return clinic


def _case(theatre, case_type=None, with_gas=True, days_ago=0):
    """A finished operation, ready to be billed."""
    from app.models import Operation
    from app.utils.clock import local_today

    with theatre["app"].app_context():
        row = Operation(
            patient_id=theatre["ids_patient"], theatre_id=theatre["ids"]["room"],
            procedure="استئصال لوز", on_date=local_today() - timedelta(days=days_ago),
            service_id=theatre["ids"]["op_svc"],
            surgeon_id=theatre["ids"]["surgeon"],
            anaesthetist_id=theatre["ids"]["gasman"] if with_gas else None,
            case_type=case_type, status="done")
        theatre["db"].session.add(row)
        theatre["db"].session.commit()
        return row.id


@pytest.fixture()
def child(theatre):
    from app.models import Patient
    from app.utils.clock import local_today

    with theatre["app"].app_context():
        row = Patient(patient_number="T-1", full_name="طفل عملية",
                      gender="male", is_active=True,
                      date_of_birth=local_today() - timedelta(days=1500))
        theatre["db"].session.add(row)
        theatre["db"].session.commit()
        theatre["ids_patient"] = row.id
        return row.id


def _rate(theatre, doctor_key, service_key, case_type, price=None,
          ctype=None, cvalue=None):
    from app.models import DoctorCaseRate

    with theatre["app"].app_context():
        theatre["db"].session.add(DoctorCaseRate(
            doctor_id=theatre["ids"][doctor_key],
            service_id=theatre["ids"][service_key],
            case_type=case_type, price_override=price,
            commission_type=ctype, commission_value=cvalue))
        theatre["db"].session.commit()


def _resolve(theatre, service_key, doctor_key, case_type):
    from app.models import Service, User
    from app.utils import case_rates

    with theatre["app"].app_context():
        service = theatre["db"].session.get(Service,
                                            theatre["ids"][service_key])
        doctor = theatre["db"].session.get(User, theatre["ids"][doctor_key])
        return (case_rates.price_for(service, doctor, case_type),
                case_rates.commission_for(service, doctor, case_type),
                case_rates.share_for(service, 1000, doctor, case_type))


# ------------------------------------------------------- the nearest rate --
def test_a_case_nobody_classified_prices_exactly_as_it_always_did(theatre, child):
    """Every operation booked before the kind existed has none. That is a
    question nobody was asked, not "private with the paperwork missing"."""
    price, commission, share = _resolve(theatre, "op_svc", "surgeon", None)
    assert price == 3000
    assert commission == ("percent", 30)
    assert share == 300


def test_the_kind_beats_the_doctors_ordinary_rate(theatre, child):
    _rate(theatre, "surgeon", "op_svc", "emergency", price=4500,
          ctype="percent", cvalue=50)
    assert _resolve(theatre, "op_svc", "surgeon", "emergency") \
        == (4500, ("percent", 50), 500)
    # …and says nothing about any other kind.
    assert _resolve(theatre, "op_svc", "surgeon", "private")[0] == 3000


def test_the_doctors_ordinary_rate_beats_the_service(theatre, child):
    from app.models import DoctorServiceCommission

    with theatre["app"].app_context():
        theatre["db"].session.add(DoctorServiceCommission(
            doctor_id=theatre["ids"]["surgeon"],
            service_id=theatre["ids"]["op_svc"],
            price_override=3500, commission_type="percent",
            commission_value=35))
        theatre["db"].session.commit()

    assert _resolve(theatre, "op_svc", "surgeon", None) \
        == (3500, ("percent", 35), 350)
    # An emergency with no exception set still lands on the ordinary rate,
    # not back on the service's.
    assert _resolve(theatre, "op_svc", "surgeon", "emergency")[0] == 3500


def test_a_price_exception_does_not_silently_stop_the_commission(theatre, child):
    """**The one that would go unnoticed.** Somebody types an emergency price
    and nothing else; if a blank commission read as "none", the surgeon would
    stop being paid on every emergency from that day, and the bill would look
    entirely normal."""
    _rate(theatre, "surgeon", "op_svc", "emergency", price=4500)

    price, commission, share = _resolve(theatre, "op_svc", "surgeon",
                                        "emergency")
    assert price == 4500
    assert commission == ("percent", 30)      # their ordinary one still stands
    assert share == 300


def test_saying_none_is_a_different_sentence_from_saying_nothing(theatre, child):
    """A hospital case a surgeon is salaried for pays no commission, and that
    is somebody's decision — it has to be sayable."""
    _rate(theatre, "surgeon", "op_svc", "hospital", ctype="none")

    _price, commission, share = _resolve(theatre, "op_svc", "surgeon",
                                         "hospital")
    assert commission == ("none", 0)
    assert share == 0


def test_a_doctor_can_be_free_on_one_kind_of_case(theatre, child):
    """Zero is a price, not a blank. A hospital list genuinely says it."""
    _rate(theatre, "surgeon", "op_svc", "hospital", price=0)
    assert _resolve(theatre, "op_svc", "surgeon", "hospital")[0] == 0
    assert _resolve(theatre, "op_svc", "surgeon", "private")[0] == 3000


def test_the_two_doctors_have_two_different_rates(theatre, child):
    """«سعر الجراح والمخدر مختلف وبيختلف بين طبيب وطبيب» — and they are rates
    on two different services, so nothing has to know which is which."""
    _rate(theatre, "surgeon", "op_svc", "emergency", price=4500)
    _rate(theatre, "gasman", "anaes", "emergency", price=900,
          ctype="percent", cvalue=60)

    assert _resolve(theatre, "op_svc", "surgeon", "emergency")[0] == 4500
    assert _resolve(theatre, "anaes", "gasman", "emergency") \
        == (900, ("percent", 60), 600)


# ------------------------------------------------ two lines, two people --
def _bill_day_case(theatre, child, operation_id):
    """Collect for a day case at the desk, and hand back the invoice."""
    from app.models import Invoice, Operation

    with theatre["app"].app_context():
        op = theatre["db"].session.get(Operation, operation_id)
        gas = op.anaesthetist_id
    client = theatre["sign_in"]("boss")
    page = client.get(f"/finance/collect/{child}")
    assert page.status_code == 200

    data = {
        "doctor_id": theatre["ids"]["surgeon"], "discount_id": "none",
        "line_service_id": [str(theatre["ids"]["op_svc"])],
        "line_desc": ["عملية لوز"], "line_price": ["3000"], "line_qty": ["1"],
        "line_no_commission": ["0"], "line_brand_id": [""],
        "line_dose_id": [""], "line_dose_number": [""], "line_vs_id": [""],
        "line_op_id": [str(operation_id)], "line_anaes_op_id": [""],
        "line_test_id": [""], "line_rx_line_id": [""],
        "line_pkg_id": [""], "line_pkg_sale_id": [""],
    }
    if gas:
        for field, value in (("line_service_id", str(theatre["ids"]["anaes"])),
                             ("line_desc", "تخدير"), ("line_price", "500"),
                             ("line_qty", "1"), ("line_no_commission", "0"),
                             ("line_brand_id", ""), ("line_dose_id", ""),
                             ("line_dose_number", ""), ("line_vs_id", ""),
                             ("line_op_id", ""),
                             ("line_anaes_op_id", str(operation_id)),
                             ("line_test_id", ""), ("line_rx_line_id", ""),
                             ("line_pkg_id", ""), ("line_pkg_sale_id", "")):
            data[field].append(value)
    client.post(f"/finance/collect/{child}", data=data, follow_redirects=True)
    with theatre["app"].app_context():
        return Invoice.query.filter_by(patient_id=child).one().id


def test_the_anaesthetist_is_paid_on_their_own_line(theatre, child):
    """Two people, two lines, two fees. One line carrying only the surgeon's
    is the anaesthetist working for whatever the surgery happened to pay."""
    from app.models import Invoice, Operation

    operation = _case(theatre, case_type="private")
    invoice_id = _bill_day_case(theatre, child, operation)

    with theatre["app"].app_context():
        invoice = theatre["db"].session.get(Invoice, invoice_id)
        lines = {i.service_id: i for i in invoice.items}
        surgery = lines[theatre["ids"]["op_svc"]]
        gas = lines[theatre["ids"]["anaes"]]

        assert surgery.doctor_id == theatre["ids"]["surgeon"]
        assert surgery.commission_amount == 900        # 30% of 3000
        assert gas.doctor_id == theatre["ids"]["gasman"]
        assert gas.commission_amount == 200            # 40% of 500

        # …and each line is claimed by its own column, so neither overwrites
        # the other.
        op = theatre["db"].session.get(Operation, operation)
        assert op.invoice_item_id == surgery.id
        assert op.anaesthesia_item_id == gas.id


def test_the_emergency_rate_reaches_the_bill(theatre, child):
    """The whole chain, end to end: a kind on the case, a rate for the kind,
    and a commission on the line that came out of it."""
    from app.models import Invoice

    _rate(theatre, "surgeon", "op_svc", "emergency", ctype="percent",
          cvalue=50)
    operation = _case(theatre, case_type="emergency")
    invoice_id = _bill_day_case(theatre, child, operation)

    with theatre["app"].app_context():
        invoice = theatre["db"].session.get(Invoice, invoice_id)
        surgery = {i.service_id: i for i in invoice.items}[
            theatre["ids"]["op_svc"]]
        assert surgery.commission_amount == 1500       # 50%, not 30%


def test_a_case_with_no_anaesthetist_raises_no_second_line(theatre, child):
    """The line appears because somebody did the work and somebody priced it,
    not because the feature exists.

    Read off the **prefill**, not off a form this test wrote: the form is
    what the screen produced, so a test that builds its own is asking
    whether its own helper is right.
    """
    from app.blueprints.finance.routes import _operation_lines
    from app.models import Invoice

    operation = _case(theatre, case_type="private", with_gas=False)
    with theatre["app"].app_context():
        lines = _operation_lines(child, "ar")
        assert len(lines) == 1
        assert "anaes_op_id" not in lines[0]

    invoice_id = _bill_day_case(theatre, child, operation)
    with theatre["app"].app_context():
        invoice = theatre["db"].session.get(Invoice, invoice_id)
        assert len(invoice.items) == 1


def test_the_anaesthetic_is_never_billed_twice(theatre, child):
    """Asked of the writer directly, because the caller happens to shield it.

    ``charge`` only ever sees operations with no surgery line yet, so today
    nothing reaches this guard twice — which is precisely why it is worth
    pinning: the day a second door posts a theatre case, the thing that stops
    a family being charged for two anaesthetics is this line, and nobody will
    think to test it then.
    """
    from app.models import Invoice, Operation
    from app.utils.theatres import _charge_anaesthesia

    operation = _case(theatre, case_type="private")
    stay = _admit(theatre, child)
    with theatre["app"].app_context():
        invoice = Invoice(invoice_number="INV-TWICE", patient_id=child,
                          admission_id=stay)
        theatre["db"].session.add(invoice)
        theatre["db"].session.flush()
        op = theatre["db"].session.get(Operation, operation)

        first = _charge_anaesthesia(op, invoice, "ar")
        assert first is not None
        assert _charge_anaesthesia(op, invoice, "ar") is None
        theatre["db"].session.commit()
        assert len(invoice.items) == 1


def test_a_switched_off_anaesthesia_service_raises_no_line(theatre, child):
    """A clinic that retired the row means it — the same as never having
    priced one."""
    from app.blueprints.finance.routes import _operation_lines
    from app.models import Service

    with theatre["app"].app_context():
        theatre["db"].session.get(Service,
                                  theatre["ids"]["anaes"]).is_active = False
        theatre["db"].session.commit()

    _case(theatre, case_type="private")
    with theatre["app"].app_context():
        lines = _operation_lines(child, "ar")
        assert len(lines) == 1
        assert "anaes_op_id" not in lines[0]


def test_a_clinic_that_prices_anaesthesia_at_nothing_never_sees_the_line(theatre, child):
    """The price is the switch, the way it is for the consultant's round. A
    clinic whose operation price includes the anaesthetic leaves it at zero."""
    from app.blueprints.finance.routes import _operation_lines
    from app.models import Service

    with theatre["app"].app_context():
        theatre["db"].session.get(Service, theatre["ids"]["anaes"]).price = 0
        theatre["db"].session.commit()

    _case(theatre, case_type="private")
    with theatre["app"].app_context():
        lines = _operation_lines(child, "ar")
        assert len(lines) == 1
        assert "anaes_op_id" not in lines[0]


def test_the_two_doors_price_a_case_the_same(theatre, child):
    """The disagreement this replaced: the desk billed a day case at the
    surgeon's rate, and the ward billed the same operation at the list
    price — so the family paid one number as a day case and another as an
    admission, and neither screen knew the other existed.

    Both numbers are taken **through the doors themselves**, not from the
    resolver they now share. Asking the resolver twice would prove only that
    it is consistent with itself, which it cannot help being — and a mutation
    putting ``service.price`` back into the ward's posting slipped past
    exactly that test.
    """
    from app.blueprints.finance.routes import _operation_lines
    from app.models import Invoice, Operation
    from app.utils import theatres as theatre_util

    _rate(theatre, "surgeon", "op_svc", "private", price=4200)
    operation = _case(theatre, case_type="private")

    with theatre["app"].app_context():
        desk = _operation_lines(child, "ar")[0]["unit_price"]

    # …and the very same case, posted the way a stay posts it.
    stay = _admit(theatre, child)
    with theatre["app"].app_context():
        op = theatre["db"].session.get(Operation, operation)
        op.admission_id = stay
        invoice = Invoice(invoice_number="INV-WARD", patient_id=child,
                          admission_id=stay)
        theatre["db"].session.add(invoice)
        theatre["db"].session.flush()
        from app.models.admission import Admission

        theatre_util.charge(theatre["db"].session.get(Admission, stay),
                            invoice, lang="ar")
        theatre["db"].session.commit()

        ward = {i.service_id: i for i in invoice.items}[
            theatre["ids"]["op_svc"]].unit_price
        assert desk == ward == 4200


def _admit(theatre, patient_id):
    """A bare stay, for posting a case the way an admission does."""
    from app.models.admission import Admission

    with theatre["app"].app_context():
        row = Admission(patient_id=patient_id,
                        doctor_id=theatre["ids"]["surgeon"])
        theatre["db"].session.add(row)
        theatre["db"].session.commit()
        return row.id


def test_the_wards_posting_pays_the_anaesthetist_too(theatre, child):
    """A case done during a stay goes onto the stay's bill, and the second
    person in the room has to reach it by that door as well as by the desk."""
    from app.models import Invoice, Operation
    from app.models.admission import Admission
    from app.utils import theatres as theatre_util

    operation = _case(theatre, case_type="private")
    stay = _admit(theatre, child)
    with theatre["app"].app_context():
        op = theatre["db"].session.get(Operation, operation)
        op.admission_id = stay
        invoice = Invoice(invoice_number="INV-WARD-2", patient_id=child,
                          admission_id=stay)
        theatre["db"].session.add(invoice)
        theatre["db"].session.flush()
        theatre_util.charge(theatre["db"].session.get(Admission, stay),
                            invoice, lang="ar")
        theatre["db"].session.commit()

        lines = {i.service_id: i for i in invoice.items}
        gas = lines[theatre["ids"]["anaes"]]
        assert gas.doctor_id == theatre["ids"]["gasman"]
        assert gas.commission_amount == 200            # 40% of 500
        assert theatre["db"].session.get(
            Operation, operation).anaesthesia_item_id == gas.id


# ---------------------------------------------------------- the catalogue --
def test_a_kind_nothing_recognises_is_not_stored(theatre, child):
    """This string decides which rate a surgeon is paid at. A value nothing
    matches would fall back to the ordinary rate while the screen showed a
    kind somebody chose."""
    from app.blueprints.theatres.routes import _a_case_type

    with theatre["app"].app_context():
        assert _a_case_type("emergency") == "emergency"
        assert _a_case_type("whatever") is None
        assert _a_case_type("") is None
        assert _a_case_type(None) is None


def test_the_clinic_can_add_a_kind_of_its_own(theatre, child):
    """Nothing reads a kind by name — a rate is found by matching whatever
    key the case carries against whatever key the rate carries."""
    from app.models import CaseType, DoctorCaseRate, Service, User
    from app.utils import case_rates
    from app.utils.case_types import make_key

    with theatre["app"].app_context():
        key = make_key("تعاقد", "contract")
        theatre["db"].session.add(CaseType(key=key, name_ar="تعاقد",
                                           sort_order=9, is_active=True))
        theatre["db"].session.flush()
        theatre["db"].session.add(DoctorCaseRate(
            doctor_id=theatre["ids"]["surgeon"],
            service_id=theatre["ids"]["op_svc"],
            case_type=key, price_override=2600))
        theatre["db"].session.commit()

        service = theatre["db"].session.get(Service, theatre["ids"]["op_svc"])
        surgeon = theatre["db"].session.get(User, theatre["ids"]["surgeon"])
        assert case_rates.price_for(service, surgeon, key) == 2600


def test_the_screens_draw_with_the_kinds_on_them(theatre, child):
    client = theatre["sign_in"]("boss")
    page = client.get("/theatres/").get_data(as_text=True)
    assert "طوارئ" in page and "case_type" in page
    assert client.get("/finance/services").status_code == 200


def test_a_clinic_with_every_kind_switched_off_behaves_as_before(theatre, child):
    """The feature is invisible where nobody wants it, and the money is
    unchanged — which is the promise made to every clinic already running."""
    from app.models import CaseType

    with theatre["app"].app_context():
        for row in CaseType.query.all():
            row.is_active = False
        theatre["db"].session.commit()

    operation = _case(theatre)
    invoice_id = _bill_day_case(theatre, child, operation)
    from app.models import Invoice

    with theatre["app"].app_context():
        invoice = theatre["db"].session.get(Invoice, invoice_id)
        surgery = {i.service_id: i for i in invoice.items}[
            theatre["ids"]["op_svc"]]
        assert surgery.commission_amount == 900        # the ordinary 30%
