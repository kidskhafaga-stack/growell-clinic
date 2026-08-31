"""Read-only mode: the program without a licence, and the guard that means it.

An unlicensed or lapsed copy still shows everything. What it will not do is
write, and *write* here means what reaches the database — not what looks like
a form.

**Why the guard sits on the session and not on the request method.** The
obvious implementation refuses POST, PUT, PATCH and DELETE and calls it done.
That is a read-only mode that writes: eighteen screens in this program change
something on a plain GET — a visit starts, an appointment is confirmed, a
message thread is opened, a certificate is stamped as printed — and every one
of them would have gone straight through. So the rule is stated once, at the
point where a row is actually inserted, updated or deleted, and there is no
route it can be forgotten on and no future route it can be forgotten on
either.

**What is still allowed.** Signing in, signing out, and the licence screen
itself. Those are how somebody reaches their data and how they fix the
problem; a lock that stopped them would be a lock on the recovery. They are
named by endpoint rather than by table, because the question is which *act*
is permitted, not which rows it happens to touch — and an endpoint list is
readable in one screen, which a table list would not be.

Nothing here runs outside a request. Seeding, migrations, the CLI, the
scheduled backup and the test suite build the world with no request in flight
and are untouched.
"""
from flask import g, has_request_context, request

# Endpoints that keep working while the program is locked.
#
# Deliberately short. Each one is here because refusing it would trap somebody
# rather than restrain them.
ALWAYS_ALLOWED = {
    "static",
    "auth.login",      # writes the sign-in audit row and last_login_at
    "auth.logout",
    "main.set_theme",  # a display preference, not the clinic's data
    "auth.set_language",
}

# Whole prefixes, for the licence screens — the way out of read-only must not
# itself be read-only.
#
# A prefix rather than a list of endpoints, and that is the whole reason there
# is no per-route escape hatch here. An exemption a route opts into is one a
# later route in the same area forgets to opt into, and the forgetting is
# silent: the screen 403s only for the clinics that are actually locked out,
# which is the one situation nobody is testing in.
ALLOWED_PREFIXES = ("settings.licence",)

_ASKING = "_read_only_asking"


class ReadOnlyError(RuntimeError):
    """A write refused because this copy is not licensed."""


def permitted():
    """Whether writes are allowed for whatever is happening right now."""
    if not has_request_context():
        # A CLI command, a scheduled job, the test suite's own setup. There is
        # no user here to lock out and no screen to explain it on.
        return True
    endpoint = request.endpoint or ""
    if endpoint in ALWAYS_ALLOWED:
        return True
    return endpoint.startswith(ALLOWED_PREFIXES)


def _blocked(session):
    """The rows this flush would really change, if any.

    ``Session.dirty`` is optimistic — assigning an attribute the value it
    already had puts an object in it — so it is asked again per object. A
    read-only mode that refused a page for touching nothing would be a bug
    nobody could reproduce.
    """
    if session.new or session.deleted:
        return True
    return any(session.is_modified(obj, include_collections=True)
               for obj in session.dirty)


def install(app, db):
    """Arm the guard on this application's session."""
    from sqlalchemy import event

    @event.listens_for(db.session, "before_flush")
    def _refuse_writes(session, flush_context, instances):  # noqa: ARG001
        if not _blocked(session):
            return
        if permitted():
            return
        # Working out the verdict reads the clinic's timezone, which is a
        # query, which autoflushes, which arrives back here with the same
        # pending rows. Without this the first blocked write recurses until
        # Python gives up — and the traceback blames the timezone.
        if getattr(g, _ASKING, False):
            return
        setattr(g, _ASKING, True)
        try:
            from app.utils.licensing import locked

            if not locked():
                return
        finally:
            setattr(g, _ASKING, False)
        raise ReadOnlyError("licence")

    @app.errorhandler(ReadOnlyError)
    def _explain(error):  # noqa: ARG001
        from flask import render_template

        db.session.rollback()
        return render_template("errors/read_only.html"), 403
