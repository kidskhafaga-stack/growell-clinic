"""One money form, sent once (MONEY_SAFETY_PLAN.md ف-٣).

Measured before it was written: the collection form sent twice — a resend
from the back button, a network retry, a second click after the browser's
four-second guard — put the exam on the bill twice and took 400 for a visit
of 200. Nothing in the form itself can tell it apart from a second exam on
the same day, so the form is given a name of its own.

* ``form_key()`` (a template global) makes a fresh key each time a page is
  drawn; the form carries it hidden.
* ``@once_per_form`` writes the key **before the view runs, in the view's own
  save**. If the view saves, the key is saved with the bill; if the view
  rolls back (nothing to collect, a closed month), the key goes with it and
  the same form can be sent again.
* The same key arriving again — one after the other, or at the same instant
  (the second waits on the first's save and then finds the key) — is not
  done again: the cashier is sent to where the first one went, and told.

A form without a key (an old page still open, a test) works as it always did.
"""
import re
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import flash, redirect, request, url_for
from flask_login import current_user
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app.extensions import db

_SHAPE = re.compile(r"^[0-9a-f]{32}$")
#: Keys older than this are let go — a page left open for a month and sent
#: is a new decision, and the table should not grow for ever.
KEEP_DAYS = 30


def form_key():
    return uuid.uuid4().hex


def _back(row):
    if row is not None and row.went_to:
        return row.went_to
    return request.referrer if (request.referrer or "").startswith(request.host_url) \
        else url_for("finance.cashier")


def _already():
    from app.i18n import t

    flash(t("forms.already_sent"), "warning")


def once_per_form(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        from app.models import FormKey

        key = (request.form.get("form_key") or "").strip().lower() \
            if request.method == "POST" else ""
        if not _SHAPE.match(key):
            return view(*args, **kwargs)
        seen = db.session.get(FormKey, key)
        if seen is not None:
            _already()
            return redirect(_back(seen))
        db.session.add(FormKey(key=key, user_id=getattr(current_user, "id", None)))
        try:
            db.session.flush()
        except IntegrityError:
            # Sent twice at the same instant: the other one saved first.
            db.session.rollback()
            _already()
            return redirect(_back(db.session.get(FormKey, key)))
        # The key is kept only if the view itself saved: a view that turned
        # the form away without saving leaves nothing — and the same form may
        # be sent again.
        session = db.session()
        saved = []

        def mark(_session):
            saved.append(True)

        event.listen(session, "after_commit", mark)
        try:
            response = view(*args, **kwargs)
        finally:
            event.remove(session, "after_commit", mark)
        if not saved:
            db.session.rollback()
            return response
        row = db.session.get(FormKey, key)
        if row is not None:
            if getattr(response, "status_code", 200) in (301, 302, 303):
                row.went_to = (response.headers.get("Location") or "")[:255] or None
            # Let go of the old ones while here.
            FormKey.query.filter(FormKey.created_at < datetime.utcnow()
                                 - timedelta(days=KEEP_DAYS)).delete(
                synchronize_session=False)
            db.session.commit()
        return response
    return wrapped


def init_app(app):
    app.jinja_env.globals["form_key"] = form_key
