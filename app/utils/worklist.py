"""Everybody the clinic has a reason to write to today, as one list.

The reasons already existed, each on its own screen: a birthday page, a recall
page, a vaccine-reminder page. Three screens is three times somebody has to
remember to look, and the one nobody opens is the one that stops happening.

**Assembling them is the easy half.** The work is the gate, and it is the same
gate for all of them:

* the file is active — an archived one is off the clinic's books;
* the family has not opted out — the one rule that must never leak, because a
  list built by joining three sources is exactly where an opt-out gets lost;
* there is a number to write to;
* and nobody has already been sent this kind of message inside its own repeat
  guard, or the list never shrinks and stops being a work list.

Each reason keeps its own repeat guard because they are not the same length of
time. Chasing a lapsed family twice in a month is nagging; a vaccine dose that
is still not given a fortnight later is worth saying again; and a birthday can
only sensibly be said once a year.

Reading only. Nothing here sends anything — every row carries the endpoint that
already owns the sending, so there is one implementation of each message and
this is a view over them.
"""
from datetime import timedelta

from app.extensions import db
from app.models import MessageLog, Patient
from app.utils.clock import local_today

# How long each reason waits before it is worth saying again. Not one number:
# these are different conversations.
REPEAT_GUARD_DAYS = {
    "birthday": 300,      # once a year, with room for a late send
    "vaccine": 14,        # a dose still not given a fortnight later is worth repeating
    "recall": 180,        # chasing a lapsed family twice in a month is nagging
}

# The `template_type` each reason is logged under, so "have we already said
# this" is a question about the data rather than something a button remembers.
TEMPLATE_TYPES = {
    "birthday": "birthday",
    "vaccine": "vaccine_due",
    "recall": "patient_recall",
}

# How far ahead a birthday counts as "this week's work".
BIRTHDAY_AHEAD_DAYS = 7


def _sent_recently(kind, today=None):
    """Patient ids already sent ``kind`` inside its own repeat guard."""
    today = today or local_today()
    since = today - timedelta(days=REPEAT_GUARD_DAYS[kind])
    rows = (db.session.query(MessageLog.patient_id)
            .filter(MessageLog.template_type == TEMPLATE_TYPES[kind],
                    MessageLog.patient_id.isnot(None),
                    MessageLog.created_at >= since)
            .distinct().all())
    return {r[0] for r in rows}


def reachable(patient):
    """Whether the clinic may write to this patient at all.

    Three questions that have to be asked together and in one place. Asked
    separately on three screens, one of them eventually forgets the opt-out —
    and a message to somebody who asked not to be written to is the one
    failure here that cannot be taken back.
    """
    if patient is None or not patient.is_active:
        return False
    if patient.wa_opt_out:
        return False
    return bool(patient.contact_phone)


def _next_birthday(dob, today):
    """This year's birthday, or next year's if it has passed. Feb 29 → Feb 28."""
    try:
        nb = dob.replace(year=today.year)
    except ValueError:
        nb = dob.replace(year=today.year, day=28)
    if nb < today:
        try:
            nb = dob.replace(year=today.year + 1)
        except ValueError:
            nb = dob.replace(year=today.year + 1, day=28)
    return nb


def _birthdays(today, skip):
    rows = []
    horizon = today + timedelta(days=BIRTHDAY_AHEAD_DAYS)
    for patient in Patient.query.filter_by(is_active=True).all():
        if patient.id in skip or not patient.date_of_birth:
            continue
        if not reachable(patient):
            continue
        when = _next_birthday(patient.date_of_birth, today)
        if not (today <= when <= horizon):
            continue
        rows.append({
            "kind": "birthday",
            "patient": patient,
            "due": when,
            "days": (when - today).days,
            "detail": None,
            "endpoint": "messages.send_birthday",
            "kwargs": {"patient_id": patient.id},
            "method": "get",
        })
    return rows


def _vaccines(today, skip):
    """Doses already overdue. Not "due soon".

    A work list is what has to happen, and a dose due next week is a plan.
    Mixing the two makes the list long enough to stop being read, which is how
    the overdue ones get missed.
    """
    from app.utils.vaccine_due import due_list

    rows = []
    for row in due_list(status="overdue", today=today):
        patient = row.get("patient")
        if patient is None or patient.id in skip or not reachable(patient):
            continue
        # `due_list` normalises the date onto `due`; `due_date` is the raw
        # field it was built from and is not always a date object.
        when = row.get("due")
        rows.append({
            "kind": "vaccine",
            "patient": patient,
            "due": when,
            "days": (when - today).days if when else None,
            "detail": row.get("vaccine"),
            "endpoint": "vaccinations.reminders",
            "kwargs": {},
            "method": "get",
        })
    return rows


def _recalls(today, skip):
    from app.utils import recall as rc

    rows = []
    for patient, last_visit in rc.candidates(today=today):
        # `candidates` already applies its own guard and the opt-out; the
        # shared gate is applied anyway rather than trusted, because this list
        # is the place where one source quietly disagreeing with the others
        # would go unnoticed.
        if patient.id in skip or not reachable(patient):
            continue
        rows.append({
            "kind": "recall",
            "patient": patient,
            "due": last_visit,
            "days": (last_visit - today).days if last_visit else None,
            "detail": None,
            "endpoint": "messages.recall",
            "kwargs": {},
            "method": "get",
        })
    return rows


def today_list(today=None, limit=200):
    """The day's list, most overdue first.

    Sorted by how late the thing is rather than grouped by kind: a dose three
    months overdue and a birthday tomorrow are on the same list because the
    person working it has one morning, not three.
    """
    today = today or local_today()
    rows = []
    for kind, build in (("birthday", _birthdays),
                        ("vaccine", _vaccines),
                        ("recall", _recalls)):
        try:
            rows.extend(build(today, _sent_recently(kind, today)))
        except Exception:  # noqa: BLE001 - one broken source must not blank the list
            continue
    # `days` is negative for anything overdue and positive for anything ahead,
    # so ascending puts the latest thing at the top and today's birthday above
    # next week's. A row with no date sorts as though it were today.
    rows.sort(key=lambda r: (r["days"] if r["days"] is not None else 0))
    return rows[:limit]


def counts(today=None):
    """How many of each kind, for the desk. Same list, same gate."""
    out = {kind: 0 for kind in TEMPLATE_TYPES}
    for row in today_list(today=today):
        out[row["kind"]] = out.get(row["kind"], 0) + 1
    out["total"] = sum(out[k] for k in TEMPLATE_TYPES)
    return out
