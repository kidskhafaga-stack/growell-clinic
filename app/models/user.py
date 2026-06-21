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

    # Profile.
    photo = db.Column(db.String(255))          # profile picture filename
    job_title = db.Column(db.String(120))      # المسمى الوظيفي
    branch = db.Column(db.String(120))         # الفرع

    # Doctor profile / branding.
    rx_display_name = db.Column(db.String(160))     # الاسم الظاهر في الروشتة
    professional_title = db.Column(db.String(40))   # Professor/Consultant/...
    specialty = db.Column(db.String(160))           # التخصص الرئيسي
    sub_specialties = db.Column(db.String(255))     # التخصصات الفرعية
    license_no = db.Column(db.String(60))           # رقم الترخيص/النقابة
    signature_file = db.Column(db.String(255))      # التوقيع الرقمي
    stamp_file = db.Column(db.String(255))          # الختم الطبي
    personal_logo = db.Column(db.String(255))       # شعار شخصي (اختياري)
    accent_color = db.Column(db.String(20))         # لون مميز
    rx_template_id = db.Column(db.Integer, db.ForeignKey("rx_print_templates.id"), nullable=True)

    # UI personalization (per user).
    theme = db.Column(db.String(10))                # light | dark
    font_scale = db.Column(db.String(4))            # sm | md | lg
    default_landing = db.Column(db.String(30))      # module key after login

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
    def _role_record(self):
        """Look up the editable Role row, or None (pre-seed / DB not ready)."""
        try:
            from app.models.role import Role
            return Role.query.filter_by(name=self.role).first()
        except Exception:  # noqa: BLE001 - DB not ready / outside app context
            return None

    @property
    def is_admin(self):
        rec = self._role_record()
        if rec is not None:
            return rec.is_admin
        return self.role == "admin"

    def can_access(self, module):
        """Whether this user's role may reach ``module``."""
        rec = self._role_record()
        if rec is not None:
            return rec.is_admin or module in rec.module_list
        return role_can_access(self.role, module)  # static fallback

    @property
    def modules(self):
        """Modules visible to this user (drives the sidebar)."""
        rec = self._role_record()
        if rec is not None:
            return rec.module_list
        return role_modules(self.role)

    def display_name(self, lang="ar"):
        """Return the localized display name with a sensible fallback."""
        if lang == "en" and self.full_name_en:
            return self.full_name_en
        return self.full_name

    def doctor_print_name(self, lang="ar"):
        """Name shown on the doctor's prescriptions/printouts."""
        if self.rx_display_name:
            return self.rx_display_name
        base = self.display_name(lang)
        return f"{self.professional_title} {base}" if self.professional_title else base

    def role_label(self, lang="ar"):
        rec = self._role_record()
        if rec is not None:
            return rec.label(lang)
        return self.role

    @staticmethod
    def valid_role(role):
        try:
            from app.models.role import Role
            if Role.query.filter_by(name=role).first():
                return True
        except Exception:  # noqa: BLE001
            pass
        return role in ROLES

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
