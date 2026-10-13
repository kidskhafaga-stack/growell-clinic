"""Governance — the committee register and its terms of reference (OGM.05,
OGM.01), the quarterly reports to the governing body (OGM.03, EFS.02 ev. 5),
the ethics committee's issues (OGM.15), contracted services and suppliers
(OGM.13, OGM.10), and the staff health program (OGM.17). The logic is in
``utils/governance`` and ``utils/staff_health``."""
from functools import wraps

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.quality import quality_bp
from app.blueprints.quality.routes import _team
from app.extensions import db
from app.i18n import t
from app.models.governance import CHARTER_KEYS, ContractedService, EthicsIssue, GovernanceReport
from app.models.staff_health import ENTRY_KINDS, HAZARDS, RESULTS, RISK_LEVELS
from app.utils import governance as gov
from app.utils import staff_health as sh
from app.utils.clock import local_today
from app.utils.facility_safety import FacilityError


def _go(fn, where):
    try:
        fn()
    except FacilityError as err:
        db.session.rollback()
        flash(t(f"facility.err_{err}"), "error")
        return redirect(where)
    db.session.commit()
    flash(t("facility.saved"), "success")
    return redirect(where)


def _file():
    from app.utils.uploads import save_document

    file = request.files.get("file")
    if not file or not file.filename:
        return None
    stored = save_document(file)
    if stored is None:
        raise FacilityError("bad_file")
    return stored


# ============================================================== committees ==
@quality_bp.route("/committees")
@_team
def committees():
    today = local_today()
    return render_template("quality/committees.html", rows=gov.committees(today),
                           reports=gov.reports_board(today), quarter=gov.quarter_of(today),
                           today=today)


@quality_bp.route("/committees/<key>/charter", methods=["POST"])
@_team
def committee_charter(key):
    if key not in CHARTER_KEYS:
        abort(404)
    return _go(lambda: gov.save_charter(current_user, key, request.form),
               url_for("quality.committees") + f"#c-{key}")


@quality_bp.route("/committees/<key>/review/<int:year>", methods=["POST"])
@_team
def committee_review(key, year):
    if key not in CHARTER_KEYS:
        abort(404)
    return _go(lambda: gov.save_review(current_user, key, year, request.form),
               url_for("quality.committees") + f"#c-{key}")


@quality_bp.route("/governing-report", methods=["POST"])
@_team
def governing_report():
    return _go(lambda: gov.save_report(current_user, request.form, file=_file()),
               url_for("quality.committees") + "#reports")


@quality_bp.route("/governing-report/<int:report_id>/feedback", methods=["POST"])
@_team
def governing_feedback(report_id):
    row = db.get_or_404(GovernanceReport, report_id)
    return _go(lambda: gov.feedback(row, request.form), url_for("quality.committees") + "#reports")


# ================================================================== ethics ==
@quality_bp.route("/ethics")
@_team
def ethics():
    return render_template("quality/ethics.html", data=gov.ethics_board(local_today()), today=local_today())


@quality_bp.route("/ethics", methods=["POST"])
@_team
def ethics_new():
    return _go(lambda: gov.raise_issue(current_user, request.form), url_for("quality.ethics"))


@quality_bp.route("/ethics/<int:issue_id>", methods=["POST"])
@_team
def ethics_work(issue_id):
    row = db.get_or_404(EthicsIssue, issue_id)
    return _go(lambda: gov.work_issue(row, request.form), url_for("quality.ethics") + f"#e{row.id}")


# ======================================================= contracts, suppliers ==
@quality_bp.route("/contracts")
@_team
def contracts():
    today = local_today()
    return render_template("quality/contracts.html", data=gov.services_board(today),
                           suppliers=gov.suppliers_board(today), today=today)


@quality_bp.route("/contracts", methods=["POST"])
@_team
def contract_new():
    return _go(lambda: gov.save_service(request.form), url_for("quality.contracts"))


@quality_bp.route("/contracts/<int:service_id>/evaluate", methods=["POST"])
@_team
def contract_evaluate(service_id):
    row = db.get_or_404(ContractedService, service_id)
    return _go(lambda: gov.evaluate_service(row, current_user, request.form),
               url_for("quality.contracts") + f"#s{row.id}")


@quality_bp.route("/supplier/<int:supplier_id>/evaluate", methods=["POST"])
@_team
def supplier_evaluate(supplier_id):
    from app.models import Supplier

    row = db.get_or_404(Supplier, supplier_id)
    return _go(lambda: gov.evaluate_supplier(row, current_user, request.form),
               url_for("quality.contracts") + "#suppliers")


# ============================================================ staff health ==
def _health(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        if not sh.may_open(current_user):
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)
    return wrapped


@quality_bp.route("/staff-health")
@_health
def staff_health():
    return render_template("quality/staff_health.html", data=sh.board(local_today()), risks=sh.risks(),
                           hazards=HAZARDS, levels=RISK_LEVELS, today=local_today())


@quality_bp.route("/staff-health/risk", methods=["POST"])
@_health
def staff_health_risk():
    return _go(lambda: sh.save_risk(current_user, request.form), url_for("quality.staff_health") + "#risks")


@quality_bp.route("/staff-health/<int:user_id>", methods=["GET", "POST"])
@_health
def staff_health_file(user_id):
    from app.models import User

    staff = db.get_or_404(User, user_id)
    if request.method == "POST":
        return _go(lambda: sh.record(current_user, staff, request.form),
                   url_for("quality.staff_health_file", user_id=staff.id))
    return render_template("quality/staff_health_file.html", staff=staff, rows=sh.file_of(staff),
                           kinds=ENTRY_KINDS, results=RESULTS, today=local_today())


# =============================================================== community ==
# GAHAR CAI — the partners, the needs assessment every two years, the
# activities and initiatives with their satisfaction, and the advertisements.
@quality_bp.route("/community")
@_team
def community():
    from app.models.community import ACTIVITY_KINDS, NEEDS, PARTNER_KINDS
    from app.utils import community as cm

    today = local_today()
    year = request.args.get("year", type=int) or today.year
    return render_template("quality/community.html", data=cm.board(today),
                           activities=cm.activities_board(year, today), partner_kinds=PARTNER_KINDS,
                           activity_kinds=ACTIVITY_KINDS, needs=NEEDS, today=today)


@quality_bp.route("/community/partner", methods=["POST"])
@_team
def community_partner():
    from app.utils import community as cm

    return _go(lambda: cm.save_partner(request.form), url_for("quality.community") + "#partners")


@quality_bp.route("/community/partner/<int:partner_id>/contacted", methods=["POST"])
@_team
def community_contacted(partner_id):
    from app.models.community import CommunityPartner
    from app.utils import community as cm

    row = db.get_or_404(CommunityPartner, partner_id)
    return _go(lambda: cm.contacted(row, request.form), url_for("quality.community") + "#partners")


@quality_bp.route("/community/assessment", methods=["POST"])
@_team
def community_assessment():
    from app.utils import community as cm

    return _go(lambda: cm.save_assessment(current_user, request.form, file=_file()),
               url_for("quality.community") + "#needs")


@quality_bp.route("/community/assessment/<int:assessment_id>/share", methods=["POST"])
@_team
def community_share(assessment_id):
    from app.models.community import NeedsAssessment
    from app.utils import community as cm

    row = db.get_or_404(NeedsAssessment, assessment_id)
    return _go(lambda: cm.share(row, request.form), url_for("quality.community") + "#needs")


@quality_bp.route("/community/activity", methods=["POST"])
@_team
def community_activity():
    from app.utils import community as cm

    return _go(lambda: cm.save_activity(current_user, request.form), url_for("quality.community") + "#activities")


@quality_bp.route("/community/ad", methods=["POST"])
@_team
def community_ad():
    from app.utils import community as cm

    return _go(lambda: cm.review_ad(current_user, request.form), url_for("quality.community") + "#ads")
