"""One money form, sent once (MONEY_SAFETY_PLAN.md ف-٣).

Each money form carries a key made when the page was drawn. The first time
it arrives the key is written **in the same save** as the bill or the
payment; the same form arriving again finds its key and is turned back to
where the first one went (`utils/once`).
"""
from datetime import datetime

from app.extensions import db


class FormKey(db.Model):
    __tablename__ = "form_keys"

    # An ``id`` like every table here: the demo clean-up and the patient
    # merge walk tables by it. The key is what is unique.
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # Where the first sending ended — the receipt, the bill — so the second
    # is shown what was done instead of an error.
    went_to = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                           index=True)

    def __repr__(self):
        return f"<FormKey {self.key}>"
