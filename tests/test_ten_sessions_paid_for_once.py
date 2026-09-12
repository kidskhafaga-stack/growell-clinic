"""Selling a course of sessions, and spending it one visit at a time.

Asked for in one line — *«خلي الاثنين متاحين باقة وجلسة بجلسة»* — and the
word that matters is **both**. A psychology course is the case: some families
pay for ten up front at a better rate, some pay each time they come, and the
same service has to sell either way on the same screen without becoming two
services with two prices and two commissions to keep in step.

What these tests hold is the part that is easy to get wrong quietly:

**The money moves once.** The package is an ordinary invoice line at an
ordinary price. Nothing here holds money the accounts cannot see, and nothing
here invents a second way for money to arrive.

**And then it must not move again.** A family that paid in March and pays
again in April is the vaccine double-charge wearing different clothes — it
looks exactly like an ordinary charge, and nobody spots it but the parent.
So a covered session comes to the desk at zero, and the balance goes down by
exactly one.

**A gone balance is not one fact.** Spent, expired and cancelled read
differently to the person at the desk and must never be one empty column
standing for all three.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    """A clinic that runs psychology sessions, and a child booked into them."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Service, ServicePackage, Setting, User

        Setting.set("facility_capabilities",
                    '["general_consultation", "followup"]')
        # The cash-drawer shift gate is somebody else's rule and somebody
        # else's tests; switched off so these read the money, not the till.
        Setting.set("require_shift_to_collect", "0")
        boss = User(username="boss", full_name="مدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        doctor = User(username="doc", full_name="د. منى", role="doctor",
                      is_active=True)
        doctor.set_password("secret")
        db.session.add_all([boss, doctor])
        db.session.flush()

        session_svc = Service(name="جلسة نفسية", code="PSY-1", price=300,
                              category="consultation", is_active=True)
        other_svc = Service(name="تخاطب", code="SPEECH-1", price=250,
                            category="consultation", is_active=True)
        db.session.add_all([session_svc, other_svc])
        db.session.flush()

        offer = ServicePackage(service_id=session_svc.id,
                               name_ar="باقة ١٠ جلسات", sessions=10,
                               price=2500, is_active=True)
        db.session.add(offer)

        child = Patient(full_name="سلمى", patient_number="P-1",
                        date_of_birth=date(2018, 5, 1), gender="female",
                        is_active=True)
        db.session.add(child)
        db.session.commit()
        ids = {"child": child.id, "doctor": doctor.id, "boss": boss.id,
               "session_svc": session_svc.id, "other_svc": other_svc.id,
               "offer": offer.id}

    def sign_in():
        client = app.test_client()
        client.post("/login", data={"username": "boss", "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "sign_in": sign_in, "ids": ids}


def _sell(clinic, offer_id=None, price="2500"):
    """Reception puts the course on the bill and takes the money for it."""
    ids = clinic["ids"]
    return clinic["sign_in"]().post(f"/finance/collect/{ids['child']}", data={
        "doctor_id": ids["doctor"], "discount_id": "none",
        "line_service_id": [str(ids["session_svc"])],
        "line_desc": ["باقة ١٠ جلسات"], "line_price": [price],
        "line_qty": ["1"], "line_no_commission": ["0"],
        "line_brand_id": [""], "line_dose_id": [""], "line_dose_number": [""],
        "line_vs_id": [""], "line_op_id": [""], "line_test_id": [""],
        "line_rx_line_id": [""], "line_pkg_id": [""],
        "line_pkg_sale_id": [str(offer_id or ids["offer"])],
        "amount": [price], "method": ["cash"],
    }, follow_redirects=True)


def _draw(clinic, balance_id, price="0", desc="جلسة من الباقة",
          service_id=None, qty="1"):
    """A later visit: the session is on the bill, paid for months ago."""
    ids = clinic["ids"]
    return clinic["sign_in"]().post(f"/finance/collect/{ids['child']}", data={
        "doctor_id": ids["doctor"], "discount_id": "none",
        "line_service_id": [str(service_id or ids["session_svc"])],
        "line_desc": [desc], "line_price": [price], "line_qty": [qty],
        "line_no_commission": ["1"],
        "line_brand_id": [""], "line_dose_id": [""], "line_dose_number": [""],
        "line_vs_id": [""], "line_op_id": [""], "line_test_id": [""],
        "line_rx_line_id": [""], "line_pkg_id": [str(balance_id)],
        "line_pkg_sale_id": [""],
    }, follow_redirects=True)


def _balances(clinic):
    from app.models import PatientPackage

    return (PatientPackage.query
            .filter_by(patient_id=clinic["ids"]["child"])
            .order_by(PatientPackage.id).all())


# ------------------------------------------------------- selling a course --
def test_a_sold_package_is_money_on_an_ordinary_invoice(clinic):
    """**The money moves once, through the till everyone already uses.**

    A package that held its own money would be a second cash path — a balance
    the accounts cannot see, reconciled by nobody. The line is an ordinary
    line, and the balance exists because that line does.
    """
    from app.models import Invoice

    _sell(clinic)
    with clinic["app"].app_context():
        invoice = Invoice.query.one()
        assert invoice.total == 2500
        assert invoice.paid == 2500

        balance = _balances(clinic)[0]
        assert balance.sessions_total == 10
        assert balance.remaining == 10
        # …and it points at the line that paid for it. Without this link,
        # "was this course actually paid for" has no answer but somebody's word.
        assert balance.invoice_id == invoice.id
        assert balance.invoice_item_id == invoice.items[0].id


def test_the_offer_can_be_renamed_without_rewriting_what_a_family_bought(clinic):
    """The sale copies the name, the count and the price. A clinic reworking
    its price list must not thereby change a course somebody already paid for.
    """
    from app.models import ServicePackage

    _sell(clinic)
    with clinic["app"].app_context():
        offer = clinic["db"].session.get(ServicePackage,
                                         clinic["ids"]["offer"])
        offer.name_ar = "باقة ٦ جلسات"
        offer.sessions = 6
        offer.price = 1800
        clinic["db"].session.commit()

        balance = _balances(clinic)[0]
        assert balance.sessions_total == 10
        assert balance.price_paid == 2500
        assert "١٠" in balance.display_name("ar")


def test_a_posted_package_id_nobody_offers_sells_nothing(clinic):
    """A posted id is a number anybody can type, and this one creates a
    balance. Resolved against the real catalogue or not at all."""
    _sell(clinic, offer_id=9999)
    with clinic["app"].app_context():
        assert _balances(clinic) == []


def test_a_package_of_something_this_clinic_cannot_do_is_not_offered(clinic):
    """The same rule the price list itself follows: a package for a service
    nobody here performs is a promise somebody has to ring back and unmake.

    ``SVC-DENT-CLEAN`` is a code **this program shipped** for a capability
    nobody switched on — which is the only kind of service the filter can
    honestly judge. A clinic's own row is bound to nothing, so a package of
    it stays on the list: no shipped code means no opinion.
    """
    from app.models import Service, ServicePackage
    from app.utils import packages as pkgs

    with clinic["app"].app_context():
        dental = Service(name="تنظيف أسنان", code="SVC-DENT-CLEAN", price=600,
                         category="procedure", is_active=True)
        ours = Service(name="حاجة من عندنا", code="OURS-1", price=200,
                       category="procedure", is_active=True)
        clinic["db"].session.add_all([dental, ours])
        clinic["db"].session.flush()
        clinic["db"].session.add_all([
            ServicePackage(service_id=dental.id, sessions=8, price=4000,
                           is_active=True),
            ServicePackage(service_id=ours.id, sessions=8, price=1400,
                           is_active=True)])
        clinic["db"].session.commit()

        offered = {row.service_id for row in pkgs.sellable()}
        assert dental.id not in offered
        assert ours.id in offered          # never asked != does nothing
        assert clinic["ids"]["session_svc"] in offered


# ----------------------------------------------------- spending a session --
def test_a_covered_session_comes_to_the_desk_at_nothing(clinic):
    """**The double charge this exists to stop.** The family paid in March;
    the April visit must not look like an ordinary 300-pound one."""
    _sell(clinic)
    with clinic["app"].app_context():
        balance_id = _balances(clinic)[0].id

    screen = clinic["sign_in"]().get(
        f"/finance/collect/{clinic['ids']['child']}")
    assert screen.status_code == 200

    from app import create_app  # noqa: F401  (app already built)

    with clinic["app"].app_context():
        from app.blueprints.finance.routes import _cover_with_packages

        lines = _cover_with_packages(clinic["ids"]["child"], [{
            "service_id": clinic["ids"]["session_svc"],
            "description": "جلسة نفسية", "unit_price": 300, "quantity": 1,
        }], "ar")
        assert lines[0]["unit_price"] == 0
        assert lines[0]["pkg_id"] == balance_id
        # And it says which session it was, because that is the question the
        # line is read for six weeks later.
        assert "1" in lines[0]["description"] and "10" in lines[0]["description"]
        # The doctor's share was paid when the course was sold. A *fixed*
        # commission does not care that this line is zero.
        assert lines[0]["no_commission"] == "1"


def test_the_zero_line_survives_and_the_balance_goes_down_by_one(clinic):
    """A zero line is normally an empty row and gets dropped. This one is a
    real charge that happens to cost nothing, and dropping it would lose the
    only record the family has of which session that was."""
    from app.models import Invoice

    _sell(clinic)
    with clinic["app"].app_context():
        balance_id = _balances(clinic)[0].id

    _draw(clinic, balance_id)
    with clinic["app"].app_context():
        balance = _balances(clinic)[0]
        assert balance.remaining == 9
        assert balance.used == 1

        # One invoice per visit-day is this clinic's rule, so the draw lands
        # on the same bill the course was sold on when both happen today.
        later = Invoice.query.order_by(Invoice.id.desc()).first()
        assert later.items[-1].unit_price == 0
        assert later.items[-1].description == "جلسة من الباقة"
        # The session points back at the line that recorded it.
        assert balance.uses[0].invoice_item_id == later.items[-1].id


def test_an_empty_row_is_still_an_empty_row(clinic):
    """The zero test is relaxed for a covered line and for nothing else — a
    clinic in use must not start keeping the blank rows it always dropped."""
    from app.models import Invoice

    ids = clinic["ids"]
    clinic["sign_in"]().post(f"/finance/collect/{ids['child']}", data={
        "doctor_id": ids["doctor"], "discount_id": "none",
        "line_service_id": ["", ""], "line_desc": ["كشف", ""],
        "line_price": ["0", "0"], "line_qty": ["1", "1"],
        "line_no_commission": ["0", "0"], "line_brand_id": ["", ""],
        "line_dose_id": ["", ""], "line_dose_number": ["", ""],
        "line_vs_id": ["", ""], "line_op_id": ["", ""],
        "line_test_id": ["", ""], "line_rx_line_id": ["", ""],
        "line_pkg_id": ["", ""], "line_pkg_sale_id": ["", ""],
    }, follow_redirects=True)
    with clinic["app"].app_context():
        assert Invoice.query.count() == 0


def test_a_price_typed_onto_a_covered_line_is_not_collected(clinic):
    """Taking a session *and* the money for it is the family paying twice for
    the one thing they prepaid."""
    from app.models import Invoice

    _sell(clinic)
    with clinic["app"].app_context():
        balance_id = _balances(clinic)[0].id

    _draw(clinic, balance_id, price="300")
    with clinic["app"].app_context():
        later = Invoice.query.order_by(Invoice.id.desc()).first()
        assert later.items[-1].unit_price == 0
        # The bill is still only what the course cost — the session added
        # nothing to it.
        assert later.total == 2500
        assert _balances(clinic)[0].remaining == 9


def test_a_balance_covers_its_own_service_and_no_other(clinic):
    """Ten psychology sessions do not pay for a speech-therapy appointment,
    however plausible both look on a bill."""
    from app.utils import packages as pkgs

    _sell(clinic)
    with clinic["app"].app_context():
        assert pkgs.covering(clinic["ids"]["child"],
                             clinic["ids"]["session_svc"]) is not None
        assert pkgs.covering(clinic["ids"]["child"],
                             clinic["ids"]["other_svc"]) is None


def test_two_sessions_on_one_bill_cannot_both_take_the_last_one(clinic):
    """The case a per-line check misses: the balance has one left and the
    screen carries two lines claiming it."""
    from app.blueprints.finance.routes import _cover_with_packages
    from app.models import PatientPackage

    _sell(clinic)
    with clinic["app"].app_context():
        balance = _balances(clinic)[0]
        balance.sessions_total = 1
        clinic["db"].session.commit()

        lines = _cover_with_packages(clinic["ids"]["child"], [
            {"service_id": clinic["ids"]["session_svc"],
             "description": "جلسة", "unit_price": 300, "quantity": 1},
            {"service_id": clinic["ids"]["session_svc"],
             "description": "جلسة", "unit_price": 300, "quantity": 1},
        ], "ar")
        assert lines[0]["unit_price"] == 0
        # The second is an ordinary paid session: there was one left, not two.
        assert lines[1]["unit_price"] == 300
        assert "pkg_id" not in lines[1]
        assert PatientPackage.query.count() == 1


def test_a_session_the_balance_cannot_cover_is_charged_for(clinic):
    """**Two sessions on one submitted form, and one left on the course.**

    The screen's own arithmetic runs before the form is drawn, so it never
    produces this — but a cashier who adds a second session by hand does, and
    then the two halves disagree: the balance says one, the form says two.

    Refusing the second draw is only half an answer. The session still
    happened, so the line has to be *charged*, not quietly dropped — dropping
    it is the clinic working for nothing and nobody noticing, which is the
    same failure as the double charge with the sign reversed.
    """
    from app.models import Invoice

    ids = clinic["ids"]
    _sell(clinic)
    with clinic["app"].app_context():
        balance = _balances(clinic)[0]
        balance.sessions_total = 1
        clinic["db"].session.commit()
        balance_id = balance.id

    clinic["sign_in"]().post(f"/finance/collect/{ids['child']}", data={
        "doctor_id": ids["doctor"], "discount_id": "none",
        "line_service_id": [str(ids["session_svc"])] * 2,
        "line_desc": ["جلسة من الباقة", "جلسة تانية"],
        "line_price": ["0", "300"], "line_qty": ["1", "1"],
        "line_no_commission": ["1", "0"], "line_brand_id": ["", ""],
        "line_dose_id": ["", ""], "line_dose_number": ["", ""],
        "line_vs_id": ["", ""], "line_op_id": ["", ""],
        "line_test_id": ["", ""], "line_rx_line_id": ["", ""],
        "line_pkg_id": [str(balance_id)] * 2, "line_pkg_sale_id": ["", ""],
    }, follow_redirects=True)

    with clinic["app"].app_context():
        balance = _balances(clinic)[0]
        assert balance.used == 1              # one drawn, not two
        bill = Invoice.query.order_by(Invoice.id.desc()).first()
        charged = [it for it in bill.items if it.description == "جلسة تانية"]
        assert len(charged) == 1, "the second session vanished off the bill"
        assert charged[0].unit_price == 300


def test_the_balance_cannot_go_to_eleven_of_ten(clinic):
    """The server decides, not the form: a posted package id on a spent
    course draws nothing and charges nothing."""
    from app.models import Invoice
    from app.utils import packages as pkgs

    _sell(clinic)
    with clinic["app"].app_context():
        balance = _balances(clinic)[0]
        balance.sessions_total = 1
        clinic["db"].session.commit()
        balance_id = balance.id

    _draw(clinic, balance_id)
    _draw(clinic, balance_id)
    with clinic["app"].app_context():
        balance = _balances(clinic)[0]
        assert balance.used == 1
        assert balance.remaining == 0
        # …and the second attempt charged nothing and recorded nothing: a
        # zero line no live balance covers is an empty row again.
        bill = Invoice.query.order_by(Invoice.id.desc()).first()
        assert len(bill.items) == 2            # the course, and one session
        assert pkgs.draw(balance) is None


# ----------------------------------------------- the three ways it is gone --
def test_spent_expired_and_cancelled_are_three_different_facts(clinic):
    """One empty column standing for all three is how a refunded course and a
    finished one come to read the same on the screen that has to tell a
    parent which happened."""
    from app.utils import packages as pkgs

    _sell(clinic)
    with clinic["app"].app_context():
        balance = _balances(clinic)[0]
        assert balance.state() == "open"

        balance.expires_on = date.today() - timedelta(days=1)
        assert balance.state() == "expired"
        assert not balance.is_open()

        balance.expires_on = None
        balance.sessions_total = 0
        assert balance.state() == "spent"

        balance.sessions_total = 10
        pkgs.cancel(balance, reason="رجعنا الفلوس")
        assert balance.state() == "cancelled"
        assert balance.cancel_reason == "رجعنا الفلوس"
        assert not balance.is_open()


def test_a_course_with_no_window_never_expires(clinic):
    """Blank is "no window" and stays NULL. Zero would read as "expires the
    day it is sold" — a real thing to say, and not what blank means."""
    _sell(clinic)
    with clinic["app"].app_context():
        balance = _balances(clinic)[0]
        assert balance.expires_on is None
        assert not balance.expired(date.today() + timedelta(days=3650))


def test_a_window_is_counted_from_the_day_it_was_sold(clinic):
    from app.models import ServicePackage
    from app.utils import packages as pkgs

    with clinic["app"].app_context():
        offer = clinic["db"].session.get(ServicePackage,
                                         clinic["ids"]["offer"])
        offer.valid_days = 90
        clinic["db"].session.commit()

    _sell(clinic)
    with clinic["app"].app_context():
        balance = _balances(clinic)[0]
        assert balance.expires_on == balance.sold_on + timedelta(days=90)
        assert pkgs.covering(clinic["ids"]["child"],
                             clinic["ids"]["session_svc"],
                             on=balance.expires_on) is not None
        assert pkgs.covering(clinic["ids"]["child"],
                             clinic["ids"]["session_svc"],
                             on=balance.expires_on + timedelta(days=1)) is None


def test_the_one_about_to_be_lost_is_spent_first(clinic):
    """Two open courses, one with a window closing. Spending the endless one
    first quietly wastes the other."""
    from datetime import timedelta as td

    from app.utils import packages as pkgs

    _sell(clinic)      # no window
    _sell(clinic)      # a second, which we give a window
    with clinic["app"].app_context():
        first, second = _balances(clinic)
        second.expires_on = date.today() + td(days=14)
        clinic["db"].session.commit()

        chosen = pkgs.covering(clinic["ids"]["child"],
                               clinic["ids"]["session_svc"])
        assert chosen.id == second.id


# --------------------------------------------------------------- the screens --
def test_the_desk_sees_the_balance_before_it_quotes_a_price(clinic):
    _sell(clinic)
    page = clinic["sign_in"]().get(
        f"/finance/collect/{clinic['ids']['child']}").get_data(as_text=True)
    assert "باقة ١٠ جلسات" in page


def test_the_catalogue_screen_draws_and_takes_a_new_offer(clinic):
    from app.models import ServicePackage

    client = clinic["sign_in"]()
    assert client.get("/finance/services").status_code == 200
    client.post("/finance/services/packages/new", data={
        "service_id": clinic["ids"]["other_svc"], "sessions": "8",
        "price": "1600", "valid_days": "", "name": "باقة تخاطب",
    }, follow_redirects=True)
    with clinic["app"].app_context():
        row = ServicePackage.query.filter_by(name_ar="باقة تخاطب").one()
        assert row.sessions == 8 and row.price == 1600
        assert row.valid_days is None
        assert row.per_session == 200


def test_a_package_of_one_is_the_per_session_price_wearing_a_hat(clinic):
    from app.models import ServicePackage

    client = clinic["sign_in"]()
    client.post("/finance/services/packages/new", data={
        "service_id": clinic["ids"]["other_svc"], "sessions": "1",
        "price": "250",
    }, follow_redirects=True)
    with clinic["app"].app_context():
        assert ServicePackage.query.filter_by(
            service_id=clinic["ids"]["other_svc"]).count() == 0


def test_an_offer_a_family_bought_is_switched_off_not_deleted(clinic):
    """The balance points at it, and a course with no offer behind it is a
    thing a family paid for that nothing can describe."""
    from app.models import ServicePackage

    _sell(clinic)
    client = clinic["sign_in"]()
    client.post(f"/finance/services/packages/{clinic['ids']['offer']}/delete",
                follow_redirects=True)
    with clinic["app"].app_context():
        row = clinic["db"].session.get(ServicePackage, clinic["ids"]["offer"])
        assert row is not None
        assert row.is_active is False
        assert _balances(clinic)[0].sessions_total == 10


def test_an_offer_nobody_bought_can_be_deleted(clinic):
    from app.models import ServicePackage

    client = clinic["sign_in"]()
    client.post(f"/finance/services/packages/{clinic['ids']['offer']}/delete",
                follow_redirects=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(ServicePackage,
                                        clinic["ids"]["offer"]) is None


def test_the_family_file_shows_what_is_left(clinic):
    _sell(clinic)
    with clinic["app"].app_context():
        balance_id = _balances(clinic)[0].id
    _draw(clinic, balance_id)

    page = clinic["sign_in"]().get(
        f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "9 / 10" in page or "9 / 10".replace(" ", "") in page.replace(" ", "")


def test_the_screens_draw_on_a_clinic_that_never_defined_one(clinic):
    """The whole feature is invisible to a clinic that wants nothing to do
    with it — which is most of them, on the day it ships."""
    from app.models import ServicePackage

    with clinic["app"].app_context():
        ServicePackage.query.delete()
        clinic["db"].session.commit()

    client = clinic["sign_in"]()
    assert client.get("/finance/services").status_code == 200
    assert client.get(f"/finance/collect/{clinic['ids']['child']}").status_code == 200
    assert client.get(f"/patients/{clinic['ids']['child']}").status_code == 200
