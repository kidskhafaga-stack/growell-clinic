"""The vaccines a doctor has agreed on for one child.

The program decides what a child is due from their birthday and the doses on
file. That is right for a schedule everybody follows and wrong for the part a
clinic actually sells: a two-year-old who has had nothing here carried
twenty-one suggestions, because *every* optional vaccine they were old enough
for looked equally like an idea worth having.

Asked for as: **"if the doctor agreed with the family on certain vaccines for
this case, give those to the child as a reminder and let them stay with them."**

A plan is a promise, and the promise is what changes the sentence. A course
nobody agreed on is a suggestion by age; the same course, once the doctor and
the family have settled on it, is something this clinic said it would do — so
it can be late, and being late is worth a message. That is the same rule the
program already used for a course somebody had started, moved one step
earlier: the agreement now counts, not only the first needle.

It does **not** replace the age-based suggestions. Asked directly, and
answered: the rest stay as suggestions for the child's age and condition. The
plan raises what was agreed; it hides nothing.

``supplied_outside`` is the other half of the same question. A family who says
"I will buy it and come to you to give it" is still on a plan — the visit
still has to be arranged, the dose still recorded — but the clinic must not
order a vial for it. Counting them would have the fridge filling up with stock
nobody is going to buy.
"""
from app.extensions import db


class VaccinePlanItem(db.Model):
    __tablename__ = "vaccine_plan_items"
    __table_args__ = (
        db.UniqueConstraint("patient_id", "vaccine_id",
                            name="uq_vaccine_plan_patient_vaccine"),
    )

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    vaccine_id = db.Column(db.Integer, db.ForeignKey("vaccines.id"),
                           nullable=False, index=True)
    # The trade name, when the doctor named one. Left blank the plan follows
    # whatever the child is already locked to, or the default brand — the same
    # rule the schedule itself uses, rather than a second answer to the same
    # question.
    brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"),
                         nullable=True)
    # The family is bringing this one. Still a plan, never an order.
    supplied_outside = db.Column(db.Boolean, default=False, nullable=False)
    note = db.Column(db.String(200))
    added_by_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                            nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    patient = db.relationship("Patient")
    vaccine = db.relationship("Vaccine")
    brand = db.relationship("VaccineBrand")
    added_by = db.relationship("User")

    def __repr__(self):
        return f"<VaccinePlanItem p={self.patient_id} v={self.vaccine_id}>"


def planned_vaccine_ids(patient_id):
    """The vaccine ids agreed for one child."""
    if not patient_id:
        return set()
    return {row[0] for row in db.session.query(VaccinePlanItem.vaccine_id)
            .filter(VaccinePlanItem.patient_id == patient_id).all()}


def planned_by_patient(patient_ids):
    """``{patient_id: {vaccine_id}}`` for many children, in one query.

    The batched form, for the sweeps that walk the whole register. Asking per
    child is a query apiece — the shape this module spent an afternoon
    removing everywhere else.
    """
    if not patient_ids:
        return {}
    out = {}
    rows = (db.session.query(VaccinePlanItem.patient_id,
                             VaccinePlanItem.vaccine_id,
                             VaccinePlanItem.supplied_outside)
            .filter(VaccinePlanItem.patient_id.in_(list(patient_ids))).all())
    for patient_id, vaccine_id, _outside in rows:
        out.setdefault(patient_id, set()).add(vaccine_id)
    return out
