"""One department screen, drawn for whichever department asked for it.

Four blueprints reach this: emergency, the incubators, intensive care and the
wards. They are four modules because a clinic switches them on one at a time —
a nursery is not a ward and must not appear because somebody ticked "ward" —
and they are **one screen** because ``HOSPITAL_PLAN.md`` ٤-ب settled that they
differ by observation density rather than by substance.

What is left in each blueprint after this is a name, a kind, and whatever that
one department does that no other does: emergency has its decision, the
incubators have their four extra facts. Nothing else was ever different, and
before this file the sameness was four copies of the same eight lines waiting
to drift apart.
"""
from flask import render_template
from flask_login import current_user

from app.models.admission import OUTCOMES
from app.models.round_note import ROUND_TRENDS
from app.utils import beds as place
from app.utils import department


def render(module, kind, **extra):
    """The board for one kind of unit, worst first."""
    from app.models.place import Unit

    units = (Unit.query.filter(Unit.kind == kind, Unit.is_active.is_(True))
             .order_by(Unit.sort_order, Unit.id).all())
    return render_template(
        "departments/board.html",
        kind=kind, module=module, rows=department.live(kind), units=units,
        # Where a child goes when they are moved: offered from the board
        # itself, because the alternative is telling somebody to open the bed
        # setup, remember the child's name, and start again.
        free=place.free_beds(), outcomes=OUTCOMES, trends=ROUND_TRENDS,
        levels=department, may_build=current_user.is_admin, **extra)
