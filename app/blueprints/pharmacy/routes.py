"""The pharmacy counter.

Two screens and no more: the queue of prescriptions with something still to
hand over, and one prescription — the check the doctor was shown, the boxes,
and the act of handing them across.

**Everything clinical here already existed.** The paediatric dose, the
allergy, the interactions: ``rx_safety``, unchanged and uncopied. What did not
exist is the counter itself — a prescription was written, printed, and that
was the end of it as far as this program was concerned, while the box left the
shelf and nothing was charged.

**The pharmacist asks, never refuses.** A query on a line is recorded and the
line stays dispensable: the doctor may well have meant it, the family is
standing there, and a pharmacy that can veto a prescription is one that
prescriptions get written around.
"""
from flask import (abort, flash, g, redirect, render_template, request,
                   url_for)
from flask_login import current_user

from app.blueprints.pharmacy import pharmacy_bp
from app.extensions import db
from app.i18n import t
from app.models import MedicationOrder, Prescription, PrescriptionItem
from app.models.admission import Admission
from app.utils import pharmacy as counter
from app.utils.decorators import module_required

MODULE = "pharmacy"


@pharmacy_bp.route("/")
@module_required(MODULE)
def index():
    """The queue: who is waiting, and what for."""
    days = min(30, max(1, request.args.get("days", type=int) or 3))
    return render_template("pharmacy/index.html",
                           rows=counter.queue(days=days), days=days,
                           counter=counter,
                           queries=counter.open_queries())


@pharmacy_bp.route("/rx/<int:rx_id>")
@module_required(MODULE)
def prescription(rx_id):
    """One prescription: the check, the shelf, and the handover."""
    row = db.get_or_404(Prescription, rx_id)
    return render_template(
        "pharmacy/rx.html", rx=row, counter=counter,
        safety=counter.review(row, lang=getattr(g, "lang", "ar")),
        items=_shelf())


@pharmacy_bp.route("/line/<int:line_id>/shelf", methods=["POST"])
@module_required(MODULE)
def shelf(line_id):
    """Say which box on the shelf this written line means.

    Left to the pharmacy on purpose. The doctor writes a drug; which of three
    strengths of it the clinic actually stocks is the counter's knowledge, and
    asking the doctor to pick a store item mid-consultation is asking them to
    do somebody else's job with worse information.
    """
    line = db.get_or_404(PrescriptionItem, line_id)
    line.store_item_id = request.form.get("store_item_id", type=int)
    quantity = request.form.get("quantity", type=int)
    line.quantity = max(1, quantity) if quantity else line.quantity
    db.session.commit()
    return redirect(url_for("pharmacy.prescription",
                            rx_id=line.prescription_id))


@pharmacy_bp.route("/line/<int:line_id>/dispense", methods=["POST"])
@module_required(MODULE)
def dispense(line_id):
    """Hand it over."""
    line = db.get_or_404(PrescriptionItem, line_id)
    try:
        counter.dispense(line, user=current_user,
                         quantity=request.form.get("quantity", type=int))
    except ValueError as why:
        db.session.rollback()
        flash(t("pharm.already_dispensed" if str(why) == "already dispensed"
                else "pharm.nothing_to_dispense"), "error")
        return redirect(url_for("pharmacy.prescription",
                                rx_id=line.prescription_id))
    db.session.commit()
    flash(t("pharm.dispensed"), "success")
    return redirect(url_for("pharmacy.prescription",
                            rx_id=line.prescription_id))


@pharmacy_bp.route("/line/<int:line_id>/query", methods=["POST"])
@module_required(MODULE)
def query(line_id):
    """Ask the doctor about this line — recorded, and never a block."""
    line = db.get_or_404(PrescriptionItem, line_id)
    try:
        counter.query(line, note=request.form.get("note"), user=current_user)
    except ValueError:
        db.session.rollback()
        # A blank question would clear the flag and say nothing, which reads
        # on the doctor's screen as "the pharmacy looked and was happy".
        flash(t("pharm.need_note"), "error")
        return redirect(url_for("pharmacy.prescription",
                                rx_id=line.prescription_id))
    db.session.commit()
    flash(t("pharm.queried"), "info")
    return redirect(url_for("pharmacy.prescription",
                            rx_id=line.prescription_id))


def _shelf():
    """What the pharmacy stocks, for the picker.

    Medicines only: a prescription line is never a box of gloves, and a picker
    holding the whole store is a picker nobody uses.
    """
    from app.models import StoreItem

    return (StoreItem.query
            .filter(StoreItem.is_active.is_(True),
                    StoreItem.item_type == "drug")
            .order_by(StoreItem.name).all())


# --------------------------------------------------- the ward pharmacist ---
def _ward_or_404():
    """The ward screens exist only where there are beds.

    A module off is a module absent, and a clinic with no inpatients has no
    drug charts to review — an empty board would read as something broken
    rather than as something they do not have.
    """
    from flask import abort

    from app.utils.facility import module_enabled

    if not module_enabled("beds"):
        abort(404)


@pharmacy_bp.route("/ward")
@module_required(MODULE)
def ward():
    """Whose chart has nobody been through today.

    The clinical half of the profession, and the half a hospital buys: not a
    queue of people holding paper, but every child in a bed and whether a
    second pair of eyes has read what they are on.
    """
    _ward_or_404()
    from app.utils import clinical_pharmacy

    kind = (request.args.get("kind") or "").strip() or None
    rows = clinical_pharmacy.board(kind=kind)
    return render_template("pharmacy/ward.html", rows=rows, kind=kind,
                           counts=clinical_pharmacy.counts(rows))


@pharmacy_bp.route("/ward/<int:admission_id>")
@module_required(MODULE)
def chart(admission_id):
    """One child's chart, with the clinic's own safety check over it."""
    _ward_or_404()
    from app.utils import clinical_pharmacy

    row = db.get_or_404(Admission, admission_id)
    return render_template(
        "pharmacy/chart.html", admission=row,
        reviews=sorted(row.chart_reviews, key=lambda r: r.at, reverse=True),
        **clinical_pharmacy.chart(row, lang=getattr(g, "lang", "ar")))


@pharmacy_bp.route("/ward/<int:admission_id>/reviewed", methods=["POST"])
@module_required(MODULE)
def reviewed(admission_id):
    """Record that somebody went through it."""
    _ward_or_404()
    from app.utils import clinical_pharmacy

    row = db.get_or_404(Admission, admission_id)
    clinical_pharmacy.review(row, user=current_user,
                             note=request.form.get("note"))
    db.session.commit()
    flash(t("cpharm.reviewed"), "success")
    return redirect(url_for("pharmacy.chart", admission_id=row.id))


@pharmacy_bp.route("/order/<int:order_id>/ask", methods=["POST"])
@module_required(MODULE)
def ask(order_id):
    """Ask the doctor about one ward order — and never stop it."""
    _ward_or_404()
    from app.utils import clinical_pharmacy

    row = db.get_or_404(MedicationOrder, order_id)
    try:
        clinical_pharmacy.ask(row, note=request.form.get("note"),
                              user=current_user)
    except ValueError:
        db.session.rollback()
        flash(t("pharm.need_note"), "error")
        return redirect(url_for("pharmacy.chart",
                                admission_id=row.admission_id))
    db.session.commit()
    flash(t("cpharm.asked"), "info")
    return redirect(url_for("pharmacy.chart", admission_id=row.admission_id))


@pharmacy_bp.route("/supply")
@module_required(MODULE)
def supply():
    """What has to be made up for the wards today.

    The bench half of the job, and the larger half in most hospitals: before
    the eight o'clock round somebody makes up each child's doses for the day,
    labelled per patient. The program had nothing for it — a dose existed only
    at the moment a nurse recorded giving it, so "is this child's amoxicillin
    ready?" had no answer anywhere.
    """
    _ward_or_404()
    from app.utils import clinical_pharmacy

    kind = (request.args.get("kind") or "").strip() or None
    rows = clinical_pharmacy.supply_list(kind=kind)
    return render_template("pharmacy/supply.html", rows=rows, kind=kind,
                           counts=clinical_pharmacy.supply_counts(rows))


@pharmacy_bp.route("/order/<int:order_id>/prepare", methods=["POST"])
@module_required(MODULE)
def prepare(order_id):
    """Made up, and on its way to the ward."""
    _ward_or_404()
    from app.utils import clinical_pharmacy

    row = db.get_or_404(MedicationOrder, order_id)
    try:
        clinical_pharmacy.prepare(row, user=current_user,
                                  label=request.form.get("label"))
    except ValueError:
        db.session.rollback()
        # A stopped order is not supplied. Making up a drug nobody may give is
        # the one mistake this list can cause.
        flash(t("cpharm.not_running"), "error")
        return redirect(url_for("pharmacy.supply"))
    db.session.commit()
    flash(t("cpharm.prepared"), "success")
    return redirect(request.referrer or url_for("pharmacy.supply"))


# ------------------------------------------- the hospital's own list -------
@pharmacy_bp.route("/high-alert")
@module_required(MODULE)
def high_alert():
    """The medicines this hospital decided to be careful with.

    **Nothing is seeded, on purpose.** The medication-management standards are
    explicit that the list is the hospital's own, built from its own use and
    its own near misses — and a list of dangerous drugs bundled with the
    software would be somebody else's judgement about a ward it has never
    seen. A paediatric oncology unit and a village clinic do not fear the same
    molecules.
    """
    from app.models import GenericDrug, HighAlertDrug

    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    return render_template(
        "pharmacy/high_alert.html",
        rows=(HighAlertDrug.query.order_by(HighAlertDrug.id.desc()).all()),
        generics=(GenericDrug.query.order_by(GenericDrug.name_en).limit(400)
                  .all()))


@pharmacy_bp.route("/high-alert/add", methods=["POST"])
@module_required(MODULE)
def add_high_alert():
    """Put one on the list. A reason is required."""
    from app.models import HighAlertDrug

    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    generic_id = request.form.get("generic_id", type=int)
    reason = (request.form.get("reason") or "").strip()[:255]
    if not generic_id:
        # A row naming neither an ingredient nor a product matches nothing,
        # and a rule that matches nothing reads as cover.
        flash(t("halert.need_drug"), "error")
        return redirect(url_for("pharmacy.high_alert"))
    if not reason:
        # The reason is the point: "insulin" on a list with nothing beside it
        # tells a night nurse nothing.
        flash(t("halert.need_reason"), "error")
        return redirect(url_for("pharmacy.high_alert"))
    db.session.add(HighAlertDrug(
        generic_id=generic_id, reason=reason,
        precaution=(request.form.get("precaution") or "").strip()[:255] or None,
        added_by=current_user.id))
    db.session.commit()
    flash(t("halert.added"), "success")
    return redirect(url_for("pharmacy.high_alert"))


@pharmacy_bp.route("/high-alert/<int:row_id>/toggle", methods=["POST"])
@module_required(MODULE)
def toggle_high_alert(row_id):
    """Off the list without losing that it was once on it."""
    from app.models import HighAlertDrug

    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    row = db.get_or_404(HighAlertDrug, row_id)
    row.is_active = not row.is_active
    db.session.commit()
    return redirect(url_for("pharmacy.high_alert"))


@pharmacy_bp.route("/order/<int:order_id>/verify", methods=["POST"])
@module_required(MODULE)
def verify(order_id):
    """A pharmacist checked this order before it was dispensed."""
    _ward_or_404()
    from app.utils import clinical_pharmacy

    row = db.get_or_404(MedicationOrder, order_id)
    try:
        clinical_pharmacy.verify(row, user=current_user)
    except ValueError:
        db.session.rollback()
        flash(t("cpharm.not_running"), "error")
        return redirect(url_for("pharmacy.ward"))
    db.session.commit()
    flash(t("cpharm.verified"), "success")
    return redirect(request.referrer
                    or url_for("pharmacy.chart", admission_id=row.admission_id))


# ------------------------------------------------ two names that confuse ----
@pharmacy_bp.route("/lasa", methods=["GET", "POST"])
@module_required(MODULE)
def lasa():
    """The pairs this hospital keeps confusing, and what it does about them.

    The hospital's own, like the high-alert list: which names get mixed up
    depends on what is on their shelves, what their handwriting looks like and
    what their staff speak.
    """
    from app.models import GenericDrug, LasaPair

    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    if request.method == "POST":
        first = request.form.get("generic_a_id", type=int)
        second = request.form.get("generic_b_id", type=int)
        if not first or not second or first == second:
            # A drug confused with itself is not a pair, and half a pair
            # warns in no direction at all.
            flash(t("lasa.need_two"), "error")
            return redirect(url_for("pharmacy.lasa"))
        db.session.add(LasaPair(
            generic_a_id=min(first, second), generic_b_id=max(first, second),
            precaution=(request.form.get("precaution") or "").strip()[:255]
            or None, added_by=current_user.id))
        db.session.commit()
        flash(t("lasa.added"), "success")
        return redirect(url_for("pharmacy.lasa"))

    return render_template(
        "pharmacy/lasa.html",
        rows=LasaPair.query.order_by(LasaPair.id.desc()).all(),
        generics=(GenericDrug.query.order_by(GenericDrug.name_en).limit(400)
                  .all()))


@pharmacy_bp.route("/lasa/<int:row_id>/toggle", methods=["POST"])
@module_required(MODULE)
def toggle_lasa(row_id):
    from app.models import LasaPair

    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))
    row = db.get_or_404(LasaPair, row_id)
    row.is_active = not row.is_active
    db.session.commit()
    return redirect(url_for("pharmacy.lasa"))


# ------------------------------------------------- what went wrong ----------
@pharmacy_bp.route("/errors", methods=["GET", "POST"])
@module_required(MODULE)
def errors():
    """What went wrong, or nearly did — and what it adds up to.

    **The loop the standards describe.** A hospital's high-alert list is meant
    to be built from its own near misses and errors; until something recorded
    them the list could only be written once from memory and never revised.

    Reporting is open to anybody who can reach the pharmacy module, because a
    reporting system only the pharmacist may write to collects the pharmacy's
    own mistakes and nobody else's.
    """
    from app.models import ERROR_OUTCOMES, ERROR_STAGES
    from app.utils import clinical_pharmacy

    if request.method == "POST":
        try:
            clinical_pharmacy.report_error(
                request.form.get("what_happened"),
                (request.form.get("stage") or "").strip(),
                (request.form.get("outcome") or "").strip(),
                user=current_user,
                drug_name=request.form.get("drug_name"),
                reached=request.form.get("reached") == "1",
                action=request.form.get("action_taken"))
        except ValueError:
            db.session.rollback()
            flash(t("mederr.need_account"), "error")
            return redirect(url_for("pharmacy.errors"))
        db.session.commit()
        flash(t("mederr.recorded"), "success")
        return redirect(url_for("pharmacy.errors"))

    days = min(365, max(7, request.args.get("days", type=int) or 90))
    return render_template("pharmacy/errors.html", days=days,
                           stages=ERROR_STAGES, outcomes=ERROR_OUTCOMES,
                           summary=clinical_pharmacy.error_summary(days))


# ---------------------------------------- what they go home on --------------
@pharmacy_bp.route("/ward/<int:admission_id>/discharge")
@module_required(MODULE)
def discharge_meds(admission_id):
    """The three lists a discharge needs put beside each other."""
    _ward_or_404()
    from app.utils import clinical_pharmacy

    row = db.get_or_404(Admission, admission_id)
    return render_template(
        "pharmacy/discharge.html", admission=row,
        **clinical_pharmacy.discharge_reconciliation(
            row, lang=getattr(g, "lang", "ar")))
