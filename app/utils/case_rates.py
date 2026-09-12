"""What a case costs and what it pays — by doctor, by service, by kind of case.

Reported twice, from two sides of the same fact:

> «فيه تسعيرين للعملية اذا كانت خاصة او مستشفى او طوارئ»

> «واتعاب الجراح برده علشان الحالات الخاصة وحالات الطوارئ وحالات المستشفى»

The same appendicectomy, by the same surgeon, is three different numbers on
the family's bill *and* three different fees to the surgeon — and before this
the program had one of each.

**The nearest one set wins**, which is the pattern the bed rates already use:

1. this doctor's rate **for this kind of case**;
2. this doctor's ordinary rate;
3. the service's own price and commission.

Each level answers only what it was asked to answer. A case rate that names a
price and nothing else leaves the commission at the level below — because
``NULL`` there means *nobody said*, and ``"none"`` means *they said nothing is
paid*. Those are different sentences, and a column that cannot tell them apart
would silently stop paying a surgeon the day somebody typed an emergency
price.

And **a case nobody classified prices exactly as it always did.** Every
operation booked before the kind existed has ``case_type`` NULL, which is not
"private with the paperwork missing" — it is a question nobody was asked, and
the answer is the doctor's ordinary rate.
"""
from app.models import DoctorCaseRate


def _case_rate(service, doctor, case_type):
    """This doctor's row for this kind of case, or ``None``."""
    if service is None or doctor is None or not case_type:
        return None
    service_id = getattr(service, "id", None)
    doctor_id = getattr(doctor, "id", None)
    if not service_id or not doctor_id:
        return None
    return DoctorCaseRate.query.filter_by(
        doctor_id=doctor_id, service_id=service_id,
        case_type=case_type).first()


def price_for(service, doctor=None, case_type=None):
    """What the family is charged, at the nearest level that says.

    Falls all the way through to the service's list price, so this is safe to
    call in place of ``service.price_for(doctor)`` anywhere — and it should
    be, because two callers reading the price two ways is how one door bills
    a day case at the surgeon's rate and the other bills it at the list
    price. That disagreement was real and is what this replaced.
    """
    if service is None:
        return 0
    row = _case_rate(service, doctor, case_type)
    if row is not None and row.price_override is not None:
        return row.price_override
    return service.price_for(doctor) or 0


def commission_for(service, doctor=None, case_type=None):
    """``(type, value)`` for this doctor on this kind of case.

    A case rate with no ``commission_type`` is not an answer — it is a row
    that only had something to say about the price.
    """
    if service is None:
        return "none", 0
    row = _case_rate(service, doctor, case_type)
    if row is not None and row.commission_type:
        return row.commission_type, (row.commission_value or 0)
    return service.commission_for(doctor)


def share_for(service, amount, doctor=None, case_type=None):
    """The doctor's cut of ``amount``, never more than ``amount`` itself.

    The arithmetic is :meth:`Service.doctor_share`'s, not a second copy of
    it — only the *rate* it uses is resolved differently.
    """
    ctype, cval = commission_for(service, doctor, case_type)
    if ctype == "percent":
        return round(max(amount, 0) * (cval or 0) / 100.0, 2)
    if ctype == "fixed":
        return round(min(cval or 0, max(amount, 0)), 2)
    return 0.0


def rates_for(doctor, service):
    """Every case-type exception set for this pairing, keyed by kind.

    For the screen, which draws one row per kind and needs to know which of
    them somebody has actually filled in.
    """
    if doctor is None or service is None:
        return {}
    return {row.case_type: row for row in DoctorCaseRate.query.filter_by(
        doctor_id=getattr(doctor, "id", doctor),
        service_id=getattr(service, "id", service)).all()}
