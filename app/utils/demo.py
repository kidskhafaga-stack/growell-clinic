"""Demo data: a realistic sample dataset for presentations, plus a full reset.

``seed_demo`` populates families, patients, services, an insurer with
per-service coverage, today's appointments, invoices/payments and a couple of
ETA tax invoices (demo mode). ``reset_all`` wipes every operational/clinical/
financial record so the clinic can start clean, keeping only the system
configuration (users, roles, settings) and the vaccine reference catalogue.
"""
import random
from datetime import date, datetime, time, timedelta

from app.extensions import db
from app.models import (
    Appointment,
    Diagnosis,
    DoctorSchedule,
    EInvoiceDocument,
    Family,
    GrowthRecord,
    Invoice,
    InvoiceItem,
    MessageLog,
    Parent,
    Patient,
    PatientCoverage,
    PatientVaccine,
    PayerEntity,
    PayerServiceRate,
    Payment,
    Service,
    ServiceBundleItem,
    Setting,
    Supplier,
    User,
    VaccineInventory,
    VitalSigns,
)
from app.models.service import DoctorServiceCommission
from app.utils.finance import generate_invoice_number
from app.utils.patients import generate_patient_number

def reset_all():
    """Delete all operational data; keep users, roles, settings, catalogue."""
    from app.models import Visit

    order = [
        EInvoiceDocument, Payment, InvoiceItem, Invoice,
        PatientCoverage, PayerServiceRate, PayerEntity,
        DoctorServiceCommission, ServiceBundleItem, Service,
        MessageLog, PatientVaccine, GrowthRecord, VitalSigns, Diagnosis,
        Visit, Appointment, DoctorSchedule, VaccineInventory, Supplier,
        Parent, Patient, Family,
    ]
    counts = {}
    for model in order:
        counts[model.__tablename__] = model.query.delete(synchronize_session=False)
    Setting.set("demo_seeded", "0")
    db.session.commit()
    return counts


# Sample Arabic names for believable demo data.
_BOYS = ["يوسف", "أحمد", "عمر", "مالك", "حمزة", "آدم", "زياد", "كريم"]
_GIRLS = ["ملك", "جنى", "مريم", "ليان", "سارة", "تالة", "روان", "حلا"]
_FAMILIES = ["الشريف", "منصور", "عبد الله", "خليل", "السيد", "رمضان"]


def _doctor():
    doc = User.query.filter_by(role="doctor", is_active=True).first()
    if doc is None:
        doc = User(username="demo_doctor", full_name="د. هاني فؤاد",
                   full_name_en="Dr. Hany Fouad", role="doctor", is_active=True,
                   phone="01000000010")
        doc.set_password("demo12345")
        db.session.add(doc)
        db.session.flush()
    return doc


def seed_demo():
    """Create a demo dataset. Returns a summary dict. Idempotent-ish (guarded)."""
    if Setting.get("demo_seeded") == "1":
        return {"skipped": True}

    rnd = random.Random(42)
    doc = _doctor()
    today = datetime.utcnow().date()

    # --- Services -------------------------------------------------------
    services = []
    for name, code, price, ctype, cval, cat in [
        ("كشف", "EG-1001", 250, "percent", 40, "consultation"),
        ("استشارة", "EG-1002", 150, "percent", 50, "consultation"),
        ("رسم تطعيم", "EG-2001", 100, "fixed", 20, "vaccination_fee"),
        ("سونار", "EG-3001", 400, "percent", 30, "radiology"),
        ("تحاليل", "EG-4001", 200, "none", 0, "lab"),
    ]:
        s = Service(name=name, code=code, price=price, category=cat,
                    commission_type=ctype, commission_value=cval, is_active=True)
        db.session.add(s)
        services.append(s)
    db.session.flush()

    # --- Insurer with per-service coverage ------------------------------
    insurer = PayerEntity(name="مصر للتأمين الصحي", entity_type="insurance",
                          discount_percent=20, phone="0224000000", is_active=True)
    db.session.add(insurer)
    db.session.flush()
    for s, ctype, cval in [(services[0], "percent", 30), (services[3], "fixed", 100)]:
        db.session.add(PayerServiceRate(payer_id=insurer.id, service_id=s.id,
                                        coverage_type=ctype, coverage_value=cval))

    # --- Families, patients, coverage -----------------------------------
    patients = []
    for fam_name in _FAMILIES:
        fam = Family(family_name="عائلة " + fam_name)
        db.session.add(fam)
        db.session.flush()
        db.session.add(Parent(
            family_id=fam.id, relation="father", full_name="والد " + fam_name,
            phone=f"010{rnd.randint(10000000, 99999999)}", is_primary_contact=True,
            client_category="normal",
        ))
        for _ in range(rnd.randint(1, 3)):
            boy = rnd.random() < 0.5
            nm = rnd.choice(_BOYS if boy else _GIRLS)
            age_days = rnd.randint(60, 2200)
            p = Patient(
                patient_number=generate_patient_number(),
                family_id=fam.id, full_name=f"{nm} {fam_name}",
                date_of_birth=today - timedelta(days=age_days),
                gender="male" if boy else "female", is_active=True,
            )
            db.session.add(p)
            db.session.flush()
            patients.append(p)

    db.session.flush()
    # Two patients covered by the insurer.
    for p in patients[:2]:
        db.session.add(PatientCoverage(
            patient_id=p.id, payer_id=insurer.id,
            membership_number=f"778-{rnd.randint(10000, 99999)}",
            expiry_date=today + timedelta(days=rnd.randint(120, 600)), is_active=True,
        ))

    # --- Growth measurements (so the charts have data) ------------------
    for p in patients:
        age_m = max(1, p.age_days // 30)
        # A handful of monthly-ish points up to the child's age.
        months = sorted(set(rnd.sample(range(0, age_m + 1), min(5, age_m + 1))))
        for m in months:
            # Rough WHO-ish trajectory; demo values only.
            w = round(3.3 + m * (0.6 if m < 12 else 0.2) + rnd.uniform(-0.4, 0.4), 1)
            h = round(50 + m * (2.0 if m < 12 else 1.0) + rnd.uniform(-1, 1), 1)
            hc = round(34 + m * (0.5 if m < 12 else 0.15) + rnd.uniform(-0.5, 0.5), 1)
            db.session.add(GrowthRecord(
                patient_id=p.id,
                record_date=p.date_of_birth + timedelta(days=m * 30),
                weight_kg=max(2.5, w), height_cm=max(48, h),
                head_circ_cm=max(32, hc), source="demo",
            ))

    # --- Today's appointments (mixed statuses) --------------------------
    statuses = ["completed", "completed", "in_progress", "waiting",
                "scheduled", "scheduled", "no_show", "scheduled"]
    for i, p in enumerate(patients[:len(statuses)]):
        db.session.add(Appointment(
            patient_id=p.id, doctor_id=doc.id, appt_date=today,
            appt_time=time(9 + i // 2, 0 if i % 2 == 0 else 30),
            duration_minutes=20, status=statuses[i], reason="متابعة",
        ))

    # --- Invoices + payments + a couple of tax invoices -----------------
    from app.utils import einvoice as eta
    pay_methods = ["cash", "card", "transfer"]
    made = 0
    for i, p in enumerate(patients[:6]):
        inv = Invoice(invoice_number=generate_invoice_number(), patient_id=p.id,
                      doctor_id=doc.id, invoice_date=today - timedelta(days=i),
                      created_by=doc.id)
        db.session.add(inv)
        db.session.flush()
        chosen = rnd.sample(services, rnd.randint(1, 3))
        for s in chosen:
            net = s.price
            inv.items.append(InvoiceItem(
                service_id=s.id, description=s.name, unit_price=s.price,
                quantity=1, commission_amount=s.doctor_share(net, doc),
            ))
        db.session.flush()
        # Payment pattern: paid / partial / unpaid.
        kind = i % 3
        if kind == 0:
            inv.payments.append(Payment(amount=inv.total, method=rnd.choice(pay_methods),
                                        received_by=doc.id))
        elif kind == 1 and inv.total > 0:
            inv.payments.append(Payment(amount=round(inv.total / 2, 2),
                                        method="cash", received_by=doc.id))
        inv.recalc_status()
        made += 1
        # Mark the first two as ETA tax invoices and submit (demo).
        if i < 2:
            edoc = eta.queue_for_invoice(inv, user_id=doc.id)
            db.session.flush()
            eta.submit(edoc, user_id=doc.id)

    # --- A few WhatsApp message logs ------------------------------------
    for p in patients[:3]:
        phone = p.contact_phone
        if phone:
            db.session.add(MessageLog(
                patient_id=p.id, to_phone="2" + phone.lstrip("0"),
                body=f"مرحباً {p.full_name}، تم تأكيد موعدك.",
                provider="web", status="link",
                link="https://wa.me/2" + phone.lstrip("0"),
            ))

    # --- Suppliers + vaccine inventory (if catalogue is present) --------
    from app.models import VaccineBrand
    brand = VaccineBrand.query.first()
    if brand is not None:
        sup = Supplier(name="شركة فاكسيرا", phone="0227000000", is_active=True)
        db.session.add(sup)
        db.session.flush()
        db.session.add(VaccineInventory(
            brand_id=brand.id, supplier_id=sup.id, lot_number="LOT-DEMO-01",
            expiry_date=today + timedelta(days=45), qty_received=8, qty_used=2,
            unit_cost=80,
        ))

    Setting.set("demo_seeded", "1")
    db.session.commit()
    return {"patients": len(patients), "services": len(services),
            "invoices": made, "skipped": False}
