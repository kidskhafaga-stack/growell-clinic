"""A course of dental treatment, and the money it commits a family to.

A paediatric visit is one event: the child is seen, a bill is raised, it is
paid. Dentistry is not shaped like that. A plan is agreed on one day — four
fillings, a crown, two extractions — and carried out over weeks, with the
family paying part of it before anything starts and the rest as the work goes.

**The plan raises one invoice for the agreed total, when it is accepted.**
Not one per completed item, and that is a deliberate choice against the way a
dental program might do it. A family agreeing to a course of treatment agrees
to a figure; that figure is what they budget against, what the statement
should show, and what a deposit is a deposit *against*. Billing item by item
would mean nobody could answer "what does this cost?" until the last visit,
and the running balance a receptionist reads would climb every few days
without anything new being agreed.

It also means everything the money side already does works here unchanged:
part-payments, the running balance, the printed statement, the aging report.
The audit before this was written found exactly one thing wrong in that
machinery and fixed it; building a second, parallel way to owe this clinic
money would have been the way to reintroduce it.

**A plan is a proposal until somebody accepts it.** A draft can be edited,
re-priced and thrown away with nothing in the books. Acceptance is the moment
it becomes money, and it happens once — an accepted plan's invoice is the
family's agreement, and quietly re-raising it because somebody pressed the
button twice is how a child ends up billed for the same crown twice.
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

# draft    — being written, costs nothing, editable
# accepted — the family agreed; the invoice exists
# done     — every item carried out
# cancelled— abandoned; the invoice, if any, is settled separately
PLAN_STATUSES = ["draft", "accepted", "done", "cancelled"]

# planned — agreed, not yet carried out
# done    — carried out, on the visit that did it
# dropped — taken out of the plan before it happened
ITEM_STATUSES = ["planned", "done", "dropped"]


class TreatmentPlan(db.Model):
    """One agreed course of dental treatment for one child."""

    __tablename__ = "dental_plans"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True,
                          index=True)
    # The bill for the agreed total. Written once, at acceptance.
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"),
                           nullable=True, index=True)

    status = db.Column(db.String(10), default="draft", nullable=False,
                       index=True)
    title = db.Column(db.String(120))
    note = db.Column(db.String(500))

    created_on = db.Column(db.Date, default=local_today, nullable=False)
    accepted_at = db.Column(db.DateTime)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    author = db.relationship("User", foreign_keys=[created_by])
    invoice = db.relationship("Invoice")
    items = db.relationship("TreatmentPlanItem", back_populates="plan",
                            cascade="all, delete-orphan",
                            order_by="TreatmentPlanItem.id")

    # --- what it comes to ------------------------------------------------
    @property
    def live_items(self):
        """Everything still part of the plan. A dropped item is history."""
        return [i for i in self.items if i.status != "dropped"]

    @property
    def total(self):
        """The agreed figure — what the family said yes to."""
        return round(sum(i.price or 0 for i in self.live_items), 2)

    @property
    def done_total(self):
        """What has actually been carried out, priced.

        Not what is owed — the whole plan is owed from acceptance. This is how
        far through the work is, which is a different question and the one a
        parent asks at the desk.
        """
        return round(sum(i.price or 0 for i in self.live_items
                         if i.status == "done"), 2)

    @property
    def progress(self):
        """``(done, of)`` items carried out. Counted, not priced: "three of
        seven" is what somebody wants to hear."""
        live = self.live_items
        return sum(1 for i in live if i.status == "done"), len(live)

    @property
    def accepted(self):
        return self.status in ("accepted", "done")

    @property
    def editable(self):
        """Only a draft. Once a family has agreed a figure and been billed it,
        changing the plan underneath them is changing what they agreed to."""
        return self.status == "draft"

    def __repr__(self):
        return f"<TreatmentPlan {self.id} {self.status} {self.total}>"


class TreatmentPlanItem(db.Model):
    """One procedure, on one tooth, at a price.

    The tooth is stored on the item rather than the plan because that is the
    level the work happens at, and because the chart and the plan have to be
    able to talk about the same tooth: "55 needs a pulpotomy" is a line here
    and a finding there, and a plan that only said "pulpotomy ×2" could not be
    read back against the mouth it was written for.
    """

    __tablename__ = "dental_plan_items"

    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("dental_plans.id"),
                        nullable=False, index=True)
    # FDI, and nullable: a scale-and-polish or a fluoride varnish is done to
    # a mouth, not to a tooth, and forcing a number on it would be inventing
    # one.
    tooth = db.Column(db.Integer, index=True)
    surface = db.Column(db.String(10))

    # What is being done. A service from the clinic's own list where there is
    # one, so the price, the doctor's commission and the reports all behave
    # the way they do for everything else this clinic sells.
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"),
                           nullable=True)
    description = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, default=0, nullable=False)

    status = db.Column(db.String(10), default="planned", nullable=False,
                       index=True)
    # The visit that carried it out, so the plan and the day's work agree.
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True)
    done_on = db.Column(db.Date)
    note = db.Column(db.String(300))

    plan = db.relationship("TreatmentPlan", back_populates="items")
    service = db.relationship("Service")
    visit = db.relationship("Visit")

    def __repr__(self):
        return f"<TreatmentPlanItem {self.tooth} {self.description}>"
