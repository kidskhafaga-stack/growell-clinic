"""What the clinic looks like right now — one answer, two screens.

The appointments board asks it and so does the doctor's home, and they were
never going to stay the same answer written twice. It lived inside the board's
own module, so the dashboard could only have had a copy — and a copy is how a
clinic ends up with two screens disagreeing about how many children are
waiting.

The interesting number here is the second line of each card: not how many are
waiting, but **how long the one who has waited longest has been sitting
there**. That is the number that turns a complaint at the desk into something
the clinic saw coming, and it is why the moment is handed to the screen rather
than a count of minutes — a number rendered into the page freezes at whatever
it said when the page was drawn.
"""


def _red_flags(appointments):
    """``{appointment_id: flag}`` for the children who have vitals recorded.

    Only the ones still waiting or in the room: a completed visit's flag is
    history, and history on a live board is noise that teaches people to stop
    reading the colour.
    """
    from sqlalchemy.orm import selectinload

    from app.models import Visit
    from app.utils.red_flags import assess

    live = [a for a in appointments if a.status in ("waiting", "in_progress")]
    if not live:
        return {}
    # Newest first, so a child with more than one open visit is judged on the
    # one the nurse just filled rather than on whichever row the database
    # happened to return — which is an older, empty visit as often as not, and
    # produces a board that is silently blank about a feverish infant.
    visits = {}
    # The vitals come with the visit. `assess` reads them for every child in
    # the queue, so leaving them lazy is one query per waiting patient — on the
    # board, and now on the screen the program opens to. Caught by the
    # query-ceiling test, which is exactly the shape it was written for.
    for visit in (Visit.query
                  .options(selectinload(Visit.vitals))
                  .filter(Visit.patient_id.in_([a.patient_id for a in live]),
                          Visit.status == "open")
                  .order_by(Visit.created_at.desc(), Visit.id.desc()).all()):
        visits.setdefault(visit.patient_id, visit)

    out = {}
    for appt in live:
        visit = visits.get(appt.patient_id)
        flag = assess(appt.patient, getattr(visit, "vitals", None),
                      " ".join(filter(None, [
                          appt.reason, getattr(visit, "chief_complaint", "")])))
        if flag["level"]:
            out[appt.id] = flag
    return out


def _clinics_now(appointments, on_date, flags=None):
    """One card per عيادة that is running today — the whole-clinic view.

    Reception's question is never "who is the current patient"; there is no
    such person once two doctors are working. Their question is "what is the
    state of every عيادة right now", and the part of the answer nobody has
    today is the second line: how many are waiting for each doctor and **how
    long the worst of them has been sitting there**. That is the number that
    turns a complaint at the desk into something the clinic saw coming.

    Doctors with nothing booked today are left out — an empty card for a
    doctor who is off is noise on a screen that has to be read at a glance.
    """
    rooms = _rooms_on(on_date)
    by_doctor = {}
    for appt in appointments:
        by_doctor.setdefault(appt.doctor_id, []).append(appt)

    out = []
    for doctor_id, rows in by_doctor.items():
        waiting = [a for a in rows if a.status in ("waiting", "scheduled")]
        current = next((a for a in rows if a.status == "in_progress"), None)
        # The earliest check-in still waiting *is* the longest wait — handing
        # the screen that moment rather than a number of minutes lets the
        # counter keep ticking instead of freezing at whatever it said when
        # the page was drawn.
        checked_in = [a.checked_in_at for a in waiting if a.checked_in_at]
        out.append({
            "doctor": rows[0].doctor,
            "room": rooms.get(doctor_id),
            "current": current,
            "waiting": len(waiting),
            "longest_since": min(checked_in) if checked_in else None,
            # How many in this عيادة's queue should not be waiting. Reception
            # watches the whole clinic and is the one who can go and knock.
            "urgent": sum(1 for a in rows
                          if (flags or {}).get(a.id, {}).get("level") == "urgent"),
            "done": sum(1 for a in rows if a.status == "completed"),
        })
    # Busy عيادات first — the ones with somebody inside, then by queue length,
    # so the screen puts what needs attention where the eye lands.
    out.sort(key=lambda c: (c["current"] is None, -c["waiting"],
                            c["doctor"].display_name() if c["doctor"] else ""))
    return out


def _rooms_on(on_date):
    """``{doctor_id: ClinicRoom}`` for one day, from the daily assignments."""
    from app.models import RoomAssignment

    rows = (RoomAssignment.query.filter(RoomAssignment.on_date == on_date)
            .join(RoomAssignment.room).all())
    return {row.doctor_id: row.room for row in rows}
