"""Which department a bill is for — the question a hospital contract asks.

Asked as *«نظام التأمين ده شغال على كل الاقسام الطوارئ والداخلى والحضانة وحسب
كل عقد ايه الى داخل على العقد وايه الى المريض بيحاسب عنده»*. A clinic's
contract was a price list; a hospital's says one thing for the outpatient
clinic and another for the emergency, the ward, the incubators and intensive
care. So the bill has to say where it was run up:

* a stay's bill — the unit of the bed the child is in (or was last in);
* an emergency attendance's bill — the emergency;
* everything else — the outpatient clinic.

Read, never stored: the invoice already carries the stay and the visit.
"""

OUTPATIENT, EMERGENCY, INPATIENT, NICU, ICU = (
    "outpatient", "emergency", "inpatient", "nicu", "icu")

#: In the order a contract screen lists them.
SETTINGS = (OUTPATIENT, EMERGENCY, INPATIENT, NICU, ICU)

#: A unit's kind → the department a contract names. A day-care bed and the
#: recovery room are inpatient care as far as an agreement is concerned.
_UNIT = {"emergency": EMERGENCY, "nicu": NICU, "icu": ICU, "ward": INPATIENT,
         "day_care": INPATIENT, "recovery": INPATIENT}


def of_admission(admission):
    if admission is None:
        return None
    stays = list(getattr(admission, "stays", None) or [])
    stay = next((s for s in stays if s.until is None), None) or (
        max(stays, key=lambda s: s.since) if stays else None)
    unit = getattr(getattr(getattr(stay, "bed", None), "space", None), "unit", None)
    return _UNIT.get(getattr(unit, "kind", None), INPATIENT)


def of_invoice(invoice):
    """The department this bill belongs to (one of :data:`SETTINGS`)."""
    if invoice is None:
        return OUTPATIENT
    admission = getattr(invoice, "admission", None)
    if admission is None and getattr(invoice, "admission_id", None):
        from app.extensions import db
        from app.models.admission import Admission

        admission = db.session.get(Admission, invoice.admission_id)
    found = of_admission(admission)
    if found:
        return found
    visit = getattr(invoice, "visit", None)
    if visit is None and getattr(invoice, "visit_id", None):
        from app.extensions import db
        from app.models import Visit

        visit = db.session.get(Visit, invoice.visit_id)
    if getattr(visit, "channel", None) == "emergency":
        return EMERGENCY
    return OUTPATIENT
