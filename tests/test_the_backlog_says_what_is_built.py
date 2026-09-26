"""The backlog, checked in the direction it went wrong.

``IMPROVEMENTS_BACKLOG.md`` listed as still to do: the prescription written
from the visit, the thermal receipt, the club discount, the analytics page,
the template merge, carry-forward, the daily cap, WHO to nineteen — every
one of them built months earlier. Somebody choosing the next job from that
file would have been sent to write a screen that exists; the same fault the
About screen's «لسه» list had, and ``test_the_list_that_kept_going_stale``
now guards.

So each line the file marks as built names the thing that is built, and this
opens each one against the running program. A line that says ✅ and points
at nothing fails here.
"""
import os

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

BUILT_ROUTES = (
    "prescriptions.new",          # 2) the prescription from the visit
    "finance.invoice_mark_tax",   # 3) a tax invoice, chosen
    "patients.analytics",         # 5) the analytics page
    "messages.outcomes",          # 6) whether sending brings anyone back
    "messages.resend_failed",     # 6) the failed ones, again
    "messages.desk",              # 6) birthdays on the desk
    "visits.ai_summary",          # 9) the visit summarised
)


@pytest.mark.parametrize("endpoint", BUILT_ROUTES)
def test_what_the_backlog_calls_built_is_a_real_screen(clinic, endpoint):
    assert endpoint in clinic["app"].view_functions


def test_the_columns_it_names_exist():
    from app.models import Invoice, User
    from app.models.discount import NamedDiscount

    assert "appointment_id" in Invoice.__table__.columns      # 1)
    assert "client_category" in NamedDiscount.__table__.columns  # 4)
    for chips in ("visit_complaint_chips", "visit_exam_chips",
                  "visit_plan_chips"):                       # 9)
        assert chips in User.__table__.columns


def test_the_templates_it_names_exist():
    templates = os.path.join(ROOT, "app", "templates")
    assert os.path.exists(os.path.join(templates, "finance",
                                       "receipt_thermal.html"))    # 3)
    record = open(os.path.join(templates, "visits", "record.html"),
                  encoding="utf-8").read()
    assert "visits.carry_forward" in record                       # 9)
    assert "prescriptions.new" in record                          # 2)


def test_every_done_item_in_the_file_says_where():
    """A ✅ heading with nothing to check it against is how this file went
    stale; each one is followed by a line naming the thing."""
    text = open(os.path.join(ROOT, "IMPROVEMENTS_BACKLOG.md"),
                encoding="utf-8").read()
    for number in ("2", "3", "4", "5", "7", "14"):
        head = next(line for line in text.splitlines()
                    if line.startswith(f"### {number})"))
        assert "✅" in head, head
        after = text.split(head, 1)[1].lstrip("\n").splitlines()[0]
        assert after.startswith(">") and "`" in after, (head, after)
