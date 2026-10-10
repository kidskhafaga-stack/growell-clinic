"""What is ordered, defined — one list, kept by each room in its own module.

> «هل تم تصحيح مديول المعمل وفصله عن الاشعة ؟»

The worklists split long ago (`imaging/routes.py`, `visits.device_board`),
but the list a scan or an echo is *defined* in — its name, its price, its
machine, whether it is done here — stayed on the lab's page, behind the lab's
module. A hospital with radiology and no laboratory of its own could not add
one film; and the scans' tab carried the lab's store and the lab's sheet.

So each room keeps its own: the tests at ``/labs/tests`` (module ``labs``),
the scans at ``/imaging/catalogue`` (``imaging``), the device studies at
``/visits/studies/catalogue`` (``visits``, where their board is). The page
and the rules are one — this file — because the catalogue is one table, and
a row filed under the wrong room still moves to the right one from its row.

The lab's endpoints keep taking any kind when posted to, as they always
have; the new ones take only their own.
"""
from collections import namedtuple

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.extensions import db
from app.i18n import t
from app.models import Investigation
from app.models.prescription import INVESTIGATION_KINDS

#: ``module`` gates it, ``home`` is the room's worklist, ``active`` the
#: sidebar entry lit while it is open.
Room = namedtuple("Room", "kind module list add edit home active")
ROOMS = {
    "lab": Room("lab", "labs", "labs.tests", "labs.add_test", "labs.edit_test",
                "labs.index", "labs"),
    "imaging": Room("imaging", "imaging", "imaging.catalogue_page", "imaging.catalogue_add",
                    "imaging.catalogue_edit", "imaging.index", "imaging"),
    "diagnostic": Room("diagnostic", "visits", "visits.study_catalogue",
                       "visits.study_catalogue_add", "visits.study_catalogue_edit",
                       "visits.device_board", "device_board"),
}


def suffix(kind):
    """The locale keys' ending: the lab keeps the original words, the
    others take ``_<kind>`` — a film is not «an analysis»."""
    return "" if kind == "lab" else f"_{kind}"


def is_open(kind):
    from app.utils.facility import module_enabled

    room = ROOMS[kind]
    return module_enabled(room.module) and current_user.can_access(room.module)


def url(kind, **args):
    """The room's own list, carrying a search over if there is one."""
    return url_for(ROOMS[kind].list, **{k: v for k, v in args.items() if v})


def where_after(kind):
    """After a save: the row's own room if this person can open it, else
    the lab's (where the old pages always went)."""
    return kind if is_open(kind) else "lab"


def _admin_only():
    if not current_user.is_admin:
        abort(403, description=t("auth.no_permission"))


# ================================================================== page ==
def page(kind):
    from sqlalchemy import or_

    from app.blueprints.labs import routes as lab
    from app.models.service import Service

    _admin_only()
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    page_no = max(1, request.args.get("page", type=int) or 1)
    query = Investigation.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Investigation.name_ar.ilike(like),
                                 Investigation.name_en.ilike(like),
                                 Investigation.aliases.ilike(like),
                                 Investigation.code.ilike(like)))
    if category:
        query = query.filter(Investigation.category == category)
    # Counted per kind *after* the search, so a search that found the echo
    # under the other room says so on that room's tab.
    per_kind = dict(query.with_entities(Investigation.kind, db.func.count())
                    .group_by(Investigation.kind).all())
    query = query.filter(Investigation.kind == kind)
    total = query.count()
    rows = (query.order_by(Investigation.name_ar)
            .offset((page_no - 1) * lab.PAGE).limit(lab.PAGE).all())
    categories = [c for (c,) in db.session.query(Investigation.category)
                  .filter(Investigation.kind == kind, Investigation.category.isnot(None))
                  .distinct().order_by(Investigation.category).all()]
    is_lab = kind == "lab"
    rad = lab._radiation()
    return render_template(
        "labs/tests.html", rows=rows, kinds=INVESTIGATION_KINDS, kind=kind,
        room=ROOMS[kind], kx=suffix(kind),
        tabs=[k for k in INVESTIGATION_KINDS if k == kind or is_open(k)],
        tab_url=url, per_kind=per_kind,
        q=q, category=category, categories=categories, page=page_no,
        pages=max(1, -(-total // lab.PAGE)), total=total,
        services=(Service.query.filter(Service.is_active.is_(True))
                  .order_by(Service.name).all()),
        # The lab's own things — its sheet, its store, its release policy,
        # why a tube is turned away, where it sends out — on the lab's page.
        reference=lab._reference_state(rows) if is_lab else {},
        warehouses=lab._warehouses() if is_lab else [],
        lab_store=lab._lab_store() if is_lab else None,
        reject_reasons=lab._reception().reasons() if is_lab else [],
        release_required=lab._release().required() if is_lab else False,
        referral_labs=lab._sendout().laboratories() if is_lab else [],
        devices=lab._devices() if kind == "diagnostic" else [],
        modalities=rad.MODALITIES, dose_measures=rad.measures(),
        radiation_base=rad.base_unit)


# =================================================================== add ==
def add(kind):
    """A new row of ``kind``. The caller has checked the module."""
    _admin_only()
    kind = kind if kind in INVESTIGATION_KINDS else "lab"
    kx = suffix(kind)
    name = (request.form.get("name_ar") or "").strip()[:160]
    if not name:
        flash(t("lab.need_name" + kx), "error")
        return redirect(url(where_after(kind)))
    # A scan has no sample and no unit — its page has no box for either,
    # and anything that arrives anyway is not kept.
    is_lab = kind == "lab"
    row = Investigation(
        name_ar=name,
        name_en=(request.form.get("name_en") or "").strip()[:160] or None,
        kind=kind,
        unit=((request.form.get("unit") or "").strip()[:20] or None) if is_lab else None,
        sample_type=((request.form.get("sample_type") or "").strip()[:40] or None)
        if is_lab else None,
        # Ticked by default on the add form, so a clinic that never touches
        # this box builds a catalogue of things it does — which is what a
        # catalogue has always meant here.
        in_house=request.form.get("in_house") == "1",
        service_id=request.form.get("service_id", type=int))
    db.session.add(row)
    db.session.commit()
    flash(t("lab.test_added" + kx), "success")
    # **Step by step from here** — «اضافة واحد لواحد بالخطوات المطلوبة». A
    # lab test lands on its own page, where the steps it still needs are
    # listed in order; a scan has nothing more to define.
    if is_lab:
        return redirect(url_for("labs.test_ranges", test_id=row.id))
    return redirect(url(where_after(kind)))


# ================================================================== edit ==
def edit(test_id, kind=None):
    """The name, the price, and what the row's kind asks for. ``kind`` set,
    the row must be of it — the scans' page edits scans."""
    from app.blueprints.labs import routes as lab

    _admin_only()
    row = db.get_or_404(Investigation, test_id)
    if kind is not None and row.kind != kind:
        abort(404)
    name = (request.form.get("name_ar") or "").strip()[:160]
    if name:
        row.name_ar = name
    row.name_en = (request.form.get("name_en") or "").strip()[:160] or None
    # A scan's row has no sample box and no unit box, so a save from it must
    # not read their absence as «cleared».
    if row.kind == "lab":
        row.unit = (request.form.get("unit") or "").strip()[:20] or None
        row.sample_type = (request.form.get("sample_type") or "").strip()[:40] or None
    elif row.kind == "diagnostic":
        # The device it is done on — recording it opens that device's
        # template — and whether it is booked rather than done on the spot.
        row.device_id = request.form.get("device_id", type=int) or None
        row.needs_booking = request.form.get("needs_booking") == "1"
    elif row.kind == "imaging":
        # The machine, and the hospital's reference level for the dose — a
        # figure only the hospital sets; a blank box clears it.
        from app.utils import radiation

        modality = (request.form.get("modality") or "").strip()
        row.modality = modality if modality in radiation.MODALITIES else None
        ref = request.form.get("dose_ref_value", type=float)
        measure, unit = radiation.parse_measure(request.form.get("dose_ref_measure"))
        if ref and ref > 0 and measure:
            row.dose_ref_value, row.dose_ref_kind, row.dose_ref_unit = ref, measure, unit
        else:
            row.dose_ref_value = row.dose_ref_kind = row.dose_ref_unit = None
    # Cleared on purpose when the box is empty: a clinic that stops charging
    # for a test has to be able to say so, and an empty select means nobody
    # rather than "leave it as it was".
    row.service_id = request.form.get("service_id", type=int)
    row.is_active = request.form.get("is_active") == "1"
    # **«ما عندناش إيكو» — قالتها العيادة مرة واحدة.** A different question
    # from `is_active`: a test the clinic sends out still belongs in the
    # search, because the *order* is written here whoever performs it. All
    # this decides is whether the order joins this building's own worklist.
    row.in_house = request.form.get("in_house") == "1"
    if row.kind == "lab" and "referral_lab_id" in request.form:
        from app.models import ReferralLab

        wanted = request.form.get("referral_lab_id", type=int)
        row.referral_lab_id = (wanted if wanted and db.session.get(ReferralLab, wanted)
                               else None)
    lab._move_kind(row, request.form.get("move_kind"))
    db.session.commit()
    flash(t("lab.test_saved"), "success")
    return redirect(url(where_after(row.kind)))
