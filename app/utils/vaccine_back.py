"""Telling the families who were waiting that the vaccine arrived.

*"لو التطعيم مش متوفر يبعت يقول للحالة بالتذكير عادي، ولما يتوفر يولد للناس
المتأخرة اللي اتولدلها رسايل رسالة إنه بقى متوفر وتقدر تيجي تاخده، والناس اللي
وعدها ما جاش زي ما هما."*

Three separate instructions, and only one of them needed building.

**The reminder goes out anyway.** It already does — the due list is computed
from the child's schedule and has never consulted the fridge. That is the
right way round: a family told their child is late can plan, and a clinic that
goes quiet because a shelf is empty loses the child to the pharmacy down the
road.

**The order forecast** — *"محتاج ١٢ تطعيم من ده لأن عندك ١٢ حالة مستحقة"* — is
also already there: the reminders screen totals the same list by brand and
subtracts what is on the shelf (:func:`app.utils.vaccine_due.order_suggestion`).

**What was missing is the call back.** The dose arrives, and the families who
were told to come — and could not be served — are never told. They are the
ones who did the right thing, so they are exactly the wrong people to forget.

Who gets the message is deliberately narrow:

* they were **sent a reminder for this brand** (the reminder now records which
  brand it was about, which is what makes this answerable at all);
* the dose is **still due** — a child who came and had it is not chased;
* and they have **not already been told about this delivery**, so a clinic
  that receives three boxes in a week does not message the same family three
  times.

Nobody is messaged for a family that was promised something else and simply
did not come: that is a different conversation, and the clinic asked for it to
be left alone.
"""
from app.models import MessageLog, Patient, VaccineInventory
from app.utils import whatsapp as wa

TYPE = "vaccine_back"
REMINDER = "vaccine_due"


def _last_arrival(brand):
    """When stock for this brand most recently arrived, or None.

    The boundary for "already told": a family told about Tuesday's delivery
    should be told again about next month's, and not again about Tuesday's.
    """
    rows = [b.created_at for b in brand.batches if b.created_at]
    return max(rows) if rows else None


def waiting_for(brand):
    """The patients who were reminded about this brand and are still waiting.

    ``[{patient, reminded_at}]``, longest-waiting first — the family that has
    been put off since March is the one to call before the one from Sunday.
    """
    if brand is None or brand.stock <= 0:
        return []

    since = _last_arrival(brand)
    reminded, told = {}, set()
    for log in (MessageLog.query
                .filter(MessageLog.vaccine_brand_id == brand.id,
                        MessageLog.template_type.in_((REMINDER, TYPE)),
                        MessageLog.patient_id.isnot(None))
                .order_by(MessageLog.created_at).all()):
        if log.template_type == REMINDER:
            reminded.setdefault(log.patient_id, log.created_at)
        elif since is not None and log.created_at >= since:
            told.add(log.patient_id)

    ids = [pid for pid in reminded if pid not in told]
    if not ids:
        return []

    out = []
    for patient in Patient.query.filter(Patient.id.in_(ids),
                                        Patient.is_active.is_(True)).all():
        if _still_due(patient, brand):
            out.append({"patient": patient, "reminded_at": reminded[patient.id]})
    out.sort(key=lambda row: row["reminded_at"])
    return out


def _still_due(patient, brand):
    """Whether this child is *now* owed a dose of this vaccine.

    Asked of the schedule rather than of the reminder, because the child may
    have had the dose since — here, or at a government unit, or anywhere else
    the clinic later recorded.
    """
    from app.utils.vaccines import patient_due_reminders

    vaccine_id = brand.vaccine_id
    return any(row["vaccine"].id == vaccine_id
               for row in patient_due_reminders(patient))


def notify(brand, user_id=None, lang="ar"):
    """Tell everyone waiting that it is here. Returns the logs written."""
    from app.extensions import db
    from app.models import Setting

    logs = []
    for row in waiting_for(brand):
        patient = row["patient"]
        body = wa.render(wa.template_body(TYPE), {
            "patient": patient.display_name(lang),
            "vaccine": (brand.vaccine.display_name(lang)
                        if brand.vaccine else brand.name),
            "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        })
        log = wa.send(body, patient.contact_phone, patient_id=patient.id,
                      user_id=user_id, template_type=TYPE,
                      image_url=wa.template_image(TYPE))
        # What it was about, so this brand's next delivery knows who has
        # already heard from us.
        log.vaccine_brand_id = brand.id
        logs.append(log)
    db.session.flush()
    return logs


def brands_with_people_waiting():
    """``[(brand, count)]`` for every brand somebody is waiting on.

    Kept cheap enough for a dashboard: only brands that actually have stock
    are considered, because a brand with an empty shelf has nobody to call.
    """
    from app.models import VaccineBrand

    in_stock = {row[0] for row in (
        VaccineInventory.query
        .with_entities(VaccineInventory.brand_id).distinct().all())}
    out = []
    for brand in VaccineBrand.query.filter(VaccineBrand.id.in_(in_stock or {0})).all():
        people = waiting_for(brand)
        if people:
            out.append({"brand": brand, "count": len(people),
                        "waiting": people})
    return sorted(out, key=lambda row: -row["count"])
