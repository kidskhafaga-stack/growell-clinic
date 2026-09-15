"""Has anybody in accounts been through this bill — and signed it off.

> «فواتير الداخلي والعمليات بتبقى محتاجة مراجعة من الحسابات للتدقيق وتصديق
> الفاتورة، علشان المنصرف على المريض مع التمريض»

A clinic bill is a receipt for an afternoon and one person wrote all of it. A
stay's bill is a statement of a fortnight assembled by five different hands —
nights from the bed, doses from the round, tests from the bench, a theatre
from the list, and the consumables a nurse charged at the bedside — and not
one of those hands ever sees the whole thing. **That is what there is to
audit**, and it is the entire reason a hospital has this step and a
single-doctor clinic does not.

**It is not a payment state.** `Invoice.status` answers "has the money
arrived"; this answers "has anybody checked what is on it". The two are
independent in both directions — a stay's bill can be signed off on Tuesday
and settled the following month, and a family can pay a bill at the desk that
nobody in accounts has ever read. A single column holding both could say
neither.

**And it does not stand between a family and the till.** Collection is not
gated: a desk that cannot take money because a bill is waiting on an audit is
a desk that raises a second bill. What it gates is the one step that makes the
document final and outward-facing — the tax invoice. See `app.utils.einvoice`.

**Off unless a hospital asks for it.** The policy setting is empty by default,
which is what every clinic running this program today has, and with it empty
nothing anywhere behaves differently: no state, no queue, no gate. The same
promise the care charges make two modules over.
"""
from datetime import datetime

from app.extensions import db

#: Where a bill stands with accounts.
#:
#: ``draft`` is the absence of the other three and is stored as NULL — every
#: invoice ever raised before this existed is in it, and so is every invoice
#: in a clinic that never switches the policy on.
DRAFT, SUBMITTED, APPROVED, QUERIED = ("draft", "submitted", "approved",
                                       "queried")
REVIEW_STATES = (DRAFT, SUBMITTED, APPROVED, QUERIED)

#: What the hospital said needs auditing.
#:
#: ``""`` — nothing, and the default.
#: ``stay`` — the bills the question was actually about: a stay's, and any
#:            bill carrying a theatre case (a day case has no stay behind it
#:            and is still an operation somebody has to account for).
#: ``all``  — every invoice, for a centre that wants one rule.
POLICY_SETTING = "invoice_signoff"
POLICIES = ("", "stay", "all")


#: Who signs a bill off. **The accountant, and that is the point** — the first
#: version of this asked for `is_admin`, which in a hospital locks the audit
#: behind the one account that is not in accounts. The person the question was
#: about («مراجعة من الحسابات») is the one role that could not do it.
#:
#: `admin` stays because a single-doctor clinic that switches this on has
#: nobody else, and a rule only an empty chair satisfies is a rule that gets
#: switched off.
SIGNS_OFF = ("accountant", "admin")


def may_sign_off(user):
    """Whether this account signs bills off. **Sending one is anybody's** —
    «the bill is complete» is the ward coordinator's sentence, not
    accounts'."""
    return getattr(user, "role", None) in SIGNS_OFF


def policy():
    """What this hospital asks to be audited. ``""`` when it asks for nothing."""
    from app.models import Setting

    try:
        raw = (Setting.get(POLICY_SETTING) or "").strip()
    except Exception:  # noqa: BLE001 — a settings table that is not ready yet
        return ""
    return raw if raw in POLICIES else ""


def needs_review(invoice):
    """Whether this bill is one accounts has to sign off."""
    if invoice is None:
        return False
    rule = policy()
    if not rule:
        return False
    if rule == "all":
        return True
    return invoice.admission_id is not None or carries_theatre(invoice)


def carries_theatre(invoice):
    """Whether any line on this bill came from a theatre case.

    **A day case has no stay behind it** and is still an operation somebody
    has to account for — the room, the anaesthetist, the implants. Reading
    only `admission_id` would have sent exactly those bills out unaudited,
    and they are not the small ones.
    """
    from app.models.theatre import Operation

    if invoice is None or not invoice.id:
        return False
    items = [i.id for i in (invoice.items or []) if i.id]
    if not items:
        return False
    return db.session.query(Operation.id).filter(
        db.or_(Operation.invoice_item_id.in_(items),
               Operation.anaesthesia_item_id.in_(items))).first() is not None


def state(invoice):
    """Where this bill stands — in one word, and ``draft`` when nobody has
    touched it. Reading NULL as ``draft`` is what keeps every invoice raised
    before this existed meaning what it always meant."""
    if invoice is None:
        return DRAFT
    written = (invoice.review_state or "").strip()
    return written if written in REVIEW_STATES else DRAFT


def signed_off(invoice):
    """The one question the tax document asks before it goes out.

    ``True`` for a bill nobody has to audit — a clinic that asks for no
    review has every bill signed off by definition, and anything else would
    stop a working clinic on the morning of an upgrade.
    """
    if not needs_review(invoice):
        return True
    return state(invoice) == APPROVED


def waiting(limit=200):
    """The bills accounts still have to go through, longest-waiting first.

    Oldest first, like the bench's rack and for the same reason: a queue that
    puts this minute's bill on top is a queue where last Tuesday's is still
    there at the end of the month.
    """
    from app.models import Invoice

    rule = policy()
    if not rule:
        return []
    query = Invoice.query.filter(
        db.or_(Invoice.review_state.is_(None),
               Invoice.review_state.in_((DRAFT, SUBMITTED, QUERIED))))
    if rule == "stay":
        # Narrowed in SQL to the stays, then the theatre day cases are added
        # by reading — `carries_theatre` is a per-invoice question and there
        # is no join that answers it for a page of rows without duplicating
        # the rule in two places.
        query = query.order_by(Invoice.invoice_date, Invoice.id)
        rows = [r for r in query.limit(limit * 3).all() if needs_review(r)]
        return rows[:limit]
    return query.order_by(Invoice.invoice_date, Invoice.id).limit(limit).all()


def submit(invoice, user=None, at=None):
    """The ward or the desk says the bill is complete. Caller commits.

    Returns the invoice, or ``None`` when there is nothing to submit — no
    invoice, or one nobody has to audit. **An approved bill is not re-opened
    by this**: somebody pressing «تم» on a bill accounts already signed would
    otherwise quietly un-sign it.
    """
    if invoice is None or not needs_review(invoice):
        return None
    if state(invoice) == APPROVED:
        return invoice
    return _stamp(invoice, SUBMITTED, user, at)


def approve(invoice, user=None, at=None):
    """Accounts have been through it. Caller commits.

    Refused for an account that is not in accounts — a sign-off is a name
    against a claim that somebody checked the bill, and a name that did not is
    worse than none.
    """
    if invoice is None or not needs_review(invoice) or not may_sign_off(user):
        return None
    return _stamp(invoice, APPROVED, user, at, note=None)


def query(invoice, note, user=None, at=None):
    """Accounts are asking about it, and **the sentence is required**.

    «مرفوضة» is not a finding anybody on the ward can act on; the line they
    are asking about is the only part of this a nurse or a coordinator can do
    anything with. The pharmacist's query on a prescription line is refused
    without its words for the same reason.
    """
    said = (note or "").strip()
    if (invoice is None or not needs_review(invoice) or not said
            or not may_sign_off(user)):
        return None
    return _stamp(invoice, QUERIED, user, at, note=said[:255])


def _stamp(invoice, to, user, at, note=""):
    invoice.review_state = to
    invoice.review_by = getattr(user, "id", None)
    invoice.review_at = at or datetime.utcnow()
    if note != "":
        invoice.review_note = note
    return invoice
