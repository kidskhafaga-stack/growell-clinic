"""Which of a child's basic details nobody has filled in yet.

Asked for in one sentence, and the sentence carries the whole design:

> «انا النهارده جيت وسجلت بيانات المريض بالطريقة السريعة وكشف ومشى، جه مره
> تانيه لازم انبه الاستقبال ان يستكمل البيانات بتاعت المريض قبل تلقي خدمة
> تانيه»

The quick registration at the desk takes a name, a sex and a date of birth —
that is all it needs to get a child seen. It is the right thing to have, and
it is also how a file with no phone number on it ends up in the system. The
gap is not the quick path; it is that nothing ever said the file was still
half-written.

---

**Derived, never stored.** There is no `is_complete` column and there must not
be one. The moment reception types the phone number, the flag has to be gone —
from the booking screen, from the pickers, from the profile, everywhere, at
once. A stored flag is a second copy of a fact, and the second copy is the one
that goes stale: it would have to be recomputed on every write to a patient, a
family and a guardian, and the first one anybody forgot would leave a clinic
being nagged about a file they had already fixed. Which is exactly how people
learn to ignore a warning.

**The clinic says what «basic» means, not the program.** A paediatric clinic in
a village and a hospital admitting from theatre do not need the same things on
file, and this program does not get to decide that for them. So the fields are
a *vocabulary* and the requirement is a *setting* — the same shape as the
retention years, and for the same reason.

**Every field here is one the program already has.** Nothing was invented to
make a nicer list: each one names a column somebody can actually go and fill
in, on a screen that already exists. And ``full_name``, ``date_of_birth`` and
``gender`` are deliberately *not* here — they are ``nullable=False``, so they
can never be missing, and a check for them would be a line that can never fire.

**It tells. It never blocks.** A child arriving at three in the morning is not
made to wait for a phone number, and reception is not stopped from booking.
This is the same rule the clinical privileges follow — «بيحذّر، ما بيرفضش» —
and for the same reason: a program that refuses at the wrong moment gets
worked around, and then it is not protecting anything at all.
"""

#: What the clinic can ask to be on file, and where each one is read from.
#:
#: ``read`` takes a patient and answers whether that detail is *there*. It is
#: the whole definition: a key with no reader cannot be required, and a reader
#: that looks at nothing real cannot be satisfied.
FIELDS = {}


def _field(key, read):
    FIELDS[key] = read
    return key


def _has_phone(patient):
    """The child's own number, or any guardian's — ``contact_phone`` already
    knows the order, and it is the number somebody would actually ring."""
    return bool((patient.contact_phone or "").strip())


def _has_guardian(patient):
    """Somebody recorded as responsible for this child.

    A file with no guardian on it is a child nobody can be asked about, and on
    a consent form it is the signature line with no name behind it.
    """
    return bool(patient.family and patient.family.parents)


def _has_guardian_id(patient):
    """The primary guardian's national id — what a consent is signed against.

    Not the child's: a two-year-old does not have one, and the person giving
    permission is the person who has to be identifiable.
    """
    guardian = patient.primary_guardian
    return bool(guardian and (guardian.national_id or "").strip())


def _has_address(patient):
    guardian = patient.primary_guardian
    return bool(guardian and (guardian.address or "").strip())


def _has_national_id(patient):
    return bool((patient.national_id or "").strip())


def _has_blood_type(patient):
    return bool((patient.blood_type or "").strip())


PHONE = _field("phone", _has_phone)
GUARDIAN = _field("guardian", _has_guardian)
GUARDIAN_ID = _field("guardian_id", _has_guardian_id)
ADDRESS = _field("address", _has_address)
NATIONAL_ID = _field("national_id", _has_national_id)
BLOOD_TYPE = _field("blood_type", _has_blood_type)

#: The order they are shown in — most use to a clinic first, so a reception
#: desk reading a badge sees the thing worth chasing at the front.
ORDER = (PHONE, GUARDIAN, GUARDIAN_ID, ADDRESS, NATIONAL_ID, BLOOD_TYPE)

#: What a clinic that has never opened the setting is asked for.
#:
#: **Two, not six.** A default that flagged every file in the building would
#: be a badge on every row, which is the same as no badge at all. These two
#: are what the quick registration cannot capture and what a clinic genuinely
#: cannot work without: somebody to call, and somebody responsible.
DEFAULT_REQUIRED = (PHONE, GUARDIAN)

#: Where the clinic's own answer lives.
SETTING = "patient_basics"


def required():
    """The keys this clinic asks for, in :data:`ORDER`.

    An unset setting means the default. An **empty** setting is a real answer
    and means the clinic asked for none — so the two are stored differently,
    the same distinction this program draws everywhere between "nobody said"
    and "somebody said no".
    """
    from app.models import Setting

    try:
        raw = Setting.get(SETTING)
    except Exception:      # noqa: BLE001 — no settings table yet
        raw = None
    if raw is None:
        return tuple(DEFAULT_REQUIRED)
    chosen = {p.strip() for p in raw.split(",") if p.strip()}
    return tuple(k for k in ORDER if k in chosen and k in FIELDS)


def missing(patient, keys=None):
    """Which required details this child's file does not have, in order.

    ``None`` for a patient is an empty list rather than an error: a screen
    asking about nobody is not a screen with a problem to report.
    """
    if patient is None:
        return []
    wanted = tuple(keys) if keys is not None else required()
    return [k for k in ORDER
            if k in wanted and k in FIELDS and not FIELDS[k](patient)]


def is_complete(patient, keys=None):
    """Whether the file has everything this clinic asks for."""
    return not missing(patient, keys=keys)
