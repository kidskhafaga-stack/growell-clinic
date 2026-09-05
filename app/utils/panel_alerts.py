"""What each specialty asked the program to watch for, and what it can answer.

The survey's fourth question per specialty is *"متى ينبّهك البرنامج من نفسه؟"*,
and between them the answers name sixty alerts. They are not one kind of thing,
and treating them as one kind is how a screen ends up either silent or lying.

Sorted by what each actually needs — the classification lives in the catalogue
beside every alert, so a panel can say what it watches for even where nothing
watches yet:

``overdue``
    A date the program already holds. "The follow-up was booked and the child
    did not come." Nothing has to be invented; the appointment is in the file.

``trend``
    A comparison between two visits — EF lower than last time, seizures more
    than last month. No absolute number is needed, but two readings are, and
    which difference *matters* is often a number after all.

``number``
    A threshold the **clinic** sets. HbA1c above the figure you wrote,
    saturation below yours, ferritin over your limit. The survey refuses to
    supply one — its own answer for cardiology is *"لا يوجد رقم موحّد"* — and
    this program does not invent clinical numbers. So these are declared and do
    not fire until a clinic writes its figure down.

``cross_check``
    A drug, allergy or vaccine knowledge base the program does not have: "a
    medicine contraindicated in asthma was prescribed", "penicillin allergy
    before the antibiotic". Real, valuable, and not buildable by guessing.

``doctor``
    Something only a person can notice — a skill lost, a relapse. The program
    cannot deduce it and should not pretend to.

**The honesty is in saying which ran.** A panel that displayed six alert
headings and evaluated none of them would be worse than a panel with no alerts
at all: it would look like a safety net. What the screen shows is what actually
ran, and — to somebody who can act on it — what the rest are waiting for.

**And the waiting was the point that had been missed.** Twenty-two alerts were
declared as *"a threshold the clinic sets"* and there was **nowhere for a
clinic to set one**: the feature was built and no door led to it. Now each
answerable alert says in the catalogue what it *watches* — a lab result by its
code, a vital sign, a reading the panel itself takes, the child's age, or an
order that never came back — and a clinic writes the figure on a screen of
their own. Until they do, nothing fires, which is exactly where this started.

Nothing here invents a number. The catalogue says *what* to look at and the
clinic says *when to worry*, and neither half is any use without the other.
"""
from app.extensions import db
from app.utils import panels


def declared(key):
    """Every alert this specialty asked for, live or not."""
    return list((panels.panel(key) or {}).get("alerts") or [])


def _overdue_followup(patient_id):
    """A follow-up that was booked and did not happen.

    The one alert in the whole survey that needs no number and no new data: an
    appointment exists, its date has passed, and its status never became
    something that means the child arrived. Read against the clinic's own
    today, not the server's — the mistake that put three hours of every night's
    shifts on the wrong day was exactly this comparison done carelessly.
    """
    from app.models import Appointment
    from app.utils.clock import local_today

    # `no_show` and `scheduled` both mean the child did not come: one was
    # marked, the other was left as it was booked and the day went past. Read
    # from the status list rather than typed here, so a new status has to be
    # placed deliberately on one side or the other instead of quietly counting
    # as "attended".
    from app.models.appointment import APPOINTMENT_STATUSES

    CAME = {"in_progress", "completed"}
    CALLED_OFF = {"cancelled"}
    missed = [s for s in APPOINTMENT_STATUSES
              if s not in CAME and s not in CALLED_OFF]

    row = (Appointment.query
           .filter(Appointment.patient_id == patient_id,
                   Appointment.appt_date < local_today(),
                   Appointment.status.in_(missed))
           .order_by(Appointment.appt_date.desc())
           .first())
    if row is None:
        return None
    return {"date": row.appt_date, "days": (local_today() - row.appt_date).days}


#: The alerts that are actually evaluated, and the function that answers each.
#: Keyed by the code the catalogue uses, so a `live` flag in the data with no
#: entry here would be caught by a test rather than silently doing nothing.
LIVE = {
    "late": _overdue_followup,
    "lost_followup": _overdue_followup,
}


# --------------------------------------------------- the clinic's numbers ---
def rules():
    """``{(panel, code): rule}`` — every threshold this clinic has written.

    One query for the whole screen. The visit screen asks about several panels
    at once and there are never many rows: a clinic that has set thirty is a
    clinic that has thought hard about thirty alerts.
    """
    from app.models import PanelAlertRule

    return {(row.panel_key, row.alert_code): row
            for row in PanelAlertRule.query.all()}


def armed(key, code, known=None):
    """The clinic's number for this alert, or ``None`` when it has none.

    ``None`` is the common answer and the safe one — an alert with no number
    behind it does not fire, and never did.
    """
    rule = (known or rules()).get((key, code))
    return rule.threshold if rule is not None and rule.is_armed else None


def watchable(key):
    """This specialty's alerts the program could answer if a number existed.

    What the settings screen offers a box for. An alert with no ``watches`` in
    the catalogue is one the program cannot answer from what it holds, and
    offering a box for it would collect a number that changes nothing.
    """
    return [a for a in declared(key) if a.get("watches")]


# ------------------------------------------------------- reading a value ----
def _latest_lab(patient_id, code):
    """``(value, when)`` of the newest numeric result for a test code."""
    from app.models import Investigation, VisitInvestigation

    row = (VisitInvestigation.query
           .join(Investigation,
                 VisitInvestigation.investigation_id == Investigation.id)
           .filter(VisitInvestigation.patient_id == patient_id,
                   Investigation.code == code,
                   VisitInvestigation.result_value.isnot(None))
           .order_by(VisitInvestigation.resulted_at.desc(),
                     VisitInvestigation.id.desc())
           .first())
    if row is None:
        return None, None
    return row.result_value, (row.resulted_at or row.created_at)


def _latest_vital(patient_id, field):
    """``(value, when)`` of the newest recorded vital sign.

    Joined through the visit: a set of vitals belongs to a visit and carries
    neither the child nor a clock of its own, so the visit's date is the
    moment — which is the right one anyway, being the day it was measured.
    """
    from app.models import Visit, VitalSigns

    column = getattr(VitalSigns, field, None)
    if column is None:
        return None, None
    row = (db.session.query(VitalSigns, Visit.visit_date)
           .join(Visit, VitalSigns.visit_id == Visit.id)
           .filter(Visit.patient_id == patient_id, column.isnot(None))
           .order_by(Visit.visit_date.desc(), VitalSigns.id.desc())
           .first())
    if row is None:
        return None, None
    vitals, on_date = row
    from datetime import datetime

    return getattr(vitals, field), datetime.combine(on_date, datetime.min.time())


def _latest_panel(patient_id, code):
    """``(value, when)`` of the newest reading the panel itself took."""
    from app.models import Measurement

    row = (Measurement.query
           .filter(Measurement.patient_id == patient_id,
                   Measurement.code == code,
                   Measurement.value_num.isnot(None))
           .order_by(Measurement.recorded_at.desc(), Measurement.id.desc())
           .first())
    if row is None:
        return None, None
    return row.value_num, row.recorded_at


def _months_since(when, now=None):
    """Whole-ish months since a moment, or ``None`` when it never happened."""
    from datetime import datetime

    if when is None:
        return None
    return ((now or datetime.utcnow()) - when).days / 30.44


def _pending_order(patient_id, codes):
    """An investigation asked for and still unanswered — ``(days, name)``."""
    from datetime import datetime

    from app.models import Investigation, VisitInvestigation
    from app.models.visit import INVESTIGATION_OPEN

    row = (VisitInvestigation.query
           .join(Investigation,
                 VisitInvestigation.investigation_id == Investigation.id)
           .filter(VisitInvestigation.patient_id == patient_id,
                   Investigation.code.in_(codes),
                   VisitInvestigation.status.in_(INVESTIGATION_OPEN))
           .order_by(VisitInvestigation.created_at)
           .first())
    if row is None:
        return None
    return {"days": (datetime.utcnow() - row.created_at).days,
            "name": row.name}


def measure(patient_id, watches):
    """``(value, when)`` for whatever this alert watches, or ``(None, None)``.

    One place that knows how to read each source, so an alert added to the
    catalogue tomorrow needs no code at all — which is the promise the whole
    panel file is built on.
    """
    source = (watches or {}).get("source")
    of = (watches or {}).get("of") or ""
    if source == "lab":
        return _latest_lab(patient_id, of)
    if source == "vital":
        return _latest_vital(patient_id, of)
    if source == "panel":
        return _latest_panel(patient_id, of)
    if source == "age_months":
        from app.utils.dosing import age_months_of
        from app.models import Patient

        child = Patient.query.get(patient_id)
        return (age_months_of(child) if child is not None else None), None
    return None, None


def _fires(watches, value, when, threshold):
    """Whether this alert's condition is met. Returns the detail, or ``None``.

    Four comparisons and no fifth: above, below, how long since, and an order
    that never came back. A shape the catalogue cannot express is one the
    program refuses to guess at.
    """
    rule = (watches or {}).get("when")
    if rule == "above":
        if value is not None and value > threshold:
            return {"value": value, "limit": threshold, "at": when}
    elif rule == "below":
        if value is not None and value < threshold:
            return {"value": value, "limit": threshold, "at": when}
    elif rule == "since":
        # Never done at all is not "overdue by nothing" — it is the strongest
        # case of the same thing, and reporting silence would hide the child
        # who has never had the test the specialty follows them by.
        months = _months_since(when)
        if months is None or months > threshold:
            return {"months": None if months is None else round(months, 1),
                    "limit": threshold, "at": when}
    return None


def evaluate(patient_id, keys):
    """``[{key, code, label, detail}]`` — the alerts that actually fired.

    Only the live ones are evaluated. An alert declared and not implemented
    returns nothing at all rather than a cheerful "no problem found", because
    "we did not look" and "we looked and it is fine" are different answers and
    a screen that merged them would be the more dangerous of the two.
    """
    fired, seen, known = [], set(), rules()
    for key in keys:
        for alert in declared(key):
            code = alert.get("code")
            if code in seen:
                continue
            detail = None

            if alert.get("live"):
                check = LIVE.get(code)
                detail = check(patient_id) if check is not None else None
            elif alert.get("watches"):
                # **The clinic's own number, and nothing fires without one.**
                # A threshold alert with no row behind it is exactly as
                # dormant as it was before this existed, which is the state a
                # fresh install is in and stays in until somebody decides.
                limit = armed(key, code, known)
                if limit is not None:
                    detail = _answer(patient_id, alert, limit)

            if detail:
                seen.add(code)
                fired.append({"key": key, "code": code,
                              "label": alert.get("label_ar"),
                              "needs": alert.get("needs"), "detail": detail})
    return fired


def _answer(patient_id, alert, limit):
    """Whether this armed alert is firing for this child right now."""
    watches = alert.get("watches") or {}
    if watches.get("when") == "pending":
        # An order that never came back. The threshold is a number of days,
        # and the reading is the wait itself rather than any measurement.
        codes = [c.strip() for c in (watches.get("of") or "").split(",")
                 if c.strip()]
        found = _pending_order(patient_id, codes)
        if found and found["days"] > limit:
            return {"days": found["days"], "limit": limit,
                    "name": found["name"]}
        return None
    value, when = measure(patient_id, watches)
    return _fires(watches, value, when, limit)


def waiting(keys):
    """``{need: count}`` — what the rest are waiting on, for a person who can
    act on it. A clinic that has never set its numbers is one settings screen
    away from more alerts, and nothing anywhere said so.

    An alert the clinic **has** armed is not waiting for anything and is not
    counted: the whole point of the screen is that this number goes down as
    somebody works through it, and a count that never moved would say the
    setting had not worked.
    """
    counts, known = {}, rules()
    for key in keys:
        for alert in declared(key):
            if alert.get("live"):
                continue
            if alert.get("watches") and armed(key, alert["code"],
                                              known) is not None:
                continue
            counts[alert["needs"]] = counts.get(alert["needs"], 0) + 1
    return counts
