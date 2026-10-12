"""Environmental cleaning and disinfection — GAHAR IPC.09.

*"Cleaning activities and times are listed for each area. The schedule must
address environmental cleaning activities for each area as follows: i.
Activities to be done every day. ii. Activities to be done every shift.
iii. Deep cleaning activities"* — and the policy names (a) the risk areas,
(c) the frequency, (d) the disinfectant, (e) the method.

So an **area** carries the hospital's risk level for it, and each **task**
in it says what is done, how often (every shift, every day, or deep — deep
every so many days, the hospital's figure), with what and how. A task done
is a row with who and when. Nothing is preset: the areas, the tasks and
every interval are infection control's.
"""
from datetime import datetime

from app.extensions import db

RISKS = ("high", "medium", "low")
FREQUENCIES = ("shift", "daily", "deep")


class CleaningArea(db.Model):
    __tablename__ = "cleaning_areas"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"), index=True)
    risk = db.Column(db.String(8), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    unit = db.relationship("Unit")
    tasks = db.relationship("CleaningTask", back_populates="area",
                            order_by="CleaningTask.id", cascade="all, delete-orphan")


class CleaningTask(db.Model):
    __tablename__ = "cleaning_tasks"

    id = db.Column(db.Integer, primary_key=True)
    area_id = db.Column(db.Integer, db.ForeignKey("cleaning_areas.id"), nullable=False, index=True)
    activity = db.Column(db.String(200), nullable=False)
    frequency = db.Column(db.String(6), nullable=False)
    #: For deep cleaning — every how many days (the hospital's).
    every_days = db.Column(db.Integer)
    disinfectant = db.Column(db.String(160))
    method = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    area = db.relationship("CleaningArea", back_populates="tasks")
    done = db.relationship("CleaningDone", back_populates="task",
                           order_by="CleaningDone.done_at.desc()", lazy="dynamic")


class CleaningDone(db.Model):
    __tablename__ = "cleaning_done"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("cleaning_tasks.id"), nullable=False, index=True)
    done_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    done_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.String(255))

    task = db.relationship("CleaningTask", back_populates="done")
    doer = db.relationship("User", foreign_keys=[done_by])
