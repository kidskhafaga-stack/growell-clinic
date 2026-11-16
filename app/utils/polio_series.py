"""Polio as one series — OPV and IPV read together (IMPROVEMENTS_BACKLOG ٠.٢).

The backlog left both ceilings empty on purpose: *«شلل الأطفال سلسلة واحدة
مع OPV في البرنامج المصري. محرك واحد يفهم الاتنين، مش سقفين مستقلين»*. Read
one at a time, a child with the oral doses and none injected, or the injected
doses inside a hexavalent and fewer oral ones, looks "behind" or "done" on
the wrong card. Read together, the question has one answer.

**Every number here is the source's, quoted, and nothing else is.** The
source is WHO's position paper, read from WHO's own repository on 15
November 2026 — :data:`SOURCE`. Its «WHO position» section says, for a
country that uses OPV:

* «WHO recommends 3 doses of bOPV and 2 doses of IPV as the vaccination
  schedule»;
* «a bOPV birth dose (zero dose) followed by the primary series of 3 bOPV
  doses and 2 IPV doses. The zero dose of bOPV should be administered at
  birth, or within the first week of life»;
* «3 doses of bOPV starting from the minimum age of 6 weeks, with at least a
  4 week interval between doses»;
* «The first IPV dose should be administered from a minimum of 14 weeks of
  age (with DTP3/Penta3), with the second IPV dose being given at least 4
  months later»; and, as the alternative, «the first IPV dose at 6 weeks of
  age … and the second IPV dose at 14 weeks»;
* «For infants late in starting the routine immunization schedule (age >3
  months) the first IPV dose should be administered at the first
  immunization contact»;
* and for an IPV-only schedule, «a minimum 4 week interval between doses».

The paper names **no upper age** for completing the series, and nor does this
module: a six-year-old missing polio doses is missing them.

**What it does not do.** It changes no due date on the national schedule —
that table is the clinic's, reviewed by its doctors, and Egypt's own
programme is the authority for it. It reads what was given, says what counts
toward the series and what is still missing by the paper's own rule, the
earliest day the next dose may be given, and where the clinic's schedule
asks for fewer doses than the paper. The doctor decides.
"""
from datetime import timedelta

#: Where every number below comes from.
SOURCE = {
    "title": "Polio vaccines: WHO position paper – June 2022",
    "citation": "Weekly Epidemiological Record 2022;97(25):277–300",
    "url": "https://iris.who.int/handle/10665/357168",
}

#: «3 doses of bOPV».
OPV_PRIMARY = 3
#: «2 doses of IPV».
IPV_DOSES = 2
#: The zero dose: «at birth, or within the first week of life».
ZERO_DOSE_DAYS = 7
#: «starting from the minimum age of 6 weeks».
OPV_MIN_AGE_DAYS = 6 * 7
#: «at least a 4 week interval between doses».
OPV_MIN_GAP_DAYS = 4 * 7
#: The earliest any IPV schedule in the paper starts: «the first IPV dose at
#: 6 weeks of age» (the alternative early schedule).
IPV_MIN_AGE_DAYS = 6 * 7
#: The least interval between IPV doses any schedule in the paper allows:
#: «a minimum 4 week interval between doses» (IPV-only primary series).
IPV_MIN_GAP_DAYS = 4 * 7
#: The preferred schedule: «from a minimum of 14 weeks of age».
IPV1_PREFERRED_AGE_DAYS = 14 * 7
#: The preferred schedule: «at least 4 months later».
IPV2_PREFERRED_GAP_MONTHS = 4
#: «age >3 months» — first IPV at the first contact.
LATE_START_MONTHS = 3

OPV_CODES = ("OPV",)
IPV_CODES = ("IPV",)


def _add_months(day, months):
    from app.utils.vaccines import add_months

    return add_months(day, months)


def contains_ipv(vaccine, brand):
    """IPV given as itself or inside a combination (the hexavalent,
    Pentaxim) — read from the brand's own valency, «DTaP-IPV-HepB-Hib»."""
    if vaccine is not None and vaccine.code in IPV_CODES:
        return True
    return bool(brand is not None and "IPV" in (brand.valency or ""))


def _doses(patient):
    """``(opv_rows, ipv_rows)`` given, oldest first."""
    from app.models import PatientVaccine

    opv, ipv = [], []
    rows = (PatientVaccine.query
            .filter_by(patient_id=patient.id)
            .order_by(PatientVaccine.given_date, PatientVaccine.id).all())
    for row in rows:
        if (row.event_type or "given") != "given" or row.given_date is None:
            continue
        if row.vaccine is not None and row.vaccine.code in OPV_CODES:
            opv.append(row)
        elif contains_ipv(row.vaccine, row.brand):
            ipv.append(row)
    return opv, ipv


def _read_opv(dob, rows):
    zero, counted, not_counted = [], [], []
    last = None
    for row in rows:
        age = (row.given_date - dob).days if dob else None
        if age is not None and age <= ZERO_DOSE_DAYS and not counted:
            zero.append(row)
            continue
        if age is not None and age < OPV_MIN_AGE_DAYS:
            not_counted.append((row, "too_young"))
            continue
        if last is not None and (row.given_date - last).days \
                < OPV_MIN_GAP_DAYS:
            not_counted.append((row, "too_soon"))
            continue
        counted.append(row)
        last = row.given_date
    return zero, counted, not_counted


def _read_ipv(dob, rows):
    counted, not_counted = [], []
    last = None
    for row in rows:
        age = (row.given_date - dob).days if dob else None
        if age is not None and age < IPV_MIN_AGE_DAYS:
            not_counted.append((row, "too_young"))
            continue
        if last is not None and (row.given_date - last).days \
                < IPV_MIN_GAP_DAYS:
            not_counted.append((row, "too_soon"))
            continue
        counted.append(row)
        last = row.given_date
    return counted, not_counted


def _clinic_ipv_doses():
    """How many IPV doses the clinic's own schedule asks for (the default
    brand of the IPV vaccine), or ``None`` when it has none."""
    from app.models import Vaccine

    vaccine = Vaccine.query.filter(Vaccine.code.in_(IPV_CODES)).first()
    if vaccine is None or not vaccine.brands:
        return None
    brand = next((b for b in vaccine.brands if b.is_default),
                 vaccine.brands[0])
    return len(brand.doses) or None


def status(patient, today=None):
    """The series for one child, read by the paper's rule."""
    from app.utils.clock import local_today

    today = today or local_today()
    dob = patient.date_of_birth
    opv_rows, ipv_rows = _doses(patient)
    zero, opv, opv_skip = _read_opv(dob, opv_rows)
    ipv, ipv_skip = _read_ipv(dob, ipv_rows)
    missing = {"opv": max(OPV_PRIMARY - len(opv), 0),
               "ipv": max(IPV_DOSES - len(ipv), 0)}
    nxt = []
    if dob is not None and missing["opv"]:
        earliest = dob + timedelta(days=OPV_MIN_AGE_DAYS)
        if opv:
            earliest = max(earliest, opv[-1].given_date
                           + timedelta(days=OPV_MIN_GAP_DAYS))
        nxt.append({"kind": "opv", "earliest": max(earliest, today),
                    "number": len(opv) + 1})
    if dob is not None and missing["ipv"]:
        if not ipv:
            late = today >= _add_months(dob, LATE_START_MONTHS)
            earliest = dob + timedelta(days=IPV1_PREFERRED_AGE_DAYS)
            why = "late_start" if late else "preferred_first"
        else:
            earliest = _add_months(ipv[-1].given_date,
                                   IPV2_PREFERRED_GAP_MONTHS)
            why = "preferred_second"
        nxt.append({"kind": "ipv", "earliest": max(earliest, today),
                    "number": len(ipv) + 1, "why": why})
    clinic_ipv = _clinic_ipv_doses()
    return {
        "source": SOURCE,
        "zero": zero, "opv": opv, "ipv": ipv,
        "not_counted": [(r, why, "opv") for r, why in opv_skip]
        + [(r, why, "ipv") for r, why in ipv_skip],
        "missing": missing,
        "complete": not missing["opv"] and not missing["ipv"],
        "next": nxt,
        "need": {"opv": OPV_PRIMARY, "ipv": IPV_DOSES},
        # Where the clinic's schedule asks for fewer IPV doses than the
        # paper — said, not changed: the national schedule is Egypt's.
        "clinic_ipv": clinic_ipv,
        "fewer_ipv": clinic_ipv is not None and clinic_ipv < IPV_DOSES,
    }
