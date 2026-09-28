"""Why a family took their child home against advice — in their words.

The program knew *that* they left (``self_discharge`` on a stay, and on an
emergency attendance also ``left_unseen``) and, since ``PCC.10``, *what they
were told* before they went (``utils/refusal``). It did not know **why**: the
price, the care, the service, another hospital. Without that, a unit where
four families in a month left over the bill looks exactly like one where they
left to be nearer home.

A short list the clinic can edit (``lookups``, domain ``leave_reason``), one
tap at the moment the family is at the door, and never a reason to hold the
discharge: "didn't say" is a real answer and is recorded as one.
"""
from app.extensions import db
from app.utils import lookups

DOMAIN = "leave_reason"

#: (key, Arabic, English). The clinic renames, reorders and adds from the
#: lists screen; the keys are what the report groups by.
BUILT_IN = [
    ("price", "السعر / التكلفة", "Price / cost"),
    ("medical", "الخدمة الطبية", "Medical care"),
    ("service", "الخدمة", "Service"),
    ("elsewhere", "رايحين مكان تاني", "Going elsewhere"),
    ("family", "ظروف عائلية", "Family circumstances"),
    ("unsaid", "ما قالوش", "Did not say"),
]

#: The ways of leaving that ask the question. Going home as planned, being
#: admitted, moved or dying do not.
ASKED_ON = ("self_discharge", "left_unseen")


def ensure_seeded():
    """Add the built-in reasons once. Returns how many were made."""
    have = {row[0] for row in db.session.query(lookups.Lookup.key)
            .filter(lookups.Lookup.domain == DOMAIN).all()}
    made = 0
    for order, (key, name_ar, name_en) in enumerate(BUILT_IN):
        if key in have:
            continue
        db.session.add(lookups.Lookup(domain=DOMAIN, key=key, name_ar=name_ar,
                                      name_en=name_en, sort_order=order,
                                      is_system=True))
        made += 1
    if made:
        db.session.flush()
    return made


def options():
    ensure_seeded()
    return lookups.options(DOMAIN)


def clean(key):
    """``key`` when it is one of the clinic's reasons that is switched on,
    else ``None`` — never a reason made up from a typo."""
    key = (key or "").strip()
    if not key:
        return None
    return key if any(row.key == key for row in options()) else None


def record(episode, how_left, key, note=None):
    """Write the reason on a stay or an attendance, when how it ended asks
    for one. Returns the key written, or ``None``. The caller commits."""
    if how_left not in ASKED_ON:
        return None
    episode.leave_reason = clean(key)
    episode.leave_note = (note or "").strip()[:255] or None
    return episode.leave_reason


def label(key, lang="ar"):
    return lookups.label(DOMAIN, key, lang) if key else ""
