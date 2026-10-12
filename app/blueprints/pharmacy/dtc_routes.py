"""GAHAR MMS.01 / MMS.03 — the drug and therapeutics committee, its annual
review, and drug shortages announced to prescribers (``utils/dtc``)."""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.pharmacy import pharmacy_bp
from app.extensions import db
from app.i18n import t
from app.models.dtc import REVIEW_ELEMENTS, DrugShortage, DtcDecision
from app.utils import dtc
from app.utils.clock import local_today
from app.utils.decorators import module_required

MODULE = "pharmacy"


def _refused(err, where):
    db.session.rollback()
    flash(t("dtc.err_" + str(err)), "error")
    return redirect(where)


@pharmacy_bp.route("/dtc")
@module_required(MODULE)
def dtc_board():
    from app.models import FirstDoseWatch, GenericDrug

    year = request.args.get("year", type=int) or local_today().year
    return render_template("pharmacy/dtc.html", data=dtc.board(), year=year,
                           elements=REVIEW_ELEMENTS, today=local_today(),
                           watch=FirstDoseWatch.query.filter_by(is_active=True).all(),
                           generics=GenericDrug.query.filter_by(is_active=True).order_by(GenericDrug.name_en).all())


@pharmacy_bp.route("/dtc/meeting", methods=["POST"])
@module_required(MODULE)
def dtc_meeting_save():
    try:
        dtc.save_meeting(request.form, current_user)
    except dtc.DtcError as err:
        return _refused(err, url_for("pharmacy.dtc_board"))
    db.session.commit()
    flash(t("dtc.saved"), "success")
    return redirect(url_for("pharmacy.dtc_board"))


@pharmacy_bp.route("/dtc/decision/<int:row_id>/done", methods=["POST"])
@module_required(MODULE)
def dtc_decision_done(row_id):
    try:
        dtc.close_decision(db.get_or_404(DtcDecision, row_id), request.form.get("note"))
    except dtc.DtcError as err:
        return _refused(err, url_for("pharmacy.dtc_board"))
    db.session.commit()
    flash(t("dtc.saved"), "success")
    return redirect(url_for("pharmacy.dtc_board"))


@pharmacy_bp.route("/dtc/review/<int:year>", methods=["POST"])
@module_required(MODULE)
def dtc_review_save(year):
    back = url_for("pharmacy.dtc_board", year=year) + "#review"
    try:
        dtc.save_review(year, request.form, current_user)
    except dtc.DtcError as err:
        return _refused(err, back)
    db.session.commit()
    flash(t("dtc.saved"), "success")
    return redirect(back)


@pharmacy_bp.route("/shortages")
@login_required
def shortages():
    """Read by every prescriber — the bell brings them here."""
    return render_template("pharmacy/shortages.html", rows=dtc.active_shortages(),
                           may_announce=current_user.is_admin or current_user.can_access(MODULE))


@pharmacy_bp.route("/shortages/announce", methods=["POST"])
@module_required(MODULE)
def shortage_announce():
    from app.utils import notifications

    try:
        dtc.announce(request.form, current_user)
    except dtc.DtcError as err:
        return _refused(err, url_for("pharmacy.shortages"))
    db.session.commit()
    notifications.invalidate()
    flash(t("dtc.announced"), "success")
    return redirect(url_for("pharmacy.shortages"))


@pharmacy_bp.route("/shortages/<int:row_id>/end", methods=["POST"])
@module_required(MODULE)
def shortage_end(row_id):
    from app.utils import notifications

    dtc.end_shortage(db.get_or_404(DrugShortage, row_id))
    db.session.commit()
    notifications.invalidate()
    flash(t("dtc.saved"), "success")
    return redirect(url_for("pharmacy.shortages"))


@pharmacy_bp.route("/ward/<int:admission_id>/counselled", methods=["POST"])
@module_required(MODULE)
def discharge_counselled(admission_id):
    """GAHAR MMS.14 ev. 4 — the pharmacist's counselling at discharge."""
    from app.models.admission import Admission
    from app.utils import med_family as fam

    stay = db.get_or_404(Admission, admission_id)
    back = url_for("pharmacy.discharge_meds", admission_id=stay.id) + "#counsel"
    try:
        fam.counsel(stay, request.form, current_user, "discharge")
    except fam.FamilyMedError as err:
        db.session.rollback()
        flash(t("fammed.err_" + str(err)), "error")
        return redirect(back)
    db.session.commit()
    flash(t("fammed.saved"), "success")
    return redirect(back)


@pharmacy_bp.route("/dtc/first-dose", methods=["POST"])
@module_required(MODULE)
def first_dose_watch_add():
    """GAHAR MMS.16 ev. 2 — the hospital's first-dose list."""
    from app.utils import med_family as fam

    try:
        fam.add_watch(request.form)
    except fam.FamilyMedError as err:
        db.session.rollback()
        flash(t("fammed.err_" + str(err)), "error")
        return redirect(url_for("pharmacy.dtc_board") + "#first-dose")
    db.session.commit()
    flash(t("fammed.saved"), "success")
    return redirect(url_for("pharmacy.dtc_board") + "#first-dose")
