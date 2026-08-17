"""Editable roles & their module permissions.

Roles started as a hard-coded matrix (see ``permissions.py``); this table makes
them editable from the UI and lets admins add custom roles. The fixed set of
*modules* still lives in code (the features that exist), but which modules each
role may reach — and which roles exist — is now data.

``permissions.py`` remains the seed source and the static fallback used before
the table is populated (e.g. very first boot).
"""
from datetime import datetime

from app.extensions import db
from app.models.permissions import ADMIN_ONLY_MODULES, GRANTABLE_MODULES, MODULES


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), unique=True, nullable=False, index=True)  # slug
    label_ar = db.Column(db.String(80))
    label_en = db.Column(db.String(80))
    modules = db.Column(db.Text, default="")          # CSV of module keys
    # Fine-grained capabilities this role holds, as a CSV like `modules`.
    #
    # Roles could be created from the UI and could not hold a single
    # capability: `User.can` asked `role_has_capability(self.role, ...)`, which
    # reads a table in code keyed by the five built-in role names. So a clinic
    # that made its own "front desk" role got a receptionist who could not
    # reach the till, with nothing on any screen to say why and no way to fix
    # it except granting the capability to each person one at a time.
    #
    # It surfaced properly when a nursing station needed a role of its own.
    capabilities = db.Column(db.Text, default="")
    is_system = db.Column(db.Boolean, default=False, nullable=False)  # built-in
    is_admin = db.Column(db.Boolean, default=False, nullable=False)   # full access
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def module_list(self):
        """The modules this role reaches. Admins reach everything.

        ``ADMIN_ONLY_MODULES`` are filtered out for everybody else even if the
        stored CSV still names them — a role saved before this rule existed
        would otherwise keep showing a sidebar link that has never once
        opened. Nothing is lost by dropping them here: the routes behind both
        ask ``is_admin`` regardless, so the entry was only ever a link to a
        refusal.
        """
        if self.is_admin:
            return list(MODULES)
        wanted = {m.strip() for m in (self.modules or "").split(",") if m.strip()}
        # Preserve canonical module order.
        return [m for m in GRANTABLE_MODULES if m in wanted]

    @property
    def capability_list(self):
        """The capabilities stored on this role, in canonical order."""
        from app.models.permissions import CAPABILITIES

        if self.is_admin:
            return list(CAPABILITIES)
        wanted = {c.strip() for c in (self.capabilities or "").split(",") if c.strip()}
        return [c for c in CAPABILITIES if c in wanted]

    def set_capabilities(self, capability_keys):
        from app.models.permissions import CAPABILITIES

        asked = set(capability_keys)
        self.capabilities = ",".join(c for c in CAPABILITIES if c in asked)

    def set_modules(self, module_keys):
        """Save the ticked modules, ignoring the ones a role cannot hold.

        Filtered here rather than only in the form, so a hand-posted request
        cannot store a permission that does not work either.
        """
        asked = set(module_keys)
        keep = [m for m in GRANTABLE_MODULES if m in asked]
        if "dashboard" not in keep:        # everyone needs a landing page
            keep = ["dashboard"] + keep
        self.modules = ",".join(keep)
        _ = ADMIN_ONLY_MODULES            # named above; kept for the reader

    def label(self, lang="ar"):
        if lang == "en" and self.label_en:
            return self.label_en
        return self.label_ar or self.name

    def __repr__(self):
        return f"<Role {self.name}>"
