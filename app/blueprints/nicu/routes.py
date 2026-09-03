"""The incubators.

The same screen as emergency, at a different tempo and with four facts beside
each baby that no other department needs: hours of life, gestation at birth,
weight against birth weight, and where the last bilirubin sits against **this
baby's own** threshold.

None of those four is new. ``age_hours`` and ``gestation_weeks`` have been on
the patient since Phase 1 of ``EMERGENCY_NEWBORN_PLAN.md``, the weight is the
child's growth curve, and the bilirubin comparison is ``jaundice.assess`` —
which has existed, tested and gated behind a clinician's sign-off, since Phase
4. What did not exist is the join: a nurse read the number off the lab screen
and did the comparison in their head, on the one calculation this program
built specifically so nobody would have to.

**The old plan said this module would not be built.** *"No inpatient module.
`ward`, `nicu`, `icu` stay capabilities without screens ... a clinic that
admits patients needs a bed census, handovers and drug rounds; that is a
different program."* That was the right call when it was written and it is
superseded by ``HOSPITAL_PLAN.md``: the bed census now exists, and the
repeated readings with it. The honest gap the old plan named has been closed
rather than papered over.
"""
from flask import render_template
from flask_login import current_user

from app.blueprints.nicu import nicu_bp
from app.models.admission import OUTCOMES
from app.utils import beds as ward
from app.utils import department
from app.utils.decorators import module_required

MODULE = "nicu"
KIND = "nicu"


@nicu_bp.route("/")
@module_required(MODULE)
def index():
    from app.models.place import Unit

    units = (Unit.query.filter(Unit.kind == KIND, Unit.is_active.is_(True))
             .order_by(Unit.sort_order, Unit.id).all())
    return render_template(
        "departments/board.html",
        kind=KIND, module=MODULE, rows=department.live(KIND), units=units,
        free=ward.free_beds(), outcomes=OUTCOMES,
        levels=department, may_build=current_user.is_admin)
