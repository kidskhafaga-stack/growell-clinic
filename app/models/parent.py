"""Parent / guardian records belonging to a family.

``client_category`` drives discount eligibility in the finance phase, so it is
captured here from day one.
"""
from datetime import datetime

from app.extensions import db

# Relation of the guardian to the child.
PARENT_RELATIONS = ["father", "mother", "guardian"]

# The built-in client categories. Still the fallback for a database that has
# not been seeded yet — see :class:`ClientCategory`, which is what a clinic
# actually edits.
CLIENT_CATEGORIES = ["normal", "friend", "relative", "employee"]


class ClientCategory(db.Model):
    """Clinic-editable catalogue of client categories (نقدي / عاملين / …).

    Replaces the four names fixed in :data:`CLIENT_CATEGORIES`, which were
    ``normal``, ``friend``, ``relative`` and ``employee`` and nothing else. A
    real clinic's list turned out to be نقدي, عاملين, **أطباء** and **أعضاء
    نادي سبورتنج** — two of which had nowhere to go.

    That is not a cosmetic shortfall. The category is what a discount aims at:
    :class:`~app.models.discount.NamedDiscount` carries ``dtype="category"``
    and a ``client_category``, so the *mechanism* for "doctors pay 50% less"
    already worked. Forcing "أطباء" into ``friend`` would have attached a real
    discount to a category with the wrong name, and the first report grouping
    clients by category would say something meaningless.

    Same shape and same reasoning as
    :class:`~app.models.service.ServiceType`: **keys are not labels.** A clinic
    renaming "عادي" to "نقدي" must not change the key, because every parent row
    and every discount already stores it. Built-ins are seeded ``is_system``
    with fixed keys; their label, order and visibility are editable, and a
    clinic may add as many of its own as it likes.
    """
    __tablename__ = "client_categories"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(60))
    name_en = db.Column(db.String(60))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_system = db.Column(db.Boolean, default=False, nullable=False)

    def display_name(self, lang="ar"):
        name = self.name_en if lang == "en" else self.name_ar
        if name:
            return name
        # A built-in with no label of its own still has one in the dictionary.
        from app.i18n import t
        return t("categories." + self.key)

    def __repr__(self):
        return f"<ClientCategory {self.key}>"


class Parent(db.Model):
    __tablename__ = "parents"

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(
        db.Integer, db.ForeignKey("families.id"), nullable=False, index=True
    )

    relation = db.Column(db.String(20), nullable=False, default="father")
    full_name = db.Column(db.String(120), nullable=False)
    full_name_en = db.Column(db.String(120))
    national_id = db.Column(db.String(20))
    phone = db.Column(db.String(30))
    phone_alt = db.Column(db.String(30))
    email = db.Column(db.String(120))
    occupation = db.Column(db.String(120))
    nationality = db.Column(db.String(60))
    address = db.Column(db.String(255))

    client_category = db.Column(db.String(20), default="normal", nullable=False)
    is_primary_contact = db.Column(db.Boolean, default=False, nullable=False)
    # Name was auto-derived from the child's name on import (reception should
    # verify it) rather than entered explicitly.
    auto_named = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    family = db.relationship("Family", back_populates="parents")

    def display_name(self, lang="ar"):
        if lang == "en" and self.full_name_en:
            return self.full_name_en
        return self.full_name

    @staticmethod
    def valid_relation(value):
        return value in PARENT_RELATIONS

    @staticmethod
    def valid_category(value):
        """Whether a category may be stored on a parent.

        Asks the clinic's catalogue, not the four built-in names — otherwise a
        clinic that added "أعضاء نادي سبورتنج" would have every save of that
        family silently reset them to ``normal``, taking their discount with
        it. Falls back to the built-ins before the catalogue is seeded.
        """
        from app.utils.client_categories import valid_key

        return valid_key(value)

    def __repr__(self):
        return f"<Parent {self.full_name} ({self.relation})>"
