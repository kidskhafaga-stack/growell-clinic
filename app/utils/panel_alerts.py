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

**Two are live, and the honesty is in saying so.** A panel that displayed six
alert headings and evaluated none of them would be worse than a panel with no
alerts at all: it would look like a safety net. What the screen shows is what
actually ran, and — to somebody who can act on it — what the rest are waiting
for.
"""
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


def evaluate(patient_id, keys):
    """``[{key, code, label, detail}]`` — the alerts that actually fired.

    Only the live ones are evaluated. An alert declared and not implemented
    returns nothing at all rather than a cheerful "no problem found", because
    "we did not look" and "we looked and it is fine" are different answers and
    a screen that merged them would be the more dangerous of the two.
    """
    fired, seen = [], set()
    for key in keys:
        for alert in declared(key):
            code = alert.get("code")
            if not alert.get("live") or code in seen:
                continue
            check = LIVE.get(code)
            if check is None:
                continue
            detail = check(patient_id)
            if detail:
                seen.add(code)
                fired.append({"key": key, "code": code,
                              "label": alert.get("label_ar"), "detail": detail})
    return fired


def waiting(keys):
    """``{need: count}`` — what the rest are waiting on, for a person who can
    act on it. A clinic that has never set its numbers is one settings screen
    away from eleven more alerts, and nothing anywhere said so."""
    counts = {}
    for key in keys:
        for alert in declared(key):
            if alert.get("live"):
                continue
            counts[alert["needs"]] = counts.get(alert["needs"], 0) + 1
    return counts
