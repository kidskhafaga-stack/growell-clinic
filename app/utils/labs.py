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


#: The three halves of the same table — three rooms, three sets of hands.
#:
#: ``imaging`` is radiology: films, CT, MRI, reported by a radiologist.
#: ``diagnostic`` is what the treating team does itself — a sonar, an echo, an
#: ECG, an EEG. Asked for in those words: «الاشعة العادية غير الايكو واللترا
#: سونت وال eeg و ال ECG». The person on the X-ray machine and the person
#: doing echoes are not each other's cover.
LAB, IMAGING, DIAGNOSTIC = "lab", "imaging", "diagnostic"

#: The two that are not a sample. Both are *performed*, never drawn.
ROOMS = (IMAGING, DIAGNOSTIC)


def worklist(kind=LAB, state=None, limit=200):
    """Everything ordered **here** and not yet answered, longest-waiting first.

    Oldest first and not newest: a rack works from the bottom, and a list that
    puts this minute's order on top is a list where the sample taken at eight
    is still sitting there at two.

    **``kind`` defaults to the lab, and that default is the fix.** It used to
    default to ``None`` — everything — so the bench's own screen listed every
    echocardiogram in the building beside the blood counts, counted them under
    «to collect», and offered a «sample taken» button on them. Reported as
    «ليه ركويست الايكو موجود فى المعمل؟», which is the right question: an echo
    has no tube, and a screen that asks somebody to draw one is asking for a
    record of something that cannot happen.

    ``None`` still means both, for a caller that genuinely wants the lot.

    **And what is being done elsewhere is on none of them.** A clinic with no
    echo machine, or a family who would rather go to the hospital down the
    road, leaves an order that is real — it prints, it sits on the child's
    file, its result comes back on it — and that nobody in this building is
    ever going to touch. Left on a worklist it is a row that can only be
    cleared by somebody deciding to ignore it, and a list people learn to
    ignore is the thing this module exists to stop being.
    """
    from sqlalchemy.orm import selectinload

    query = (VisitInvestigation.query
             .options(selectinload(VisitInvestigation.patient),
                      selectinload(VisitInvestigation.investigation))
             .filter(VisitInvestigation.status.in_(OPEN_STATES),
                     _ours()))
    if kind:
        query = query.filter(VisitInvestigation.kind == kind)
    if state:
        query = query.filter(VisitInvestigation.status == state)
    return (query.order_by(VisitInvestigation.created_at,
                           VisitInvestigation.id).limit(limit).all())


def beds_of(rows):
    """``{patient_id: "unit · bed"}`` for the children on this list who are in
    a bed right now — so whoever walks with the tubes knows where to walk.

    One query for the whole list, not one per row: the rack is read all
    morning, and a list of a hundred is a hundred children at most.
    """
    from sqlalchemy.orm import selectinload

    from app.models.admission import Admission, BedStay
    from app.models.place import Bed, Space

    from app.utils.facility import module_enabled

    ids = {r.patient_id for r in rows}
    # A clinic with no beds asks the database nothing here.
    if not ids or not module_enabled("beds"):
        return {}
    stays = (BedStay.query.join(Admission, BedStay.admission_id == Admission.id)
             .options(selectinload(BedStay.bed).selectinload(Bed.space)
                      .selectinload(Space.unit))
             .filter(Admission.patient_id.in_(ids),
                     Admission.discharged_at.is_(None),
                     BedStay.until.is_(None)).all())
    lang = _screen_lang()
    out = {}
    for stay in stays:
        bed = stay.bed
        unit = bed.space.unit if bed and bed.space else None
        out[stay.admission.patient_id] = " · ".join(
            x for x in ((unit.display_name(lang) if unit else ""),
                        (bed.display_name(lang) if bed else "")) if x)
    return out


def _screen_lang():
    """The language of the screen asking, or Arabic outside a request."""
    try:
        from flask import g

        return getattr(g, "lang", "ar") or "ar"
    except RuntimeError:
        return "ar"


def _ours():
    """The filter that keeps every room's list about its own work.

    All three read it — the bench, radiology and the diagnostics room — and
    for one reason: an echo the family is having done at the hospital down
    the road is no more the echo room's work than it is the lab's.

    ``is_not(True)`` rather than ``is_(False)``. On every schema this program
    creates the two are the same query — a fresh table has the column NOT
    NULL, and the upgrade adds it with a default SQLite writes into every
    existing row — so this is not a guard against a state that happens. It is
    a choice of which way to be wrong if one ever does: this one puts an
    unanswered order **on** the bench, where somebody sees it and can say
    otherwise. The other one makes it disappear, and an order nobody can see
    is the failure this whole module was written to stop.
    """
    return VisitInvestigation.done_outside.is_not(True)


def goes_outside(investigation, asked=None):
    """Is this order going to be done somewhere else? The default, and the
    override.

    ``asked`` is what the person ordering said — ``True`` or ``False`` when
    they said anything, and ``None`` when nobody asked them. **Nobody asked
    is the ordinary case**, and the answer then is the clinic's own: a test
    it does not do is written this way without anybody being prompted, which
    is the whole point of holding the answer on the catalogue. اللي بيكتب في
    الأوضة ما يكتبش أكتر.

    ``is False`` and not ``not in_house``: a catalogue row whose column has
    never been written reads NULL, and treating that as "we do not do it"
    would send every order in an upgraded clinic out of the building.
    """
    if asked is not None:
        return bool(asked)
    if investigation is None:
        return False
    return investigation.in_house is False


def counts(kind=LAB):
    """How many are waiting to be drawn and how many to be run.

    Two numbers rather than one total, because they are two different jobs
    done by two different people.

    **And of one kind**, for the same reason the list is: a bench told it has
    five to draw, two of which are scans, has been told a number it cannot
    work to.
    """
    query = (db.session.query(VisitInvestigation.status,
                              db.func.count(VisitInvestigation.id))
             .filter(VisitInvestigation.status.in_(OPEN_STATES), _ours()))
    if kind:
        query = query.filter(VisitInvestigation.kind == kind)
    rows = (query.group_by(VisitInvestigation.status).all())
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
    if row.kind in ROOMS:
        # **Refused, not ignored.** Neither a film nor an echo has a sample to
        # draw, and a caller that reaches here has the wrong row: quietly
        # doing nothing would leave a screen saying it had been collected.
        raise ValueError("this order has no sample")
    if row.status == RESULTED:
        raise ValueError("already resulted")
    row.collected_at = at or datetime.utcnow()
    row.collected_by = getattr(user, "id", None)
    # A code typed at the bench wins; otherwise the one already on the label,
    # so the tube and the record keep the same number; otherwise a fresh one.
    row.sample_code = ((code or "").strip()[:24] or row.sample_code
                       or sample_code(row))
    row.status = COLLECTED
    return row


def label_code(row):
    """The number for the tube **before** the needle — «ليه مش بيولد رقم
    العينة؟ ويقدر يطبعها وتتقرا بالباركود؟».

    The code used to be written only when «the sample was taken» was pressed,
    so there was nothing to stick on the tube while drawing it. Now printing
    the label writes it, and :func:`collect` keeps it. Kept if already there:
    a label printed twice is the same tube. Only a lab order has a tube.
    """
    if row is None or row.kind in ROOMS:
        raise ValueError("this order has no sample")
    if not row.sample_code:
        row.sample_code = sample_code(row)
    return row.sample_code


def by_code(code):
    """The order a scanned tube belongs to, or ``None``.

    A barcode reader types the code and presses Enter; Code 39 reads back in
    capitals, and the codes are digits and dashes, so case and the spaces a
    hand-typed code picks up are ignored.
    """
    code = (code or "").strip().upper()
    if not code:
        return None
    return (VisitInvestigation.query
            .filter(db.func.upper(VisitInvestigation.sample_code) == code)
            .order_by(VisitInvestigation.id.desc()).first())


def perform(row, user=None, at=None):
    """The scan was done. The imaging half of :func:`collect`.

    Same shape, same middle state, different event — and **the state is shared
    on purpose**. ``collected`` means "it is under way and nobody has answered
    yet", which is as true of a scan that has been performed as of a sample
    that has been drawn; see the note above ``INVESTIGATION_STATUSES`` for why
    a fourth state would have made orders vanish from four screens that ask
    "has this been answered" rather than "which stage is it at".

    What it does **not** do is write a sample code or a collection time. A
    scan has neither, and this exists precisely so nobody has to pretend it
    does to move the order along.

    Re-performing overwrites — a study repeated because the child moved is the
    same order, and the time that matters is the one the pictures came from.
    """
    if row is None:
        raise ValueError("no order")
    if row.kind not in ROOMS:
        raise ValueError("a lab order is collected, not performed")
    if row.status == RESULTED:
        raise ValueError("already resulted")
    row.performed_at = at or datetime.utcnow()
    row.performed_by = getattr(user, "id", None)
    row.status = COLLECTED
    return row


def done_at(row):
    """When this order's own middle event happened, whichever kind it is.

    One reader so a screen showing both — the doctor's own file view — does
    not have to know which column belongs to which kind.
    """
    if row is None:
        return None
    return row.performed_at if row.kind in ROOMS else row.collected_at


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
    return settle(row, user=user, at=at)


def settle(row, user=None, at=None):
    """Move the order to where its answer says it is — answered, or back to
    where the sample is. Shared by `record` and by the analyte-by-analyte
    result (`utils/lab_results.save`), so the two cannot disagree about when
    an order is finished."""
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
def _drawn_on(row):
    """The clinic's day the sample was taken — the day the money was owed.

    Not the UTC day: a sample taken at half past one in the morning in Cairo
    belongs to that night of a stay being billed by the night, and reading
    the stored column's own date would file it under the day before.
    """
    from app.utils.clock import local_date

    return local_date(getattr(row, "collected_at", None))


def unbilled(patient_id=None, visit_id=None, patient_ids=None,
             admission=None, outside_stays=False):
    """Tests that have been drawn and nobody has charged for.

    **Drawn, not merely ordered.** An order somebody wrote and then thought
    better of costs nothing; the clinic has spent something the moment the
    sample exists. That is also the moment a family can be told what it costs,
    which is the other half of not billing for what did not happen.

    ``admission`` narrows to the tests that stay bills (:func:`of_stay`);
    ``outside_stays`` drops the ones ordered from a stay — the desk's
    question, so blood drawn at a child's bed on the stay's own order is not
    charged at the outpatient till.
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
    if patient_ids is not None:
        query = query.filter(
            VisitInvestigation.patient_id.in_(list(patient_ids)))
    if admission is not None:
        query = query.filter(of_stay(admission))
    if outside_stays:
        query = query.filter(VisitInvestigation.admission_id.is_(None))
    return query.order_by(VisitInvestigation.created_at,
                          VisitInvestigation.id).all()


def of_stay(admission):
    """The tests a stay bills, as a filter — read by the bill and the stay's
    own list alike, so the two never disagree.

    Two ways, and **only the first is new**:

    * **ordered from the stay** (``admission_id``) — the stay's own door, and
      the stay's bill is the only place those are charged;
    * **ordered at the visit the stay began from** — the blood drawn in the
      emergency room before anybody decided on a bed. The one way the bill
      found tests before this, kept exactly as it was.

    **What it deliberately does not take:** a test ordered on some other visit
    while the child was in. That went to the outpatient desk before this
    existed and still does — a running hospital's cashier may be collecting
    those up front, and moving them would change how its desk works under it.
    The stay's own order box is what makes that detour unnecessary.
    """
    from sqlalchemy import and_, false, or_

    if admission is None:
        return false()
    ways = [VisitInvestigation.admission_id == admission.id]
    if admission.visit_id:
        ways.append(and_(VisitInvestigation.visit_id == admission.visit_id,
                         or_(VisitInvestigation.admission_id.is_(None),
                             VisitInvestigation.admission_id == admission.id)))
    return or_(*ways)


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

    **Every test the stay bills** (:func:`of_stay`): ordered from it, or at
    the visit it began from. It used to be the second alone, so a stay that
    began without a visit had no way to order a test that would reach its
    bill at all.
    """
    from app.models.invoice import InvoiceItem

    if admission is None or invoice is None:
        return 0
    due = unbilled(admission=admission)
    for row in due:
        service = row.investigation.service
        item = InvoiceItem(
            invoice_id=invoice.id, service_id=service.id,
            description=line_for(row, lang),
            # The day the sample was taken, which is the day the clinic spent
            # something — not the day somebody got round to billing it.
            service_date=_drawn_on(row),
            unit_price=float(service.price or 0), quantity=1)
        item.commission_amount = service.doctor_share(item.net, invoice.doctor)
        db.session.add(item)
        db.session.flush()
        row.invoice_item_id = item.id
    return len(due)
