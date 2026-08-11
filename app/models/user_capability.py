"""One person allowed one thing their role is not.

Asked for in these words: *"the reception does certain things in finance"* —
without handing the whole reception role a finance capability, and without
inventing a role called "reception+" that somebody has to explain to every new
employee.

**Why this and not a new role.** A role answers "what does this job do"; a
grant answers "what is Sara allowed". Answering the second with the first
means a new role every time one person is trusted with one extra thing, and
after a year the clinic has nine roles nobody can tell apart.

**Grants only, never revocations.** This table can add a capability to a
person and cannot take one away. A revocation would make a role's own list
unreadable — you could no longer tell what a role does without checking every
holder of it — and the way to stop somebody doing something they should not is
to change their role, out in the open, where the whole clinic's permissions
are drawn on one screen.

**Who granted it and when is the point, not decoration.** The reason an
exception stays legible is that a year later somebody can see it was a
decision and whose. A capability that leaks into a role is one nobody
remembers agreeing to.
"""
from datetime import datetime

from app.extensions import db


class UserCapability(db.Model):
    __tablename__ = "user_capabilities"
    __table_args__ = (
        db.UniqueConstraint("user_id", "capability", name="uq_user_capability"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                        nullable=False, index=True)
    # One of app.models.permissions.CAPABILITIES. Validated where it is
    # granted rather than here, so an old row whose capability was later
    # renamed simply stops matching instead of breaking the screen.
    capability = db.Column(db.String(40), nullable=False, index=True)

    reason = db.Column(db.String(200))
    granted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    granted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id],
                           backref="extra_capabilities")
    granter = db.relationship("User", foreign_keys=[granted_by])

    def __repr__(self):
        return f"<UserCapability u={self.user_id} {self.capability}>"
