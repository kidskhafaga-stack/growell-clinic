"""The sterilization quality-control logbook — GAHAR IPC.15.

The standard lists the controls (a i–vii) and how often:

* **physical parameters** — temperature, time, pressure — *"monitored every
  cycle"* (ii);
* **chemical indicators**, inside and outside *"every pack"* (iii);
* **biological indicator** *"at least weekly"* (iv);
* **Bowie-Dick / Helix** — steam penetration and air removal — *"every day
  before starting to use the autoclave"* (v, vi);
* **high-level disinfectant** concentration strips, as often as the solution
  is used (vii).

So a **sterilizer** carries the hospital's acceptable values (b) — the
program holds none of its own — and each **cycle** is written as the machine
read it, with its indicator results; a failed one needs the action taken
(e). An **HLD test** is a strip on a solution. A **review** is the
authorized person signing the period (d).
"""
from datetime import datetime

from app.extensions import db

CYCLE_KINDS = ("load", "bowie_dick", "helix")
RESULTS = ("pass", "fail")
BI_RESULTS = ("pending", "pass", "fail")


class Sterilizer(db.Model):
    __tablename__ = "sterilizers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    serial = db.Column(db.String(80))
    location = db.Column(db.String(120))
    #: IPC.15 (b) — the hospital's acceptable physical values; empty is
    #: «not set», and nothing is judged against it.
    temp_min = db.Column(db.Float)
    temp_max = db.Column(db.Float)
    minutes_min = db.Column(db.Integer)
    pressure_min = db.Column(db.Float)
    pressure_max = db.Column(db.Float)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    cycles = db.relationship("SterilizerCycle", back_populates="sterilizer",
                             order_by="SterilizerCycle.run_at.desc()", lazy="dynamic")


class SterilizerCycle(db.Model):
    __tablename__ = "sterilizer_cycles"

    id = db.Column(db.Integer, primary_key=True)
    sterilizer_id = db.Column(db.Integer, db.ForeignKey("sterilizers.id"), nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)
    run_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    cycle_no = db.Column(db.String(30))
    temperature = db.Column(db.Float)
    minutes = db.Column(db.Integer)
    pressure = db.Column(db.Float)
    #: The chemical indicators of the load (iii), or the test sheet/strip of
    #: a Bowie-Dick or Helix cycle (v, vi).
    chemical = db.Column(db.String(6))
    #: A biological indicator in this load (iv), read later.
    bi = db.Column(db.String(8))
    bi_read_at = db.Column(db.DateTime)
    #: Any value outside the hospital's, or any indicator failed.
    failed = db.Column(db.Boolean, default=False, nullable=False)
    action = db.Column(db.String(255))
    run_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    sterilizer = db.relationship("Sterilizer", back_populates="cycles")
    operator = db.relationship("User", foreign_keys=[run_by])


class HldTest(db.Model):
    __tablename__ = "hld_tests"

    id = db.Column(db.Integer, primary_key=True)
    solution = db.Column(db.String(120), nullable=False)
    tested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    result = db.Column(db.String(6), nullable=False)
    action = db.Column(db.String(255))
    tested_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    tester = db.relationship("User", foreign_keys=[tested_by])


class SterilizationReview(db.Model):
    __tablename__ = "sterilization_reviews"

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(7), nullable=False, index=True)
    note = db.Column(db.String(255))
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    reviewer = db.relationship("User", foreign_keys=[reviewed_by])
