"""The inpatient wards — the fourth department, and the slowest of them.

Emergency is read in minutes and the incubators in hours; a ward is read in
**days**. The child in bed four is not going anywhere before Thursday, and the
question this screen answers is not "who first" but two others no other
department asks:

* **who has nobody been round to this morning**, and
* **who are we expecting to send home.**

Both come from ``RoundNote``, and both are the ward manager's first two
questions of the day. Everything else here is the same ``department.live``
that draws emergency and the incubators, over the same place, the same stay
and the same readings — at a different tempo, which is data a doctor sets and
not a branch in any file.

**Almost no code, and that is the point.** ``HOSPITAL_PLAN.md`` ٤-ب settled
that the four departments are four observation densities over one base rather
than four systems. This file is what that promise looks like when it is kept.
"""
from app.blueprints import department_screen
from app.blueprints.ward import ward_bp
from app.utils.decorators import module_required

MODULE = "ward"
KIND = "ward"


@ward_bp.route("/")
@module_required(MODULE)
def index():
    """Everybody admitted to a ward, worst first, unrounded before rounded."""
    return department_screen.render(MODULE, KIND)
