"""The inpatient bill: a summary over a detail, and every line with its day.

Asked for in one sentence — *«يكون عندك ملخص رئيسي … وفي نفس الوقت زر عرض
التفاصيل»* — and the reason is arithmetic: a fortnight in a hospital produces
sixty or seventy lines. Every night, every dose, every consultant's round, a
theatre. Nobody reads that in order. They read six numbers — الإقامة كذا،
العمليات كذا، الأدوية كذا — and then open the one that looks wrong.

Three decisions hold it up, and each is a way the bill goes quietly wrong:

**One set of arithmetic.** The section totals are the lines' own nets added
up, never a second figure kept anywhere. A summary that can disagree with its
detail costs more to check than the detail did.

**The line carries its own day.** It used to live inside the description text
of the bed's lines and nowhere at all on anybody else's — good enough to read,
useless to group by. So the one bill that most needed breaking down by day was
the only one that could not be.

**And the kind of bill is derived, never stored.** *«لازم نفرق بين الفواتير
الداخلية والفواتير الخارجية»* — and the invoice already answers it: a bill
raised against a stay is the stay's bill. A column saying the same thing again
could disagree with the first, and would be empty on every invoice already
raised. It is a display axis: **both kinds go through exactly the same money.**
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """A ward with a priced night, a child in it, and a bill with a past."""
    from app.models import Service, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils import bed_billing
    from app.utils.invoice_sections import ensure_seeded

    with clinic["app"].app_context():
        for module in ("beds", "ward", "pharmacy", "labs"):
            Setting.set(f"mod_enabled:{module}", "1")
        ensure_seeded()

        night = Service(name="ليلة داخلي", code="SVC-WARD", category="other",
                        price=500, is_active=True)
        drug = Service(name="دواء", category="other", price=40,
                       is_active=True)
        drug.invoice_section = "medicines"
        theatre = Service(name="عملية", category="procedure", price=3000,
                          is_active=True)
        theatre.invoice_section = "surgery"
        clinic["db"].session.add_all([night, drug, theatre])
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
                         "theatre": theatre.id, "bed": bed.id}
    return clinic


def _child(ward, name="نزيل"):
    from app.models import Patient
    from app.utils.clock import local_today

    with ward["app"].app_context():
        row = Patient(patient_number=f"W-{name}", full_name=name,
                      gender="male", is_active=True,
                      date_of_birth=local_today() - timedelta(days=900))
        ward["db"].session.add(row)
        ward["db"].session.commit()
        return row.id


def _stay(ward, patient_id, days_ago=4):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with ward["app"].app_context():
        row = place.admit(Patient.query.get(patient_id),
                          Bed.query.get(ward["ids"]["bed"]),
                          when=datetime.utcnow() - timedelta(days=days_ago))
        ward["db"].session.commit()
        return row.id


def _bill(ward, admission_id):
    """Post the nights and hand back the invoice they landed on."""
    from app.models.admission import Admission
    from app.utils import bed_billing

    with ward["app"].app_context():
        stay = ward["db"].session.get(Admission, admission_id)
        out = bed_billing.charge(stay)
        ward["db"].session.commit()
        return out["invoice"].id if out["invoice"] is not None else None


# ------------------------------------------------ which kind of bill this is --
def test_a_bill_raised_against_a_stay_is_the_stays_bill(ward):
    """Derived from what the invoice already carried. No column, so it is
    right about every bill this clinic raised before today."""
    from app.models import Invoice

    child = _child(ward, "داخلي")
    stay = _stay(ward, child)
    invoice_id = _bill(ward, stay)

    with ward["app"].app_context():
        inpatient = ward["db"].session.get(Invoice, invoice_id)
        assert inpatient.admission_id == stay
        assert inpatient.kind == "inpatient"

        walk_in = Invoice(invoice_number="INV-WALK", patient_id=child)
        ward["db"].session.add(walk_in)
        ward["db"].session.commit()
        assert walk_in.kind == "outpatient"


def test_the_kind_is_display_and_both_go_through_the_same_money(ward):
    """The rule the whole axis rests on: nothing about how money is taken
    changes with the kind. A second money path is what this avoids."""
    from app.models import Invoice, InvoiceItem, Payment

    child = _child(ward, "نفس_الطريق")
    stay = _stay(ward, child)
    invoice_id = _bill(ward, stay)

    with ward["app"].app_context():
        inpatient = ward["db"].session.get(Invoice, invoice_id)
        outpatient = Invoice(invoice_number="INV-OUT", patient_id=child)
        outpatient.items.append(InvoiceItem(description="كشف", unit_price=200,
                                            quantity=1))
        ward["db"].session.add(outpatient)
        ward["db"].session.commit()

        for invoice in (inpatient, outpatient):
            before = invoice.balance
            ward["db"].session.add(Payment(invoice_id=invoice.id, amount=100,
                                           method="cash"))
            ward["db"].session.commit()
            invoice.recalc_status()
            assert invoice.balance == round(before - 100, 2), invoice.kind
            assert invoice.status in ("partial", "paid")


def test_the_list_can_be_cut_into_the_two(ward):
    from app.models import Invoice

    child = _child(ward, "فلترة")
    stay = _stay(ward, child)
    invoice_id = _bill(ward, stay)
    with ward["app"].app_context():
        inpatient_no = ward["db"].session.get(Invoice, invoice_id).invoice_number
        ward["db"].session.add(Invoice(invoice_number="INV-OUT-1",
                                       patient_id=child))
        ward["db"].session.commit()

    client = ward["sign_in"]("boss")
    inside = client.get("/finance/invoices?kind=inpatient").get_data(as_text=True)
    assert inpatient_no in inside and "INV-OUT-1" not in inside

    outside = client.get("/finance/invoices?kind=outpatient").get_data(as_text=True)
    assert "INV-OUT-1" in outside and inpatient_no not in outside

    both = client.get("/finance/invoices").get_data(as_text=True)
    assert inpatient_no in both and "INV-OUT-1" in both


# ------------------------------------------------------- the day of the line --
def test_every_night_carries_its_own_date(ward):
    """The column this exists for. Four nights on one bill, and until now the
    only place each night's date lived was inside its description text."""
    from app.models import Invoice

    child = _child(ward, "أربع_ليالي")
    stay = _stay(ward, child, days_ago=4)
    invoice_id = _bill(ward, stay)

    with ward["app"].app_context():
        invoice = ward["db"].session.get(Invoice, invoice_id)
        dates = sorted(i.service_date for i in invoice.items)
        assert len(dates) == 4
        assert len(set(dates)) == 4, "four nights, four different days"
        # …and they are the nights themselves, not the day of the bill.
        assert dates[-1] < invoice.invoice_date


def test_a_line_nobody_dated_falls_back_without_claiming_a_day(ward):
    """NULL means "nobody recorded it", which is the true answer for every
    line written before the column existed. The fallback is display only."""
    from app.models import Invoice, InvoiceItem

    child = _child(ward, "قديم")
    with ward["app"].app_context():
        invoice = Invoice(invoice_number="INV-OLD", patient_id=child,
                          invoice_date=date(2026, 3, 5))
        invoice.items.append(InvoiceItem(description="بند قديم", unit_price=90,
                                         quantity=1))
        ward["db"].session.add(invoice)
        ward["db"].session.commit()

        line = invoice.items[0]
        assert line.service_date is None          # nothing was invented
        assert line.on_date == date(2026, 3, 5)   # and it still groups


def test_a_procedure_from_last_weeks_visit_is_dated_to_that_visit(ward):
    """The carry-over case, and the one where the wrong date is actually
    wrong: a procedure added on Tuesday and collected on Friday belongs to
    Tuesday, and the bill is the only place that would ever say so."""
    from app.models import Invoice, Service, Visit, VisitService
    from app.utils.clock import local_today

    child = _child(ward, "مؤجل")
    tuesday = local_today() - timedelta(days=3)
    with ward["app"].app_context():
        from app.models import User

        doctor = User.query.filter_by(role="doctor").first()
        visit = Visit(patient_id=child, doctor_id=doctor.id,
                      visit_date=tuesday)
        ward["db"].session.add(visit)
        ward["db"].session.flush()
        service = ward["db"].session.get(Service, ward["ids"]["drug"])
        ward["db"].session.add(VisitService(
            visit_id=visit.id, service_id=service.id, name=service.name,
            quantity=1))
        ward["db"].session.commit()
        doctor_id = doctor.id

    ward["sign_in"]("boss").post(f"/finance/collect/{child}", data={
        "doctor_id": doctor_id, "discount_id": "none",
        "line_service_id": [str(ward["ids"]["drug"])],
        "line_desc": ["دواء"], "line_price": ["40"], "line_qty": ["1"],
        "line_no_commission": ["0"], "line_brand_id": [""],
        "line_dose_id": [""], "line_dose_number": [""],
        "line_vs_id": [str(_vs_id(ward, child))],
        "line_op_id": [""], "line_test_id": [""], "line_rx_line_id": [""],
        "line_pkg_id": [""], "line_pkg_sale_id": [""],
    }, follow_redirects=True)

    with ward["app"].app_context():
        invoice = Invoice.query.filter_by(patient_id=child).one()
        assert invoice.items[0].service_date == tuesday
        assert invoice.invoice_date != tuesday


def _vs_id(ward, patient_id):
    from app.models import Visit, VisitService

    with ward["app"].app_context():
        return (VisitService.query.join(Visit)
                .filter(Visit.patient_id == patient_id).one().id)


def test_a_date_typed_into_the_form_is_not_believed(ward):
    """A date is as forgeable as an id, and this one decides which day of a
    stay a charge lands on. Read from the resolved row or not at all."""
    from app.models import Invoice, Service, User, Visit, VisitService
    from app.utils.clock import local_today

    child = _child(ward, "مزوّر")
    tuesday = local_today() - timedelta(days=2)
    with ward["app"].app_context():
        doctor = User.query.filter_by(role="doctor").first()
        visit = Visit(patient_id=child, doctor_id=doctor.id,
                      visit_date=tuesday)
        ward["db"].session.add(visit)
        ward["db"].session.flush()
        service = ward["db"].session.get(Service, ward["ids"]["drug"])
        ward["db"].session.add(VisitService(visit_id=visit.id,
                                            service_id=service.id,
                                            name=service.name, quantity=1))
        ward["db"].session.commit()
        doctor_id = doctor.id

    ward["sign_in"]("boss").post(f"/finance/collect/{child}", data={
        "doctor_id": doctor_id, "discount_id": "none",
        "line_service_id": [str(ward["ids"]["drug"])],
        "line_desc": ["دواء"], "line_price": ["40"], "line_qty": ["1"],
        "line_no_commission": ["0"], "line_brand_id": [""],
        "line_dose_id": [""], "line_dose_number": [""],
        "line_vs_id": [str(_vs_id(ward, child))],
        "line_op_id": [""], "line_test_id": [""], "line_rx_line_id": [""],
        "line_pkg_id": [""], "line_pkg_sale_id": [""],
        # A date nobody would accept, posted anyway.
        "line_service_date": ["1999-01-01"],
    }, follow_redirects=True)

    with ward["app"].app_context():
        invoice = Invoice.query.filter_by(patient_id=child).one()
        assert invoice.items[0].service_date == tuesday


# ------------------------------------------------------ the summary itself --
def test_the_summary_is_the_lines_added_up_and_nothing_else(ward):
    """One set of arithmetic. A total kept anywhere but here is a total that
    can disagree with the bill it summarises."""
    from app.models import Invoice, InvoiceItem
    from app.utils import invoice_totals

    child = _child(ward, "مجموع")
    stay = _stay(ward, child, days_ago=2)
    invoice_id = _bill(ward, stay)

    with ward["app"].app_context():
        invoice = ward["db"].session.get(Invoice, invoice_id)
        invoice.items.append(InvoiceItem(service_id=ward["ids"]["drug"],
                                         description="دواء", unit_price=40,
                                         quantity=3))
        invoice.items.append(InvoiceItem(service_id=ward["ids"]["theatre"],
                                         description="عملية", unit_price=3000,
                                         quantity=1))
        ward["db"].session.commit()

        rows = invoice_totals.by_section(invoice, "ar")
        by_key = {r["key"]: r for r in rows}
        assert by_key["accommodation"]["total"] == 1000     # two nights
        assert by_key["medicines"]["total"] == 120          # 40 × 3
        assert by_key["surgery"]["total"] == 3000
        # And the summary adds up to the bill. Not approximately.
        assert round(sum(r["total"] for r in rows), 2) == invoice.total


def test_a_section_with_nothing_in_it_is_not_a_heading(ward):
    """A summary of eight headings, five of them zero, is a summary nobody's
    eye can land on."""
    from app.models import Invoice
    from app.utils import invoice_totals

    child = _child(ward, "فاضي")
    stay = _stay(ward, child, days_ago=1)
    invoice_id = _bill(ward, stay)
    with ward["app"].app_context():
        invoice = ward["db"].session.get(Invoice, invoice_id)
        rows = invoice_totals.by_section(invoice, "ar")
        assert [r["key"] for r in rows] == ["accommodation"]


def test_a_line_with_no_service_is_unclassified_not_guessed(ward):
    """A box off the pharmacy shelf carries no service to read a section
    from. Putting money under a heading nobody chose is exactly what a
    summary is read to rule out."""
    from app.models import Invoice, InvoiceItem
    from app.utils import invoice_totals

    child = _child(ward, "بدون_خدمة")
    with ward["app"].app_context():
        invoice = Invoice(invoice_number="INV-FREE", patient_id=child)
        invoice.items.append(InvoiceItem(description="حاجة مكتوبة بالإيد",
                                         unit_price=75, quantity=1))
        ward["db"].session.add(invoice)
        ward["db"].session.commit()

        rows = invoice_totals.by_section(invoice, "ar")
        assert rows[0]["key"] == "other"
        assert rows[0]["section"] is None      # honest: nobody classified it


def test_unclassified_sorts_last(ward):
    """It is the bucket somebody should empty, not the heading a bill leads
    with."""
    from app.models import Invoice, InvoiceItem
    from app.utils import invoice_totals

    child = _child(ward, "ترتيب")
    with ward["app"].app_context():
        invoice = Invoice(invoice_number="INV-ORDER", patient_id=child)
        invoice.items.append(InvoiceItem(description="بدون", unit_price=10,
                                         quantity=1))
        invoice.items.append(InvoiceItem(service_id=ward["ids"]["theatre"],
                                         description="عملية", unit_price=3000,
                                         quantity=1))
        ward["db"].session.add(invoice)
        ward["db"].session.commit()

        assert [r["key"] for r in
                invoice_totals.by_section(invoice, "ar")] == ["surgery", "other"]


def test_the_clinic_decides_the_order_of_its_own_summary(ward):
    """Nothing here reads a section by name — the grouping is whatever
    sections exist, in whatever order the clinic put them. That is the
    property that made this axis safe to open in the first place."""
    from app.models import Invoice, InvoiceItem, InvoiceSection
    from app.utils import invoice_totals

    child = _child(ward, "ترتيبهم")
    with ward["app"].app_context():
        invoice = Invoice(invoice_number="INV-SORT", patient_id=child)
        invoice.items.append(InvoiceItem(service_id=ward["ids"]["night"],
                                         description="ليلة", unit_price=500,
                                         quantity=1))
        invoice.items.append(InvoiceItem(service_id=ward["ids"]["theatre"],
                                         description="عملية", unit_price=3000,
                                         quantity=1))
        ward["db"].session.add(invoice)
        ward["db"].session.commit()
        assert [r["key"] for r in invoice_totals.by_section(invoice, "ar")] \
            == ["accommodation", "surgery"]

        # The clinic moves the theatre to the top of its bills.
        surgery = InvoiceSection.query.filter_by(key="surgery").one()
        surgery.sort_order = -1
        ward["db"].session.commit()
        assert [r["key"] for r in invoice_totals.by_section(invoice, "ar")] \
            == ["surgery", "accommodation"]


def test_the_detail_groups_by_the_day_the_work_happened(ward):
    from app.models import Invoice
    from app.utils import invoice_totals

    child = _child(ward, "باليوم")
    stay = _stay(ward, child, days_ago=3)
    invoice_id = _bill(ward, stay)
    with ward["app"].app_context():
        invoice = ward["db"].session.get(Invoice, invoice_id)
        rows = invoice_totals.by_section(invoice, "ar")
        days = invoice_totals.by_day(rows[0]["items"])
        assert len(days) == 3
        assert [d["day"] for d in days] == sorted(d["day"] for d in days)
        assert sum(d["total"] for d in days) == rows[0]["total"]


def test_one_afternoons_receipt_is_not_broken_into_days(ward):
    """An afternoon's bill with a heading per day is noise. The breakdown
    appears because the bill spans days, not because the feature exists."""
    from app.models import Invoice, InvoiceItem
    from app.utils import invoice_totals

    child = _child(ward, "يوم_واحد")
    with ward["app"].app_context():
        invoice = Invoice(invoice_number="INV-DAY", patient_id=child)
        invoice.items.append(InvoiceItem(service_id=ward["ids"]["drug"],
                                         description="دواء", unit_price=40,
                                         quantity=1))
        invoice.items.append(InvoiceItem(service_id=ward["ids"]["theatre"],
                                         description="عملية", unit_price=3000,
                                         quantity=1))
        ward["db"].session.add(invoice)
        ward["db"].session.commit()
        assert invoice_totals.spans_days(invoice) is False

        stay = _stay(ward, _child(ward, "فترة"), days_ago=3)
    long_bill = _bill(ward, stay)
    with ward["app"].app_context():
        assert invoice_totals.spans_days(
            ward["db"].session.get(Invoice, long_bill)) is True


# ------------------------------------------------------------- the screens --
def test_the_bill_screen_draws_the_summary_and_the_days(ward):
    from app.models import Invoice, InvoiceItem

    child = _child(ward, "شاشة")
    stay = _stay(ward, child, days_ago=3)
    invoice_id = _bill(ward, stay)
    with ward["app"].app_context():
        invoice = ward["db"].session.get(Invoice, invoice_id)
        invoice.items.append(InvoiceItem(service_id=ward["ids"]["theatre"],
                                         description="عملية", unit_price=3000,
                                         quantity=1))
        ward["db"].session.commit()

    page = ward["sign_in"]("boss").get(
        f"/finance/invoices/{invoice_id}").get_data(as_text=True)
    assert "الإقامة" in page and "العمليات" in page
    assert "3000.00" in page or "3000" in page


def test_the_bill_reads_right_before_anybody_seeded_the_sections(ward):
    """A clinic mid-upgrade has no section rows yet, and the bill still has
    to be readable: headings named, icons drawn, totals right.

    The first version of this screen called ``ensure_seeded()`` on the way in,
    copying the services screen. A mutation test showed every check still
    passing without it — and that was the honest answer: filling a clinic's
    catalogue as a side effect of *looking at a bill* is a write on a read
    path, and the built-in fallback is what the fallback is for. So the
    seeding came out, and this asserts what it was pretending to protect.
    """
    from app.models import Invoice, InvoiceSection
    from app.utils import invoice_totals

    child = _child(ward, "غير_مهيّأ")
    stay = _stay(ward, child, days_ago=2)
    invoice_id = _bill(ward, stay)
    with ward["app"].app_context():
        InvoiceSection.query.delete()
        ward["db"].session.commit()
        assert InvoiceSection.query.count() == 0

        rows = invoice_totals.by_section(
            ward["db"].session.get(Invoice, invoice_id), "ar")
        assert [r["key"] for r in rows] == ["accommodation"]
        assert rows[0]["icon"] == "bi-house-heart"    # not a blank square
        assert rows[0]["total"] == 1000

    page = ward["sign_in"]("boss").get(f"/finance/invoices/{invoice_id}")
    assert page.status_code == 200
    # …and looking at it wrote nothing: a read path stays a read path.
    with ward["app"].app_context():
        assert InvoiceSection.query.count() == 0
