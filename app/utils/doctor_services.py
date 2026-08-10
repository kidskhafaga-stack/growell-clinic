"""Which services a doctor actually performs.

Asked for in these words: mark the services a doctor provides so they are not
lost among services that do not exist for them. A clinic's catalogue grows to
cover everybody — nebuliser sessions, spirometry, ear piercing, a dozen lab
panels — and each doctor does a handful of them. The rest are noise in front
of the one they are looking for, every visit, all day.

**The rule that matters is what an unmarked doctor means.**

A doctor with no marks at all performs **everything**. Silence has to mean
"nobody has filled this in", never "provides nothing" — a clinic that upgrades
and has not yet been through the doctors would otherwise find every service
list on every screen empty, on a working morning, with patients in the room.
That is the failure this module exists to make impossible, and it is why the
rule lives in one function instead of being re-decided at each call site.

**Nothing is hidden, either.** Marked services come first and the rest stay in
the list behind a heading. Reception covering an unusual case, a doctor filling
in for a colleague, a service somebody genuinely does once a year — none of
them should hit a wall built out of a convenience feature. The complaint was
about *searching*, so the fix is about order, not about permission.
"""


def marked_ids(doctor):
    """Service ids this doctor is marked as performing (possibly empty)."""
    if doctor is None:
        return set()
    doctor_id = getattr(doctor, "id", doctor)
    if doctor_id is None:
        return set()
    try:
        from app.models import DoctorServiceCommission

        rows = (DoctorServiceCommission.query
                .filter(DoctorServiceCommission.doctor_id == doctor_id,
                        DoctorServiceCommission.provides.is_(True))
                .all())
        return {row.service_id for row in rows}
    except Exception:                                       # pragma: no cover
        # A service list is not worth a 500. Falling back to "unmarked" shows
        # the whole catalogue, which is exactly what happened before this.
        return set()


def has_marks(doctor):
    """Has anybody said what this doctor does?"""
    return bool(marked_ids(doctor))


def split(doctor, services):
    """``(mine, others)`` for a list of services, in the order given.

    An unmarked doctor gets everything in ``mine`` and nothing in ``others``,
    so a caller can render the two groups without ever asking whether the
    clinic has set this up.
    """
    services = list(services or [])
    ids = marked_ids(doctor)
    if not ids:
        return services, []
    mine = [s for s in services if s.id in ids]
    others = [s for s in services if s.id not in ids]
    return mine, others
