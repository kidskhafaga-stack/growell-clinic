"""Cost centres: which part of the clinic a line of money belongs to.

The list is the clinic's own shape — the outpatient clinics, and each unit,
theatre, laboratory, pharmacy and dental chair it runs — so nobody sets it up
before it is useful. A clinic may rename a centre, switch one off, or add its
own (a physiotherapy room) and point services at it.

**Revenue is placed, never chosen.** Every invoice line already says where it
came from, and :func:`for_item` reads that in one fixed order:

1. what wrote the line, when it knew — the theatre, the drug round, the
   pharmacy counter, the dental plan (``InvoiceItem.cost_centre_id`` set);
2. the service, when the clinic pointed it at a centre;
3. a vaccine is the vaccination service's;
4. a laboratory test is the laboratory's, an X-ray the imaging department's;
5. anything else on a stay's bill is the unit the child was in that day;
6. anything else from an emergency attendance is the emergency department's;
7. and the rest is the outpatient clinics'.

The answer is written on the line the first time the bill reaches the books,
and on the journal line beside it, so it never moves afterwards: a closed
month says the same thing in a year as it did the day it closed.

**Costs are placed only when somebody says so.** An expense entered against a
centre is that centre's; one entered against none is shared, and the report
shows it on a line of its own — the clinic decided that, rather than have the
program spread the rent by a rule nobody agreed (``IMPROVEMENTS_BACKLOG.md``).
A dose of vaccine given is the vaccination service's cost, because that is a
fact and not a rule.
"""
from app.extensions import db
from app.models import CostCentre

#: The program's own centres: (key, Arabic, English, the module that runs it).
#: The units are not here — there is one centre for each unit the clinic built.
SYSTEM = (
    ("outpatient", "العيادات الخارجية", "Outpatient clinics", "visits"),
    ("emergency", "الطوارئ", "Emergency", "emergency"),
    ("theatres", "العمليات", "Operating theatres", "theatres"),
    ("lab", "المعمل", "Laboratory", "labs"),
    ("imaging", "الأشعة", "Imaging", "labs"),
    ("pharmacy", "الصيدلية", "Pharmacy", "pharmacy"),
    ("dentistry", "الأسنان", "Dentistry", "dentistry"),
    ("vaccinations", "التطعيمات", "Vaccinations", "vaccinations"),
)
_SYSTEM = {key: (ar, en, module) for key, ar, en, module in SYSTEM}

#: The service categories that name their own department.
_CATEGORY_CENTRE = {"lab": "lab", "radiology": "imaging"}


def unit_key(unit_id):
    return f"unit:{unit_id}"


def centre(key):
    """The centre for ``key``, made the first time it is asked for.

    ``None`` for a key that is neither the program's nor a unit that exists —
    never a centre made up from a typo.
    """
    if not key:
        return None
    row = CostCentre.query.filter_by(key=key).first()
    if row is not None:
        return row
    if key in _SYSTEM:
        ar, en, _module = _SYSTEM[key]
        order = [k for k, *_ in SYSTEM].index(key)
        row = CostCentre(key=key, name_ar=ar, name_en=en, sort_order=order)
    elif key.startswith("unit:"):
        from app.models import Unit

        try:
            unit = db.session.get(Unit, int(key.split(":", 1)[1]))
        except ValueError:
            unit = None
        if unit is None:
            return None
        row = CostCentre(key=key, name_ar=unit.name, name_en=unit.name,
                         unit_id=unit.id, sort_order=100 + (unit.sort_order or 0))
    else:
        return None
    db.session.add(row)
    db.session.flush()
    return row


def centre_id(key):
    row = centre(key)
    return row.id if row is not None else None


def for_unit(unit):
    """The centre of a unit (a ward, the NICU), or ``None`` for no unit."""
    return centre(unit_key(unit.id)) if unit is not None else None


def unit_on(admission, day):
    """The unit the child was in on ``day`` during ``admission``.

    The last stay that had begun by that day — so a day between two stays is
    the unit the child had been in, not the one they had not reached yet. A
    line dated before the first bed (charged on arrival) is the first unit;
    one with no day is the latest. ``None`` without a bed at all.
    """
    from app.utils.clock import local_date

    stays = sorted((s for s in admission.stays if s.bed is not None),
                   key=lambda s: s.since)
    if not stays:
        return None
    if day is None:
        return stays[-1].bed.unit
    begun = [s for s in stays if local_date(s.since) <= day]
    return (begun[-1] if begun else stays[0]).bed.unit


def _is_vaccine(item):
    if item.vaccine_brand_id:
        return True
    service = item.service
    return service is not None and (
        service.service_type == "vaccination"
        or service.category == "vaccination_fee")


def _emergency(invoice):
    from app.models import EmergencyVisit

    return bool(invoice.visit_id) and EmergencyVisit.query.filter_by(
        visit_id=invoice.visit_id).first() is not None


def for_item(item):
    """The centre this invoice line's revenue belongs to (see the module's
    seven steps). Writes it on the line when the line has none, and returns
    the centre's id."""
    if item.cost_centre_id:
        return item.cost_centre_id
    item.cost_centre_id = _work_out(item)
    return item.cost_centre_id


def _work_out(item):
    service = item.service
    if service is not None and service.cost_centre_id:
        return service.cost_centre_id
    if _is_vaccine(item):
        return centre_id("vaccinations")
    if service is not None and service.category in _CATEGORY_CENTRE:
        return centre_id(_CATEGORY_CENTRE[service.category])
    invoice = item.invoice
    if invoice is not None and invoice.admission_id:
        from app.models import Admission

        admission = db.session.get(Admission, invoice.admission_id)
        unit = unit_on(admission, item.on_date) if admission else None
        if unit is not None:
            return for_unit(unit).id
    if invoice is not None and _emergency(invoice):
        return centre_id("emergency")
    return centre_id("outpatient")


def stamp(item, key=None, unit=None):
    """Set the centre on a line being written by something that knows —
    the theatre, the drug round, a bed night. Never overwrites one set."""
    if item.cost_centre_id:
        return
    row = for_unit(unit) if unit is not None else centre(key)
    if row is not None:
        item.cost_centre_id = row.id


# ------------------------------------------------------------- the list --
def ensure_all():
    """Make the centre of everything the clinic runs now: the program's own
    for each module switched on, and one for each active unit. Returns the
    ones made."""
    from app.models import Unit
    from app.utils.facility import module_enabled

    made = []
    have = {c.key for c in CostCentre.query.all()}
    for key, _ar, _en, module in SYSTEM:
        if key not in have and module_enabled(module):
            made.append(centre(key))
    if module_enabled("beds"):
        for unit in Unit.query.filter_by(is_active=True).all():
            if unit_key(unit.id) not in have:
                made.append(centre(unit_key(unit.id)))
    return [m for m in made if m is not None]


def listing(active_only=True):
    """The centres in the order they are shown."""
    query = CostCentre.query
    if active_only:
        query = query.filter(CostCentre.is_active.is_(True))
    return query.order_by(CostCentre.sort_order, CostCentre.id).all()


def add_own(name_ar, name_en=None):
    """A centre the clinic adds itself. Returns it."""
    taken = [c.key for c in CostCentre.query.filter(
        CostCentre.key.like("own:%")).all()]
    number = max((int(k.split(":", 1)[1]) for k in taken
                  if k.split(":", 1)[1].isdigit()), default=0) + 1
    row = CostCentre(key=f"own:{number}", name_ar=name_ar,
                     name_en=name_en or None, sort_order=200 + number)
    db.session.add(row)
    db.session.flush()
    return row
