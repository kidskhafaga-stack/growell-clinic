"""Seed a starter catalogue of common paediatric lab tests and imaging studies
from a data file (`data/starter_investigations.json`).

Idempotent: only inserts entries whose code (or, for the older codeless rows,
whose Arabic name) is not already present. Doctors pick from these — with a
free-text fallback — when ordering investigations.

**Why the list grew, and why a code arrived with it.**

Every specialty in the specialties survey answers *"تحاليل تريد رؤيتها كمنحنى"*
with its own list, and between them they name sixty-three things. Eight of them
were in this catalogue. The rest — HbA1c, ferritin, albumin, creatinine and
eGFR, IgE, drug levels, NT-proBNP, INR, calprotectin, coeliac antibodies,
microalbumin, T2\u002a, platelets — a doctor had to type by hand.

That is not only inconvenient, it breaks the curve. `lab_series` groups results
by catalogue id where there is one and **by name where there is not**, so
"HbA1c" typed on Sunday and "hba1c" typed on Thursday are two curves for one
test. Seeding them is what makes the chart question answerable at all.

The code exists because a panel has to name a test from a data file, and a name
is not a name for long — a clinic renames an entry and every reference by text
stops matching. The survey review made the same point about the answer sheet.

**Three of the survey's chart answers are not tests, and are not here.** A chest
X-ray, a panoramic film, before-and-after photographs, retinopathy screening
dates: those are attachments and appointments. They are listed under "charts" in
the questionnaire because that is where a doctor thinks of them, but nothing
draws a curve through a photograph, and a catalogue entry promising one would be
a promise the program cannot keep. What *is* chartable and already works is the
third group — plaque index, decayed-tooth count, intraocular pressure, squint
angle, visual acuity — because those are specialty-panel measurements, and
`series.curves_for` has drawn panel readings since the panels existed.
"""
import json
import os

from app.extensions import db
from app.models import Investigation

#: Where the starter list lives. **Data, not code** — «متخليهاش فى الكود
#: بالنسبة للعيادة»: the same shape the drug register has had since it
#: existed (`data/egypt_drugs.json.gz`). Loaded once into the clinic's own
#: catalogue, and from then on the list is the clinic's — to add to from the
#: visit screen, and to rename or hide from its own list
#: (`prescriptions.investigations`).
STARTER_FILE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "data", "starter_investigations.json"))


def _load_starter():
    """``[(code, name_ar, name_en, kind, category, unit)]`` from the file.

    ``code`` is empty for the entries that predate it having a meaning:
    nothing in the program refers to a urine culture by key. Where there is
    one, it is what a specialty panel finds the test by.
    """
    with open(STARTER_FILE, encoding="utf-8") as fh:
        rows = json.load(fh)["investigations"]
    return [(r.get("code") or None, r["name_ar"], r.get("name_en") or None,
             r.get("kind") or "lab", r.get("category") or None,
             r.get("unit") or None) for r in rows]


COMMON_INVESTIGATIONS = _load_starter()

#: The seeded categories that belong to each room, for the one-time move of a
#: clinic's existing rows. **Only the program's own words are moved**: a
#: category somebody typed themselves is theirs, and guessing at it would
#: refile their catalogue on an assumption they never made.
SEEDED_DIAGNOSTIC_CATEGORIES = ("سونار", "قلب", "مخ وأعصاب")


def move_diagnostics_out_of_radiology():
    """One-time: refile the studies that are not radiology. Returns the count.

    ``diagnostic`` arrived after these rows existed, so every sonar, echo and
    ECG a clinic already had is sitting under ``imaging`` and would land on
    the radiology list — which is the same category error that put an echo on
    the lab bench, one room along.

    **It moves only the program's own words.** A row is refiled when its
    category is one this seed wrote (:data:`SEEDED_DIAGNOSTIC_CATEGORIES`) and
    its kind is still the old one. A clinic that typed its own category keeps
    it, because guessing at somebody else's vocabulary is how a catalogue gets
    refiled on an assumption nobody made — and a wrong guess here hides a
    child's outstanding order on a screen its department never opens.

    **The orders move with the catalogue, and only with it.** A
    ``VisitInvestigation`` carries its own ``kind`` as a snapshot, so an
    existing echo order would keep pointing at radiology even after the
    catalogue row moved. They are moved by following ``investigation_id`` —
    never by matching on the name, which would catch a free-typed order whose
    words merely look similar.

    Idempotent: a second run finds nothing left with the old kind.
    """
    from app.extensions import db
    from app.models.visit import VisitInvestigation

    rows = (Investigation.query
            .filter(Investigation.kind == "imaging",
                    Investigation.category.in_(SEEDED_DIAGNOSTIC_CATEGORIES))
            .all())
    if not rows:
        return 0
    ids = [r.id for r in rows]
    for row in rows:
        row.kind = "diagnostic"
    (VisitInvestigation.query
     .filter(VisitInvestigation.investigation_id.in_(ids),
             VisitInvestigation.kind == "imaging")
     .update({"kind": "diagnostic"}, synchronize_session=False))
    db.session.commit()
    return len(rows)


#: The starter entries this clinic has been given, by key. Kept so an entry
#: is given **once**: one the clinic deleted is not brought back by the next
#: update, because the list is theirs now.
SEEN_KEY = "starter_investigations_seen"


def _key(code, name_ar):
    return f"code:{code}" if code else f"name:{name_ar}"


def _seen():
    from app.models import Setting

    try:
        return set(json.loads(Setting.get(SEEN_KEY) or "[]"))
    except (TypeError, ValueError):
        return set()


def seed_investigations():
    """Load the starter list into the clinic's catalogue. Idempotent.

    Matched on the code where there is one and on the Arabic name where there
    is not. Both, because this runs on clinics that already have the older
    codeless rows: matching on code alone would insert a second ferritin
    beside the one they have been ordering for months, and every result taken
    under the old row would fall out of the new row's curve.

    A row that exists but has no code **is given one** rather than duplicated,
    which is what lets an upgraded clinic's history join the panels.

    **Each entry is given once.** Once the clinic has it — made here, or found
    already there — it is the clinic's: renamed, re-united, hidden or deleted,
    the next update leaves it as the clinic left it.
    """
    from app.models import Setting

    seen = _seen()
    created = adopted = 0
    for code, name_ar, name_en, kind, category, unit in COMMON_INVESTIGATIONS:
        key = _key(code, name_ar)
        row = None
        if code:
            row = Investigation.query.filter_by(code=code).first()
        if row is None:
            row = Investigation.query.filter_by(name_ar=name_ar).first()

        if row is not None:
            # Only ever fill a blank. A clinic that renamed a test, or set its
            # own unit, keeps what it chose — the seed is a starting point, not
            # an owner.
            if code and not row.code:
                row.code = code
                adopted += 1
            if unit and not row.unit:
                row.unit = unit
            seen.add(key)
            continue
        if key in seen:
            # Given before and gone since: the clinic deleted it.
            continue

        db.session.add(Investigation(
            code=code, name_ar=name_ar, name_en=name_en, kind=kind,
            category=category, unit=unit, is_active=True,
        ))
        seen.add(key)
        created += 1
    Setting.set(SEEN_KEY, json.dumps(sorted(seen), ensure_ascii=False))
    db.session.commit()
    return created
