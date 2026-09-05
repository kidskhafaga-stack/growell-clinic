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
from flask import flash, g, redirect, render_template, request, url_for
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
