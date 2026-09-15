"""اللي اتطلب، واللي اتعلّق، واللي حد كان قاعد يشوفه — ICD.20 و ICD.21.

اقرا `models/blood.py` الأول للسبب في جدولين. الملف ده بيجاوب التلات أسئلة
اللي المراجِع بيفتح الملف علشانهم:

* **ليه اتطلب؟** — `ICD.20` دليل ٣، ومكتوب في الطلب نفسه ومطلوب.
* **حد شاف الكيس قبل ما يتعلّق؟** — `ICD.21` دليل ٣.
* **حد كان قاعد جنب الطفل وهو ماشي؟** — `ICD.21` دليل ٤، **ودي مشتقّة**:
  القراءات هي `Observation` عادية متعلّمة بالنقل، فالإجابة بتتحسب من السجل
  ومحدّش بيسجّلها تاني.

---

**والبرنامج ما بيحطّش رقم من عنده.** المعيار بيسيب المعدّل ومدد المراقبة
لسياسة المستشفى — *"The rate for blood transfusion"*، *"Conditions when the
bag shall be discarded"* — فالمعدّل بيتكتب بكلام العيادة، ومدة المراقبة
**إعداد بيبدأ فاضي**، وطول ما هو فاضي مفيش حاجة بتتقال عليها إنها اتأخرت. نفس
القاعدة اللي تقييمات المخاطر اتبنت عليها.

**وهي بتقول، وعمرها ما بتمنع.** مفيش نقل بيترفض لأن بند ناقص: الكيس بيتعلّق
والشاشة بتفضل تقول إن حد ما شافوش. الرفض هنا كان معناه دم بيتعلّق والبرنامج
مقفول.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.blood import (CANCELLED, EMERGENCY, PRODUCTS, READY,
                              REQUESTED, TRANSFUSED, URGENCIES, BloodRequest,
                              Transfusion)

#: How often this hospital's policy says to take readings during a
#: transfusion, in minutes. Empty by default — see the module docstring.
INTERVAL_SETTING = "blood_watch_minutes"

#: Where one bag stands.
#:
#: ``ordered``   a request with no bag against it yet
#: ``unchecked`` a bag hung that nobody recorded checking — `ICD.21` ev. 3
#: ``running``   hung, checked, and going
#: ``unwatched`` **running with no readings taken** — `ICD.21` ev. 4, and the
#:               one this screen exists for
#: ``reacted``   a reaction was recorded
#: ``done``      finished with no reaction
ORDERED, UNCHECKED, RUNNING, UNWATCHED, REACTED, DONE = (
    "ordered", "unchecked", "running", "unwatched", "reacted", "done")
BAG_STATES = (ORDERED, UNCHECKED, RUNNING, UNWATCHED, REACTED, DONE)


def interval_minutes():
    """The clinic's monitoring interval, or ``None`` when it has not said."""
    from app.models import Setting

    try:
        raw = (Setting.get(INTERVAL_SETTING) or "").strip()
    except Exception:                   # noqa: BLE001 — settings not ready
        return None
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return None
    return minutes if minutes > 0 else None


def watching(transfusion):
    """The readings taken to watch this bag, oldest first — `ICD.21` ev. 4.

    Ordinary observations, found by the column that ties them to the bag. The
    transfusion stores no copy of them: two copies of one temperature are two
    chances to disagree, and the one on the transfusion is the one nobody
    updates.
    """
    from app.models.observation import Observation

    if transfusion is None or not transfusion.id:
        return []
    return (Observation.query
            .filter(Observation.transfusion_id == transfusion.id)
            .order_by(Observation.taken_at, Observation.id).all())


def state(transfusion, now=None, readings=None):
    """Where one bag stands, in one word.

    **`reacted` outranks everything**, finished or not: a bag that caused a
    reaction is the record somebody will come back to, and letting «خلص» sit
    on top of it would file the most important transfusion of the month as
    routine.
    """
    if transfusion is None:
        return ORDERED
    if transfusion.reaction:
        return REACTED
    if transfusion.started_at is None:
        return ORDERED
    if transfusion.bag_checked is not True:
        # Evidence 3 is about a check *before* it goes up, so a bag already
        # running with no check recorded stays here rather than counting as
        # watched — the gap does not close by the transfusion proceeding.
        return UNCHECKED
    if transfusion.finished_at is not None:
        return DONE
    if not (watching(transfusion) if readings is None else readings):
        return UNWATCHED
    return RUNNING


def overdue_watch(transfusion, now=None, readings=None):
    """Whether the next reading is late by the clinic's own interval.

    ``False`` whenever the hospital has stated no interval, and for a bag that
    is not running — a bag nobody has hung cannot be behind on readings, and
    an unwatched one is already the loudest thing on the screen.
    """
    minutes = interval_minutes()
    if minutes is None or transfusion is None or not transfusion.is_running:
        return False
    rows = watching(transfusion) if readings is None else readings
    last = rows[-1].taken_at if rows else transfusion.started_at
    if last is None:
        return False
    return (now or datetime.utcnow()) - last >= timedelta(minutes=minutes)


def missing(transfusion):
    """Which of `ICD.21`'s recorded elements this bag still has no answer for.

    Keys, not sentences — the screen names them. ``reaction`` counts as
    answered by ``False`` as well as ``True``: *"the occurrence of complications
    **or not**"* is the shape this codebase has settled on four times now.
    """
    if transfusion is None:
        return ["bag_checked", "two_people", "watch", "reaction"]
    out = []
    if transfusion.bag_checked is None:
        out.append("bag_checked")
    if not transfusion.two_people_checked:
        out.append("two_people")
    if not watching(transfusion):
        out.append("watch")
    if transfusion.reaction is None and transfusion.finished_at is not None:
        # Asked only once the bag is down. A running transfusion has not yet
        # had the chance to cause anything, and marking it incomplete would
        # put every bag in the ward on a gap list while it runs.
        out.append("reaction")
    return out


def for_admission(admission):
    """Every request on this stay, newest first, with its bags."""
    if admission is None or not admission.id:
        return []
    return (BloodRequest.query
            .filter(BloodRequest.admission_id == admission.id)
            .order_by(BloodRequest.requested_at.desc(),
                      BloodRequest.id.desc()).all())


def for_patient(patient_id, limit=50):
    """This child's blood, across every stay — the file's own reader."""
    return (BloodRequest.query
            .filter(BloodRequest.patient_id == patient_id)
            .order_by(BloodRequest.requested_at.desc(),
                      BloodRequest.id.desc()).limit(limit).all())


def panel(admission, now=None):
    """Everything the stay screen prints about blood, in one list."""
    when = now or datetime.utcnow()
    out = []
    for request in for_admission(admission):
        bags = []
        for bag in request.transfusions:
            readings = watching(bag)
            bags.append({
                "bag": bag,
                "state": state(bag, now=when, readings=readings),
                "late": overdue_watch(bag, now=when, readings=readings),
                "readings": readings,
                "missing": missing(bag),
            })
        out.append({"request": request, "bags": bags})
    return out


def unwatched(admission, now=None):
    """The bags running on this stay that nobody has taken a reading for.

    The sentence `ICD.21` evidence 4 is about, and the only thing on the
    screen that is a finding rather than a gap: the bag is going into a child
    right now and nothing has been written down.
    """
    return tuple(item["bag"] for group in panel(admission, now=now)
                 for item in group["bags"] if item["state"] == UNWATCHED)


# ------------------------------------------------------- writing it -------
def request(patient, product, indication, user=None, admission=None,
            operation=None, units=None, urgency=None, product_note=None,
            family_told=None, at=None):
    """Order blood, or refuse. Caller commits.

    **The indication is required**, and it is the only required field here.
    `ICD.20` element (د) asks for it *"so that the blood bank can check that
    the product ordered is suitable for diagnosis"* — a request without one is
    exactly the request this standard was written about, and letting it
    through would put the gap in the blood bank instead of on this screen.
    """
    if patient is None:
        raise ValueError("no patient")
    if product not in PRODUCTS:
        raise ValueError("unknown product")
    said = (indication or "").strip()
    if not said:
        raise ValueError("no indication")
    row = BloodRequest(
        patient_id=patient.id,
        admission_id=getattr(admission, "id", None),
        operation_id=getattr(operation, "id", None),
        product=product,
        product_note=(product_note or "").strip()[:120] or None,
        units=units,
        indication=said,
        urgency=urgency if urgency in URGENCIES else "routine",
        requested_by=getattr(user, "id", None),
        requested_at=at or datetime.utcnow(),
        family_told=family_told)
    db.session.add(row)
    return row


def sample_checked(request_row, user=None, at=None):
    """`ICD.20` (ز) — the label on the sample matches the form. Caller commits."""
    if request_row is None:
        return None
    request_row.sample_checked_by = getattr(user, "id", None)
    request_row.sample_checked_at = at or datetime.utcnow()
    if request_row.state == REQUESTED:
        request_row.state = READY
    return request_row


def hang(request_row, unit_code=None, given_by=None, checked_by=None,
         bag_checked=None, bag_note=None, rate=None, at=None):
    """Start one bag. Caller commits.

    **Not refused for a missing check**, and that is deliberate: the bag goes
    up in an emergency and the record says nobody wrote the check down. A
    program that refused here would be a program somebody works around with
    paper, and then nothing is recorded at all.
    """
    if request_row is None:
        raise ValueError("no request")
    if request_row.state == CANCELLED:
        # The one refusal. A cancelled request is one somebody decided against,
        # and hanging a bag against it would record blood given on an order
        # that was withdrawn.
        raise ValueError("request cancelled")
    bag = Transfusion(
        request_id=request_row.id,
        patient_id=request_row.patient_id,
        unit_code=(unit_code or "").strip()[:64] or None,
        bag_checked=bag_checked,
        bag_note=(bag_note or "").strip()[:200] or None,
        given_by=getattr(given_by, "id", given_by),
        checked_by=getattr(checked_by, "id", checked_by),
        rate=(rate or "").strip()[:60] or None,
        started_at=at or datetime.utcnow())
    db.session.add(bag)
    request_row.state = TRANSFUSED
    return bag


def watch(bag, user=None, at=None, **readings):
    """Record one set of observations taken to watch this bag. Caller commits.

    An ordinary `Observation` carrying the bag's id — see the model's comment
    on why this is a column and not a table.
    """
    from app.models.observation import Observation

    if bag is None:
        raise ValueError("no transfusion")
    kept = {k: v for k, v in readings.items() if v is not None}
    if not kept:
        # An empty reading clears the «nobody has watched this» flag without
        # anybody having gone near the child — the same refusal the blank
        # round note and the blank observation are built on.
        raise ValueError("no readings")
    row = Observation(patient_id=bag.patient_id, transfusion_id=bag.id,
                      taken_at=at or datetime.utcnow(),
                      recorded_at=datetime.utcnow(),
                      recorded_by=getattr(user, "id", None), **kept)
    db.session.add(row)
    return row


def finish(bag, reaction=None, reaction_note=None, stopped_early=False,
           at=None):
    """The bag is down. Caller commits.

    ``reaction`` keeps its three states: ``None`` nobody said, ``False`` none
    occurred, ``True`` one did — and ``True`` is what element (ح) then asks
    the note to describe.
    """
    if bag is None:
        return None
    bag.finished_at = at or datetime.utcnow()
    bag.stopped_early = bool(stopped_early)
    if reaction is not None:
        bag.reaction = reaction
    if reaction_note is not None:
        bag.reaction_note = reaction_note.strip() or None
    return bag


def cancel(request_row, reason=None, at=None):
    """The blood is not going to be given. Caller commits.

    Refused once a bag has been hung against it: a request that ended in a
    transfusion cannot be un-asked, and recording it as cancelled would leave
    blood in a child with no order behind it.
    """
    if request_row is None or request_row.transfusions:
        return None
    request_row.state = CANCELLED
    request_row.cancelled_at = at or datetime.utcnow()
    request_row.cancel_reason = (reason or "").strip()[:200] or None
    return request_row


def emergencies_waiting(limit=50):
    """Open emergency requests, oldest first — for whoever is chasing them."""
    return (BloodRequest.query
            .filter(BloodRequest.urgency == EMERGENCY,
                    BloodRequest.state.in_((REQUESTED, READY)))
            .order_by(BloodRequest.requested_at, BloodRequest.id)
            .limit(limit).all())
