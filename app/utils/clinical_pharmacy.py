"""The ward pharmacist: whose chart has nobody been through today.

**Not the counter.** :mod:`app.utils.pharmacy` is the dispensing pharmacy — a
queue of people holding paper, a box off the shelf, money. This is the other
half of the same profession and the half a hospital is bought for: somebody
who reads the drug chart of every child in a bed, against that child's weight
and their kidneys and the four other things they are on, and says something to
the doctor before a dose is given rather than after.

``HOSPITAL_PLAN.md`` مرحلة ج بند ٧ names three things and **none of the
clinical rules are written here**: the paediatric dose lives in
:mod:`app.utils.dosing`, the interactions and allergies in
:mod:`app.utils.rx_safety`, and the ward already hands its chart to that check
through ``drug_round.safety``. The pharmacist sees exactly what the doctor and
the nurse see, which is the point of a third pair of eyes and would be
defeated by a third rulebook.

What is here is the **work**, and it has the shape of every other ward
question this program answers:

* **who has nobody been through today** — the same sentence as the ward
  round's, because a chart reviewed on Monday says nothing about the drug
  started on Wednesday;
* **a review is a row**, not a flag: a stay with no query on it looks exactly
  like a stay nobody has opened, and those are opposite facts;
* **and a query is a question, never a block.** The order goes on being given
  while it is open. The answer is usually "yes, I meant it", the child is in
  the bed, and a pharmacy that can stop a ward's drug is one the ward starts
  writing around.

**And the other half is work rather than reading.** A hospital pharmacy makes
up what each ward needs before the round — labelled per child, per drug, per
day — and in most hospitals that is the larger half of the job. The program
had nothing for it: a dose existed only at the moment a nurse recorded giving
it, so *"is this child's amoxicillin ready?"* had no answer anywhere. See
:func:`supply_list` and :func:`prepare`.

**How many doses is arithmetic on the doctor's own order** — six-hourly for a
day is four — and never a judgement about what a child needs. A PRN order has
no count at all, because there is no hour it is owed at.

**What this module will not do**, and the list is worth stating: it does not
choose a diluent, a final volume, an infusion time or a stability window, and
it does not formulate parenteral nutrition or adjust a dose for a kidney.
Every one of those is a clinical number or a rulebook, and the rule that stops
this program inventing an alert threshold stops it inventing these. A clinic
with its own recipe writes it on the order, where a person wrote it.
"""
from datetime import datetime

from app.extensions import db
from app.models import ChartReview, MedicationOrder
from app.models.admission import Admission


def reviewed_today(admission_ids, on_date=None):
    """``{admission_id: ChartReview}`` for reviews done on the clinic's today.

    One query for the whole board, and the clinic's day rather than the
    server's — comparing a stored UTC moment against a local date is the
    mistake this program has already paid for in four money reports.
    """
    from app.utils.clock import local_today
    from app.utils.live import day_bounds

    if not admission_ids:
        return {}
    start, end = day_bounds(on_date or local_today())
    rows = (ChartReview.query
            .filter(ChartReview.admission_id.in_(admission_ids),
                    ChartReview.at >= start, ChartReview.at < end)
            .order_by(ChartReview.at).all())
    return {row.admission_id: row for row in rows}


def open_queries(admission_ids=None):
    """``{admission_id: [order]}`` — questions the doctor has not answered.

    Grouped by stay because that is how the board reads: a child with two
    unanswered questions is one row that needs somebody, not two.
    """
    query = MedicationOrder.query.filter(
        MedicationOrder.queried_at.isnot(None),
        MedicationOrder.answered_at.is_(None),
        MedicationOrder.stopped_at.is_(None))
    if admission_ids is not None:
        if not admission_ids:
            return {}
        query = query.filter(MedicationOrder.admission_id.in_(admission_ids))
    out = {}
    for row in query.order_by(MedicationOrder.queried_at).all():
        out.setdefault(row.admission_id, []).append(row)
    return out


def board(kind=None, on_date=None):
    """Every child in a bed, unreviewed first, with what they are on.

    Unreviewed first and not alphabetical: the whole reason to open this
    screen is to find who has been missed, and a list that buries them among
    the ones already done is a list that gets read from the top and abandoned.
    """
    from app.utils import drug_round
    from app.models.place import Bed, Space, Unit

    stays = (Admission.query
             .filter(Admission.discharged_at.is_(None))
             .order_by(Admission.admitted_at).all())
    if kind:
        stays = [s for s in stays
                 if s.bed is not None and s.bed.unit is not None
                 and s.bed.unit.kind == kind]
    if not stays:
        return []

    ids = [s.id for s in stays]
    done = reviewed_today(ids, on_date)
    asked = open_queries(ids)
    charts = drug_round.running_orders(ids)

    known = high_alert_map()
    rows = []
    for stay in stays:
        orders = list(charts.get(stay.id) or [])
        rows.append({
            "admission": stay, "patient": stay.patient, "bed": stay.bed,
            "orders": orders, "drugs": len(orders),
            "review": done.get(stay.id),
            "queries": asked.get(stay.id) or [],
            # The two the standards ask about: what this hospital said it is
            # careful with, and what nobody with a pharmacy training has
            # looked at yet.
            "high_alert": sum(1 for o in orders
                              if high_alert_for(o, known) is not None),
            "unverified": sum(1 for o in orders if o.verified_at is None),
        })
    # Nobody has been to them, then whoever has the most on their chart —
    # which is the honest proxy for who is most worth a second pair of eyes.
    rows.sort(key=lambda r: (r["review"] is not None, -r["drugs"]))
    return rows


def counts(rows=None):
    """``{beds, unreviewed, queries}`` — the three numbers on the heading."""
    rows = board() if rows is None else rows
    return {"beds": len(rows),
            "unreviewed": sum(1 for r in rows if r["review"] is None),
            "queries": sum(len(r["queries"]) for r in rows)}


def chart(admission, lang="ar"):
    """This stay's drug chart with the clinic's own safety check over it.

    ``drug_round.safety`` and nothing else — the same call the ward screen
    makes. A clinical pharmacy with its own idea of an interaction would be a
    second copy of a clinical rule, free to disagree with the prescription
    screen about the same child on the same day.
    """
    from app.utils import drug_round

    if admission is None:
        return {"orders": [], "safety": None}
    orders = list(drug_round.running_orders([admission.id])
                  .get(admission.id) or [])
    known = high_alert_map()
    return {"orders": orders,
            "high_alert": {o.id: high_alert_for(o, known) for o in orders},
            "safety": drug_round.safety(admission, lang=lang)}


def review(admission, user=None, note=None, at=None):
    """Record that somebody went through this chart. Returns the row.

    A second review on the same day is a second row rather than an update:
    two pharmacists looking at the same child four hours apart is two events,
    and the board only ever asks whether *any* of them happened today.
    """
    if admission is None:
        raise ValueError("no stay")
    from app.utils import drug_round

    row = ChartReview(
        admission_id=admission.id, patient_id=admission.patient_id,
        at=at or datetime.utcnow(), by_id=getattr(user, "id", None),
        drugs_seen=len(drug_round.running_orders([admission.id])
                       .get(admission.id) or []),
        note=(note or "").strip()[:255] or None)
    db.session.add(row)
    return row


def ask(order, note=None, user=None, at=None):
    """Ask the doctor about one order. Never stops it."""
    if order is None:
        raise ValueError("no order")
    text = (note or "").strip()[:255]
    if not text:
        # A question with no question in it would flag the order and say
        # nothing, which reads on the doctor's screen as somebody having
        # looked and been satisfied.
        raise ValueError("no note")
    order.query_note = text
    order.queried_at = at or datetime.utcnow()
    order.queried_by = getattr(user, "id", None)
    # Asking again reopens: a doctor answered, the pharmacist is still not
    # happy, and the second question is the one that matters.
    order.answer_note = None
    order.answered_at = None
    order.answered_by = None
    return order


def answer(order, note=None, user=None, at=None):
    """The doctor's reply. The question stays on the order afterwards.

    Clearing it would leave a changed dose with nothing saying why, and an
    unchanged one with nothing saying it was defended.
    """
    if order is None or order.queried_at is None:
        raise ValueError("nothing asked")
    order.answer_note = (note or "").strip()[:255] or None
    order.answered_at = at or datetime.utcnow()
    order.answered_by = getattr(user, "id", None)
    return order


# ------------------------------------------------------ making them up -----
def doses_in_a_day(order):
    """How many doses a day this order comes to, or ``None`` for a PRN.

    Arithmetic on what the doctor wrote and nothing else. ``None`` is the
    honest answer for "when needed": there is no hour it is owed at, so there
    is no number of them in a day, and a pharmacy supplies those by agreement
    rather than by a count this program made up.
    """
    if order is None or order.is_prn or not order.every_hours:
        return None
    return max(1, int(24 // max(1, int(order.every_hours))))


def prepared_on(order_ids, on_date=None):
    """``{order_id: DosePrep}`` for the batches made up on a clinic date."""
    from app.models import DosePrep
    from app.utils.clock import local_today

    if not order_ids:
        return {}
    rows = (DosePrep.query
            .filter(DosePrep.order_id.in_(order_ids),
                    DosePrep.for_date == (on_date or local_today()))
            .all())
    return {row.order_id: row for row in rows}


def supply_list(kind=None, on_date=None):
    """What the pharmacy has to make up today, child by child.

    Grouped by child rather than by drug, because that is how a unit-dose bag
    is filled and how it is checked: one label, one patient, everything they
    are on. A list sorted by drug would have somebody walking the shelves once
    per patient instead of once per round.

    Children with nothing left to make up drop off — the list is the work
    remaining, and one that keeps everybody on it is one nobody can see the
    end of.
    """
    from app.utils import drug_round
    from app.utils.clock import local_today

    on_date = on_date or local_today()
    stays = (Admission.query
             .filter(Admission.discharged_at.is_(None))
             .order_by(Admission.admitted_at).all())
    if kind:
        stays = [s for s in stays
                 if s.bed is not None and s.bed.unit is not None
                 and s.bed.unit.kind == kind]
    if not stays:
        return []

    charts = drug_round.running_orders([s.id for s in stays])
    every_order = [o for orders in charts.values() for o in orders]
    done = prepared_on([o.id for o in every_order], on_date)

    rows = []
    for stay in stays:
        lines = []
        for order in charts.get(stay.id) or []:
            count = doses_in_a_day(order)
            lines.append({
                "order": order, "doses": count,
                "units": (None if count is None
                          else count * max(1, int(order.units_per_dose or 1))),
                "prep": done.get(order.id),
            })
        if not lines or all(ln["prep"] is not None for ln in lines):
            continue
        rows.append({"admission": stay, "patient": stay.patient,
                     "bed": stay.bed, "lines": lines,
                     "left": sum(1 for ln in lines if ln["prep"] is None)})
    # Most left to do first: a pharmacist works the biggest bag first because
    # it is the one most likely to still be unfinished when the round starts.
    rows.sort(key=lambda r: -r["left"])
    return rows


def prepare(order, user=None, doses=None, units=None, label=None,
            on_date=None, note=None):
    """Record that today's supply of this drug is made up. Returns the row.

    Making it up again on the same day updates rather than adds: a bag redone
    because the order changed at noon is still one bag going up to the ward,
    and two rows would tell the ward it was ready twice.
    """
    from app.models import DosePrep
    from app.utils.clock import local_today

    if order is None:
        raise ValueError("no order")
    if not order.is_running:
        # A stopped order is not supplied. Making up a drug nobody may give is
        # the one mistake this list can cause, so it is refused here rather
        # than left to the screen.
        raise ValueError("not running")

    for_date = on_date or local_today()
    row = DosePrep.query.filter_by(order_id=order.id,
                                   for_date=for_date).first()
    if row is None:
        row = DosePrep(order_id=order.id, admission_id=order.admission_id,
                       patient_id=order.patient_id, for_date=for_date)
        db.session.add(row)
    counted = doses_in_a_day(order) if doses is None else doses
    row.doses = counted
    row.units = (units if units is not None
                 else (None if counted is None
                       else counted * max(1, int(order.units_per_dose or 1))))
    row.prepared_at = datetime.utcnow()
    row.prepared_by = getattr(user, "id", None)
    row.label = (label or "").strip()[:255] or None
    row.note = (note or "").strip()[:255] or None
    return row


def supply_counts(rows=None):
    """``{children, drugs}`` still to make up — the heading's two numbers."""
    rows = supply_list() if rows is None else rows
    return {"children": len(rows),
            "drugs": sum(r["left"] for r in rows)}


# --------------------------------------------- the hospital's own list -----
def high_alert_map():
    """``{("generic", id): row}`` and ``{("drug", id): row}`` — the list.

    One query and a dict, because every screen that draws a chart asks about
    every line on it. Empty for a hospital that has not written its list,
    which is where a fresh install stays: **nothing is seeded**, because a
    list of dangerous drugs bundled with the software would be somebody
    else's judgement about a ward it has never seen.
    """
    from app.models import HighAlertDrug

    out = {}
    for row in HighAlertDrug.query.filter(
            HighAlertDrug.is_active.is_(True)).all():
        if row.generic_id:
            out[("generic", row.generic_id)] = row
        if row.drug_id:
            out[("drug", row.drug_id)] = row
    return out


def high_alert_for(order, known=None):
    """The list's row for this order, or ``None``.

    Matched on the **active ingredient** first, so every brand of it is caught
    including the one this clinic has not stocked yet — the same argument the
    interaction pairs are built on — and on the product only when the concern
    genuinely is that box.
    """
    if order is None:
        return None
    known = high_alert_map() if known is None else known
    drug = getattr(order, "drug", None)
    if drug is not None:
        hit = known.get(("drug", drug.id))
        if hit is not None:
            return hit
        if getattr(drug, "generic_id", None):
            hit = known.get(("generic", drug.generic_id))
            if hit is not None:
                return hit
    # A hand-typed line still matches when it names the ingredient: a ward
    # that types "morphine" rather than picking a box is exactly the ward this
    # flag is for.
    from app.models import GenericDrug

    name = (getattr(order, "drug_name", "") or "").strip().lower()
    if not name:
        return None
    for (kind, ident), row in known.items():
        if kind != "generic":
            continue
        found = db.session.get(GenericDrug, ident)
        if found is None:
            continue
        for label in (found.name_en, found.name_ar):
            if label and label.strip().lower() == name:
                return row
    return None


def verify(order, user=None, at=None):
    """A pharmacist checked this order. Never a block, only a record.

    A hospital at three in the morning with no pharmacist on site still gives
    the antibiotic, and a program that refused would be worked around by the
    end of the first night — which is how a control stops meaning anything.
    The gap is made visible and kept visible instead.
    """
    if order is None:
        raise ValueError("no order")
    if not order.is_running:
        raise ValueError("not running")
    order.verified_at = at or datetime.utcnow()
    order.verified_by = getattr(user, "id", None)
    return order


def unverified(admission_ids=None):
    """Running orders no pharmacist has checked — high-alert ones first.

    The order the standards care about most is the one nobody looked at, and
    among those the ones this hospital has already said it is careful with.
    """
    query = MedicationOrder.query.filter(
        MedicationOrder.verified_at.is_(None),
        MedicationOrder.stopped_at.is_(None))
    if admission_ids is not None:
        if not admission_ids:
            return []
        query = query.filter(MedicationOrder.admission_id.in_(admission_ids))
    rows = query.order_by(MedicationOrder.started_at).all()
    known = high_alert_map()
    rows.sort(key=lambda o: high_alert_for(o, known) is None)
    return rows
