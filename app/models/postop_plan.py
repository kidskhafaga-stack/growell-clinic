"""The post-operative plan of care — GAHAR SAS.12.

*"Postoperative care plan is determined and recorded before patient
transfer."* The intent names what goes in it: *"the level of care, patient
position, activity, required monitoring, diet, medications, intravenous
fluids, and required investigations follow-up"* — eight things, and eight
columns, for the same reason :class:`AnaesthesiaPlan` has six: a box of free
text cannot say whether the diet was thought about, and neither can an
auditor reading it a year later.

**Every word is the surgeon's.** The headings are the standard's; the program
writes none of the content. The one it offers is the level of care, as a
choice of three, because that is a decision rather than an account.

**A new version, never an overwrite.** EOC 4: *"implemented and updated based
on changes in clinical conditions"*. Editing in place would leave the plan the
recovery nurse followed at two o'clock indistinguishable from the one written
at four, so each save is a row and the latest is the plan. The earlier ones
stay, with who wrote them and when.
"""
from datetime import datetime

from app.extensions import db

#: (1) Level of care — where the child goes to be looked after.
HOME, WARD, ICU = ("home", "ward", "icu")
LEVELS = (HOME, WARD, ICU)


class PostOpPlan(db.Model):
    """One version of one case's post-operative plan."""

    __tablename__ = "postop_plans"

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey("operations.id"),
                             nullable=False, index=True)

    level = db.Column(db.String(8))              # (1) مستوى الرعاية
    position = db.Column(db.Text)                # (2) الوضع
    activity = db.Column(db.Text)                # (3) الحركة
    monitoring = db.Column(db.Text)              # (4) المراقبة المطلوبة
    diet = db.Column(db.Text)                    # (5) الأكل
    medications = db.Column(db.Text)             # (6) الأدوية
    fluids = db.Column(db.Text)                  # (7) المحاليل
    investigations = db.Column(db.Text)          # (8) الفحوصات والمتابعة

    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)

    operation = db.relationship("Operation", backref=db.backref(
        "postop_plans", cascade="all, delete-orphan",
        order_by="PostOpPlan.at"))
    by = db.relationship("User")

    #: The eight, in the order the standard lists them.
    ELEMENTS = ("level", "position", "activity", "monitoring", "diet",
                "medications", "fluids", "investigations")

    @property
    def missing(self):
        """Which of the eight nobody filled in — the finding, named."""
        return [f for f in self.ELEMENTS
                if not (getattr(self, f) or "").strip()]

    def __repr__(self):
        return f"<PostOpPlan op={self.operation_id} at={self.at}>"
