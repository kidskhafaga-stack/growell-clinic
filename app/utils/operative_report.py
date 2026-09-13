"""Assembling SAS.08's nine elements — deriving five, asking for four.

Same rule as the discharge summary one standard along: **the program does not
ask a surgeon to type what it already knows.** The two stamps, the people, the
procedure and findings, and every implant with its lot number are all in the
record already — element (e)'s *"including the batch number"* is answered by
work done for SAS.06 (ز) and SAS.11 months before this standard was read.

What the theatre writes is (c), (f), (g) and (h). Then somebody signs (i).

---

**The timing is the standard's, not the program's.**

EOC 1: *"The procedure report is readily available for all patients who
underwent a procedure **before leaving the procedural unit**."* That is an
event this program already records, so :func:`late` can say plainly that a
report was written after the child had gone — without inventing a number of
minutes, which is what it would have had to do if the standard had said
"promptly".
"""
from datetime import datetime

from app.extensions import db
from app.models.operative_report import OperativeReport

#: The nine, in the standard's lettering. ``written`` names the columns a
#: person fills in; ``None`` means the record answers it already.
ELEMENTS = (
    ("a", "times", None),
    ("b", "staff", None),
    ("c", "diagnoses", ("pre_diagnosis", "post_diagnosis")),
    ("d", "procedure", None),
    ("e", "implants", None),
    ("f", "complications", ("complications",)),
    ("g", "specimen", ("specimen",)),
    ("h", "blood", ("blood_loss_ml",)),
    ("i", "signature", None),
)

#: What :func:`state` can answer.
STATES = ("none", "short", "unsigned", "complete")


def for_operation(operation):
    """This case's report, or ``None`` — and ``None`` is the finding."""
    return getattr(operation, "operative_report", None) if operation else None


def state(operation):
    """``none`` · ``short`` · ``unsigned`` · ``complete``.

    **``unsigned`` is its own word.** A complete report nobody has signed is
    not a complete report — element (i) is one of the nine — but it is a very
    different thing from a half-written one, and a screen that called both
    "short" would send the registrar back to boxes that are already filled.
    """
    row = for_operation(operation)
    if row is None:
        return "none"
    if row.blanks:
        return "short"
    return "complete" if row.signed else "unsigned"


def missing(operation):
    """Which written elements are still unanswered, in the standard's order."""
    row = for_operation(operation)
    if row is None:
        return list(OperativeReport.WRITTEN)
    return row.blanks


def late(operation):
    """Was the report written after the child left the unit? — EOC 1.

    ``None`` while either end is missing, which is not "on time": a case with
    no report and a case still in the unit are both simply unanswerable, and
    :func:`state` is where that shows.

    **The event is the standard's own.** It names *"before leaving the
    procedural unit"*, so the program compares against the moment it already
    records for that and invents no interval of its own.
    """
    row = for_operation(operation)
    left = getattr(operation, "discharged_at", None) if operation else None
    if row is None or left is None:
        return None
    return row.written_at > left


# ------------------------------------------------ what the record holds ---
def times(operation):
    """(a) — ``{"start", "end"}`` off the two stamps the theatre already makes."""
    return {"start": getattr(operation, "started_at", None),
            "end": getattr(operation, "finished_at", None)}


def staff(operation):
    """(b) — everybody the record names, including anaesthesia.

    Returns a list of ``{"role", "name"}``. ``team`` is free text and is
    carried through as one entry rather than parsed: the standard asks for the
    names, and a program splitting a sentence on commas would invent people.
    """
    if operation is None:
        return []
    out = []
    for role, person in (("surgeon", operation.surgeon),
                         ("anaesthetist", operation.anaesthetist)):
        if person is not None:
            out.append({"role": role, "name": person})
    if (operation.team or "").strip():
        out.append({"role": "team", "name": operation.team.strip()})
    return out


def implants(operation):
    """(e) — every implant with its lot and serial.

    Read straight off ``OperationImplant``, which has carried the batch number
    since SAS.06 (ز): *"including the batch number"* was answered before this
    standard was read.
    """
    from app.utils.facility import module_enabled

    if operation is None or not module_enabled("theatres"):
        return []
    from app.utils import theatres as theatre

    return [i for i in theatre.implants_for(operation)
            if i.state == "implanted"]


def assemble(operation):
    """All nine elements, each saying where its answer comes from.

    Returns ``{"letter", "key", "written", "filled"}`` in ACT-style order.
    ``filled`` means *this case has an answer* — for a derived element that
    the record holds something, for a written one that somebody wrote it.
    """
    row = for_operation(operation)
    stamps = times(operation)
    holds = {
        "times": bool(stamps["start"] and stamps["end"]),
        "staff": bool(staff(operation)),
        "procedure": bool((getattr(operation, "findings", "") or "").strip()),
        "implants": bool(implants(operation)),
        "signature": bool(row and row.signed),
    }
    out = []
    for letter, key, columns in ELEMENTS:
        if columns is None:
            filled = holds.get(key, False)
        else:
            filled = bool(row) and not any(c in row.blanks for c in columns)
        out.append({"letter": letter, "key": key,
                    "written": columns is not None, "filled": filled})
    return out


# ------------------------------------------------------- writing it ------
def write(operation, user=None, **fields):
    """Write or correct this case's report. Returns the row, or ``None``.

    Only the columns the standard asks a person for are accepted, plus the two
    notes — a caller cannot reach the stamps or move the report to another
    case by passing a keyword.

    **Not refused before the case has finished.** A registrar writing up as
    the skin is closed is the behaviour EOC 1 is asking for, and a program
    that made them wait would be pushing the writing later.
    """
    if operation is None:
        return None
    row = for_operation(operation)
    if row is None:
        # Through the relationship, not the foreign key: the line above has
        # just cached ``None`` on this operation, and setting ``operation_id``
        # alone would leave every later reader in this request — `sign` most
        # of all — believing the case still has no report. Twice learned.
        row = OperativeReport(operation=operation,
                              written_by=getattr(user, "id", None))
        db.session.add(row)
    for name in ("pre_diagnosis", "post_diagnosis", "complications_note",
                 "specimen_note"):
        if name in fields:
            setattr(row, name, (fields[name] or "").strip() or None)
    for name in ("complications", "specimen"):
        if name in fields:
            # Three states in, three states out. ``None`` means nobody said
            # and must survive the round trip.
            value = fields[name]
            setattr(row, name, None if value is None else bool(value))
    for name in ("blood_loss_ml", "transfused_units"):
        if name in fields:
            value = fields[name]
            # A zero is an answer. Only ``None`` is an absence — and a
            # **negative number is not an answer either**. The first draft
            # clamped it to nought, which is worse than storing the nonsense:
            # nought reads as «no measurable blood loss», a real and useful
            # clinical fact, so a typo would have been filed as a measurement
            # nobody took. Unanswered is the truth, and it leaves the element
            # blank on the card so somebody goes back to the box.
            if value is None or int(value) < 0:
                setattr(row, name, None)
            else:
                setattr(row, name, int(value))
    return row


def sign(operation, user=None, at=None):
    """The performing physician signs the report — element (i).

    **Refused on a case with no report**, and **stamped once**: a second press
    is somebody pressing twice, and moving the stamp would lose when the
    surgeon actually put their name to it.
    """
    row = for_operation(operation)
    if row is None or row.signed:
        return None
    row.signed_by = getattr(user, "id", None)
    row.signed_at = at or datetime.utcnow()
    return row


def unwritten():
    """Finished cases with no report — the queue behind EOC 1.

    Cases still in theatre are not on it: a report is owed *after* the
    procedure, and a list that counted them could never be cleared.

    **No date window.** The first draft took ``start`` and ``end``, and
    nothing ever passed them — a switch with no hand on it, which in this
    program is a promise nobody keeps. The queue is «what is owed», and a
    queue that could be filtered down to an empty week would be a way of not
    seeing the case from last month.
    """
    from app.models.theatre import Operation

    return (Operation.query
            .filter(Operation.status == "done")
            .outerjoin(OperativeReport,
                       OperativeReport.operation_id == Operation.id)
            .filter(OperativeReport.id.is_(None))
            .order_by(Operation.on_date.desc(), Operation.id.desc())
            .all())
