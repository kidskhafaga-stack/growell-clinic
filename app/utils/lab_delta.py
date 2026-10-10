"""The delta check — a result read against the child's own last one.

A haemoglobin of 7 is low; a haemoglobin of 7 in a child who was 12 on
Tuesday is either a child bleeding or a tube from somebody else. Ranges catch
the first and never the second, and a laboratory that releases the second
has put another child's blood in this child's file. So, before release, each
number is set beside the child's previous number of the same analyte, and a
move too large to be likely is said on the bench — for a second look, a
re-draw or a phone call. **It blocks nothing.**

**How far is «too far» is the laboratory's** (``LabAnalyte.delta_abs`` in the
analyte's unit, ``delta_pct`` of the previous, ``delta_days`` how old a
previous may be and still count). No figure is supplied here; an analyte with
none is never compared — the program does not invent clinical numbers.

**What is compared is kept on the result** (``delta_prev``, ``delta_prev_at``,
``delta_hit``), the way the range is: correcting last week's value next month
does not rewrite what this one was read against.

**Different units are not compared.** A creatinine in µmol/L after one in
mg/dL moved by a factor of 88 and nothing happened to the child — the same
reason the curves keep each unit its own series (`utils/lab_series`).
"""
from app.extensions import db


def armed(analyte):
    return analyte is not None and (analyte.delta_abs is not None
                                    or analyte.delta_pct is not None)


def previous(order, analyte_id, unit=None):
    """The child's newest earlier value of this analyte, or ``None``:
    ``(value, when)``. Earlier means an order written before this one."""
    from app.models import LabResultValue, VisitInvestigation

    query = (LabResultValue.query
             .join(VisitInvestigation, LabResultValue.order_id == VisitInvestigation.id)
             .filter(VisitInvestigation.patient_id == order.patient_id,
                     VisitInvestigation.id != order.id,
                     VisitInvestigation.created_at <= order.created_at,
                     LabResultValue.analyte_id == analyte_id,
                     LabResultValue.value.isnot(None)))
    row = (query.order_by(VisitInvestigation.created_at.desc(),
                          LabResultValue.id.desc()).first())
    if row is None:
        return None
    if unit and row.unit and row.unit.strip().casefold() != unit.strip().casefold():
        return None
    when = row.order.collected_at or row.order.resulted_at or row.order.created_at
    return row.value, when


def check(row, order, at=None):
    """Compare ``row`` (a value being written on ``order``) and keep what it
    was compared with. Returns whether it moved too far."""
    row.delta_prev = row.delta_prev_at = row.delta_hit = None
    analyte = row.analyte
    if row.value is None or not armed(analyte):
        return False
    found = previous(order, analyte.id, row.unit)
    if found is None:
        return False
    old, when = found
    taken = order.collected_at or order.created_at or at
    if analyte.delta_days and when is not None and taken is not None \
            and (taken - when).days > analyte.delta_days:
        return False
    diff = abs(row.value - old)
    hit = bool((analyte.delta_abs is not None and diff > analyte.delta_abs)
               or (analyte.delta_pct is not None and old
                   and diff / abs(old) * 100 > analyte.delta_pct))
    row.delta_prev, row.delta_prev_at, row.delta_hit = old, when, hit or None
    return hit


def set_limits(analyte, form):
    """The laboratory's figures for one analyte; a blank box clears it."""
    def number(key, cast=float):
        raw = (form.get(key) or "").strip().replace("٫", ".").replace(",", ".")
        if not raw:
            return None
        try:
            value = cast(raw)
        except ValueError:
            raise ValueError(key) from None
        if value <= 0:
            raise ValueError(key)
        return value

    analyte.delta_abs = number("delta_abs")
    analyte.delta_pct = number("delta_pct")
    analyte.delta_days = number("delta_days", int)
    db.session.flush()


__all__ = ["armed", "check", "previous", "set_limits"]
