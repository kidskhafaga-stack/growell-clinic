"""What the assistant has actually cost the clinic.

The clinic asked to see "the remaining tokens and the usage". Half of that is
possible and half of it is not, and saying so plainly is better than a number
that looks authoritative and is invented.

**Remaining is not knowable.** No provider — Anthropic, OpenAI, Google — tells
a chat request how much quota is left on the key. That number lives in the
vendor's billing console, changes on their schedule, and depends on a plan the
program has never been told about. A screen that guessed at it would be wrong
in the direction that hurts: a clinic that trusts "you have plenty left" and
stops mid-consultation.

**Usage is knowable, exactly.** Every one of the three request shapes already
reports the tokens it consumed, in the response the program is reading anyway:
OpenAI puts it in ``usage``, Anthropic in ``usage``, Gemini in
``usageMetadata``. Nothing extra is sent to anybody to collect this — it is
being thrown away today.

So this table records what was spent, per call, with the feature that spent it.
A clinic that can see "the visit summaries are three quarters of the bill" can
decide something. A clinic looking at one monthly total from the vendor cannot.

Kept deliberately small: no prompts, no replies, no patient id. What was asked
is in the visit record where it belongs, and a second copy of clinical text in
a metering table is a second place to leak it from.
"""
from datetime import datetime

from app.extensions import db


class AiUsage(db.Model):
    """One row per provider call that came back with a token count."""

    __tablename__ = "ai_usage"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    # Which part of the program spent it — "chat", "visit_summary",
    # "rx_review"… This is the column the whole table exists for.
    feature = db.Column(db.String(40), index=True)
    provider = db.Column(db.String(30))
    model = db.Column(db.String(80))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    prompt_tokens = db.Column(db.Integer, default=0, nullable=False)
    completion_tokens = db.Column(db.Integer, default=0, nullable=False)

    user = db.relationship("User", lazy="joined")

    @property
    def total_tokens(self):
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)
