"""«أنماط المرضى» — SMART_PATTERNS_PLAN ج-٥ ب (``utils/patient_patterns``).

One screen with a part for each question: who will probably not come this
week, whose vaccine series or programme is about to drop, who keeps coming
to the emergency department, and what next month looked like in the years
before. A part shows only where its department runs.
"""
from flask import render_template, request

from app.blueprints.reports import reports_bp
from app.utils.decorators import module_required

TABS = ("no_show", "series", "er", "season")


@reports_bp.route("/patient-patterns")
@module_required("reports")
def patient_patterns():
    from app.utils import patient_patterns as pp
    from app.utils.facility import module_enabled

    tabs = [k for k in TABS
            if (k != "series" or module_enabled("vaccinations") or module_enabled("programs"))
            and (k != "er" or module_enabled("emergency"))]
    tab = request.args.get("tab") if request.args.get("tab") in tabs else tabs[0]
    data = {}
    if tab == "no_show":
        data["rows"] = pp.no_show_risk()
    elif tab == "series":
        data["series"] = pp.series_at_risk() if module_enabled("vaccinations") else []
        data["programs"] = pp.programs_at_risk() if module_enabled("programs") else []
    elif tab == "er":
        data["rows"] = pp.frequent_er()
    else:
        data["season"] = pp.season()
    return render_template("reports/patient_patterns.html", tabs=tabs, tab=tab, data=data,
                           pp=pp)
