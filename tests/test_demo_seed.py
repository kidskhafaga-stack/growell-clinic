"""The demo data is a guest in a clinic that is already running.

``seed_demo`` is pressed on a live database, not an empty one: the catalogue
is there, the doctors are there, and — the thing this file is about — the
clinic may already have priced a doctor's service on the doctor's own screen.
That pairing is unique in the table, so the demo writing its own row for the
same doctor and the same service is not a duplicate that gets ignored, it is
an ``IntegrityError`` that takes the whole request down with a 500.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def app_ctx():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _doctor_and_service():
    """The two rows a real clinic has before anyone loads the demo."""
    from app.extensions import db
    from app.models import Service, User

    doc = User(username="real_doctor", full_name="د. أحمد", role="doctor",
               is_active=True)
    doc.set_password("secret")
    db.session.add(doc)
    exam = Service(name="كشف", category="consultation", price=200,
                   is_active=True)
    db.session.add(exam)
    db.session.flush()
    return doc, exam


def test_the_demo_loads_on_a_clinic_that_already_priced_its_doctor(app_ctx):
    """The crash this file exists for: a 500 on /settings/data/seed-demo."""
    from app.extensions import db
    from app.models.service import DoctorServiceCommission
    from app.utils.demo import seed_demo

    doc, exam = _doctor_and_service()
    db.session.add(DoctorServiceCommission(
        doctor_id=doc.id, service_id=exam.id, price_override=333,
        commission_type="fixed", commission_value=111))
    db.session.commit()

    result = seed_demo()

    assert not result.get("skipped"), "the demo refused to run at all"


def test_the_demo_does_not_overwrite_a_price_the_clinic_agreed(app_ctx):
    """Reusing the row is not enough — the clinic's number has to survive.

    480 / fixed 400 is what the demo would have written for this pairing. If
    any of those three numbers appears here, the demo edited a real agreement
    between a clinic and its doctor.
    """
    from app.extensions import db
    from app.models.service import DoctorServiceCommission
    from app.utils.demo import seed_demo

    doc, exam = _doctor_and_service()
    db.session.add(DoctorServiceCommission(
        doctor_id=doc.id, service_id=exam.id, price_override=333,
        commission_type="percent", commission_value=111))
    db.session.commit()

    seed_demo()

    rows = DoctorServiceCommission.query.filter_by(
        doctor_id=doc.id, service_id=exam.id).all()
    assert len(rows) == 1, "the pairing was written twice"
    assert rows[0].price_override == 333
    assert rows[0].commission_type == "percent"
    assert rows[0].commission_value == 111


def test_the_demo_still_shows_per_doctor_pricing_on_an_empty_clinic(app_ctx):
    """The guard must not cost the demo the thing it was seeding.

    Per-doctor pricing is one of the things the demo exists to demonstrate:
    two doctors, the same consultation, different money. Skipping rows that
    already exist must not turn into skipping rows that don't.
    """
    from app.extensions import db
    from app.models.service import DoctorServiceCommission
    from app.utils.demo import seed_demo

    _doctor_and_service()
    db.session.commit()

    seed_demo()

    rows = DoctorServiceCommission.query.all()
    assert len(rows) >= 4, "the demo stopped seeding per-doctor pricing"
    doctors = {r.doctor_id for r in rows}
    assert len(doctors) >= 2, "per-doctor pricing needs more than one doctor"
