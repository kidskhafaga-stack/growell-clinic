"""The lab bench: what was asked for, what has been drawn, what came back.

``HOSPITAL_PLAN.md`` مرحلة ج، بند ٦ names four things — *"طلب داخلي، وعينة،
ونتيجة رقمية، ومنحنى"* — and two of them were already built. The numeric
result has been on ``VisitInvestigation`` since August, and ``lab_series``
draws the curve from it. The order exists too: the visit screen has written
one for years.

**What was missing is the middle, and it is the half a hospital lives in.**

An order went straight from `requested` to `resulted`, because the only hands
it ever passed through were the doctor's, typing in what a paper report said.
That is a clinic. In a hospital somebody goes to the bed, draws the blood,
labels the tube, and somebody else runs it — and until that is recorded, two
completely different situations look identical on screen:

* nobody has drawn this child's blood yet, and
* the blood is in a rack downstairs, waiting.

The first needs a person to walk to a bed. The second needs nothing but time.
A list that cannot tell them apart is a list that gets checked by phone.

**No second place for a result.** The number goes on the order it answers —
the same row the visit screen shows and the curve is drawn from. A `LabResult`
table would have been the obvious shape and the wrong one: two copies of one
number, and the curve reading whichever half the last screen wrote to.

**And the price is the switch, again.** A test is charged as a ``Service`` on
the catalogue entry. No service, and the test is ordered, drawn, run and
resulted without ever reaching a bill — which is how a hospital whose lab is
not billed separately says so, without a setting for it.
"""
from datetime import datetime

from app.extensions import db
from app.models import Investigation, VisitInvestigation
from app.models.visit import INVESTIGATION_OPEN

# Where an order is. Recorded, not derived: see the module docstring — the
# difference between "nobody has been to the bed" and "it is in the rack" is
# the whole reason this module exists, and no timestamp on its own says it.
REQUESTED, COLLECTED, RESULTED = "requested", "collected", "resulted"

# What is still the lab's problem. `resulted` is not here on purpose: once
# there is an answer the order belongs to whoever asked for it, and that list
# already exists — `results_inbox.arrived_unread`.
#
# **The model's own list, not a second copy.** Every screen outside this
# module asks the same question — "has this been answered yet" — and the day
# a fourth state is added, one copy of the answer is the difference between a
# new state appearing everywhere and an order vanishing off four screens.
OPEN_STATES = tuple(INVESTIGATION_OPEN)


def worklist(kind=None, state=None, limit=200):
    """Everything ordered and not yet answered, longest-waiting first.

    Oldest first and not newest: a rack works from the bottom, and a list that
    puts this minute's order on top is a list where the sample taken at eight
    is still sitting there at two.
    """
    from sqlalchemy.orm import selectinload

    query = (VisitInvestigation.query
             .options(selectinload(VisitInvestigation.patient),
                      selectinload(VisitInvestigation.investigation))
             .filter(VisitInvestigation.status.in_(OPEN_STATES)))
    if kind:
        query = query.filter(VisitInvestigation.kind == kind)
    if state:
        query = query.filter(VisitInvestigation.status == state)
    return (query.order_by(VisitInvestigation.created_at,
                           VisitInvestigation.id).limit(limit).all())


def counts():
    """How many are waiting to be drawn and how many to be run.

    Two numbers rather than one total, because they are two different jobs
    done by two different people.
    """
    rows = (db.session.query(VisitInvestigation.status,
                             db.func.count(VisitInvestigation.id))
            .filter(VisitInvestigation.status.in_(OPEN_STATES))
            .group_by(VisitInvestigation.status).all())
    found = dict(rows)
    return {"to_collect": found.get(REQUESTED, 0),
            "to_run": found.get(COLLECTED, 0)}


def waiting_minutes(row, now=None):
    """How long this order has been open. Whole minutes, from when it was
    written — the number the person reading the list is actually asking for."""
    if row is None or row.created_at is None:
        return 0
    return max(0, int(((now or datetime.utcnow()) - row.created_at)
                      .total_seconds() // 60))


def collect(row, user=None, code=None, at=None):
    """The sample was taken. Stamps the tube and moves the order along.

    Re-collecting is allowed and overwrites: a haemolysed sample is redrawn,
    and the tube that matters is the one that reached the bench. What is not
    allowed is collecting an order that already has an answer — that is a
    keystroke on the wrong row, and it would put a fresh sample time on a
    result taken from an older one.
    """
    if row is None:
        raise ValueError("no order")
    if row.status == RESULTED:
        raise ValueError("already resulted")
    row.collected_at = at or datetime.utcnow()
    row.collected_by = getattr(user, "id", None)
    row.sample_code = (code or "").strip()[:24] or sample_code(row)
    row.status = COLLECTED
    return row


def sample_code(row):
    """What goes on the tube.

    The order's own id, padded, with the clinic's date in front of it. Short
    enough to write on a label by hand at three in the morning, and unique
    because the id is — a random string would look more serious and would give
    a person holding a tube nothing to look the order up by.
    """
    from app.utils.clock import local_today

    return f"{local_today():%y%m%d}-{row.id:05d}"


def record(row, value=None, unit=None, low=None, high=None, text=None,
           comment=None, user=None, at=None):
    """Write the answer onto the order it answers.

    **One door**, called both by the lab bench and by the visit screen where a
    doctor types in what a paper report said — the two were going to drift,
    and the half that drifts is always the one that decides whether the order
    is finished.

    A blank number clears the range with it: a band with nothing to compare it
    to is a band on an empty chart, and a stale range under a new reading is
    worse than none because it is invisible.
    """
    if row is None:
        raise ValueError("no order")
    row.result_value = value
    row.result_unit = (unit or "").strip()[:20] or None
    row.result_low = low if value is not None else None
    row.result_high = high if value is not None else None
    if text is not None:
        row.result_text = (text or "").strip() or None
    if comment is not None:
        row.result_comment = (comment or "").strip() or None

    if row.has_result:
        row.status = RESULTED
        row.resulted_at = at or datetime.utcnow()
        row.resulted_by = getattr(user, "id", None)
    else:
        # Cleared back out. It falls back to where the sample says it is, not
        # to `requested` — the blood was still drawn, and sending somebody to
        # the bed again for a result that was typed and deleted is the kind of
        # thing that makes a ward stop trusting the screen.
        row.status = COLLECTED if row.collected_at else REQUESTED
        row.resulted_at = None
        row.resulted_by = None
    return row


# ------------------------------------------------------------- the money ---
def unbilled(patient_id=None, visit_id=None):
    """Tests that have been drawn and nobody has charged for.

    **Drawn, not merely ordered.** An order somebody wrote and then thought
    better of costs nothing; the clinic has spent something the moment the
    sample exists. That is also the moment a family can be told what it costs,
    which is the other half of not billing for what did not happen.
    """
    query = (VisitInvestigation.query
             .join(Investigation,
                   VisitInvestigation.investigation_id == Investigation.id)
             .filter(VisitInvestigation.collected_at.isnot(None),
                     VisitInvestigation.invoice_item_id.is_(None),
                     Investigation.service_id.isnot(None)))
    if patient_id is not None:
        query = query.filter(VisitInvestigation.patient_id == patient_id)
    if visit_id is not None:
        query = query.filter(VisitInvestigation.visit_id == visit_id)
    return query.order_by(VisitInvestigation.created_at,
                          VisitInvestigation.id).all()


def line_for(row, lang="ar"):
    """What the test reads as on a bill: the catalogue's name for the service,
    and the test's own name when the clinic prices several tests as one."""
    service = row.investigation.service if row.investigation else None
    name = (service.display_name(lang) if service is not None
            else (row.name or ""))
    own = row.investigation.display_name(lang) if row.investigation else row.name
    parts = [name] if name else []
    if own and own != name:
        parts.append(own)
    return " · ".join(parts)[:200] or (row.name or "")[:200]


def charge(admission, invoice, user=None, lang="ar"):
    """Put this stay's drawn-and-unbilled tests on its bill. Returns how many.

    **Found through the stay's own encounter**, because that is the link that
    exists: an order carries the visit it was written at, and an admission
    carries the visit it began from. A stay that never had one has no lab
    lines here rather than borrowing another visit's — the shape every other
    missing price in this program takes.
    """
    from app.models.invoice import InvoiceItem

    if admission is None or invoice is None or not admission.visit_id:
        return 0
    due = unbilled(visit_id=admission.visit_id)
    for row in due:
        service = row.investigation.service
        item = InvoiceItem(
            invoice_id=invoice.id, service_id=service.id,
            description=line_for(row, lang),
            unit_price=float(service.price or 0), quantity=1)
        item.commission_amount = service.doctor_share(item.net, invoice.doctor)
        db.session.add(item)
        db.session.flush()
        row.invoice_item_id = item.id
    return len(due)
