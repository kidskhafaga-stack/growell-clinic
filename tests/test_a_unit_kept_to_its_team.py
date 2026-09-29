"""A unit kept to its own doctors and nurses — with a way in that is written down.

Asked as: *«إيه رأيك نخلّي كل قسم مقصور على التمريض والأطباء بتوعه؟»*, with
the rule this project keeps for permissions: *«من غير ما نكسر حاجه شغال»*.

What is held here:

* a unit with no team is open to everybody, exactly as before;
* with a team, somebody not on it sees on the map that a bed is taken, not
  who or why, and a stay page asks for a reason instead of showing the child;
* a reason (not a blank) opens that stay for a shift, and is written down
  with the name for the manager to read;
* whoever runs the clinic sees every unit, and only they set the teams.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_bed_bill_the_books_never_heard_of import (  # noqa: E402,F401
    _admit, _child, hospital)


@pytest.fixture()
def team(hospital):
    """A nurse on the ward's team; the doctor is not on it."""
    from app.models import User
    from app.models.place import Unit

    with hospital["app"].app_context():
        nurse = User(username="nurse", full_name="م. هبة", role="nursing", is_active=True)
        nurse.set_password("secret")
        hospital["db"].session.add(nurse)
        hospital["db"].session.commit()
        hospital["nurse"] = nurse.id
        hospital["unit"] = Unit.query.one().id
    hospital["sign_in"]("boss").post(f"/beds/unit/{hospital['unit']}/team",
                                     data={"user_id": [hospital["nurse"]]})
    return hospital


def test_a_unit_with_no_team_is_open_as_before(hospital):
    stay = _admit(hospital, _child(hospital, "مفتوح"))
    page = hospital["sign_in"]("doc").get(f"/beds/admission/{stay}")
    assert page.status_code == 200
    assert "مفتوح" in hospital["sign_in"]("doc").get("/beds/").get_data(as_text=True)


def test_somebody_not_on_the_team_sees_a_bed_taken_not_who(team):
    stay = _admit(team, _child(team, "سرّي"))
    board = team["sign_in"]("doc").get("/beds/").get_data(as_text=True)
    assert "data-team-only" in board and "سرّي" not in board
    page = team["sign_in"]("doc").get(f"/beds/admission/{stay}")
    assert page.status_code == 403 and "data-break-glass" in page.get_data(as_text=True)
    assert "سرّي" not in page.get_data(as_text=True)
    assert "data-case-closed" in team["sign_in"]("doc").get(
        f"/beds/panel/{stay}").get_data(as_text=True)
    assert team["sign_in"]("doc").get(f"/beds/admission/{stay}/consent").status_code == 403
    # Its own nurse, and the owner, read it as ever.
    assert team["sign_in"]("nurse").get(f"/beds/admission/{stay}").status_code == 200
    assert "سرّي" in team["sign_in"]("boss").get("/beds/").get_data(as_text=True)


def test_a_reason_opens_it_for_a_shift_and_is_written_down(team):
    from app.models import ActivityLog
    from app.models.unit_staff import BreakGlass

    stay = _admit(team, _child(team, "نبطشية"))
    doc = team["sign_in"]("doc")
    doc.post(f"/beds/admission/{stay}/break-glass", data={"reason": "  "})
    assert doc.get(f"/beds/admission/{stay}").status_code == 403
    doc.post(f"/beds/admission/{stay}/break-glass", data={"reason": "نبطشية الليل"})
    assert doc.get(f"/beds/admission/{stay}").status_code == 200
    with team["app"].app_context():
        row = BreakGlass.query.one()
        assert (row.user_id, row.reason, row.unit_id) == (
            team["ids"]["doctor"], "نبطشية الليل", team["unit"])
        assert ActivityLog.query.filter_by(action="stay.break_glass").count() == 1
        row.at = datetime.utcnow() - timedelta(hours=13)
        team["db"].session.commit()
    assert doc.get(f"/beds/admission/{stay}").status_code == 403      # shift over
    setup = team["sign_in"]("boss").get("/beds/setup").get_data(as_text=True)
    assert "data-glass-log" in setup and "نبطشية الليل" in setup


def test_only_the_owner_sets_a_team_and_clearing_it_opens_the_unit(team):
    from app.models.unit_staff import UnitStaff

    assert team["sign_in"]("doc").post(f"/beds/unit/{team['unit']}/team",
                                       data={"user_id": [team["ids"]["doctor"]]}).status_code == 403
    stay = _admit(team, _child(team, "رجع مفتوح"))
    team["sign_in"]("boss").post(f"/beds/unit/{team['unit']}/team", data={})
    with team["app"].app_context():
        assert UnitStaff.query.count() == 0
    assert team["sign_in"]("doc").get(f"/beds/admission/{stay}").status_code == 200
