"""Has anybody in accounts been through this bill — «تدقيق وتصديق الفاتورة».

> «فواتير الداخلي والعمليات بتبقى محتاجة مراجعة من الحسابات للتدقيق وتصديق
> الفاتورة، علشان المنصرف على المريض مع التمريض»

A clinic bill is a receipt for an afternoon and one person wrote all of it. A
stay's bill is a fortnight assembled by five different hands — nights from the
bed, doses from the round, tests from the bench, a theatre from the list, and
the consumables a nurse charged at the bedside — and not one of them ever sees
the whole. **That is what there is to audit**, and it is why a hospital has
this step and a single-doctor clinic does not.

What this file pins:

* **It is not a payment state.** `status` says whether the money arrived; this
  says whether anybody checked what is on the bill, and the two move
  independently in both directions.
* **It never stands between a family and the till.** Collection is not gated —
  a desk that cannot take money because a bill is waiting on an audit is a
  desk that raises a second bill. What it gates is the tax invoice: the
  document that leaves the building with the hospital's name on it.
* **A day case is an operation too.** Reading only `admission_id` would have
  sent exactly those bills out unaudited, and they are not the small ones.
* **And off is the default**, so a clinic running this today sees no state, no
  queue, and no gate.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hospital():
    """A child, an outpatient bill, a stay and its bill, and an admin."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Invoice, Patient, Setting, User
        from app.models.admission import Admission
        from app.utils.clock import local_today

        Setting.set("mod_enabled:finance", "1")
        people = {}
        for username, name, role in (("boss", "المدير", "admin"),
                                     ("acct", "المحاسب", "accountant"),
                                     ("desk", "الاستقبال", "reception")):
            user = User(username=username, full_name=name, role=role,
                        is_active=True)
            user.set_password("secret")
            db.session.add(user)
            people[username] = user
        db.session.flush()
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      is_active=True, date_of_birth=local_today())
        db.session.add(kid)
        db.session.flush()
        stay = Admission(patient_id=kid.id, admitted_at=local_today())
        db.session.add(stay)
        db.session.flush()
        clinic_bill = Invoice(invoice_number="INV-OUT", patient_id=kid.id,
                              invoice_date=local_today())
        stay_bill = Invoice(invoice_number="INV-IN", patient_id=kid.id,
                            admission_id=stay.id, invoice_date=local_today())
        db.session.add_all([clinic_bill, stay_bill])
        db.session.commit()
        ids = {k: v.id for k, v in people.items()}
        ids.update({"kid": kid.id, "stay": stay.id,
                    "clinic_bill": clinic_bill.id, "stay_bill": stay_bill.id})

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    def policy(value):
        from app.models import Setting

        with app.app_context():
            Setting.set("invoice_signoff", value)
            db.session.commit()

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in,
            "policy": policy}


def _bill(hospital, key="stay_bill"):
    from app.models import Invoice

    hospital["db"].session.expire_all()
    return hospital["db"].session.get(Invoice, hospital["ids"][key])


# ------------------------------------------- a clinic sees none of this ----
def test_a_clinic_that_asks_for_no_review_has_none(hospital):
    """**The promise to every clinic already running this.** No state, no
    queue, no gate — and a bill that was final yesterday is final today."""
    from app.utils import invoice_signoff as rv

    with hospital["app"].app_context():
        assert rv.policy() == ""
        assert rv.needs_review(_bill(hospital)) is False
        assert rv.signed_off(_bill(hospital)) is True
        assert rv.waiting() == []


def test_a_word_that_is_not_a_policy_is_no_policy(hospital):
    from app.utils import invoice_signoff as rv

    hospital["policy"]("sometimes")
    with hospital["app"].app_context():
        assert rv.policy() == ""
        assert rv.needs_review(_bill(hospital)) is False


# ---------------------------------------------- which bills get audited ----
def test_the_stays_bill_does_and_the_afternoons_does_not(hospital):
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        assert rv.needs_review(_bill(hospital, "stay_bill")) is True
        assert rv.needs_review(_bill(hospital, "clinic_bill")) is False


def test_a_centre_can_ask_for_every_bill(hospital):
    from app.utils import invoice_signoff as rv

    hospital["policy"]("all")
    with hospital["app"].app_context():
        assert rv.needs_review(_bill(hospital, "clinic_bill")) is True


def test_a_day_case_is_an_operation_too(hospital):
    """**No stay behind it, and still an operation somebody has to account
    for** — the room, the anaesthetist, the implants. Reading only
    `admission_id` would have sent exactly these out unaudited, and they are
    not the small ones."""
    from app.models.invoice import InvoiceItem
    from app.models.theatre import Operation, Theatre
    from app.utils import invoice_signoff as rv
    from app.utils.clock import local_today

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        bill = _bill(hospital, "clinic_bill")
        item = InvoiceItem(invoice_id=bill.id, description="استئصال",
                           unit_price=3000, quantity=1)
        room = Theatre(name="غرفة ١")
        hospital["db"].session.add_all([item, room])
        hospital["db"].session.flush()
        hospital["db"].session.add(Operation(
            patient_id=hospital["ids"]["kid"], theatre_id=room.id,
            procedure="استئصال", on_date=local_today(),
            invoice_item_id=item.id))
        hospital["db"].session.commit()

        assert rv.needs_review(_bill(hospital, "clinic_bill")) is True


def test_nothing_is_claimed_about_a_bill_that_is_not_there(hospital):
    from app.utils import invoice_signoff as rv

    hospital["policy"]("all")
    with hospital["app"].app_context():
        assert rv.needs_review(None) is False
        assert rv.state(None) == "draft"
        assert rv.carries_theatre(None) is False


# ------------------------------------------------- the three movements -----
def test_a_bill_nobody_has_touched_reads_as_draft(hospital):
    """NULL is «draft», which is what every invoice already raised carries."""
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        row = _bill(hospital)
        assert row.review_state is None
        assert rv.state(row) == "draft"
        assert rv.signed_off(row) is False


def test_the_ward_sends_it_and_accounts_sign_it(hospital):
    from app.models import User
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        boss = hospital["db"].session.get(User, hospital["ids"]["acct"])
        row = _bill(hospital)

        rv.submit(row, user=boss)
        assert rv.state(row) == "submitted"
        assert rv.signed_off(row) is False

        rv.approve(row, user=boss)
        assert rv.state(row) == "approved"
        assert rv.signed_off(row) is True
        assert row.review_by == boss.id
        assert row.review_at is not None


def test_a_query_without_a_sentence_is_refused(hospital):
    """«مرفوضة» is not a finding anybody on the ward can act on. The line they
    are asking about is the only part of this a coordinator can do anything
    with — the pharmacist's query on a prescription is refused for the same
    reason."""
    from app.models import User
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        boss = hospital["db"].session.get(User, hospital["ids"]["acct"])
        row = _bill(hospital)

        assert rv.query(row, "", user=boss) is None
        assert rv.query(row, "   ", user=boss) is None
        assert rv.state(row) == "draft"

        assert rv.query(row, "بند المستلزمات مكرر", user=boss) is not None
        assert rv.state(row) == "queried"
        assert row.review_note == "بند المستلزمات مكرر"


def test_submitting_does_not_unsign_a_bill_accounts_already_signed(hospital):
    """Somebody pressing «تم» on a signed bill would otherwise quietly take
    the sign-off off it."""
    from app.models import User
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        boss = hospital["db"].session.get(User, hospital["ids"]["acct"])
        row = _bill(hospital)
        rv.approve(row, user=boss)

        rv.submit(row, user=boss)

        assert rv.state(row) == "approved"


def test_a_bill_nobody_audits_cannot_be_submitted_or_signed(hospital):
    from app.models import User
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        boss = hospital["db"].session.get(User, hospital["ids"]["acct"])
        clinic_bill = _bill(hospital, "clinic_bill")

        assert rv.submit(clinic_bill, user=boss) is None
        assert rv.approve(clinic_bill, user=boss) is None
        assert rv.query(clinic_bill, "حاجة", user=boss) is None


# --------------------------------------- what it gates, and what it does not
def test_the_tax_invoice_waits_for_the_sign_off(hospital):
    """**This is the step the audit is for.** The tax invoice is the document
    that leaves the building with the hospital's name on it."""
    from app.models import User
    from app.utils import einvoice as eta
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        boss = hospital["db"].session.get(User, hospital["ids"]["acct"])
        row = _bill(hospital)

        assert eta.queue_for_invoice(row, user_id=boss.id) is None
        assert row.is_tax is False

        rv.approve(row, user=boss)
        assert eta.queue_for_invoice(row, user_id=boss.id) is not None
        assert row.is_tax is True


def test_and_a_clinic_with_no_policy_is_never_stopped(hospital):
    from app.utils import einvoice as eta

    with hospital["app"].app_context():
        row = _bill(hospital)
        assert eta.queue_for_invoice(row, user_id=None) is not None


def test_collection_is_never_gated(hospital):
    """A desk that cannot take money because a bill is waiting on an audit is
    a desk that raises a second bill. **Payment and audit are two facts** and
    the bill carries both without either touching the other."""
    from app.models.invoice import Payment
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        row = _bill(hospital)
        hospital["db"].session.add(Payment(invoice_id=row.id, amount=100,
                                           method="cash"))
        hospital["db"].session.commit()
        again = _bill(hospital)

        assert again.paid == 100
        assert rv.state(again) == "draft"


def test_the_audit_is_not_a_fifth_payment_status(hospital):
    """`status` answers «has the money arrived»; the review answers «has
    anybody checked what is on it». One column holding both could say
    neither."""
    from app.models.invoice import INVOICE_STATUSES

    for word in ("submitted", "approved", "queried"):
        assert word not in INVOICE_STATUSES


# ------------------------------------------------------------ the queue ----
def test_the_queue_holds_what_is_still_waiting(hospital):
    from app.models import User
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        boss = hospital["db"].session.get(User, hospital["ids"]["acct"])

        assert [i.invoice_number for i in rv.waiting()] == ["INV-IN"]

        rv.approve(_bill(hospital), user=boss)
        hospital["db"].session.commit()

        assert rv.waiting() == []


def test_a_queried_bill_is_still_waiting(hospital):
    """It went back to the ward; it did not go away."""
    from app.models import User
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        boss = hospital["db"].session.get(User, hospital["ids"]["acct"])
        rv.query(_bill(hospital), "بند مكرر", user=boss)
        hospital["db"].session.commit()

        assert [i.invoice_number for i in rv.waiting()] == ["INV-IN"]


def test_the_queue_is_empty_when_nobody_asked_for_one(hospital):
    from app.utils import invoice_signoff as rv

    with hospital["app"].app_context():
        assert rv.waiting() == []


# ------------------------------------------------------------ the screens --
def test_the_card_is_absent_from_a_bill_nobody_audits(hospital):
    """A card that appears everywhere saying «nothing to do» is a card people
    stop reading."""
    hospital["policy"]("stay")
    page = hospital["sign_in"]().get(
        "/finance/invoices/%s" % hospital["ids"]["clinic_bill"]
    ).get_data(as_text=True)

    assert "data-invoice-review" not in page


def test_and_present_on_one_that_is(hospital):
    hospital["policy"]("stay")
    page = hospital["sign_in"]().get(
        "/finance/invoices/%s" % hospital["ids"]["stay_bill"]
    ).get_data(as_text=True)

    assert "data-invoice-review" in page
    assert 'data-review-state="draft"' in page


def test_the_accountant_is_offered_the_sign_off(hospital):
    """Signing off is accounts'; saying «the bill is complete» is anybody's."""
    hospital["policy"]("stay")
    page = hospital["sign_in"]("acct").get(
        "/finance/invoices/%s" % hospital["ids"]["stay_bill"]
    ).get_data(as_text=True)

    assert "data-review-submit" in page
    assert "data-review-approve" in page


def test_the_accountant_is_the_one_who_signs(hospital):
    """**The role the whole thing is for.** The first version of this asked
    for `is_admin`, which in a hospital locks «مراجعة من الحسابات» behind the
    one account that is not in accounts. A mutation found it: the test that
    was supposed to prove reception could not sign was really proving
    reception cannot reach the finance module at all."""
    from app.models import User
    from app.utils import invoice_signoff as rv

    with hospital["app"].app_context():
        people = {k: hospital["db"].session.get(User, hospital["ids"][k])
                  for k in ("boss", "acct", "desk")}

        assert rv.may_sign_off(people["acct"]) is True
        assert rv.may_sign_off(people["boss"]) is True
        assert rv.may_sign_off(people["desk"]) is False
        assert rv.may_sign_off(None) is False


def test_the_util_refuses_a_sign_off_from_outside_accounts(hospital):
    """A sign-off is a name against a claim that somebody checked the bill,
    and a name that did not is worse than none."""
    from app.models import User
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    with hospital["app"].app_context():
        desk = hospital["db"].session.get(User, hospital["ids"]["desk"])
        row = _bill(hospital)

        assert rv.approve(row, user=desk) is None
        assert rv.query(row, "بند مكرر", user=desk) is None
        assert rv.state(row) == "draft"


def test_and_cannot_sign_one_by_posting_to_the_route(hospital):
    """**A guard from one side is half a rule**, and the missing half is the
    one somebody gets through. Posted by an account that *does* reach the
    finance module — reception never gets that far, so testing with them
    proved the module gate and nothing about this one."""
    from app.utils import invoice_signoff as rv

    hospital["policy"]("stay")
    hospital["sign_in"]("acct").post(
        "/finance/invoices/%s/review" % hospital["ids"]["stay_bill"],
        data={"action": "approve"}, follow_redirects=True)

    with hospital["app"].app_context():
        assert rv.state(_bill(hospital)) == "approved"


def test_the_queue_screen_says_when_nobody_asked_for_one(hospital):
    """An empty table reads as «nothing to do today» when the truth is
    «nobody turned this on»."""
    page = hospital["sign_in"]().get(
        "/finance/invoice-review").get_data(as_text=True)

    assert "data-review-off" in page


def test_the_queue_screen_lists_the_waiting_bill(hospital):
    hospital["policy"]("stay")
    page = hospital["sign_in"]().get(
        "/finance/invoice-review").get_data(as_text=True)

    assert "data-review-row" in page
    assert "INV-IN" in page
    assert "INV-OUT" not in page


def test_the_column_is_in_the_upgrade_list():
    from app.utils.schema import ADDITIONS

    for column in ("review_state", "review_by", "review_at", "review_note"):
        assert any(t == "invoices" and c == column for t, c, _ in ADDITIONS), column


def test_todays_finance_roles_all_sign_and_the_route_guard_is_the_next_one(
        hospital):
    """**Why a mutation can remove the route's role check and nothing fails.**

    The finance module is reachable by `admin` and `accountant`, and those are
    exactly the two roles that may sign off — so today every account that can
    open the screen can also sign, and the check in the route never fires. It
    is kept because that coincidence is one settings change away from ending,
    and on a money path the cheap guard stays.

    This test is the alarm for that day: add a role that reaches finance
    without signing rights and it fails here, which is the moment the route's
    check starts doing work and wants a test of its own.
    """
    from app.models.permissions import ROLES, role_modules
    from app.utils import invoice_signoff as rv

    reach = {r for r in ROLES if "finance" in (role_modules(r) or [])}

    assert reach == set(rv.SIGNS_OFF)


def test_the_hub_has_a_door_only_where_the_queue_can_hold_something(hospital):
    """The lesson from the consent wording editor, which was built complete
    and had no way in from anywhere it was used — and from the three finance
    screens before it that had the same fault. Turned inside out here: a card
    leading to a queue that can never hold anything is the same waste."""
    off = hospital["sign_in"]().get("/finance/").get_data(as_text=True)
    assert "data-review-hub" not in off

    hospital["policy"]("stay")
    on = hospital["sign_in"]().get("/finance/").get_data(as_text=True)
    assert "data-review-hub" in on
