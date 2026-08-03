"""Making a user out of a doctor the file names and the clinic does not have.

The decision was taken with the plan and the reasoning has not changed: every
report built this month joins on ``doctor_id`` — the doctor filter on the
invoices screen, the doctor column in the tax export, the commission reports,
the doctor statements. A name kept as text on the row falls out of all of them,
which leaves a clinic holding ten years of a doctor's work that no report can
see.

Three things make it safe rather than merely convenient:

**The account cannot be used.** It is created inactive, with a random password
nobody is told. Nothing can be signed in to, so creating one is not a way in.

**It is never automatic.** It is one option in a dropdown, on a screen listing
every doctor in the file, and the preview names who will be created before
anything is written. Matching an existing user stays the default — creating is
what is left when nothing matches, which is the same rule the categories and
the services follow.

**And one person is one user.** Grouping is by the source's own doctor code
where the file has one, because a name gets typed several ways across a decade
and creating a user per spelling is the failure this is supposed to prevent.
"""
import re
import secrets

# What survives into a username. Arabic names give nothing here, which is fine:
# the fallback is a numbered login, and the name people read is ``full_name``.
_ASCII = re.compile(r"[^a-z0-9]+")


def username_for(name, taken):
    """A free username for an imported doctor.

    ``taken`` is the set of usernames already in use; it is passed in so a
    whole file's worth of doctors can be created without a query per name.
    """
    base = _ASCII.sub(".", (name or "").strip().lower()).strip(".")
    base = base[:40] or "doctor"
    if base not in taken:
        return base
    for suffix in range(2, 1000):
        candidate = f"{base}.{suffix}"
        if candidate not in taken:
            return candidate
    return f"{base}.{secrets.token_hex(4)}"


def create_doctor(name, taken=None):
    """An inactive practitioner user carrying the file's name.

    Not committed here — the caller commits once, with the rows, so a failed
    import does not leave users behind for doctors whose history never landed.
    """
    from app.extensions import db
    from app.models import User

    if taken is None:
        taken = {row[0] for row in db.session.query(User.username).all()}

    username = username_for(name, taken)
    taken.add(username)
    user = User(username=username, full_name=(name or username)[:120],
                role="doctor", is_practitioner=True, is_active=False,
                job_title=None)
    # Random and never shown. The account is inactive, so this only exists
    # because the column cannot be null — there is no password to leak.
    user.set_password(secrets.token_urlsafe(32))
    db.session.add(user)
    return user


def create_all(names, taken=None):
    """``{name: user}`` for a whole screen's worth of "create this one".

    One query for the existing usernames however many are created, and one
    flush at the end so the caller gets ids without committing.
    """
    from app.extensions import db
    from app.models import User

    names = [n for n in names if (n or "").strip()]
    if not names:
        return {}
    if taken is None:
        taken = {row[0] for row in db.session.query(User.username).all()}
    made = {name: create_doctor(name, taken) for name in names}
    db.session.flush()
    return made
