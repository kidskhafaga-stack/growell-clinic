"""«Child Examination (ER)» — one attendance on one A4 page.

The owner brought the paper form an emergency department fills by hand:
the child and the times, the temperature, weight and height; a brief history
with allergies, medication, a past DAMA, chronic illness; the focused
examination; the provisional diagnosis beside the investigations; the drug
orders («each order must be dated, timed and signed»); the disposition
(admitted to PICU, NICU, the inpatient ward or surgery — improved and
discharged — transferred — DAMA); the discharge order by the treating
doctor; the condition at discharge; the follow-up care.

Every one of those is already written somewhere in the program — on the
attendance, its encounter, its orders and tests. This gathers them in the
paper's order so the department's record is the page the doctor signs.

**Nothing here is the program's own words.** A section the file has is
printed as the file has it; a section it has not is ``None`` and the page
leaves ruled lines for a pen. The weight and the height are the ones taken
during this attendance — last month's weight on today's sheet would read as
today's. The current medication and «other» history are not held anywhere as
a list, so they are always for the pen.
"""
from app.extensions import db


def _local_date(moment):
    from app.utils.clock import local_date

    return local_date(moment) if moment else None


def _first_temperature(row):
    """The first temperature taken since the child arrived."""
    from app.models.observation import Observation

    q = (Observation.query
         .filter(Observation.patient_id == row.patient_id,
                 Observation.taken_at >= row.arrived_at,
                 Observation.temperature_c.isnot(None)))
    if row.departed_at:
        q = q.filter(Observation.taken_at <= row.departed_at)
    obs = q.order_by(Observation.taken_at.asc(), Observation.id.asc()).first()
    return obs.temperature_c if obs is not None else None


def _measured_here(row):
    """``(weight_kg, height_cm)`` measured during this attendance — the
    latest of each, or ``None``."""
    from app.models import GrowthRecord

    start = _local_date(row.arrived_at)
    q = GrowthRecord.query.filter(GrowthRecord.patient_id == row.patient_id,
                                  GrowthRecord.record_date >= start)
    if row.departed_at:
        q = q.filter(GrowthRecord.record_date <= _local_date(row.departed_at))
    weight = height = None
    for rec in q.order_by(GrowthRecord.record_date.desc(),
                          GrowthRecord.id.desc()):
        if weight is None and rec.weight_kg:
            weight = rec.weight_kg
        if height is None and rec.height_cm:
            height = rec.height_cm
    return weight, height


def _dama_before(row):
    """Earlier times this child left against medical advice — from
    emergency, or from a stay. ``[date]``, newest first."""
    from app.models import Admission, EmergencyVisit

    dates = [_local_date(v.departed_at) for v in EmergencyVisit.query.filter(
        EmergencyVisit.patient_id == row.patient_id,
        EmergencyVisit.id != row.id,
        EmergencyVisit.disposition == "self_discharge",
        EmergencyVisit.arrived_at < row.arrived_at)]
    dates += [_local_date(a.discharged_at) for a in Admission.query.filter(
        Admission.patient_id == row.patient_id,
        Admission.outcome == "self_discharge",
        Admission.discharged_at < row.arrived_at)]
    return sorted((d for d in dates if d), reverse=True)


def build(row, lang="ar"):
    """Everything the sheet prints, in the paper's order."""
    from app.models import Visit
    from app.utils import emergency_orders as eo

    p = row.patient
    visit = db.session.get(Visit, row.visit_id) if row.visit_id else None
    weight, height = _measured_here(row)
    diagnoses = []
    if visit is not None:
        diagnoses = sorted(visit.diagnoses,
                           key=lambda d: (d.dx_type == "final", d.id))
    tests = list(reversed(eo.tests_for(row)))
    orders = [o for o in eo.for_attendance(row) if o.cancelled_at is None]
    orders.sort(key=lambda o: (o.created_at, o.id))
    followups = [x for x in (row.followup_instructions,
                             visit.followup_instructions if visit else None)
                 if (x or "").strip()]
    # The same words written on both is one instruction, not two.
    followups = list(dict.fromkeys(x.strip() for x in followups))
    return {
        "patient": p,
        "visit": visit,
        "date": _local_date(row.arrived_at),
        "temperature": _first_temperature(row),
        "weight": weight,
        "height": height,
        "history": ((visit.chief_complaint or "").strip() or None)
        if visit is not None else None,
        "allergies": (p.allergies or "").strip() or None,
        "chronic": (p.chronic_diseases or "").strip() or None,
        "dama_before": _dama_before(row),
        "exam": ((visit.clinical_exam or "").strip() or None)
        if visit is not None else None,
        "diagnoses": diagnoses,
        "tests": tests,
        "orders": orders,
        "disposition": row.disposition,
        "admitted_to": row.admitted_to,
        "discharge_doctor": row.discharge_doctor,
        "condition": (row.condition or "").strip() or None,
        "followups": followups,
        "followup_due": visit.followup_due if visit is not None else None,
    }
