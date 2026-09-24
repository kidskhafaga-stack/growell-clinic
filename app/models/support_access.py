"""A door the owner opens — the developer's account.

Asked for in these words: «يوزر للمبرمج ده يعمل أي شيء في البرنامج، يضيف
مديول، يعدّل … والأمان مهم».

**An account that can do anything, in a hospital that is running, is the most
dangerous thing the program could hold** — so it is not an account that is
always there. It is a door:

* the account exists, and **cannot sign in** unless the owner has opened a
  window for it — for a length of time the owner chose, with a reason the
  owner wrote;
* inside the window it holds the owner's powers, so a module can be switched
  on, a setting changed, a list rebuilt — the work it was asked in for;
* the window closes itself when its time is up, and the owner can close it
  sooner; a closed window signs the account out on its next click, even one
  that ticked "remember me";
* **every page opened and every change saved inside it is written down**, in
  tables the data reset does not empty — "start again" starts the clinic's
  work again, it does not erase that somebody from outside was in.

And a handful of things stay the owner's alone even inside a window, because
each is a way to leave without a trace or to come back without a door:
making, changing or removing staff accounts; wiping the data; restoring a
backup over the live database; installing a licence; and this door itself.
"""
from datetime import datetime

from app.extensions import db

#: How long the owner may open the door for, in hours. A security choice the
#: owner makes from a short list — long enough for a morning's work, never a
#: standing arrangement.
DURATIONS = (1, 4, 8, 24)


class SupportWindow(db.Model):
    """One time the owner let the developer in."""

    __tablename__ = "support_windows"

    id = db.Column(db.Integer, primary_key=True)
    #: The developer's account this window is for. One window, one account:
    #: a door opened for one person is not open for everybody.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                        nullable=False, index=True)
    reason = db.Column(db.String(255), nullable=False)
    opened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    opened_by = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    closed_at = db.Column(db.DateTime)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    user = db.relationship("User", foreign_keys=[user_id])
    opener = db.relationship("User", foreign_keys=[opened_by])
    closer = db.relationship("User", foreign_keys=[closed_by])
    actions = db.relationship("SupportAction", back_populates="window",
                              order_by="SupportAction.at",
                              cascade="all, delete-orphan")

    def open_at(self, now=None):
        now = now or datetime.utcnow()
        return self.closed_at is None and now < self.expires_at

    @property
    def ended_at(self):
        """When it actually stopped — closed early, or ran out."""
        if self.closed_at is not None:
            return min(self.closed_at, self.expires_at)
        return self.expires_at


class SupportAction(db.Model):
    """One thing the developer did inside a window."""

    __tablename__ = "support_actions"

    id = db.Column(db.Integer, primary_key=True)
    window_id = db.Column(db.Integer, db.ForeignKey("support_windows.id"),
                          nullable=False, index=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    method = db.Column(db.String(8), nullable=False)
    #: The screen's name in the program and the address, **without** the
    #: query string: a search box's words are a child's name, and this log is
    #: read by people who have no business reading those.
    endpoint = db.Column(db.String(120))
    path = db.Column(db.String(255))
    status = db.Column(db.Integer)
    #: Refused because it is the owner's alone — kept, because an attempt is
    #: the line in this log somebody most needs to see.
    refused = db.Column(db.Boolean, default=False, nullable=False)
    ip_address = db.Column(db.String(45))

    window = db.relationship("SupportWindow", back_populates="actions")
