"""User model and authentication helpers."""
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager
from app.models.permissions import ROLES, role_can_access, role_modules


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Bilingual display names.
    full_name = db.Column(db.String(120), nullable=False)
    full_name_en = db.Column(db.String(120))

    role = db.Column(db.String(20), nullable=False, default="reception")
    email = db.Column(db.String(120))
    phone = db.Column(db.String(30))

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # --- Password handling -------------------------------------------------
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # --- Permissions -------------------------------------------------------
    @property
    def is_admin(self):
        return self.role == "admin"

    def can_access(self, module):
        """Whether this user's role may reach ``module``."""
        return role_can_access(self.role, module)

    @property
    def modules(self):
        """Modules visible to this user (drives the sidebar)."""
        return role_modules(self.role)

    def display_name(self, lang="ar"):
        """Return the localized display name with a sensible fallback."""
        if lang == "en" and self.full_name_en:
            return self.full_name_en
        return self.full_name

    @staticmethod
    def valid_role(role):
        return role in ROLES

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
