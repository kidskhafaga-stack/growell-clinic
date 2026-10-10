"""The next test, by the laboratory's rule — reflex testing.

A TSH out of range is answered with an FT4; a positive screen with its
confirmation. A laboratory writes these rules once and its doctors agree to
them, so that the child is not called back for a second needle a week later.

**Every rule is the laboratory's**: which analyte, above or below which
figure, and which test follows. Nothing is preset here.

**Two ways a rule acts**, chosen per rule:

* ``suggest`` (the default) — the doctor sees «the laboratory suggests FT4,
  because TSH 7.2 is above 4.5» on the visit, and orders it with one press or
  says no;
* ``order`` — for the rules the laboratory and its doctors agreed run on
  their own: the order is written at once, on the same visit, and says it was
  the rule's (``reflex_of``), so the bill and the file show why it is there.

A value corrected so that the rule no longer holds withdraws a suggestion
nobody has acted on; an order already written stays for the laboratory to
cancel — an order is not unwritten by a program.
"""
from app.extensions import db
from app.models import LabReflexHit, LabReflexRule

OPS = ("above", "below")
MODES = ("suggest", "order")


def rules_for(test_id):
    return (LabReflexRule.query.filter_by(investigation_id=test_id, is_active=True)
            .order_by(LabReflexRule.id).all())


def fires(rule, value):
    if value is None:
        return False
    return value > rule.value if rule.op == "above" else value < rule.value


def add_rule(test, form, user=None):
    """A rule from the test's page. Raises ``ValueError(key)``."""
    from app.models import Investigation

    analyte_id = form.get("analyte_id", type=int)
    if analyte_id not in {link.analyte_id for link in test.analyte_links}:
        raise ValueError("need_analyte")
    op = form.get("op")
    if op not in OPS:
        raise ValueError("need_op")
    raw = (form.get("value") or "").strip().replace("٫", ".").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("need_value") from None
    then = db.session.get(Investigation, form.get("then_id", type=int) or 0)
    if then is None or then.id == test.id:
        raise ValueError("need_then")
    mode = form.get("mode") if form.get("mode") in MODES else "suggest"
    rule = LabReflexRule(investigation_id=test.id, analyte_id=analyte_id, op=op,
                         value=value, then_id=then.id, mode=mode,
                         created_by=getattr(user, "id", None))
    db.session.add(rule)
    db.session.flush()
    return rule


def _already_ordered(order, then_id):
    from app.models import VisitInvestigation

    return (VisitInvestigation.query
            .filter(VisitInvestigation.visit_id == order.visit_id,
                    VisitInvestigation.investigation_id == then_id,
                    VisitInvestigation.id != order.id,
                    VisitInvestigation.created_at >= order.created_at)
            .first())


def place(order, rule, user=None, ordered_by=None, note=None):
    """Write the rule's test on the source order's visit."""
    from app.models import VisitInvestigation
    from app.utils import labs as bench

    then = rule.then
    row = VisitInvestigation(
        visit_id=order.visit_id, patient_id=order.patient_id,
        investigation_id=then.id, kind=then.kind, name=then.name_ar,
        name_en=then.name_en, ordered_by=ordered_by, reflex_of=order.id,
        done_outside=bench.goes_outside(then, asked=None),
        request_notes=note)
    db.session.add(row)
    db.session.flush()
    return row


def evaluate(order, user=None):
    """After a result is written: each rule of this test, against its value.
    Returns the hits that are new."""
    if order.investigation_id is None:
        return []
    values = {v.analyte_id: v.value for v in (order.analyte_values or [])
              if v.value is not None}
    hits = {h.rule_id: h for h in LabReflexHit.query.filter_by(order_id=order.id)}
    new = []
    for rule in rules_for(order.investigation_id):
        value = values.get(rule.analyte_id)
        hit = hits.get(rule.id)
        if not fires(rule, value):
            if hit is not None and hit.status == "open":
                hit.status = "withdrawn"
            continue
        if hit is not None and hit.status in ("open", "ordered", "dismissed"):
            hit.value = value
            continue
        hit = LabReflexHit(order_id=order.id, rule_id=rule.id, value=value)
        db.session.add(hit)
        if rule.mode == "order" and order.visit_id and not _already_ordered(order, rule.then_id):
            placed = place(order, rule, user, note=f"{rule.analyte.name} {value:g}")
            hit.status, hit.new_order_id = "ordered", placed.id
        new.append(hit)
    db.session.flush()
    return new


def open_for_visit(visit_id):
    """The suggestions a doctor has not answered, for the visit's screen."""
    from app.models import VisitInvestigation

    rows = (LabReflexHit.query.join(VisitInvestigation, LabReflexHit.order_id == VisitInvestigation.id)
            .filter(VisitInvestigation.visit_id == visit_id, LabReflexHit.status == "open")
            .order_by(LabReflexHit.id).all())
    out = []
    for hit in rows:
        done = _already_ordered(hit.order, hit.rule.then_id)
        if done is not None:
            hit.status, hit.new_order_id = "ordered", done.id
            continue
        out.append(hit)
    return out


__all__ = ["MODES", "OPS", "add_rule", "evaluate", "fires", "open_for_visit", "place",
           "rules_for"]
