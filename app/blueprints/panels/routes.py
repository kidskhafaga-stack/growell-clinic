"""Which extra questions each specialty asks, and who is being asked them.

A module rather than a setting because of what "off" has to mean: a clinic
that does not work specialties should not have the section on its
consultation screen at all — not an empty picker, not a disabled control,
absent. A setting hides a control; a module removes the ground it stood on.

Admin-only, because nobody else ever opens it. A doctor meets the panels on
the visit screen, which is where the work is; this is where somebody decides
which panels exist for this clinic and who works them.

The screen is not a shell to satisfy the landing-page guard. It answers three
questions a person actually asks: what does each panel ask for, which doctors
are on it, and is anybody filling it in.
"""
from flask import render_template
from flask_login import login_required

from app.blueprints.panels import panels_bp
from app.extensions import db
from app.utils.decorators import admin_required, module_required

MODULE = "panels"


@panels_bp.route("/")
@login_required
@module_required(MODULE)
@admin_required
def index():
    """The panels this clinic has, with their doctors and their use.

    Usage is counted from `Measurement.panel` rather than
    `Visit.specialty_panel`: the measurement row is stamped with the panel it
    was entered from at the moment it was saved, so it stays true for a visit
    whose doctor later changes specialty. It is also the only one that can
    count a visit that recorded under two.
    """
    from app.models import Measurement, User
    from app.utils import panels as catalogue

    counts = dict(
        db.session.query(Measurement.panel, db.func.count(
            db.func.distinct(Measurement.visit_id)))
        .filter(Measurement.panel.isnot(None))
        .group_by(Measurement.panel).all())

    doctors = [u for u in User.query.filter_by(is_active=True).all()
               if User.sees_patients(u.role, u.is_practitioner)]

    rows = []
    for key, meta in catalogue.all_panels().items():
        rows.append({
            "key": key,
            "meta": meta,
            "fields": len(meta.get("fields") or []),
            "reads": meta.get("reads") or [],
            "visits": counts.get(key, 0),
            "doctors": [d for d in doctors if key in catalogue.for_doctor(d)],
        })

    # Panels nobody is on come last: the useful half of this screen is what is
    # in use, and a clinic that has enabled the module has usually enabled it
    # for one or two.
    rows.sort(key=lambda r: (not r["doctors"], -r["visits"], r["key"]))
    return render_template("panels/index.html", rows=rows,
                           doctors=doctors, orphans=sorted(
                               set(counts) - set(catalogue.all_panels())))
