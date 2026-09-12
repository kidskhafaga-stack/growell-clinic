"""Nursing and medical care — both ways a hospital charges it.

The question came twice. First without an answer:

> «نسبة تقريباً من إجمالي الفاتورة بتتحسب الرعاية الطبية والتمريضية، عند
> إنهاء ولا على مستوى الليلة؟ مش عارف الصراحة»

and then, after both of us went and looked, with one:

> «هل ينفع نعملها تستوعب الاثنين حسب نظام المستشفى، علشان الآراء متباينة —
> فى ناس بتحسبها كده وفى ناس بتحسبها كده؟»

They are, and it does. **The program holds a rule and the hospital says which
shape it is** — choosing one and shipping it would have been this program
settling a commercial policy that genuinely differs from hospital to hospital,
which is the same restraint that stops it inventing a clinical number.

Four things these hold, and each is a bill somebody argues with:

**The line is recomputed, not accumulated.** Every other charge here is
written once and stands. This one is a function of the rest of the bill, so a
stay posted again on its fifth night must correct its line to five days — not
add a second line of four. A long stay is posted every day, so an accumulating
charge would bill the fourth night's nursing four times by the fourth night.

**A percentage is never levied on a care charge.** Not on itself, not on the
other one.

**Which parts it is levied on is the hospital's to say** — the Egyptian
practice is a percentage of the total *excluding medicines and stamps*, and
naming sections is what makes such a charge checkable by a family at all.

**And a clinic that defines none has nothing happen.**
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hospital(clinic):
    """A ward, a child in it, and services across four bill sections."""
    from app.models import Service, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils import bed_billing
    from app.utils.invoice_sections import ensure_seeded

    with clinic["app"].app_context():
        for module in ("beds", "ward"):
            Setting.set(f"mod_enabled:{module}", "1")
        Setting.set("require_shift_to_collect", "0")
        ensure_seeded()

        night = Service(name="ليلة داخلي", code="SVC-WARD", category="other",
                        price=1000, is_active=True)
        drug = Service(name="دواء", category="other", price=100,
                       is_active=True)
        drug.invoice_section = "medicines"
        theatre = Service(name="عملية", category="procedure", price=2000,
                          is_active=True)
        theatre.invoice_section = "surgery"
        nursing = Service(name="رعاية تمريضية", category="other", price=0,
                          is_active=True)
        nursing.invoice_section = "nursing"
        medical = Service(name="رعاية طبية", category="other", price=0,
                          is_active=True)
        medical.invoice_section = "medical"
        clinic["db"].session.add_all([night, drug, theatre, nursing, medical])
        clinic["db"].session.flush()

        unit = Unit(name="قسم داخلي", kind="ward", rate_service_id=night.id,
                    billing_basis=bed_billing.default_basis("ward"))
        clinic["db"].session.add(unit)
        clinic["db"].session.flush()
        space = Space(unit_id=unit.id, name="غرفة ١", kind="room")
        clinic["db"].session.add(space)
        clinic["db"].session.flush()
        bed = Bed(space_id=space.id, name="سرير ١", sort_order=0)
        clinic["db"].session.add(bed)
        clinic["db"].session.commit()
        clinic["ids"] = {"night": night.id, "drug": drug.id,
                         "theatre": theatre.id, "nursing": nursing.id,
                         "medical": medical.id, "bed": bed.id}
    return clinic


def _rule(hospital, service="nursing", basis="per_day", amount=150,
          sections=None, kind=None, name="رعاية"):
    from app.models import CareCharge

    with hospital["app"].app_context():
        row = CareCharge(name_ar=name, service_id=hospital["ids"][service],
                         basis=basis, amount=amount,
                         sections=",".join(sections) if sections else None,
                         invoice_kind=kind, is_active=True)
        hospital["db"].session.add(row)
        hospital["db"].session.commit()
        return row.id


def _child(hospital, name="نزيل"):
    from app.models import Patient
    from app.utils.clock import local_today

    with hospital["app"].app_context():
        row = Patient(patient_number=f"H-{name}", full_name=name,
                      gender="male", is_active=True,
                      date_of_birth=local_today() - timedelta(days=900))
        hospital["db"].session.add(row)
        hospital["db"].session.commit()
        return row.id


def _stay(hospital, patient_id, days_ago=4):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with hospital["app"].app_context():
        row = place.admit(Patient.query.get(patient_id),
                          Bed.query.get(hospital["ids"]["bed"]),
                          when=datetime.utcnow() - timedelta(days=days_ago))
        hospital["db"].session.commit()
        return row.id


def _post(hospital, admission_id):
    """Run the stay's posting, the way a screen does."""
    from app.models.admission import Admission
    from app.utils import bed_billing

    with hospital["app"].app_context():
        out = bed_billing.charge(
            hospital["db"].session.get(Admission, admission_id))
        hospital["db"].session.commit()
        return out["invoice"].id if out["invoice"] is not None else None


def _lines(hospital, invoice_id):
    from app.models import Invoice

    invoice = hospital["db"].session.get(Invoice, invoice_id)
    return {i.description: i for i in invoice.items}


def _care_lines(hospital, invoice_id):
    from app.models import Invoice

    invoice = hospital["db"].session.get(Invoice, invoice_id)
    return [i for i in invoice.items if i.care_charge_id is not None]


# ------------------------------------------------------- the two shapes --
def test_a_daily_rate_counts_the_nights_the_bill_already_charged(hospital):
    """Not a second count of the stay: two counters of the same thing drift
    apart the first time anybody corrects one of them."""
    _rule(hospital, basis="per_day", amount=150)
    child = _child(hospital, "باليوم")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=4))

    with hospital["app"].app_context():
        care = _care_lines(hospital, invoice_id)
        assert len(care) == 1
        assert care[0].quantity == 4          # four nights, four days of care
        assert care[0].unit_price == 150
        assert care[0].net == 600


def test_a_percentage_is_taken_of_what_the_bill_comes_to(hospital):
    from app.models import Invoice, InvoiceItem

    _rule(hospital, service="medical", basis="percent", amount=12,
          name="رسوم خدمة")
    child = _child(hospital, "بالنسبة")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=2))

    with hospital["app"].app_context():
        invoice = hospital["db"].session.get(Invoice, invoice_id)
        # 2 nights × 1000 = 2000, and 12% of it.
        care = _care_lines(hospital, invoice_id)
        assert len(care) == 1
        assert care[0].net == 240
        # …and the line says where the number came from, so a family asking
        # "why 240" reads the answer off the bill.
        assert "12" in care[0].description and "2000" in care[0].description
        assert invoice.total == 2240


def test_both_at_once_because_plenty_of_hospitals_do_both(hospital):
    _rule(hospital, service="nursing", basis="per_day", amount=150,
          name="رعاية تمريضية")
    _rule(hospital, service="medical", basis="percent", amount=10,
          name="رعاية طبية")
    child = _child(hospital, "الاتنين")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=2))

    with hospital["app"].app_context():
        care = sorted(_care_lines(hospital, invoice_id), key=lambda i: i.net)
        assert len(care) == 2
        # 10% of the 2000 of nights — **not** of the nights plus the nursing.
        assert {i.net for i in care} == {200.0, 300.0}


# --------------------------------------------- recomputed, not accumulated --
def test_posting_the_stay_again_corrects_the_line(hospital):
    """**The one that would bill a family four times over.** A long stay is
    posted every day; a charge that added instead of correcting would have
    the fourth night's nursing on the bill four times by the fourth night."""
    from app.models import Admission

    _rule(hospital, basis="per_day", amount=150)
    child = _child(hospital, "تاني")
    stay = _stay(hospital, child, days_ago=2)
    invoice_id = _post(hospital, stay)

    with hospital["app"].app_context():
        assert len(_care_lines(hospital, invoice_id)) == 1
        assert _care_lines(hospital, invoice_id)[0].quantity == 2

    # Two nights later, posted again.
    with hospital["app"].app_context():
        row = hospital["db"].session.get(Admission, stay)
        row.admitted_at = datetime.utcnow() - timedelta(days=4)
        hospital["db"].session.commit()
    _post(hospital, stay)

    with hospital["app"].app_context():
        care = _care_lines(hospital, invoice_id)
        assert len(care) == 1, "a second care line was added instead of corrected"
        assert care[0].quantity == 4
        assert care[0].net == 600


def test_a_nursing_charge_filed_under_accommodation_does_not_count_itself(hospital):
    """**A runaway, and a plausible one.** Plenty of hospitals file nursing
    under «الإقامة» — it is part of what the room costs. If the day count then
    reads its own line as a night, two nights become three on the next
    posting, three become four, and the bill grows every time somebody opens
    the stay.

    Found by a mutation that passed: the count excluded care lines, and
    nothing in the suite billed one into the accommodation section, so
    removing the exclusion changed nothing visible.
    """
    from app.models import Admission, Service

    with hospital["app"].app_context():
        nursing = hospital["db"].session.get(Service,
                                             hospital["ids"]["nursing"])
        nursing.invoice_section = "accommodation"
        hospital["db"].session.commit()

    _rule(hospital, basis="per_day", amount=150)
    child = _child(hospital, "مش_بيعد_نفسه")
    stay = _stay(hospital, child, days_ago=2)
    invoice_id = _post(hospital, stay)
    with hospital["app"].app_context():
        assert _care_lines(hospital, invoice_id)[0].quantity == 2

    # Posted again with nothing changed: it must still say two.
    _post(hospital, stay)
    with hospital["app"].app_context():
        assert _care_lines(hospital, invoice_id)[0].quantity == 2

    # …and a genuine third night moves it to three, not to four or five.
    with hospital["app"].app_context():
        hospital["db"].session.get(Admission, stay).admitted_at = (
            datetime.utcnow() - timedelta(days=3))
        hospital["db"].session.commit()
    _post(hospital, stay)
    with hospital["app"].app_context():
        assert _care_lines(hospital, invoice_id)[0].quantity == 3


def test_a_percentage_grows_with_the_bill_it_is_taken_of(hospital):
    from app.models import Invoice, InvoiceItem

    _rule(hospital, service="medical", basis="percent", amount=10)
    child = _child(hospital, "بيكبر")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=1))
    with hospital["app"].app_context():
        assert _care_lines(hospital, invoice_id)[0].net == 100   # 10% of 1000

        invoice = hospital["db"].session.get(Invoice, invoice_id)
        invoice.items.append(InvoiceItem(service_id=hospital["ids"]["theatre"],
                                         description="عملية", unit_price=2000,
                                         quantity=1))
        hospital["db"].session.commit()

        from app.utils import care_charges

        care_charges.apply(invoice)
        hospital["db"].session.commit()
        assert _care_lines(hospital, invoice_id)[0].net == 300   # 10% of 3000


def test_a_rule_switched_off_takes_its_line_with_it(hospital):
    """A derived line that stops being derived from anything is a charge
    nobody can account for."""
    from app.models import CareCharge

    rule = _rule(hospital, basis="per_day", amount=150)
    child = _child(hospital, "اتلغى")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=2))
    with hospital["app"].app_context():
        assert len(_care_lines(hospital, invoice_id)) == 1
        hospital["db"].session.get(CareCharge, rule).is_active = False
        hospital["db"].session.commit()

        from app.models import Invoice
        from app.utils import care_charges

        care_charges.apply(hospital["db"].session.get(Invoice, invoice_id))
        hospital["db"].session.commit()
        assert _care_lines(hospital, invoice_id) == []


# ------------------------------------------------- what it is levied on --
def test_the_percentage_excludes_the_sections_it_was_told_to(hospital):
    """The Egyptian practice, and the reason the bill-section axis was built
    open: a percentage of the total *excluding medicines*."""
    from app.models import Invoice, InvoiceItem
    from app.utils import care_charges

    _rule(hospital, service="medical", basis="percent", amount=10,
          sections=["accommodation", "surgery"])
    child = _child(hospital, "غير_الأدوية")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=1))

    with hospital["app"].app_context():
        invoice = hospital["db"].session.get(Invoice, invoice_id)
        invoice.items.append(InvoiceItem(service_id=hospital["ids"]["drug"],
                                         description="دواء", unit_price=500,
                                         quantity=1))
        hospital["db"].session.commit()
        care_charges.apply(invoice)
        hospital["db"].session.commit()

        # 10% of the 1000 night — the 500 of medicine is out of the base.
        assert _care_lines(hospital, invoice_id)[0].net == 100


def test_naming_no_sections_means_the_whole_bill(hospital):
    """A real policy, not an unset field: a hospital that takes its fee on
    everything says so by naming no exclusions."""
    from app.models import Invoice, InvoiceItem
    from app.utils import care_charges

    _rule(hospital, service="medical", basis="percent", amount=10,
          sections=None)
    child = _child(hospital, "كله")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=1))
    with hospital["app"].app_context():
        invoice = hospital["db"].session.get(Invoice, invoice_id)
        invoice.items.append(InvoiceItem(service_id=hospital["ids"]["drug"],
                                         description="دواء", unit_price=500,
                                         quantity=1))
        hospital["db"].session.commit()
        care_charges.apply(invoice)
        hospital["db"].session.commit()
        assert _care_lines(hospital, invoice_id)[0].net == 150   # 10% of 1500


def test_a_percentage_is_never_levied_on_a_care_charge(hospital):
    """Two of these on one bill, each taking a cut of the other, is a number
    nobody can check and nobody meant."""
    _rule(hospital, service="nursing", basis="per_day", amount=500,
          name="تمريض")
    # Deliberately levied on *everything*, nursing included — and it still
    # must not reach the nursing line.
    _rule(hospital, service="medical", basis="percent", amount=10,
          sections=None, name="خدمة")
    child = _child(hospital, "مش_على_بعض")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=1))

    with hospital["app"].app_context():
        care = {i.service_id: i for i in _care_lines(hospital, invoice_id)}
        # 10% of the 1000 night only — not of 1000 + 500 of nursing.
        assert care[hospital["ids"]["medical"]].net == 100


def test_two_percentages_do_not_feed_each_other(hospital):
    _rule(hospital, service="medical", basis="percent", amount=10, name="أ")
    _rule(hospital, service="nursing", basis="percent", amount=10, name="ب")
    child = _child(hospital, "اتنين_نسب")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=1))
    with hospital["app"].app_context():
        care = _care_lines(hospital, invoice_id)
        assert len(care) == 2
        assert {i.net for i in care} == {100.0}     # both 10% of the same 1000


# ------------------------------------------------------------ which bills --
def test_a_rule_can_be_inpatient_only(hospital):
    """Read against ``Invoice.kind``, which is derived from the stay — so
    this reuses the axis rather than inventing a second one."""
    from app.models import Invoice
    from app.utils import care_charges

    _rule(hospital, basis="per_day", amount=150, kind="inpatient")
    child = _child(hospital, "داخلي_بس")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=1))
    with hospital["app"].app_context():
        assert len(_care_lines(hospital, invoice_id)) == 1

        walk_in = Invoice(invoice_number="INV-OUT", patient_id=child)
        hospital["db"].session.add(walk_in)
        hospital["db"].session.commit()
        care_charges.apply(walk_in)
        hospital["db"].session.commit()
        assert [i for i in walk_in.items if i.care_charge_id] == []


# -------------------------------------------------------------- the rest --
def test_a_clinic_that_defined_none_sees_no_change(hospital):
    """The promise made to every clinic already running."""
    from app.models import Invoice

    child = _child(hospital, "مفيش_قواعد")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=3))
    with hospital["app"].app_context():
        invoice = hospital["db"].session.get(Invoice, invoice_id)
        assert _care_lines(hospital, invoice_id) == []
        assert invoice.total == 3000       # three nights and nothing else


def test_nobodys_percentage_rides_on_a_care_charge(hospital):
    """It is the hospital's own fee for its nurses and its supervision — the
    same rule a box off the pharmacy shelf follows."""
    from app.models import Service

    with hospital["app"].app_context():
        nursing = hospital["db"].session.get(Service,
                                             hospital["ids"]["nursing"])
        nursing.commission_type = "percent"
        nursing.commission_value = 50
        hospital["db"].session.commit()

    _rule(hospital, basis="per_day", amount=150)
    child = _child(hospital, "مفيش_عمولة")
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=2))
    with hospital["app"].app_context():
        line = _care_lines(hospital, invoice_id)[0]
        assert line.commission_amount == 0
        assert line.doctor_id is None


def test_a_zero_rule_writes_nothing(hospital):
    """Nothing to charge is nothing to write — not a zero line saying the
    hospital charged for nursing and asked for nothing."""
    from app.models import CareCharge

    rule = _rule(hospital, basis="per_day", amount=150)
    child = _child(hospital, "صفر")
    with hospital["app"].app_context():
        hospital["db"].session.get(CareCharge, rule).amount = 0
        hospital["db"].session.commit()
    invoice_id = _post(hospital, _stay(hospital, child, days_ago=2))
    with hospital["app"].app_context():
        assert _care_lines(hospital, invoice_id) == []


def test_the_screen_draws_and_takes_a_rule(hospital):
    from app.models import CareCharge

    client = hospital["sign_in"]("boss")
    assert client.get("/finance/services").status_code == 200
    client.post("/finance/services/care/new", data={
        "name": "رسوم خدمة", "service_id": hospital["ids"]["medical"],
        "basis": "percent", "amount": "12",
        "sections": ["accommodation", "surgery"],
        "invoice_kind": "inpatient",
    }, follow_redirects=True)
    with hospital["app"].app_context():
        row = CareCharge.query.filter_by(name_ar="رسوم خدمة").one()
        assert row.basis == "percent" and row.amount == 12
        assert row.section_keys == {"accommodation", "surgery"}
        assert row.invoice_kind == "inpatient"


def test_a_rule_that_has_billed_is_switched_off_not_deleted(hospital):
    """Its lines point at it, and deleting it would leave charges on
    somebody's account that nothing explains."""
    from app.models import CareCharge

    rule = _rule(hospital, basis="per_day", amount=150)
    child = _child(hospital, "اتفوتر")
    _post(hospital, _stay(hospital, child, days_ago=1))

    hospital["sign_in"]("boss").post(
        f"/finance/services/care/{rule}/delete", follow_redirects=True)
    with hospital["app"].app_context():
        row = hospital["db"].session.get(CareCharge, rule)
        assert row is not None and row.is_active is False


def test_a_section_nothing_recognises_is_not_stored(hospital):
    """A key nothing matches would silently exclude everything — a service
    fee of zero that looks like a policy."""
    from app.models import CareCharge

    hospital["sign_in"]("boss").post("/finance/services/care/new", data={
        "name": "مخترع", "service_id": hospital["ids"]["medical"],
        "basis": "percent", "amount": "10",
        "sections": ["accommodation", "حاجة_مخترعة"],
    }, follow_redirects=True)
    with hospital["app"].app_context():
        row = CareCharge.query.filter_by(name_ar="مخترع").one()
        assert row.section_keys == {"accommodation"}
