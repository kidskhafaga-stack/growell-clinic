"""A clinic with a day's worth of people and things in it.

The flow tests need the same world each time — a doctor, a cashier, a child,
a service with a commission on it, a vaccine with stock in two batches — and
building it inline in every test buries what each test is actually about.

Everything is handed back as **ids**, never as model objects: the tests open
their own app contexts, and an object loaded in the fixture's session would be
read in one session and written from another, which is how a test comes to
report a stock deduction that did happen as if it hadn't.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    """A working clinic: staff, a child, a priced service, and vaccines.

    The two vaccine batches are created **later-expiry first** on purpose, so
    a test that expects first-expiry-first-out is actually testing something —
    with the batches in order, insertion order and FEFO give the same answer
    and the test would pass either way.
    """
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import (Patient, Service, User, Vaccine, VaccineBrand,
                                VaccineBrandDose, VaccineInventory, Visit)

        people = {}
        for username, role, name in (("boss", "admin", "المدير"),
                                     ("doc", "doctor", "د. أحمد"),
                                     ("desk", "reception", "الاستقبال"),
                                     ("acct", "accountant", "المحاسب")):
            user = User(username=username, full_name=name, role=role,
                        is_active=True)
            user.set_password("secret")
            db.session.add(user)
            people[username] = user
        db.session.flush()

        exam = Service(name="كشف", category="consultation", price=200,
                       commission_type="percent", commission_value=40,
                       is_active=True)
        nebul = Service(name="جلسة تنفس", category="procedure", price=150,
                        commission_type="percent", commission_value=50,
                        is_active=True)
        db.session.add_all([exam, nebul])

        child = Patient(patient_number="P1", full_name="طفل", gender="male",
                        date_of_birth=date(2025, 1, 1), is_active=True)
        db.session.add(child)
        db.session.flush()

        visit = Visit(patient_id=child.id, doctor_id=people["doc"].id,
                      visit_date=date.today())
        db.session.add(visit)

        # An optional (clinic-supplied) vaccine — the kind that costs money and
        # comes out of the clinic's own fridge.
        pcv = Vaccine(code="PCV", name_ar="المكورات الرئوية", is_mandatory=False)
        db.session.add(pcv)
        db.session.flush()
        brand = VaccineBrand(vaccine_id=pcv.id, name="Prevenar", price=900,
                             doses_per_vial=1)
        db.session.add(brand)
        db.session.flush()
        for number, months in ((1, 2), (2, 4), (3, 6)):
            db.session.add(VaccineBrandDose(brand_id=brand.id,
                                            dose_number=number,
                                            age_months=months))
        db.session.add(VaccineInventory(brand_id=brand.id, lot_number="LATE",
                                        qty_received=5, qty_used=0,
                                        expiry_date=date(2030, 1, 1)))
        db.session.add(VaccineInventory(brand_id=brand.id, lot_number="SOON",
                                        qty_received=5, qty_used=0,
                                        expiry_date=date(2027, 1, 1)))

        # A government vaccine: free, and never drawn from clinic stock.
        opv = Vaccine(code="OPV", name_ar="شلل الأطفال", is_mandatory=True)
        db.session.add(opv)
        db.session.flush()
        gov_brand = VaccineBrand(vaccine_id=opv.id, name="OPV", price=0)
        db.session.add(gov_brand)
        db.session.flush()
        db.session.add(VaccineBrandDose(brand_id=gov_brand.id, dose_number=1,
                                        age_months=2))
        db.session.add(VaccineInventory(brand_id=gov_brand.id, lot_number="GOV",
                                        qty_received=5, qty_used=0,
                                        expiry_date=date(2030, 1, 1)))
        db.session.commit()

        ids = {"exam": exam.id, "nebul": nebul.id, "child": child.id,
               "visit": visit.id, "pcv": pcv.id, "brand": brand.id,
               "opv": opv.id, "gov_brand": gov_brand.id,
               "doctor": people["doc"].id, "admin": people["boss"].id,
               "desk": people["desk"].id, "accountant": people["acct"].id}

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    yield {"app": app, "db": db, "ids": ids, "sign_in": sign_in}
