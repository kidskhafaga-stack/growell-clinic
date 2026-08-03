"""The clinic's own list of payer kinds — club, syndicate, insurer, and its own.

The third fixed list to be opened up, after the service types and the client
categories, and the reason is the same each time: six names chosen by somebody
who has never seen this clinic's books. "جمعية", "بنك", "مدرسة" and "سفارة"
are all real payers here, and forcing them into "other" makes every report that
groups by type say nothing worth reading.

Two rules carried over unchanged, because both were learned the hard way on the
client categories:

**Keys never change.** Every payer row stores one, and ``cash`` in particular is
read by name — it is how the clinic's own price list is recognised. Renaming is
renaming the *label*.

**A built-in cannot be deleted, and a kind in use cannot either.** Deleting one
would leave payers pointing at a type that no longer exists, which is a report
that quietly drops rows rather than an error anybody sees.
"""
from app.extensions import db
from app.models import PayerType

# The six that were fixed in the code, with the wording the screens already
# used. Seeded as system rows so a clinic starts where it started before.
BUILT_IN = [
    ("cash", "تعاقد نقدي", "Cash price list"),
    ("club", "نادي", "Club"),
    ("syndicate", "نقابة", "Syndicate"),
    ("insurance", "تأمين", "Insurance"),
    ("company", "شركة", "Company"),
    ("other", "أخرى", "Other"),
]


def ensure_seeded():
    """Create the built-in kinds once. Idempotent, and never overwrites edits."""
    made = 0
    for order, (key, name_ar, name_en) in enumerate(BUILT_IN):
        if PayerType.query.filter_by(key=key).first() is not None:
            continue
        db.session.add(PayerType(key=key, name_ar=name_ar, name_en=name_en,
                                 sort_order=order, is_active=True,
                                 is_system=True))
        made += 1
    if made:
        db.session.commit()
    return made


def all_types():
    return PayerType.query.order_by(PayerType.sort_order, PayerType.id).all()


def active_types():
    return (PayerType.query.filter_by(is_active=True)
            .order_by(PayerType.sort_order, PayerType.id).all())


def valid_key(key):
    """Whether a key exists — **including an inactive one**.

    A payer already filed under a kind the clinic has since hidden must keep
    it: rejecting it here would silently reset that payer to "club" the next
    time anybody saved an unrelated field on the same form.
    """
    key = (key or "").strip()
    return bool(key) and PayerType.query.filter_by(key=key).first() is not None


def label(key, lang="ar"):
    """The kind's name for display, falling back to the key itself.

    Screens used to print ``t('payer_types.' ~ key)``, which shows the raw key
    for anything a clinic added — the same bug the client categories had.
    """
    row = PayerType.query.filter_by(key=(key or "").strip()).first()
    return row.display_name(lang) if row is not None else (key or "—")


def usage_counts():
    """``{key: how many payers are filed under it}`` — for the delete guard."""
    from app.models import PayerEntity

    counts = {}
    for (key,) in db.session.query(PayerEntity.entity_type).all():
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def make_key(name, name_en=None):
    """An ASCII key from the name, unique. Same rule as the categories."""
    import re

    base = re.sub(r"[^a-z0-9]+", "_", (name_en or "").strip().lower()).strip("_")
    if not base:
        base = "type"
    key, n = base[:30], 2
    while PayerType.query.filter_by(key=key).first() is not None:
        key = f"{base[:26]}_{n}"
        n += 1
    return key
