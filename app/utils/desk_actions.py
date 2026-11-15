"""Customer service that takes action — through the desk's own door.

``HOSPITAL_PLAN.md`` ٦ «خدمة العملاء بالذكاء الاصطناعي، وهي بتاخد أكشن». The
step after a suggested reply: the family asks to cancel, to move the visit,
whether the result is out, what they still owe — and the answer is an action
or a fact, not a sentence the desk has to go and look up.

The rules the plan agreed before any of this was written:

* **the program prepares, a person does.** It reads what the family asked
  and puts the action in front of the person on the conversation; cancelling
  is their press, the reply is theirs to edit and send. Nothing goes to the
  family, and no booking moves, on its own;
* **with that person's permissions, not open ones.** An action or a fact is
  offered only to someone who could have done or seen it on its own screen:
  the bookings to whoever reaches the appointments, a result's *state* to
  whoever reaches the laboratory or the medical file, the balance to whoever
  works the till;
* **a result's state, never the result.** «لسه» / «طلعت والدكتور بيراجعها» /
  «جاهزة» — the numbers go to the family the way the laboratory sends them
  (`lab_share`), after the doctor has seen them, or not at all.

Reading the request is a word list, on purpose: it is shown to the person as
«the family seems to be asking to …», they can see why, and it is the same
answer tomorrow. The model drafts the reply; it does not decide the action.
"""
import re
from datetime import timedelta

from app.extensions import db

#: The few things a family asks the desk to *do* or to *tell*, and the words
#: that say so — the Egyptian the desk receives, and English. Normalised the
#: same way the message is (:func:`_norm`), so «إلغاء» and «الغاء» are one.
WORDS = {
    "cancel": ("الغي", "الغاء", "هلغي", "نلغي", "مش هقدر اجي", "مش هنقدر نيجي",
               "مش هنيجي", "مش جايين", "مش هنقدر نحضر", "cancel"),
    "reschedule": ("اغير الميعاد", "تغيير الميعاد", "نغير الميعاد",
                   "ميعاد تاني", "يوم تاني", "اجل", "تاجيل", "نأجل", "نوخر",
                   "اقدم الميعاد", "نقدم الميعاد", "reschedule", "postpone",
                   "another day"),
    "result": ("النتيجه", "نتيجه", "التحليل", "تحليل", "التحاليل", "الاشعه",
               "result"),
    "balance": ("عليا كام", "علينا كام", "عليه كام", "المتبقي", "الباقي كام",
                "حسابي", "الحساب كام", "الفاتوره", "balance", "how much do we owe"),
}
INTENTS = tuple(WORDS)

#: How far back a test is still "the result" a family is asking about.
RESULT_DAYS = 45

_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟـ]")


def _norm(text):
    text = _DIACRITICS.sub("", (text or "").lower())
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي"),
                 ("ؤ", "و"), ("ئ", "ي")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text)


_NORMED = {k: tuple(_norm(w) for w in v) for k, v in WORDS.items()}


def intents(text):
    """What the family seems to be asking for, in a fixed order, with the
    word that said so: ``[(intent, word), …]``."""
    said = _norm(text)
    found = []
    for intent in INTENTS:
        hit = next((w for w in _NORMED[intent] if w and w in said), None)
        if hit:
            found.append((intent, hit))
    # «I can't come, can we do another day» is a move, not a cancellation.
    names = [i for i, _w in found]
    if "cancel" in names and "reschedule" in names:
        found = [f for f in found if f[0] != "cancel"]
    return found


# ------------------------------------------------- who may see what ------
def may_book(user):
    return bool(user and user.is_authenticated
                and user.can_access("appointments"))


def may_see_results(user):
    return bool(user and user.is_authenticated
                and (user.can_access("labs") or user.can("patient_medical")))


def may_see_balance(user):
    return bool(user and user.is_authenticated
                and getattr(user, "can_collect", False))


# ------------------------------------------------------------- facts -----
def upcoming(patient_ids):
    """The family's bookings still to come, soonest first."""
    from app.models import Appointment
    from app.utils.clock import local_today

    if not patient_ids:
        return []
    return (Appointment.query
            .filter(Appointment.patient_id.in_(patient_ids),
                    Appointment.appt_date >= local_today(),
                    Appointment.status.notin_(("cancelled", "no_show",
                                               "completed")))
            .order_by(Appointment.appt_date, Appointment.appt_time).all())


def result_state(order):
    """``waiting`` / ``with_doctor`` / ``ready`` — the state, never the value.

    *Ready* is what the laboratory's own rule lets go to the family: written,
    released where the hospital asks for release, seen by the doctor, and —
    for a critical or sensitive one — the family already called
    (`lab_share`). Anything short of that is with the doctor."""
    from app.utils import lab_release, lab_share

    if not order.has_result:
        return "waiting"
    if lab_release.awaiting(order):
        return "with_doctor"
    if order.doctor_seen_at is None:
        return "with_doctor"
    if lab_share.held(order):
        return "with_doctor"
    return "ready"


def recent_tests(patient_ids):
    from datetime import datetime

    from app.models import VisitInvestigation

    if not patient_ids:
        return []
    since = datetime.utcnow() - timedelta(days=RESULT_DAYS)
    return (VisitInvestigation.query
            .filter(VisitInvestigation.patient_id.in_(patient_ids),
                    VisitInvestigation.done_outside.is_(False),
                    VisitInvestigation.created_at >= since)
            .order_by(VisitInvestigation.created_at.desc()).limit(10).all())


def owed(patient_ids):
    """``(total, [invoice, …])`` still owed by the family."""
    from app.models import Invoice

    if not patient_ids:
        return 0.0, []
    rows = [i for i in (Invoice.query
                        .filter(Invoice.patient_id.in_(patient_ids),
                                Invoice.status != "refunded").all())
            if (i.balance or 0) > 0]
    return round(sum(i.balance for i in rows), 2), rows


# ------------------------------------------------------- the panel -------
def panel(user, patients, text, lang="ar"):
    """What the person on this conversation can do about what was asked.

    ``patients`` are the children on this conversation (siblings on one
    number included). Every block is ``None`` when the person could not have
    seen or done it on its own screen — not empty, absent.
    """
    from app.i18n import t
    from app.utils.money import format_money

    ids = [p.id for p in patients if p is not None]
    names = {p.id: p.display_name(lang) for p in patients if p is not None}
    asked = intents(text)
    out = {"asked": asked, "names": names,
           "bookings": None, "tests": None, "balance": None, "drafts": {}}

    if may_book(user):
        rows = upcoming(ids)
        out["bookings"] = rows
        if rows:
            first = rows[0]
            out["drafts"]["booking"] = t(
                "desk_act.d_booking", child=names.get(first.patient_id, ""),
                date=first.appt_date.isoformat(), time=first.time_label,
                doctor=(first.doctor.display_name(lang)
                        if first.doctor else ""))
    if may_see_results(user):
        tests = [(o, result_state(o)) for o in recent_tests(ids)]
        out["tests"] = tests
        if tests:
            lines = [t("desk_act.d_result_" + state,
                       test=o.display_name(lang))
                     for o, state in tests[:4]]
            out["drafts"]["result"] = "\n".join(lines)
    if may_see_balance(user):
        total, rows = owed(ids)
        out["balance"] = {"total": total, "invoices": rows}
        out["drafts"]["balance"] = (
            t("desk_act.d_balance", v=format_money(total)) if total
            else t("desk_act.d_balance_none"))
    return out


def cancel(appointment, user, reason=None, lang="ar"):
    """Cancel a booking the family asked to cancel on the conversation —
    the same steps the board's own «إلغاء» takes: the status, the reminders
    that would have told them to come, and the queue behind them."""
    from app.utils import appt_reminder as reminders
    from app.utils import queue_turns

    if appointment is None or not appointment.can_transition_to("cancelled"):
        return False
    appointment.cancel_reason = (reason or "").strip()[:200] or None
    appointment.apply_status("cancelled")
    reminders.resync(appointment, user_id=getattr(user, "id", None),
                     lang=lang)
    queue_turns.after_change(appointment, user_id=getattr(user, "id", None),
                             lang=lang)
    db.session.flush()
    return True
