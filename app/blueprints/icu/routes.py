"""Intensive care — the ward's screen, read four times as often.

The only thing that separates this department from the one next door is **how
often somebody looks**: an hourly observation order instead of a morning one,
and a child whose last reading the program calls urgent is the normal case
here rather than the alarm.

None of that is a difference in code. The interval is on the child's
``ObservationOrder``, written by the doctor who admitted them; the thresholds
are the clinic's one copy in ``red_flags`` and ``vital_bands``. So this file
is a name and a kind, and if it ever grows a rule of its own that rule is
almost certainly a second copy of a number that already exists somewhere.

It is a separate module rather than a unit kind on the ward screen for the
reason every department here is: a hospital that runs wards and no intensive
care must not find an intensive care screen in its sidebar after an update.
"""
from app.blueprints import department_screen
from app.blueprints.icu import icu_bp
from app.utils.decorators import module_required

MODULE = "icu"
KIND = "icu"


@icu_bp.route("/")
@module_required(MODULE)
def index():
    return department_screen.render(MODULE, KIND)
