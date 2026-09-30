"""What is given to a child in emergency who has no bed — and on whose word.

The rules are in `models/emergency_order`; this is where they are enforced,
so the screen, a test and anything written later cannot disagree about them:

* nothing from an outside doctor is given before one of ours approves it;
* a paper from one of our doctors is given at once, in their name, and they
  are asked to confirm it only if they were in the building when it was
  entered;
* one of our doctors writing is the prescriber, and nobody else is asked;
* a closed attendance takes no new orders, and nothing given is undone.

Tests and scans ordered from the attendance are ordinary orders on the
attendance's own encounter — `channel="emergency"` — made the first time one
is needed, the way a stay gets its own (`utils/stay_orders`). The lab, the
results inbox and the file read them there, and the desk bills them there.
"""
from datetime import datetime

from app.extensions import db
from app.models import User, Visit, VisitInvestigation
from app.models.emergency_order import (HOSPITAL_RX, OURS, OUTSIDE_RX,
                                        SOURCES, EmergencyOrder)
from app.utils.clock import local_today

#: The attendance's own encounter, in ``Visit.channel``.
EMERGENCY = "emergency"


class Closed(ValueError):
    """An order on an attendance that has ended."""


class NotADoctor(ValueError):
    """A prescriber, approver or confirmer who is not one of our doctors."""


def is_doctor(user):
    return bool(user is not None and getattr(user, "is_active", False)
                and User.sees_patients(user.role, user.is_practitioner))


def doctors():
    """Our doctors, for «whose paper is this» — every active account that
    consults, contracted doctors with an account included."""
    rows = User.query.filter(User.is_active.is_(True)).order_by(
        User.full_name).all()
    return [u for u in rows if is_doctor(u)]


def present_now():
    """The doctors the rota has **in the building** now — present, not on
    call from home. Asked once, when a paper is entered."""
    try:
        from app.utils.on_call import covering

        ids = set()
        for group in covering(roles_only=False):
            for duty in group["present"]:
                if duty.doctor_id:
                    ids.add(duty.doctor_id)
        return ids
    except Exception:  # noqa: BLE001 — a rota problem never blocks a dose
        return set()


# ------------------------------------------------------------- writing ---
def write(attendance, user, source=OURS, name=None, drug=None, service=None,
          dose=None, route=None, store_item=None, units=None, note=None,
          prescriber=None, outside_doctor=None, at=None):
    """Write one thing to give. Returns the order; the caller commits.

    ``user`` is whoever is at the keyboard. For ``ours`` they are the
    prescriber and must be a doctor; for ``hospital_rx`` the prescriber is
    the doctor on the paper; for ``outside_rx`` it is the name on the paper.
    """
    from app.models.medication import ROUTES

    if attendance is None or not attendance.is_open:
        raise Closed("attendance closed")
    if source not in SOURCES:
        raise ValueError("unknown source")
    name = (name or "").strip()
    if not name and drug is not None:
        name = (getattr(drug, "trade_name", "") or "").strip()
    if not name and service is not None:
        name = (service.name or "").strip()
    if not name:
        raise ValueError("no name")

    row = EmergencyOrder(
        emergency_visit_id=attendance.id, patient_id=attendance.patient_id,
        drug_id=getattr(drug, "id", None),
        service_id=getattr(service, "id", None),
        name=name[:200], dose=(dose or "").strip()[:80] or None,
        route=route if route in ROUTES else None,
        store_item_id=getattr(store_item, "id", None),
        units=max(1, min(99, int(units or 1))),
        note=(note or "").strip()[:255] or None,
        source=source, entered_by=getattr(user, "id", None),
        created_at=at or datetime.utcnow())

    if source == OURS:
        if not is_doctor(user):
            raise NotADoctor("only a doctor writes an order")
        row.prescriber_id = user.id
    elif source == HOSPITAL_RX:
        if not is_doctor(prescriber):
            raise NotADoctor("the paper names no doctor of ours")
        row.prescriber_id = prescriber.id
        # Asked only when they could walk over and look; a doctor at home is
        # not chased for a paper they wrote this morning.
        row.confirm_asked = (prescriber.id != getattr(user, "id", None)
                             and prescriber.id in present_now())
    else:
        outside = (outside_doctor or "").strip()
        if not outside:
            raise ValueError("no outside doctor")
        row.outside_doctor = outside[:120]
    db.session.add(row)
    db.session.flush()
    return row


def approve(order, user, at=None):
    """One of our doctors saw the child and agrees to the outside paper."""
    if not is_doctor(user):
        raise NotADoctor("only a doctor approves")
    if order.state != "waiting_doctor":
        raise ValueError("nothing to approve")
    order.approved_by = user.id
    order.approved_at = at or datetime.utcnow()
    return order


def give(order, user, at=None):
    """It was given. Refused for anything not ready — above all an outside
    paper no doctor of ours has approved."""
    if order.state != "ready":
        raise ValueError(order.state)
    order.given_at = at or datetime.utcnow()
    order.given_by = getattr(user, "id", None)
    return order


def cancel(order, user, reason=None, at=None):
    """Not given after all. What was given is not cancelled — it happened."""
    if order.state in ("given", "cancelled"):
        raise ValueError(order.state)
    order.cancelled_at = at or datetime.utcnow()
    order.cancelled_by = getattr(user, "id", None)
    order.cancel_reason = (reason or "").strip()[:200] or None
    return order


def confirm(order, user, at=None):
    """The doctor on the paper says it is theirs."""
    if not order.awaiting_confirmation:
        raise ValueError("nothing to confirm")
    if getattr(user, "id", None) != order.prescriber_id:
        raise NotADoctor("not their paper")
    order.confirmed_at = at or datetime.utcnow()
    return order


# ------------------------------------------------------------- reading ---
def for_attendance(attendance):
    """Everything written for this attendance, oldest first."""
    return (EmergencyOrder.query
            .filter_by(emergency_visit_id=attendance.id)
            .order_by(EmergencyOrder.created_at, EmergencyOrder.id).all())


def awaiting_confirmation(user):
    """Papers given in this doctor's name that they were asked to confirm."""
    if user is None or not getattr(user, "id", None):
        return []
    return (EmergencyOrder.query
            .filter(EmergencyOrder.prescriber_id == user.id,
                    EmergencyOrder.source == HOSPITAL_RX,
                    EmergencyOrder.confirm_asked.is_(True),
                    EmergencyOrder.confirmed_at.is_(None),
                    EmergencyOrder.cancelled_at.is_(None))
            .order_by(EmergencyOrder.created_at).all())


def waiting_doctor(limit=100):
    """Outside papers no doctor of ours has approved, on children still in
    the department — oldest first."""
    from app.models import EmergencyVisit

    return (EmergencyOrder.query
            .join(EmergencyVisit,
                  EmergencyVisit.id == EmergencyOrder.emergency_visit_id)
            .filter(EmergencyOrder.source == OUTSIDE_RX,
                    EmergencyOrder.approved_at.is_(None),
                    EmergencyOrder.cancelled_at.is_(None),
                    EmergencyVisit.departed_at.is_(None))
            .order_by(EmergencyOrder.created_at).limit(limit).all())


def states_by_attendance(ids):
    """``{attendance id: {state: count}}`` for the register, in one query."""
    out = {}
    if not ids:
        return out
    for row in (EmergencyOrder.query
                .filter(EmergencyOrder.emergency_visit_id.in_(list(ids)))
                .all()):
        bucket = out.setdefault(row.emergency_visit_id, {})
        bucket[row.state] = bucket.get(row.state, 0) + 1
    return out


# ----------------------------------------------------- tests and scans ---
def encounter(attendance, user):
    """The visit this attendance's tests are written on, made the first time
    one is needed — closed from the start and with no appointment, so it
    raises no consultation fee and sits in nobody's queue."""
    if attendance.visit is not None:
        return attendance.visit
    now = datetime.utcnow()
    visit = Visit(patient_id=attendance.patient_id, doctor_id=user.id,
                  visit_date=local_today(), status="completed",
                  completed_at=now, channel=EMERGENCY)
    db.session.add(visit)
    db.session.flush()
    attendance.visit = visit
    return visit


def order_test(attendance, user, investigation=None, name=None, kind=None,
               notes=None, outside=None):
    """A test or scan for a child in emergency. Returns the order."""
    from app.models.prescription import INVESTIGATION_KINDS
    from app.utils import labs

    if attendance is None or not attendance.is_open:
        raise Closed("attendance closed")
    name_en = None
    if investigation is not None:
        name, name_en, kind = (investigation.name_ar, investigation.name_en,
                               investigation.kind)
    name = (name or "").strip()[:200]
    if not name:
        raise ValueError("no name")
    kind = kind if kind in INVESTIGATION_KINDS else "lab"
    visit = encounter(attendance, user)
    row = VisitInvestigation(
        visit_id=visit.id, patient_id=attendance.patient_id,
        investigation_id=getattr(investigation, "id", None),
        kind=kind, name=name, name_en=(name_en or "").strip()[:200] or None,
        request_notes=(notes or "").strip()[:255] or None,
        done_outside=labs.goes_outside(investigation, asked=outside),
        ordered_by=user.id)
    db.session.add(row)
    db.session.flush()
    return row


def tests_for(attendance):
    if attendance.visit_id is None:
        return []
    return (VisitInvestigation.query
            .filter_by(visit_id=attendance.visit_id)
            .order_by(VisitInvestigation.created_at.desc(),
                      VisitInvestigation.id.desc()).all())


# ------------------------------------------------------------- the bill ---
# «وطريقة الحساب ... وهل يقدر يعمل مراجعة قبل الحساب حاجه اتصرفت عليه
# بالغلط». What was given is offered at the desk as lines the cashier sees
# and can take off before a pound changes hands — the same door every other
# charge in this program comes through. Only what was **given** is owed.

INCLUSIVE, SEPARATE = "inclusive", "separate"
SUPPLIES_MODES = (INCLUSIVE, SEPARATE)


def includes_supplies(service):
    """Whether this service's price already includes the drug and supplies
    used to give it. Unset is not inclusive: nothing used is given away
    because nobody said."""
    return bool(service is not None
                and getattr(service, "supplies_mode", None) == INCLUSIVE)


def _owes_service(order):
    return order.service_id is not None and order.invoice_item_id is None


def _owes_item(order):
    return (order.store_item_id is not None
            and not includes_supplies(order.service)
            and order.item_invoice_item_id is None)


def unbilled(patient_id=None):
    """Given, not cancelled, and something on it still to be charged."""
    query = EmergencyOrder.query.filter(
        EmergencyOrder.given_at.isnot(None),
        EmergencyOrder.cancelled_at.is_(None))
    if patient_id is not None:
        query = query.filter(EmergencyOrder.patient_id == patient_id)
    rows = query.order_by(EmergencyOrder.given_at, EmergencyOrder.id).all()
    return [o for o in rows if _owes_service(o) or _owes_item(o)]


def _when(order):
    from app.utils.clock import to_local

    return to_local(order.given_at).strftime("%Y-%m-%d %H:%M")


def checkout_lines(orders, lang="ar"):
    """The desk's lines for these treatments.

    The service at its price, marked as that treatment's charge; the drug or
    supply on a line of its own when the service does not include it — or
    when there is no service at all. Priced from the shelf and carrying no
    commission: nobody's percentage rides on the vial.
    """
    lines = []
    for o in orders:
        what = o.name + (f" · {o.dose}" if o.dose else "")
        if _owes_service(o):
            svc = o.service
            price = (svc.price_for(o.prescriber) if o.prescriber is not None
                     else svc.price) or 0
            label = svc.display_name(lang) if hasattr(svc, "display_name") else svc.name
            lines.append({
                "service_id": svc.id,
                "description": f"{label} — {what} ({_when(o)})"[:200],
                "unit_price": price, "quantity": 1,
                "er_order_id": o.id})
        if _owes_item(o):
            item = o.store_item
            name = (item.display_name(lang) if hasattr(item, "display_name")
                    else item.name)
            lines.append({
                "service_id": "",
                "description": f"{name} — {what} ({_when(o)})"[:200],
                "unit_price": getattr(item, "sell_price", 0) or 0,
                "quantity": max(1, int(o.units or 1)),
                "no_commission": "1",
                "er_item_id": o.id})
    return lines


def take_off_shelf(orders, invoice, user=None, lang="ar"):
    """What these treatments used leaves the stock, once each, under the
    invoice's issue document — charged on its own line or inside the
    service's price alike: a vial used is a vial gone.

    Never refused for want of stock, for the reason the ward's doses are
    not: it was given, and the count is the store's to reconcile.
    """
    from app.models import StockMovement
    from app.utils import cost_centres
    from app.utils.costing import issue_unit_cost
    from app.utils.store_docs import open_document

    rows = [o for o in (orders or [])
            if o.store_item is not None and o.stock_movement_id is None]
    if not rows or invoice is None:
        return 0
    centre = cost_centres.centre_id("emergency")
    document = getattr(invoice, "_iss_doc", None)
    for o in rows:
        if document is None:
            document = open_document("issue", reference=invoice.invoice_number)
        movement = StockMovement(
            item_id=o.store_item_id, kind="out",
            qty=-abs(max(1, int(o.units or 1))),
            reason=f"{o.name} — {_when(o)}"[:160],
            unit_cost=issue_unit_cost(o.store_item),
            cost_centre_id=centre,
            created_by=getattr(user, "id", None), document_id=document.id)
        db.session.add(movement)
        db.session.flush()
        o.stock_movement_id = movement.id
    invoice._iss_doc = document
    return len(rows)
