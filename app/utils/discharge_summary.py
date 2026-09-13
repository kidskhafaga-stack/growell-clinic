"""Assembling ACT.15's nine elements — deriving eight, asking for six.

**The rule this module is built on:** the program does not ask a doctor to
type something it already knows. A stay carries its reason, its operations,
its inpatient drug orders and the name of whoever discharged the child, and
every one of those is element of the discharge summary the standard asks for.
Typing them again would be a second answer that drifts from the first, and it
would be the doctor paying for the program's convenience.

So ``assemble`` returns all nine elements side by side — each one saying
whether it came off the record or out of somebody's hands — and the writing
screen asks for the six that exist nowhere else.

**And the gap stays visible.** ``state`` never reports ``complete`` for a
summary with a blank element, and a discharge is **never refused** for a
missing summary: refusing to record that a child went home because the
paperwork is not finished would leave them in a bed for ever in the program's
telling, which is the argument ``theatres.finish`` already settled. The screen
says the summary is missing, and goes on saying it.
"""
from datetime import datetime

from app.extensions import db
from app.models.admission import Admission
from app.models.discharge_summary import DischargeSummary

#: The nine, in the standard's own order and lettering. ``written`` names the
#: column a person fills in; ``None`` means the record answers it already.
#:
#: Quoted, not invented — every line of this table is in the handbook at
#: ACT.15, and nothing has been added to it.
ELEMENTS = (
    ("a", "reason", None),
    ("b", "diagnosis", "diagnosis"),
    ("c", "investigations", None),
    ("d", "findings", "findings"),
    ("e", "procedures", None),
    ("f", "medications", None),
    ("g", "condition", "condition"),
    ("h", "instructions", ("diet", "medicines", "followup")),
    ("i", "discharged_by", None),
)

#: What ``state`` can answer. ``none`` is an absence, not an empty summary.
STATES = ("none", "short", "complete")


def for_admission(admission):
    """This stay's summary, or ``None`` — and ``None`` is the finding."""
    return getattr(admission, "discharge_summary", None) if admission else None


def state(admission):
    """``none`` · ``short`` · ``complete``, derived every time it is asked.

    * ``none`` — nobody has written one. No row, and that is the whole point
      of it being a row: a stay from before this existed reads as *unwritten*
      rather than as a summary somebody left blank.
    * ``short`` — written, with elements still empty. Named so it cannot be
      mistaken for done, the way the checklist's *signed short* is.
    * ``complete`` — all six written elements have something in them.

    **Never ``complete`` because the record happens to be empty.** A stay with
    no investigations and no operations is not a more complete summary than
    one with them; those elements are answered by the record either way, and
    completeness is only ever about what a person had to write.
    """
    row = for_admission(admission)
    if row is None:
        return "none"
    return "complete" if not row.blanks else "short"


def missing(admission):
    """Which written elements are still blank, in the standard's order."""
    row = for_admission(admission)
    if row is None:
        return list(DischargeSummary.WRITTEN)
    return row.blanks


def delay_hours(admission):
    """Hours between the child leaving and the summary being written.

    ``None`` while either end is missing. **Measured, never graded** — the
    standard asks for *"an approved timeframe"* and names no number, so the
    program names none either. What it does is make the number visible, which
    is what *"delays in the completion of the discharge summary are associated
    with higher rates of readmission"* asks somebody to look at.

    Negative is not possible and not guarded against: a summary written before
    the discharge is a summary written while the child was still in, which is
    a real and good thing, and it simply reads as zero hours of delay.
    """
    row = for_admission(admission)
    if row is None or not admission.discharged_at:
        return None
    gap = row.written_at - admission.discharged_at
    return max(0, int(gap.total_seconds() // 3600))


# ------------------------------------------------ what the record holds ----
def investigations_during(admission):
    """The child's investigations over the span of the stay, oldest first.

    **Derived from the window**, because ``VisitInvestigation`` hangs off a
    visit and there is no admission on it. An order placed on the day the
    child was admitted belongs to this episode whichever door it came
    through, which is exactly what a discharge summary means by
    *"investigations"*.

    An open stay runs to now.
    """
    from app.models.visit import VisitInvestigation

    if admission is None or not admission.admitted_at:
        return []
    end = admission.discharged_at or datetime.utcnow()
    return (VisitInvestigation.query
            .filter(VisitInvestigation.patient_id == admission.patient_id,
                    VisitInvestigation.created_at >= admission.admitted_at,
                    VisitInvestigation.created_at <= end)
            .order_by(VisitInvestigation.created_at.asc(),
                      VisitInvestigation.id.asc())
            .all())


def procedures_during(admission):
    """The operations done on this stay — ``Operation.admission_id``."""
    from app.utils.facility import module_enabled

    if admission is None or not module_enabled("theatres"):
        return []
    from app.models.theatre import Operation

    return (Operation.query
            .filter(Operation.admission_id == admission.id)
            .order_by(Operation.on_date.asc(), Operation.id.asc())
            .all())


def medicines_during(admission):
    """The inpatient drug orders written on this stay."""
    if admission is None:
        return []
    from app.models.medication import MedicationOrder

    return (MedicationOrder.query
            .filter(MedicationOrder.admission_id == admission.id)
            .order_by(MedicationOrder.id.asc())
            .all())


def medicines_before(admission):
    """What the child was already on when they came in.

    The standard asks for medications *"(before/during)"* — two facts, and the
    one nobody records anywhere is what the child arrived taking. This reads
    the standing list as it stood on the day of admission: started by then,
    and not stopped before then.
    """
    if admission is None or not admission.admitted_at:
        return []
    from app.models.patient_medication import PatientMedication
    from app.utils.clock import local_date

    day = local_date(admission.admitted_at)
    rows = (PatientMedication.query
            .filter(PatientMedication.patient_id == admission.patient_id)
            .order_by(PatientMedication.id.asc()).all())
    return [m for m in rows
            if (m.started_on is None or m.started_on <= day)
            and (m.stopped_on is None or m.stopped_on >= day)]


def provisional_diagnoses(admission):
    """The diagnoses from the visit this stay came in through, if any.

    **Offered, never stored here.** The screen shows them beside the final
    diagnosis box so nobody retypes a word — but the final diagnosis is the
    stay's own conclusion and is written, because a stay that changed the
    answer must be able to say so.
    """
    visit = getattr(admission, "visit", None) if admission else None
    return list(getattr(visit, "diagnoses", []) or [])


def assemble(admission):
    """All nine elements, each with where it came from.

    Returns a list of ``{"letter", "key", "written", "filled"}`` in ACT.15's
    order. ``written`` is ``True`` for the elements a person supplies;
    ``filled`` says whether this stay actually has an answer — for a derived
    element that means the record holds something, and for a written one that
    means somebody wrote it.
    """
    row = for_admission(admission)
    holds = {
        "reason": bool((getattr(admission, "reason", "") or "").strip()),
        "investigations": bool(investigations_during(admission)),
        "procedures": bool(procedures_during(admission)),
        "medications": bool(medicines_during(admission)
                            or medicines_before(admission)),
        "discharged_by": getattr(admission, "discharged_by", None) is not None,
    }
    out = []
    for letter, key, column in ELEMENTS:
        if column is None:
            filled = holds.get(key, False)
        elif isinstance(column, tuple):
            # (h) is three boxes and is answered only when all three are.
            filled = bool(row) and not any(c in row.blanks for c in column)
        else:
            filled = bool(row) and column not in row.blanks
        out.append({"letter": letter, "key": key,
                    "written": column is not None, "filled": filled})
    return out


# ------------------------------------------------------- writing it -------
def write(admission, user=None, **fields):
    """Write or correct this stay's summary. Returns the row, or ``None``.

    Refused for a stay that does not exist. **Not refused for an open stay**:
    a summary begun while the child is still in a bed is the good case, and
    the standard's own complaint is about summaries written too late.

    Only the six written columns are accepted, so a caller cannot set the
    stamps or move the summary to another stay by passing a keyword.
    """
    if admission is None:
        return None
    row = for_admission(admission)
    if row is None:
        # **Through the relationship, not the foreign key.** The line above
        # has just asked this stay for its summary and been told ``None``,
        # and SQLAlchemy caches that answer on the instance until the session
        # is committed. Setting ``admission_id`` alone leaves the cached
        # ``None`` in place, so every later reader *in the same request* —
        # ``hand_over`` above all — is told the stay has no summary and
        # quietly does nothing. Assigning the relationship populates the
        # backref there and then.
        #
        # Found by a test that wrote a summary and handed it over in one
        # breath, which is exactly what the ward screen does.
        row = DischargeSummary(admission=admission,
                               patient_id=admission.patient_id,
                               written_by=getattr(user, "id", None))
        db.session.add(row)
    for name in DischargeSummary.WRITTEN:
        if name in fields:
            setattr(row, name, (fields[name] or "").strip() or None)
    return row


def hand_over(admission, user=None, at=None):
    """Record that a copy reached the family — evidence 4. Returns the row.

    ``None`` where there is no summary to hand over, which is the honest
    answer: a clerk cannot give a family a document nobody has written.
    **Stamped once**, like the call for a theatre patient: the second press is
    a second copy, not a second handover, and moving the stamp would erase
    when the family actually got it.
    """
    row = for_admission(admission)
    if row is None or row.given_at:
        return None
    row.given_at = at or datetime.utcnow()
    row.given_by = getattr(user, "id", None)
    return row


def unwritten(limit=None):
    """Stays that ended with no summary, most recently discharged first.

    The queue behind evidence 2. Open stays are not on it — a child still in
    a bed has not been discharged, and a list that counted them would be a
    list nobody could ever clear.
    """
    query = (Admission.query
             .filter(Admission.discharged_at.isnot(None))
             .outerjoin(DischargeSummary,
                        DischargeSummary.admission_id == Admission.id)
             .filter(DischargeSummary.id.is_(None))
             .order_by(Admission.discharged_at.desc()))
    return query.limit(limit).all() if limit else query.all()
