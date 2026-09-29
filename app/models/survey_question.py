"""The survey's questions, in order, and where each answer leads.

Asked as: *«تقدر المؤسسة تضيف أسئلة وتخلّي أسئلة مرتبطة بأسئلة … لو نعم
يروح لأسئلة أكتر، لو لا كده»* — and, on the prototype, *«ممكن أبني سؤال:
لو لا روح على السؤال الفلاني»*.

**The five built-in questions keep their home.** Their wording and whether
they are shown still live where the survey builder has always kept them
(``Setting`` ``survey_q_*`` / ``survey_show_*``), and their answers in
``Feedback``'s own columns, which the reports read. A built-in row here only
carries its **place in the order** and **its jumps**. The clinic's own
questions carry everything, and their answers go to ``Feedback.answers``.

**A jump is a rule on an answer**, never on a question: *"if this one is
'no', go to question 5"*. Each kind of question has a fixed set of answer
groups a rule can name (:data:`BUCKETS`) — a star rating is low, middle or
high, not five separate rules nobody would write. A jump goes forward only,
or to the end, so a survey cannot loop.

**A branch question** (``branch_only``) is skipped in the normal order and
reached only when an answer sends someone to it. Without that, the happy
family is asked "what went wrong with the bill?" on the way past.
"""
import json
from datetime import datetime

from app.extensions import db

#: The kinds of question. The built-ins are "stars", "nps" and "text".
KINDS = ("stars", "yesno", "single", "multi", "text", "nps")
#: The answer groups a jump can be written for, per kind. "single" is one
#: group per option, named by its position (``o0``, ``o1`` …).
BUCKETS = {
    "stars": ("low", "mid", "high"),
    "nps": ("low", "mid", "high"),
    "yesno": ("yes", "no"),
}
#: The built-in questions and the ``Feedback`` column each one fills.
BUILT_IN = {"doctor": ("stars", "doctor_rating"),
            "service": ("stars", "service_rating"),
            "finance": ("stars", "finance_rating"),
            "nps": ("nps", "nps"),
            "comment": ("text", "comment")}
END = "end"


class SurveyQuestion(db.Model):
    __tablename__ = "survey_questions"

    id = db.Column(db.Integer, primary_key=True)
    # "doctor", "service" … for a built-in; "q<n>" for the clinic's own.
    key = db.Column(db.String(24), unique=True, nullable=False, index=True)
    builtin = db.Column(db.Boolean, nullable=False, default=False)
    kind = db.Column(db.String(12), nullable=False, default="yesno")
    text_ar = db.Column(db.String(255))
    text_en = db.Column(db.String(255))
    # One option per line, the two languages line for line.
    options_ar = db.Column(db.Text)
    options_en = db.Column(db.Text)
    branch_only = db.Column(db.Boolean, nullable=False, default=False)
    # Which parts of the clinic it is asked about: cost-centre keys, comma
    # separated. Empty is everywhere.
    centre_keys = db.Column(db.String(255))
    # {"no": "q7", "low": "end"} — answer group → question key or "end".
    jumps = db.Column(db.Text)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # ---------------------------------------------------------------- read
    def text(self, lang="ar"):
        if lang == "en" and self.text_en:
            return self.text_en
        return self.text_ar or self.text_en or ""

    def options(self, lang="ar"):
        own = self.options_en if lang == "en" and self.options_en else self.options_ar
        return [line.strip() for line in (own or "").splitlines() if line.strip()]

    def buckets(self):
        if self.kind == "single":
            return tuple(f"o{i}" for i in range(len(self.options("ar"))))
        return BUCKETS.get(self.kind, ())

    def jump_map(self):
        try:
            data = json.loads(self.jumps or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def centres(self):
        return [k.strip() for k in (self.centre_keys or "").split(",") if k.strip()]

    def __repr__(self):
        return f"<SurveyQuestion {self.key}>"
