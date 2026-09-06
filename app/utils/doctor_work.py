"""One doctor's own work over a window: what they saw, and what it earned.

Asked for as a screen of their own: *"عايز أعمل شاشة الطبيب يشوف فيها حالاته
المحجوزة، نصيبه قد إيه النهارده، على مدار الشهر، شاف كام حالة جديدة، شاف كام
حالة بأنواعها — كشف، أول مرة، قديمة، استشارة، تطعيم، وأي خدمات هو بيقدمها زي
رسم القلب"*.

**Every part of that answer already existed, in three different places.** The
case counts by service and the share per service were in the printable staff
statement, under Reports, which most doctors cannot open. New-versus-returning
was computed inside the appointments board. The share for today and this month
was a fourth calculation on the board again. A doctor asking "how am I doing"
had to visit three screens and could reach none of them.

So this module is the answer, once, and the report and the screen both read it.
Writing a second version would have been the easier morning and the wrong
trade: a doctor's pay is a number two calculations must never disagree about.

**Two things it deliberately does not do.**

It does not say what the doctor has been *paid*. The program can total what
they have earned; there is no record anywhere of money handed to a doctor, so
"how much is still owed to me" is a number nobody could compute honestly. A
screen that showed it would be inventing the subtrahend. It is left out and
said out loud rather than guessed.

And it does not decide who may read it. Scope is the caller's business — a
doctor sees their own, whoever runs the clinic may ask about anybody — because
a rule about who sees whose money should live where the permissions are, not
inside the arithmetic.
"""
from collections import Counter

from app.extensions import db


def _paid_in(doctor_id, date_from, date_to):
    from app.models import DoctorPayout

    return DoctorPayout.paid_to(doctor_id, date_from, date_to)


def _appointments(doctor_id, date_from, date_to):
    """Real visits in the window. A cancelled or no-show slot is not a patient
    seen, and counting one is a doctor told they were busier than they were."""
    from app.models import Appointment

    return (Appointment.query
            .filter(Appointment.doctor_id == doctor_id,
                    Appointment.appt_date >= date_from,
                    Appointment.appt_date <= date_to,
                    Appointment.status.notin_(("cancelled", "no_show")))
            .order_by(Appointment.appt_date, Appointment.appt_time).all())


def by_type(appointments, lang="ar"):
    """``[{key, label, color, count}]`` — كشف / متابعة / استشارة / تطعيم …

    Ordered by the catalogue rather than by count, so a doctor reading it twice
    in a day finds each row where they left it. Types the clinic has retired
    still appear when something in the window used them: the row is history,
    and dropping it would silently change a total.
    """
    from app.utils.visit_types import active_types, label as type_label

    counted = Counter(a.appt_type for a in appointments)
    rows, seen = [], set()
    for kind in active_types():
        rows.append({"key": kind.key, "label": kind.display_name(lang),
                     "color": kind.color, "count": counted.get(kind.key, 0)})
        seen.add(kind.key)
    for key in counted:
        if key not in seen:
            rows.append({"key": key, "label": type_label(key, lang),
                         "color": "blue", "count": counted[key]})
    return rows


def new_and_returning(appointments, date_from, date_to):
    """``{new, returning, total}`` — patients, not appointments.

    **New means the child's first-ever real visit falls inside the window**,
    and it is asked of the whole clinic rather than of this doctor: a child who
    has been coming for two years and sees a second doctor for the first time
    is not a new patient, and counting them as one would tell a clinic it was
    growing when it was rotating.

    Counted per patient, so a child seen three times in a month is one
    returning patient and not three.
    """
    from app.models import Appointment

    patients = {a.patient_id for a in appointments if a.patient_id}
    if not patients:
        return {"new": 0, "returning": 0, "total": 0}

    first_seen = dict(
        db.session.query(Appointment.patient_id,
                         db.func.min(Appointment.appt_date))
        .filter(Appointment.patient_id.in_(patients),
                Appointment.status.notin_(("cancelled", "no_show")))
        .group_by(Appointment.patient_id).all())

    new = sum(1 for p in patients
              if first_seen.get(p) and date_from <= first_seen[p] <= date_to)
    return {"new": new, "returning": len(patients) - new, "total": len(patients)}


def by_service(doctor_id, date_from, date_to, lang="ar"):
    """``([{label, count, gross, share}], share_total)`` — the money, per thing.

    Invoice lines carry their own commission, so the share is read off each
    line rather than recomputed from a percentage: a line discounted at the
    desk, or priced by hand, already has the right number on it and working it
    out again from the service's rate would quietly disagree with the invoice
    the patient was given.

    Vaccines are their own row because their money is shaped differently: the
    doctor's cut is a fee on the brand recorded against the dose, not a
    commission on an invoice line, and folding it into the services would make
    a total nobody could trace back.

    **And the lines are gathered by whose they are, not whose invoice they sit
    on** (``InvoiceItem.earner_id``). A stay's bill belongs to the admitting
    doctor and carries the surgeon's operation and the visiting consultant's
    round on it; asking the invoice would have paid all three at one rate and
    put all three on one statement.
    """
    from app.models import Invoice, InvoiceItem, PatientVaccine

    lines_q = (InvoiceItem.query
               .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
               .filter(InvoiceItem.earned_by(doctor_id),
                       Invoice.invoice_date >= date_from,
                       Invoice.invoice_date <= date_to))

    groups, invoices, seen = {}, [], set()
    for line in lines_q.order_by(Invoice.invoice_date, Invoice.id).all():
        if line.invoice_id not in seen:
            seen.add(line.invoice_id)
            invoices.append(line.invoice)
        key = line.service_id or 0
        row = groups.get(key)
        if row is None:
            label = (line.service.display_name(lang) if line.service
                     else (line.description or "—"))
            row = groups[key] = {"label": label, "count": 0,
                                 "gross": 0.0, "share": 0.0}
        row["count"] += line.quantity or 1
        row["gross"] += line.net
        row["share"] += line.commission_amount or 0

    rows = sorted(({"label": r["label"], "count": r["count"],
                    "gross": round(r["gross"], 2),
                    "share": round(r["share"], 2)} for r in groups.values()),
                  key=lambda r: -r["share"])

    doses = (PatientVaccine.query
             .filter(PatientVaccine.doctor_id == doctor_id,
                     PatientVaccine.event_type == "given",
                     PatientVaccine.given_outside.is_(False),
                     PatientVaccine.given_date >= date_from,
                     PatientVaccine.given_date <= date_to).all())
    vaccine_share = round(sum((d.brand.doctor_fee or 0)
                              for d in doses if d.brand), 2)
    if doses:
        from app.i18n import t

        rows.append({
            "label": t("reports.vaccines_line"), "count": len(doses),
            "gross": round(sum((d.brand.price or 0) for d in doses if d.brand), 2),
            "share": vaccine_share,
        })

    # Their own lines, not the whole of every bill they appear on.
    # Cover is its own row for the reason the vaccines are: it is money of a
    # different shape — no invoice, no patient — and folding it into the
    # services would make a total nobody could trace back.
    duty_rows = _duty_rows(doctor_id, date_from, date_to)
    rows.extend(duty_rows)
    duty_share = round(sum(r["share"] for r in duty_rows), 2)

    share = round(sum(i.share_for(doctor_id) for i in invoices)
                  + vaccine_share + duty_share, 2)
    return rows, share, invoices



def _duty_earned(doctor_id, date_from=None, date_to=None):
    """What cover has earned them — nothing at all when the rota is off.

    **Off means absent, not zero-by-accident.** Every module-owned question
    asked from a screen every clinic opens goes through ``module_enabled``
    first, so a clinic that does not roster never pays a query for a table it
    has no rows in.
    """
    from app.utils.facility import module_enabled

    if not module_enabled("duty"):
        return 0.0
    from app.utils import duty

    return duty.earned(doctor_id, date_from, date_to)


def _duty_rows(doctor_id, date_from, date_to):
    """Their cover in the window, grouped by shift. Empty when the rota is off."""
    from app.utils.facility import module_enabled

    if not module_enabled("duty"):
        return []
    from app.utils import duty

    return [{"label": row["label"], "count": row["count"],
             # A shift has no price to a patient, so there is no gross to
             # show. Zero and not the share repeated: a column headed "billed"
             # carrying the doctor's own pay is a number that reads as revenue.
             "gross": 0.0, "share": row["share"]}
            for row in duty.by_slot(doctor_id, date_from, date_to)]


def _refunded_share(doctor_id, date_from=None, date_to=None):
    """The doctor's share of every refund on their invoices.

    Proportional to what went back, per invoice — see
    :func:`app.utils.refunds.doctor_share_of`. Read off the notices rather
    than recomputed from today's invoice, because the notice carries the
    figure the doctor was told at the time and an invoice can be edited after
    a refund.
    """
    from app.models import RefundNotice

    query = db.session.query(db.func.sum(RefundNotice.doctor_amount)).filter(
        RefundNotice.doctor_id == doctor_id)
    if date_from is not None:
        query = query.filter(db.func.date(RefundNotice.created_at) >= date_from)
    if date_to is not None:
        query = query.filter(db.func.date(RefundNotice.created_at) <= date_to)
    return round(query.scalar() or 0, 2)


def earned_ever(doctor_id):
    """Everything this doctor has ever earned, in two aggregate queries.

    Summed in SQL rather than by loading the invoices: a balance is made of
    every invoice since the clinic opened, and :func:`by_service` builds row
    objects it does not need here. On a clinic three years in, the difference
    is a screen that opens and a screen that hangs.
    """
    from app.models import Invoice, InvoiceItem, PatientVaccine, VaccineBrand

    lines = (db.session.query(db.func.sum(InvoiceItem.commission_amount))
             .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
             .filter(InvoiceItem.earned_by(doctor_id)).scalar()) or 0
    # And the money that went back out takes its share with it. Without this,
    # a clinic that refunded a visit still owed the doctor their cut of money
    # it no longer had: `commission_amount` is the snapshot written when the
    # line was billed, and nothing had ever subtracted from it.
    lines -= _refunded_share(doctor_id)
    doses = (db.session.query(db.func.sum(VaccineBrand.doctor_fee))
             .join(PatientVaccine, PatientVaccine.brand_id == VaccineBrand.id)
             .filter(PatientVaccine.doctor_id == doctor_id,
                     PatientVaccine.event_type == "given",
                     PatientVaccine.given_outside.is_(False)).scalar()) or 0
    # And the nights they covered. A third shape of money, and the only one
    # with no patient behind it: a shift is owed by the clinic, not paid out
    # of somebody's bill. Leaving it out here would have shown a resident a
    # balance of zero on a month they worked eleven nights.
    return round(lines + doses + _duty_earned(doctor_id), 2)


def account(doctor_id):
    """``{earned, paid, balance}`` over all time — what is still owed.

    **All time, and deliberately not the window the screen is showing.** A
    balance is what has happened since the beginning; subtracting every payment
    ever made from one month's earnings would produce a number that means
    nothing and looks authoritative. The window answers "how was this month";
    this answers "where do we stand".
    """
    from app.models import DoctorPayout

    earned = earned_ever(doctor_id)
    paid = DoctorPayout.paid_to(doctor_id)
    return {"earned": earned, "paid": paid,
            "balance": round(earned - paid, 2)}


def summary(doctor_id, date_from, date_to, lang="ar"):
    """Everything one doctor's screen shows for one window.

    ``{types, patients, services, money, cases, seen}`` — and ``money`` carries
    what was billed, what the clinic collected against it and the doctor's
    share. **Not what the doctor has received**: nothing in the program records
    paying a doctor, so the difference between earned and paid cannot be
    computed and is not offered.
    """
    appointments = _appointments(doctor_id, date_from, date_to)
    services, share, invoices = by_service(doctor_id, date_from, date_to, lang)

    return {
        "types": by_type(appointments, lang),
        "patients": new_and_returning(appointments, date_from, date_to),
        "services": services,
        "money": {
            "billed": round(sum(i.total for i in invoices), 2),
            "collected": round(sum(i.paid for i in invoices), 2),
            "share": share,
            # What was handed over *in this window* — activity, beside the
            # activity it sits next to.
            "paid": _paid_in(doctor_id, date_from, date_to),
        },
        # And where the account stands overall. Never mixed with the window
        # above: earned-this-month minus paid-ever is not a number.
        "account": account(doctor_id),
        # Two different counts on purpose. `seen` is appointments kept — the
        # doctor's day. `cases` is billed items, which is larger whenever one
        # visit carried an ECG as well as the consultation, and it is the
        # number the share is made of.
        "seen": len(appointments),
        "cases": sum(r["count"] for r in services),
    }
