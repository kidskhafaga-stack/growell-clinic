"""A clinic two years into its life, made up from nothing.

    python -m tools.loadtest.fake_clinic loadtest.db [--patients 8000]

Builds a **new** SQLite file — it refuses one that already exists, and it
refuses the path the clinic itself is configured to use — and fills it with
invented families, children, two years of visits, appointments, invoices and
payments, plus today's list for three doctors. Every row is fiction: the
names are drawn from short lists, the phone numbers are not anybody's.

The copy is stamped (``Setting load_test_copy = 1``), and the driver refuses
to run against any database that is not. A load test pointed at a working
clinic would be the test causing the outage it is meant to predict.

The bulk rows go in through the table, not the ORM — eight thousand children
one object at a time would take longer than the test. What the screens read
is the same either way: the columns are the model's own.
"""
import argparse
import os
import random
import sys
from datetime import datetime, time, timedelta

MARK = "load_test_copy"

BOYS = ["محمد", "أحمد", "يوسف", "عمر", "علي", "مصطفى", "كريم", "آدم", "زياد",
        "حمزة", "مالك", "سليم"]
GIRLS = ["مريم", "فاطمة", "جنى", "ملك", "حبيبة", "نور", "سلمى", "ليلى", "هنا",
         "رقية", "جودي", "تالين"]
FAMILIES = ["السيد", "عبد الله", "حسن", "إبراهيم", "محمود", "علي", "سالم",
            "منصور", "فؤاد", "رشاد", "جمال", "يونس", "خليل", "شاكر", "نصار"]
COMPLAINTS = ["حرارة وكحة", "إسهال", "طفح جلدي", "متابعة نمو", "التهاب أذن",
              "ترجيع", "رشح", "مغص"]

# The staff a small working clinic has, and the password they all share —
# this is a made-up clinic and nothing about it is secret.
PASSWORD = "loadtest-123"
STAFF = [("admin", "admin", "مدير التجربة"),
         ("reception1", "reception", "استقبال ١"),
         ("reception2", "reception", "استقبال ٢"),
         ("doctor1", "doctor", "د. أول"),
         ("doctor2", "doctor", "د. تاني"),
         ("doctor3", "doctor", "د. تالت"),
         ("cashier", "accountant", "الكاشير")]


def _refuse(path):
    """Why this path must not be built on, or ``None``."""
    if os.path.exists(path):
        return f"{path} already exists — this builds a new file only"
    clinic = (os.environ.get("DATABASE_URL") or "").replace("sqlite:///", "")
    if clinic and os.path.abspath(clinic) == os.path.abspath(path):
        return f"{path} is the clinic's own database (DATABASE_URL)"
    try:
        from app.settings_file import load_env
        load_env()
        configured = (os.environ.get("DATABASE_URL") or "").replace("sqlite:///", "")
        if configured and os.path.abspath(configured) == os.path.abspath(path):
            return f"{path} is the database clinic.env points at"
    except Exception:  # noqa: BLE001 - no clinic.env is fine
        pass
    return None


def _sequence(first):
    """``(base, width, n)`` from a number the program generated, so the made-up
    rows continue the program's own series and the next real one follows."""
    digits = len(first) - len(first.rstrip("0123456789"))
    return first[:-digits], digits, int(first[-digits:])


def build(path, patients=8000, seed=7, today=None, log=print):
    """Build the copy. Returns a summary dict."""
    why = _refuse(path)
    if why:
        raise SystemExit(f"refused: {why}")
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.abspath(path)

    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    assert os.path.abspath(path) in app.config["SQLALCHEMY_DATABASE_URI"]
    rnd = random.Random(seed)
    with app.app_context():
        from app.models import (Appointment, Family, Invoice, InvoiceItem,
                                Parent, Patient, Payment, Service, Setting,
                                User, Visit)
        from app.utils.finance import generate_invoice_number
        from app.utils.patients import generate_patient_number

        from app.utils.clock import local_today

        db.create_all()
        # The clinic's day, which is what the screens filter today's list by.
        today = today or local_today()
        Setting.set(MARK, "1")
        Setting.set("facility_configured", "1")
        # Collecting cash normally needs an open cashier shift; the test is
        # about the database under load, not the drawer, so the gate is off
        # in this copy and the report says so.
        Setting.set("require_shift_to_collect", "0")
        Setting.set("patient_number_scheme", "fixed")

        people = {}
        for username, role, name in STAFF:
            user = User(username=username, full_name=name, role=role,
                        is_active=True, is_super_admin=(username == "admin"))
            user.set_password(PASSWORD)
            db.session.add(user)
            people[username] = user
        db.session.flush()
        doctors = [people[f"doctor{i}"].id for i in (1, 2, 3)]

        exam = Service(name="كشف", category="consultation", price=250,
                       commission_type="percent", commission_value=40,
                       is_active=True)
        follow = Service(name="استشارة", category="consultation", price=150,
                         commission_type="percent", commission_value=50,
                         is_active=True)
        db.session.add_all([exam, follow])
        db.session.commit()

        # --- families and children ---------------------------------------
        base, width, n = _sequence(generate_patient_number())
        fam_rows, parent_rows, child_rows = [], [], []
        family_count = max(1, patients // 2)
        for f in range(family_count):
            fam_rows.append({"family_name": "عائلة " + rnd.choice(FAMILIES)})
        db.session.execute(Family.__table__.insert(), fam_rows)
        first_family = db.session.query(db.func.min(Family.id)).scalar()
        for f in range(family_count):
            parent_rows.append({
                "family_id": first_family + f, "relation": "father",
                "full_name": "والد " + rnd.choice(FAMILIES),
                "phone": f"0100{rnd.randint(1000000, 9999999)}",
                "is_primary_contact": True})
        db.session.execute(Parent.__table__.insert(), parent_rows)
        for i in range(patients):
            boy = rnd.random() < 0.5
            child_rows.append({
                "patient_number": f"{base}{n + i:0{width}d}",
                "family_id": first_family + (i % family_count),
                "full_name": f"{rnd.choice(BOYS if boy else GIRLS)} "
                             f"{rnd.choice(FAMILIES)}",
                "date_of_birth": today - timedelta(days=rnd.randint(20, 5000)),
                "gender": "male" if boy else "female", "is_active": True,
                "created_at": datetime.utcnow()})
        db.session.execute(Patient.__table__.insert(), child_rows)
        first_child = db.session.query(db.func.min(Patient.id)).scalar()
        db.session.commit()
        log(f"  {patients} children in {family_count} families")

        # --- two years of visits, appointments, invoices ------------------
        visits = patients * 4
        inv_base, inv_width, inv_n = _sequence(generate_invoice_number())
        appt_rows, visit_rows, inv_rows = [], [], []
        for i in range(visits):
            child = first_child + rnd.randrange(patients)
            doctor = rnd.choice(doctors)
            day = today - timedelta(days=rnd.randint(1, 730))
            appt_rows.append({
                "patient_id": child, "doctor_id": doctor, "appt_date": day,
                "appt_time": time(rnd.randint(9, 20), rnd.choice((0, 20, 40))),
                "duration_minutes": 20, "status": "completed",
                "reason": "متابعة"})
            visit_rows.append({
                "patient_id": child, "doctor_id": doctor, "visit_date": day,
                "chief_complaint": rnd.choice(COMPLAINTS),
                "status": "completed"})
            inv_rows.append({
                "invoice_number": f"{inv_base}{inv_n + i:0{inv_width}d}",
                "patient_id": child, "doctor_id": doctor,
                "invoice_date": day, "status": "paid",
                "created_by": people["cashier"].id})
        for table, rows in ((Appointment.__table__, appt_rows),
                            (Visit.__table__, visit_rows),
                            (Invoice.__table__, inv_rows)):
            for k in range(0, len(rows), 5000):
                db.session.execute(table.insert(), rows[k:k + 5000])
        first_invoice = db.session.query(db.func.min(Invoice.id)).scalar()
        item_rows, pay_rows = [], []
        for i in range(visits):
            price = rnd.choice((250, 150))
            item_rows.append({
                "invoice_id": first_invoice + i,
                "service_id": exam.id if price == 250 else follow.id,
                "description": "كشف" if price == 250 else "استشارة",
                "unit_price": price, "quantity": 1,
                "commission_amount": price * 0.4})
            pay_rows.append({
                "invoice_id": first_invoice + i, "amount": price,
                "method": rnd.choice(("cash", "cash", "card")),
                "received_by": people["cashier"].id,
                "paid_at": datetime.combine(inv_rows[i]["invoice_date"],
                                            time(12, 0))})
        for table, rows in ((InvoiceItem.__table__, item_rows),
                            (Payment.__table__, pay_rows)):
            for k in range(0, len(rows), 5000):
                db.session.execute(table.insert(), rows[k:k + 5000])
        db.session.commit()
        log(f"  {visits} past visits, appointments and paid invoices")

        # --- today's list -------------------------------------------------
        today_rows = []
        # A child is booked once today: a second booking for the same child
        # the same day is a real thing, but it folds into one invoice by
        # design and would make "was this booking paid" a harder question
        # than the test is asking.
        todays = iter(rnd.sample(range(patients), min(patients, 40 * len(doctors))))
        for d, doctor in enumerate(doctors):
            for slot in range(40):
                today_rows.append({
                    "patient_id": first_child + next(todays),
                    "doctor_id": doctor, "appt_date": today,
                    "appt_time": time(9 + slot // 3, (slot % 3) * 20),
                    "duration_minutes": 20,
                    "status": "waiting" if slot < 30 else "scheduled",
                    "reason": "كشف"})
        db.session.execute(Appointment.__table__.insert(), today_rows)
        db.session.commit()
        log(f"  {len(today_rows)} appointments on today's list")
    return {"path": os.path.abspath(path), "patients": patients,
            "visits": visits, "today": len(today_rows),
            "password": PASSWORD, "staff": [s[0] for s in STAFF]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("path")
    parser.add_argument("--patients", type=int, default=8000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    started = datetime.utcnow()
    summary = build(args.path, patients=args.patients, seed=args.seed)
    took = (datetime.utcnow() - started).total_seconds()
    print(f"built {summary['path']} in {took:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
