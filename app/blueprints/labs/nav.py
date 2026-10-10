"""The lab's own bar — one row of doors, grouped, on every lab page.

The rack carried eleven buttons in one undifferentiated block, and every
other lab page carried one: «الرف». A technician looking for the reagent
lots had to read them all, and from the reagent lots there was no way to the
quality control but back through the rack. So the doors are one bar, said
once (``labs/_nav.html``), in the lab's own four groups — the day's work,
quality, running the lab, and setting it up — with the counts that need
somebody on them in red, on whichever page it is open.
"""
from flask_login import current_user

from app.blueprints.labs import labs_bp


@labs_bp.app_template_global("lab_nav_state")
def lab_nav_state():
    from app.utils import (lab_competency, lab_poct, lab_quality, lab_reagents,
                           lab_release, lab_results, lab_sendout)

    return {
        "to_release": lab_release.waiting_count() if lab_release.required() else 0,
        "release_on": lab_release.required(),
        "sent_labs": bool(lab_sendout.laboratories()),
        "expired_lots": lab_reagents.expired_on_shelf(),
        "qc_failures": lab_quality.failed_without_action(),
        "poct_attention": lab_poct.needing_attention(),
        "staff_attention": lab_competency.attention(),
        "critical_open": len(lab_results.all_waiting()),
        "may_build": bool(current_user.is_authenticated and current_user.is_admin),
    }
