"""What the desk's screens do for the channels while they refresh.

There is no scheduler in this program: the day board and the till already
poll all day, and the WhatsApp queue rides on them. After each of those
answers — never before, so no screen waits on a mail server — this:

* reads the clinic's mailbox, at most every few minutes
  (``mail_channel.maybe_poll``, its turn taken with ``Setting.swap``);
* renews Instagram's 60-day token when it is near its end
  (``social.instagram_token``), so an account nobody answered for a month
  does not quietly go dark.
"""


def _beat():
    from app.utils import mail_channel, social

    mail_channel.maybe_poll()
    if social.instagram_mode() == "login" and social.instagram_ready():
        social.instagram_token()
        from app.extensions import db
        db.session.commit()


def after_response(response):
    from flask import current_app

    app = current_app._get_current_object()

    def work():
        with app.app_context():
            try:
                _beat()
            except Exception:  # noqa: BLE001 — a heartbeat never breaks a screen
                from app.extensions import db
                db.session.rollback()
    response.call_on_close(work)
    return response


__all__ = ["after_response"]
