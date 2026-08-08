"""The clinic's own short lists — item types, categories, units, store kinds.

This is the fourth time the same problem has come up. Service types were a
fixed list in the code, then client categories, then payer kinds; each was
opened up on its own, with its own model, its own screen and its own copy of
the same three rules. A fifth, sixth and seventh copy is not a pattern, it is
a habit — so the lists that were still hardcoded move here together.

What was actually wrong with them differed in an instructive way:

* ``WAREHOUSE_KINDS`` was a Python list. A clinic with a pharmacy store or a
  second fridge could not name it.
* Item categories and units were worse, and looked better: the picker offered
  the built-in defaults **plus every value anybody had ever typed**. So you
  could add by typing — and never remove. One "قطعه" typed instead of "قطعة"
  sat beside the correct one for the life of the installation, and every
  person after chose between them at random.

**Two layers, because the clinic asked for two.** A *type* says what a thing
fundamentally is — drug, vaccine, consumable — and a *category* groups within
it: antibiotic, antiseptic, examination tool. Categories carry ``parent_key``
so a screen can offer only the ones that belong to the chosen type, which is
what stops the second list growing into an unreadable pile.

**The rules, carried over unchanged from the three that came before:**

*Keys never change.* Rows elsewhere store them. Renaming renames the *label*.

*A built-in cannot be deleted, and neither can one in use* — deleting it would
leave items pointing at something that no longer exists, which is a report
that quietly drops rows rather than an error somebody sees. Switching it off
is always available: it leaves history readable and takes it off tomorrow's
list.
"""
from datetime import datetime

from app.extensions import db


class Lookup(db.Model):
    """One entry in one of the clinic's short lists."""

    __tablename__ = "lookups"
    __table_args__ = (
        db.UniqueConstraint("domain", "key", name="uq_lookup_domain_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    # Which list this belongs to — see app/utils/lookups.py::DOMAINS.
    domain = db.Column(db.String(24), nullable=False, index=True)
    key = db.Column(db.String(40), nullable=False)
    name_ar = db.Column(db.String(80))
    name_en = db.Column(db.String(80))
    # For a category: the item type it belongs under. Empty means "any", which
    # is what an imported or hand-typed category starts as.
    parent_key = db.Column(db.String(40), index=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Shipped with the program. Editable in wording, never deletable — a
    # clinic that removes "قطعة" leaves half its own catalogue unreadable.
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def display_name(self, lang="ar"):
        name = (self.name_en if lang == "en" else self.name_ar) or ""
        return name.strip() or self.key

    def __repr__(self):
        return f"<Lookup {self.domain}:{self.key}>"
