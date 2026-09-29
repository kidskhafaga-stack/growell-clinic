"""Who works in a unit, and who opened a child's stay there without being one.

Asked as: *«إيه رأيك نخلّي كل قسم مقصور على التمريض والأطباء بتوعه؟»*.

**Off until a unit says otherwise.** A unit with nobody listed is open to
everybody who reaches the beds, exactly as before — nothing that works today
stops working the morning this arrives. List its team and it closes to the
rest.

**Closed is not locked.** At three in the morning the doctor on call covers
every unit, and a door that will not open is a child nobody can read about.
So anybody with the beds module can still open a stay in a unit that is not
theirs — by saying why (``BreakGlass``). The reason and the name are written
down, the manager can read them, and the access lasts a shift, not forever.
"""
from datetime import datetime

from app.extensions import db


class UnitStaff(db.Model):
    """One person on one unit's team."""
    __tablename__ = "unit_staff"
    __table_args__ = (db.UniqueConstraint("unit_id", "user_id",
                                          name="uq_unit_staff"),)

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"),
                        nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                        nullable=False, index=True)
    added_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])


class BreakGlass(db.Model):
    """Somebody not on a unit's team opened a stay in it, and said why."""
    __tablename__ = "break_glass"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"),
                        nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                        nullable=False, index=True)
    reason = db.Column(db.String(255), nullable=False)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)

    user = db.relationship("User")
    admission = db.relationship("Admission")
