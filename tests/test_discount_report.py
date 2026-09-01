"""What the clinic gave away, as opposed to what it offers.

The discounts screen lists the rules. This answers a different question, and
the one with money in it: *"مين خد خصم فعلاً، وبكام، في فترة"*. A clinic can
run four named discounts and have no idea that one of them costs more than
the other three together — or, more often, that most of what went out was not
a named discount at all. It was typed line by line at the till.

That split is the point. A rule the clinic decided on and a number somebody
entered by hand are the same money and completely different problems: one is
a pricing decision to review, the other is a conversation with a person.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the screens filter by.
#
# These built their world with `local_today()` while the report they check
# filters on `local_today()`, and the two disagree for the three hours a day
# when it is already tomorrow in Cairo and still today in UTC. The suite went
# green at 23:28 Cairo and red at 00:20, on the same commit, with nothing
# changed in between. conftest.py warns about exactly this at the top of the
# file.
from app.utils.clock import local_today  # noqa: E402


def _invoice(clinic, *, gross=200, discount=0, percent=False, rule=None,
             when=None, by=None, status="unpaid"):
    """One invoice with one line, discounted or not."""
    from app.models import Invoice, InvoiceItem

    db = clinic["db"]
    invoice = Invoice(patient_id=clinic["ids"]["child"],
                      invoice_number=f"INV-{Invoice.query.count() + 1:04d}",
                      invoice_date=when or local_today(), status=status,
                      discount_name=rule,
                      created_by=by or clinic["ids"]["admin"])
    db.session.add(invoice)
    db.session.flush()
    db.session.add(InvoiceItem(invoice_id=invoice.id, description="كشف",
                               unit_price=gross, quantity=1,
                               discount_value=discount,
                               discount_is_percent=percent))
    db.session.commit()
    return invoice


def _report(clinic, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return clinic["sign_in"]("boss").get(
        "/reports/discounts" + (f"?{query}" if query else "")).data.decode()


# ============================================== the totals ==================
def test_it_totals_what_was_actually_given(clinic):
    with clinic["app"].app_context():
        _invoice(clinic, gross=200, discount=50)
        _invoice(clinic, gross=300, discount=10, percent=True)   # 30
        _invoice(clinic, gross=100)                              # none

    page = _report(clinic)
    assert ">80.0<" in page or ">80<" in page, "the total is not 50 + 30"


def test_an_invoice_with_no_discount_is_not_listed(clinic):
    """A report that lists every invoice is the invoices screen."""
    with clinic["app"].app_context():
        _invoice(clinic, gross=100)

    assert _word("disc_none") in _report(clinic)


def test_a_cancelled_invoice_is_not_a_discount(clinic):
    """It was never given: the whole invoice was undone."""
    with clinic["app"].app_context():
        _invoice(clinic, gross=200, discount=50, status="cancelled")

    assert _word("disc_none") in _report(clinic)


# ============================================== the split ===================
def test_a_named_rule_is_totalled_under_its_name(clinic):
    with clinic["app"].app_context():
        _invoice(clinic, gross=200, discount=50, rule="خصم الإخوة")
        _invoice(clinic, gross=200, discount=20, rule="خصم الإخوة")

    page = _report(clinic)
    assert "خصم الإخوة" in page
    assert ">70.0<" in page or ">70<" in page


def test_a_discount_with_no_rule_is_called_what_it_is(clinic):
    """Typed at the counter. Lumping it in with the named rules hides the
    thing most worth seeing."""
    with clinic["app"].app_context():
        _invoice(clinic, gross=200, discount=50)      # no rule

    page = _report(clinic)
    assert _word("disc_by_hand") in page


def test_it_says_who_gave_it(clinic):
    """"ومين إداله" — a total by staff member is the conversation this report
    exists to start."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        desk = db.session.get(User, clinic["ids"]["desk"])
        name = desk.display_name("ar")
        _invoice(clinic, gross=200, discount=50, by=desk.id)

    assert name in _report(clinic)


# ============================================== context =====================
def test_the_share_of_billing_is_shown(clinic):
    """3,000 given away is a rounding error on 200,000 and a crisis on
    12,000. The number alone is not actionable."""
    with clinic["app"].app_context():
        _invoice(clinic, gross=800, discount=200)     # 200 of 1000 billed
        _invoice(clinic, gross=200)

    page = _report(clinic)
    assert "20.0%" in page


def test_the_period_is_honoured(clinic):
    """Every other report on this screen takes a range; one that quietly
    showed everything would be read as this month's."""
    with clinic["app"].app_context():
        _invoice(clinic, gross=200, discount=50,
                 when=local_today() - timedelta(days=90))

    inside = local_today().replace(day=1)
    page = _report(clinic, date_from=inside.isoformat(),
                   date_to=local_today().isoformat())
    assert _word("disc_none") in page


# ============================================== reachable ===================
def test_it_is_on_the_reports_screen(clinic):
    """Three screens have been built and lost in this program already."""
    page = clinic["sign_in"]("boss").get("/reports/").data.decode()
    assert "/reports/discounts" in page


def _word(key, section="reports", lang="ar"):
    import json

    path = os.path.join(os.path.dirname(__file__), "..", "app", "i18n",
                        "locales", f"{lang}.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)[section][key]
