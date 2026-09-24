"""SAS.03 — what "assessed before the procedure" is made of, and what is missing.

:func:`evidence` answers the standard's five evidence items for one case, in
its own order, each with the reason it is not met. A surveyor reading a
record asks exactly these five questions; a screen that shows a green
"assessed" and nothing else is asking none of them.

**Before the procedure** is measured against the moment the program already
stamps: ``Operation.started_at``. An assessment written after the child went
in is an assessment of a child who is already asleep, and :func:`late` says
so rather than letting it count.

**A postponed case starts again** — *"Patient assessment should be reviewed
and repeated if a surgery/invasive procedure is postponed or canceled"*. The
new booking has no assessment of its own; :func:`starting_point` opens the
form on the old one's words so it is reviewed, not retyped, and nothing is
saved until somebody presses save on the new booking.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Lookup
from app.models.preop_assessment import (KINDS, MEDICAL, NURSING,
                                         RISK_CLASS_DOMAIN, PreOpAssessment,
                                         PreOpRisk)

#: The elements each kind is judged on, in the order the screen shows them.
ELEMENTS = {
    MEDICAL: ("indication", "history", "examination", "risk_class", "risks"),
    NURSING: ("fasting", "weight", "vitals", "allergies", "general"),
}

#: The columns each kind may write.
FIELDS = {
    MEDICAL: ("indication", "history", "examination", "risk_class",
              "risks_none"),
    NURSING: ("fasting_food_at", "fasting_fluid_at", "weight_kg", "vitals",
              "allergies_checked", "general"),
}


def risk_classes():
    """The hospital's risk classification, active entries only."""
    return (Lookup.query.filter_by(domain=RISK_CLASS_DOMAIN, is_active=True)
            .order_by(Lookup.sort_order, Lookup.id).all())


def risk_class_label(key):
    if not key:
        return None
    row = Lookup.query.filter_by(domain=RISK_CLASS_DOMAIN, key=key).first()
    return row.name_ar if row else key


def add_risk_class(name):
    """A line on the hospital's risk classification. The caller commits."""
    from app.utils.lookups import make_key

    name = (name or "").strip()[:80]
    if not name:
        raise ValueError("no name")
    row = Lookup.query.filter_by(domain=RISK_CLASS_DOMAIN).filter(
        Lookup.name_ar == name).first()
    if row is not None:
        row.is_active = True
        return row
    row = Lookup(domain=RISK_CLASS_DOMAIN,
                 key=make_key(name, RISK_CLASS_DOMAIN), name_ar=name,
                 is_active=True,
                 sort_order=Lookup.query.filter_by(
                     domain=RISK_CLASS_DOMAIN).count())
    db.session.add(row)
    return row


# ----------------------------------------------------------- reading ----
def get(operation, kind):
    if operation is None or kind not in KINDS:
        return None
    return PreOpAssessment.query.filter_by(operation_id=operation.id,
                                           kind=kind).first()


def risks(operation):
    if operation is None:
        return []
    return (PreOpRisk.query.filter_by(operation_id=operation.id)
            .order_by(PreOpRisk.noted_at, PreOpRisk.id).all())


def _text(value):
    return bool((value or "").strip()) if isinstance(value, str) else False


def missing(operation, kind):
    """Which elements of this kind nobody has answered, named."""
    row = get(operation, kind)
    if row is None:
        return list(ELEMENTS[kind])
    if kind == MEDICAL:
        have = {
            "indication": _text(row.indication),
            "history": _text(row.history),
            "examination": _text(row.examination),
            "risk_class": bool(row.risk_class),
            # Answered by a list of risks **or** by the surgeon saying there
            # are none — never by silence.
            "risks": bool(row.risks_none) or bool(risks(operation)),
        }
    else:
        have = {
            "fasting": (row.fasting_food_at is not None
                        and row.fasting_fluid_at is not None),
            "weight": row.weight_kg is not None,
            "vitals": _text(row.vitals),
            "allergies": row.allergies_checked is not None,
            "general": _text(row.general),
        }
    return [e for e in ELEMENTS[kind] if not have[e]]


def state(operation, kind):
    """``none`` · ``short`` · ``complete``."""
    if get(operation, kind) is None:
        return "none"
    return "short" if missing(operation, kind) else "complete"


def late(operation, kind):
    """Written after the child went into theatre? ``None`` while either end
    is missing."""
    row = get(operation, kind)
    started = getattr(operation, "started_at", None)
    if row is None or started is None:
        return None
    return row.at > started


def open_risks(operation):
    """Risks with no action taken — EOC 5's gap."""
    return [r for r in risks(operation) if not r.managed]


def evidence(operation):
    """The five evidence items, each ``{"met": bool, "why": str | None}``.

    ``why`` is a short key the screen translates — the reason the item is
    not met, so the screen can say what to do rather than show a red dot.
    """
    from app.utils import theatres as theatre

    started = getattr(operation, "started_at", None)

    def before(moment):
        return started is None or (moment is not None and moment <= started)

    out = {}
    for number, kind in ((1, MEDICAL), (2, NURSING)):
        row = get(operation, kind)
        if row is None:
            out[number] = {"met": False, "why": "none"}
        elif missing(operation, kind):
            out[number] = {"met": False, "why": "short"}
        elif not before(row.at):
            out[number] = {"met": False, "why": "late"}
        else:
            out[number] = {"met": True, "why": None}

    work = theatre.workup_state(operation)
    out[3] = {"met": work in ("ready", "not_needed"),
              "why": None if work in ("ready", "not_needed") else work}

    medical = get(operation, MEDICAL)
    found = risks(operation)
    if not found and not (medical and medical.risks_none):
        out[4] = {"met": False, "why": "unasked"}
    elif any(not before(r.noted_at) for r in found):
        out[4] = {"met": False, "why": "late"}
    else:
        out[4] = {"met": True, "why": None}

    if not found:
        out[5] = {"met": bool(medical and medical.risks_none),
                  "why": None if medical and medical.risks_none else "unasked"}
    elif any(not r.managed for r in found):
        out[5] = {"met": False, "why": "open"}
    elif any(not before(r.managed_at) for r in found):
        out[5] = {"met": False, "why": "late"}
    else:
        out[5] = {"met": True, "why": None}
    return out


def replaced(operation):
    """The booking this case was postponed from, or ``None``."""
    from app.models import Operation

    if operation is None:
        return None
    return Operation.query.filter_by(postponed_to_id=operation.id).first()


def starting_point(operation, kind):
    """``(values, source)`` for the form: this case's own assessment
    (``"current"``), else the one from the booking it replaced
    (``"postponed"``) to be reviewed, else nothing."""
    row = get(operation, kind)
    source = "current"
    if row is None:
        old = replaced(operation)
        row = get(old, kind) if old is not None else None
        source = "postponed" if row is not None else None
    if row is None:
        return {}, None
    return {f: getattr(row, f) for f in FIELDS[kind]}, source


# ----------------------------------------------------------- writing ----
def _clean(value):
    return (value or "").strip() or None


def save(operation, kind, user=None, now=None, **fields):
    """Write this case's assessment of one kind. The caller commits.

    Refuses what could not be true: a fasting time in the future, a weight
    that is not a child's, a risk class that is not on the hospital's list.
    """
    now = now or datetime.utcnow()
    if operation is None or operation.status == "cancelled":
        raise ValueError("no case")
    if kind not in KINDS:
        raise ValueError("unknown kind")
    row = get(operation, kind)
    if row is None:
        row = PreOpAssessment(operation_id=operation.id, kind=kind)
        db.session.add(row)
    if kind == MEDICAL:
        key = _clean(fields.get("risk_class"))
        if key is not None and key not in {r.key for r in risk_classes()}:
            raise ValueError("not on the list")
        row.indication = _clean(fields.get("indication"))
        row.history = _clean(fields.get("history"))
        row.examination = _clean(fields.get("examination"))
        row.risk_class = key
        none = fields.get("risks_none")
        # "No risks identified" over a list of risks is two answers that
        # cannot both be true — refused rather than guessed between.
        if none and risks(operation):
            raise ValueError("risks listed")
        row.risks_none = none
    else:
        for name in ("fasting_food_at", "fasting_fluid_at"):
            moment = fields.get(name)
            if moment is not None and moment > now + timedelta(minutes=5):
                raise ValueError("future")
            setattr(row, name, moment)
        weight = fields.get("weight_kg")
        if weight is not None and not 0.3 <= weight <= 250:
            raise ValueError("weight")
        row.weight_kg = weight
        row.vitals = _clean(fields.get("vitals"))
        row.allergies_checked = fields.get("allergies_checked")
        row.general = _clean(fields.get("general"))
    row.at = now
    row.by_id = getattr(user, "id", None)
    return row


def add_risk(operation, risk, action=None, user=None, now=None):
    """An identified risk — EOC 4 — with its action if it is already known.
    Naming a risk clears "no risks identified": the two cannot both be
    true."""
    now = now or datetime.utcnow()
    if operation is None or operation.status == "cancelled":
        raise ValueError("no case")
    risk = (risk or "").strip()[:255]
    if not risk:
        raise ValueError("no risk")
    row = PreOpRisk(operation_id=operation.id, risk=risk, noted_at=now,
                    noted_by=getattr(user, "id", None))
    db.session.add(row)
    if _clean(action):
        act(row, action, user=user, now=now)
    medical = get(operation, MEDICAL)
    if medical is not None and medical.risks_none:
        medical.risks_none = False
    return row


def act(risk_row, action, user=None, now=None):
    """What was done about it — EOC 5."""
    action = (action or "").strip()[:255]
    if risk_row is None or not action:
        raise ValueError("no action")
    risk_row.action = action
    risk_row.managed_at = now or datetime.utcnow()
    risk_row.managed_by = getattr(user, "id", None)
    return risk_row
