"""Key/value system settings.

A simple, future-proof store for clinic-wide configuration (clinic name,
default growth reference, currency, etc.) that admins can edit without code
changes. Values are stored as strings; callers cast as needed.
"""
from datetime import datetime

from app.extensions import db

# Prefixes read as a group by `Setting.group`. Writing any key under one
# has to drop that group's cached read as well as its own.
GROUPED_PREFIXES = ("mod_enabled:",)


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @classmethod
    def get(cls, key, default=None):
        """A setting's value, read from the database once per request.

        This is called from everywhere — templates, decorators, pricing — so
        on a busy screen the same handful of rows were being fetched hundreds
        of times to render one page.
        """
        from app.utils.request_cache import remember

        value = remember(f"setting:{key}", lambda: cls._read(key))
        return default if value is None else value

    @classmethod
    def group(cls, prefix):
        """Every setting under ``prefix:``, as one query, cached per request.

        `module_enabled` is asked once per module while a page is drawn, and
        the sidebar draws every module — so fifteen keys meant fifteen round
        trips on every screen in the program. They are one table read.
        """
        from app.utils.request_cache import remember

        def load():
            rows = cls.query.filter(cls.key.like(f"{prefix}:%")).all()
            return {r.key: r.value for r in rows}

        return remember(f"settings:group:{prefix}", load)

    @classmethod
    def _read(cls, key):
        row = cls.query.filter_by(key=key).first()
        return row.value if row else None

    @classmethod
    def set(cls, key, value):
        from app.utils.request_cache import forget

        row = cls.query.filter_by(key=key).first()
        if row is None:
            row = cls(key=key, value=str(value))
            db.session.add(row)
        else:
            row.value = str(value)
        # A settings screen has to show what it just saved.
        forget(f"setting:{key}")
        # And any grouped read that would still be holding the old value —
        # `module_enabled` reads every `mod_enabled:` row in one query and
        # caches the lot, so forgetting the single key alone would leave the
        # module switch you just flipped reading its previous answer for the
        # rest of the request.
        if key.startswith(GROUPED_PREFIXES):
            forget("settings:group:" + key.split(":", 1)[0])
        return row

    def __repr__(self):
        return f"<Setting {self.key}={self.value!r}>"
