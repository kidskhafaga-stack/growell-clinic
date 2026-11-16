"""One telephone call, as the clinic's switchboard reported it.

``CONNECTHUB_PLAN.md`` stage 6 — «التليفون (VoIP/CTI): حسب السنترال اللي عند
كل عميل». No two clinics have the same switchboard, so the program does not
speak any one of them: the switchboard tells **the program's own door** that a
call is ringing, was answered, or ended (``utils/telephony.py``), and every
switchboard that can call a web address on those events can be wired to it.

What is kept is what the switchboard said — the number, the extension, the
times — and what the clinic did about it: who returned a missed call, and
when. **No sound is recorded**: recording a call needs the caller told and
agreeing, and that is a decision for each clinic, not a default.
"""
from datetime import datetime

from app.extensions import db

DIRECTIONS = ("in", "out")
#: ringing → answered → ended; or ringing → missed.
STATUSES = ("ringing", "answered", "ended", "missed")


class PhoneCall(db.Model):
    __tablename__ = "phone_calls"

    id = db.Column(db.Integer, primary_key=True)
    # The switchboard's own id for the call, so the ring, the answer and the
    # hang-up land on one row however many times each is sent.
    call_ref = db.Column(db.String(120), unique=True, index=True,
                         nullable=False)
    direction = db.Column(db.String(4), nullable=False, default="in")
    # The other party, as international digits (``utils.whatsapp
    # .normalize_phone``) — the same form every other channel matches on.
    number = db.Column(db.String(32), index=True)
    raw_number = db.Column(db.String(64))
    extension = db.Column(db.String(20), index=True)
    status = db.Column(db.String(10), nullable=False, default="ringing")
    started_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    answered_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    # A missed call returned: by whom, when, and what was said.
    returned_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    returned_at = db.Column(db.DateTime)
    returned_note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    @property
    def seconds(self):
        if self.answered_at and self.ended_at:
            return max(int((self.ended_at - self.answered_at)
                           .total_seconds()), 0)
        return None
