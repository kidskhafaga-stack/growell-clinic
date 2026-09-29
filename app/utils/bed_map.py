"""The live bed map: what each unit looks like now, how full it has been, and
the case behind a bed — read from the stays, never from a flag on a bed.

Asked as: *«عايز أعمل شكل تفاعلي — الغرف شكل غرفة، والطوارئ شكل بارتشن، وفي
الرعاية شكل سرير رعاية، وفي الحضانة شكل حضانة وكبسولة … أدوس عليه وأضيف
مريض … ويبدأ يعدّ ساعة أو يوم … وأعرف إشغال اليوم وإشغال المدة لكل قسم …
ونعرف تفاصيل الحالة: متشخصة إيه، العلاج، مطلوب أشعة، تحاليل، إيه اللي خلص
وإيه اللي مستني»* — and *«ده ليه مش بقدر أمسحه؟»* about a unit two children
were staying in.

**A unit that is no longer used is retired, not deleted.** Its stays point at
its beds, so it cannot go; closing it with the reason "retired" takes it off
the map once nobody is in it, and reopening it brings it back.
"""
from datetime import datetime, timedelta

from app.extensions import db

#: The closure reason that retires a place (``utils/closures``).
RETIRED = "retired"
#: How far back "the period" goes when nobody says.
PERIOD_DAYS = 30


def retired_unit_ids():
    """Units closed with the reason "retired" and not reopened."""
    from app.models.closure import Closure

    return {uid for (uid,) in db.session.query(Closure.unit_id)
            .filter(Closure.unit_id.isnot(None), Closure.reason == RETIRED,
                    Closure.reopened_at.is_(None)).all()}


def board(units):
    """The board from ``utils/beds.board`` without the retired units nobody
    is in. A retired unit with a child still in it stays drawn — the child
    is what somebody has to act on."""
    retired = retired_unit_ids()
    return [row for row in units
            if row["unit"].id not in retired or row["taken"]]


# ------------------------------------------------------------ occupancy ---
def occupancy(days=PERIOD_DAYS, now=None):
    """``{unit_id: percent}`` over the last ``days``: the hours children spent
    in the unit's beds, over the hours its beds in service could have held.

    The beds in service are today's — a bed added last week counts for the
    whole period. Close enough for "how full has it been", and said so on the
    screen rather than hidden.
    """
    from app.models import BedStay
    from app.models.place import Bed, Space, Unit

    now = now or datetime.utcnow()
    start = now - timedelta(days=days)
    beds = dict(db.session.query(Space.unit_id, db.func.count(Bed.id))
                .join(Bed, Bed.space_id == Space.id)
                .join(Unit, Space.unit_id == Unit.id)
                .filter(Bed.is_active.is_(True), Space.is_active.is_(True),
                        Unit.is_active.is_(True))
                .group_by(Space.unit_id).all())
    used = {}
    rows = (db.session.query(Space.unit_id, BedStay.since, BedStay.until)
            .join(Bed, BedStay.bed_id == Bed.id)
            .join(Space, Bed.space_id == Space.id)
            .filter(BedStay.since < now,
                    db.or_(BedStay.until.is_(None), BedStay.until > start))
            .all())
    for unit_id, since, until in rows:
        hours = ((min(until or now, now) - max(since, start)).total_seconds()
                 / 3600)
        used[unit_id] = used.get(unit_id, 0) + max(hours, 0)
    out = {}
    for unit_id, count in beds.items():
        possible = count * days * 24
        out[unit_id] = round(used.get(unit_id, 0) * 100 / possible) if possible else None
    return out


def diagnoses_by_admission(admissions):
    """``{admission_id: [titles]}`` from the visit each stay came from — one
    query for the whole board."""
    from app.models.diagnosis import Diagnosis

    visit_of = {a.id: a.visit_id for a in admissions if a.visit_id}
    if not visit_of:
        return {}
    titles = {}
    for visit_id, title in (db.session.query(Diagnosis.visit_id, Diagnosis.title)
                            .filter(Diagnosis.visit_id.in_(set(visit_of.values())))
                            .order_by(Diagnosis.id).all()):
        titles.setdefault(visit_id, []).append(title)
    return {aid: titles.get(vid, []) for aid, vid in visit_of.items()}


def signed_admissions(admissions):
    """The stays on the board whose guardian has signed the admission
    consent — one query for the whole board."""
    from app.models import Consent

    ids = [a.id for a in admissions]
    if not ids:
        return set()
    return {aid for (aid,) in db.session.query(Consent.admission_id)
            .filter(Consent.admission_id.in_(ids),
                    Consent.consent_type == "admission",
                    Consent.signature_file.isnot(None)).all()}


# ------------------------------------------------------------- the case ---
def panel(admission):
    """The case behind a bed, for the side panel: what it is, what is being
    given, and what is still waiting — each read from where it is written."""
    from app.models import MedicationOrder
    from app.models.visit import INVESTIGATION_OPEN, VisitInvestigation

    stay = next((s for s in admission.stays if s.until is None), None)
    meds = (MedicationOrder.query
            .filter(MedicationOrder.admission_id == admission.id,
                    MedicationOrder.stopped_at.is_(None))
            .order_by(MedicationOrder.started_at).all())
    since = admission.admitted_at
    # The investigations of this stay: those ordered on the visit it came
    # from, and on any visit of the child's since it began.
    from app.models import Visit
    visit_ids = {v for (v,) in db.session.query(Visit.id).filter(
        Visit.patient_id == admission.patient_id,
        Visit.created_at >= (since - timedelta(days=1)) if since else False).all()}
    if admission.visit_id:
        visit_ids.add(admission.visit_id)
    asked = (VisitInvestigation.query
             .filter(VisitInvestigation.visit_id.in_(visit_ids))
             .order_by(VisitInvestigation.id).all()) if visit_ids else []
    waiting = [i for i in asked if i.status in INVESTIGATION_OPEN]
    done = [i for i in reversed(asked) if i.status == "resulted"][:8]
    dx = diagnoses_by_admission([admission]).get(admission.id, [])
    return {"admission": admission, "patient": admission.patient,
            "stay": stay, "bed": stay.bed if stay else None,
            "diagnoses": dx, "meds": meds,
            "labs_waiting": [i for i in waiting if i.kind == "lab"],
            "imaging_waiting": [i for i in waiting if i.kind == "imaging"],
            "done": done}


# ----------------------------------------------------------------- live ---
def fingerprint(_ident=0):
    """Everything the map shows that can change without the page knowing:
    who is in which bed, which places are open, and what is closed."""
    import hashlib

    from app.models import BedStay
    from app.models.closure import Closure
    from app.models.place import Bed, Space, Unit

    parts = (
        db.session.query(BedStay.id, BedStay.bed_id, BedStay.admission_id)
        .filter(BedStay.until.is_(None)).order_by(BedStay.id).all(),
        db.session.query(Bed.id, Bed.is_active, Bed.name, Bed.kind).order_by(Bed.id).all(),
        db.session.query(Space.id, Space.is_active, Space.name).order_by(Space.id).all(),
        db.session.query(Unit.id, Unit.is_active, Unit.name).order_by(Unit.id).all(),
        db.session.query(Closure.id, Closure.reopened_at).order_by(Closure.id).all(),
    )
    return hashlib.md5(repr(parts).encode()).hexdigest()
