"""Root cause analysis — the fishbone and the Pareto (RCA_PLAN.md).

Asked for on a screenshot of another program's «تحليل الأسباب»: *«الداش
بورد دي حلوه للجودة جوه المستشفيات والإدارة العليا»*.

**A problem** is one of three: a quality measure that missed its target
(``measure``), what the complaints or the incident reports of a period say
(``complaints`` / ``incidents`` — counted, never typed), or one the team
writes in (``manual``). **A cause** sits on one bone of the fishbone — the
same eight the complaints already close with (``complaint.ROOT_CAUSES``), so
a cause counted from the complaints and one written by hand land on the same
bone — and carries a weight: how many times it happened, as the team counted.

A cause can open an improvement project (``ImprovementProject``), and the
problem keeps the measure's value from the day it was opened, so the screen
can say whether the measure moved since.
"""
from datetime import datetime

from app.extensions import db

#: Where a problem comes from.
SOURCES = ("measure", "complaints", "incidents", "manual")
#: Counted from the program, never typed.
SYSTEM_SOURCES = ("complaints", "incidents")


class RcaProblem(db.Model):
    __tablename__ = "rca_problems"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    source = db.Column(db.String(12), nullable=False, default="manual")
    measure_id = db.Column(db.Integer, db.ForeignKey("performance_measures.id"), index=True)
    #: The part of the hospital it belongs to — its head sees it.
    cost_centre_id = db.Column(db.Integer, db.ForeignKey("cost_centres.id"), index=True)
    note = db.Column(db.Text)
    #: The measure's value and period on the day the problem was opened.
    baseline = db.Column(db.Float)
    baseline_period = db.Column(db.String(10))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime)

    measure = db.relationship("PerformanceMeasure")
    cost_centre = db.relationship("CostCentre")
    by = db.relationship("User")
    causes = db.relationship("RcaCause", back_populates="problem",
                             order_by="RcaCause.weight.desc()")

    @property
    def is_open(self):
        return self.closed_at is None


class RcaCause(db.Model):
    __tablename__ = "rca_causes"

    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("rca_problems.id"), nullable=False, index=True)
    category = db.Column(db.String(16), nullable=False)
    text = db.Column(db.String(200), nullable=False)
    weight = db.Column(db.Integer, nullable=False, default=1)
    note = db.Column(db.String(255))
    project_id = db.Column(db.Integer, db.ForeignKey("improvement_projects.id"), index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    problem = db.relationship("RcaProblem", back_populates="causes")
    project = db.relationship("ImprovementProject")
    by = db.relationship("User")
