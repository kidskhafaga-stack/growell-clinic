"""The public request page — "اطلب موعد" from a post, a bio or a QR.

``CONNECTHUB_PLAN.md``, stage one. A family that saw a post about a doctor
can ask for a time without an account and without the desk being on the
phone. What it writes is a **request** in the ordinary queue
(``BOOKING_APPROVAL_PLAN.md``): the desk reads it, the doctor approves where
they do, and it is booked through the booking screen like every other. So
the page tells the family their request *arrived* — never that a time is
theirs.

The rules a door onto the open internet needs:

* **off until the clinic opens it** — a closed page is a 404, not a form;
* a ceiling per caller, a field only scripts fill, and the CSRF token;
* the campaign tag (``?src=``) is cleaned to letters, digits and ``_.:-``
  before it is kept — it is the family's link, not trusted input;
* **the urgent does not wait for anybody**: words that say emergency are
  answered on the page itself, at once, with the clinic's number — by the
  written rule the inbox uses (``utils/triage``), not by a model.
"""
from flask import abort, current_app, g, redirect, render_template, request, url_for

from app.blueprints.booking_page import booking_page_bp
from app.extensions import db
from app.models import Setting
from app.utils import channels, leads
from app.utils.appointments import list_doctors, parse_date_arg
from app.utils.clock import local_today
from app.utils.decorators import client_ip
from app.utils.rate_limit import BOOKING_PAGE_PER_MINUTE, limit
from app.utils.triage import urgent_word

#: The field only a script fills. Named like a real one on purpose.
TRAP = "website"


def _clinic(lang):
    if lang == "en":
        return (Setting.get("clinic_name") or Setting.get("clinic_name_ar")
                or "Clinic")
    return Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "العيادة"


def _page(**ctx):
    lang = getattr(g, "lang", "ar")
    logo = Setting.get("clinic_logo") or None
    return render_template(
        "booking_page/form.html", clinic=_clinic(lang),
        clinic_phone=(Setting.get("clinic_phone") or "").strip() or None,
        logo_url=(url_for("static", filename="uploads/clinic/" + logo)
                  if logo else None),
        lang=lang, trap=TRAP, **ctx)


def _doctor(raw):
    """A doctor the clinic books with, or ``None`` — never an arbitrary
    user id from a public URL."""
    try:
        wanted = int(raw or 0)
    except (TypeError, ValueError):
        return None
    return next((d for d in list_doctors() if d.id == wanted), None)


@booking_page_bp.route("", methods=["GET"])
@limit("booking_page", BOOKING_PAGE_PER_MINUTE * 4, methods=("GET",))
def form():
    if not channels.page_open():
        abort(404)
    doctor = _doctor(request.args.get("doctor"))
    return _page(state="form", tag=channels.clean_tag(request.args.get("src")),
                 doctor=doctor, doctors=list_doctors(), today=local_today(),
                 values={})


@booking_page_bp.route("", methods=["POST"])
@limit("booking_page", BOOKING_PAGE_PER_MINUTE)
def submit():
    if not channels.page_open():
        abort(404)
    form = request.form
    tag = channels.clean_tag(form.get("src"))
    if (form.get(TRAP) or "").strip():
        # A script. It is shown the same "arrived" page a family is, so it
        # learns nothing — and nothing is written.
        return redirect(url_for("booking_page.done"))
    message = (form.get("message") or "").strip()
    urgent = urgent_word(message)
    wanted = parse_date_arg(form.get("wanted_date"), default=None)
    if wanted is not None and wanted < local_today():
        wanted = None
    doctor = _doctor(form.get("doctor"))
    try:
        leads.take_from_page(form.get("name"), form.get("phone"),
                             form.get("child"), message, tag=tag,
                             doctor_id=doctor.id if doctor else None,
                             wanted_date=wanted, ip_address=client_ip())
    except ValueError:
        return _page(state="form", tag=tag, doctor=doctor,
                     doctors=list_doctors(), today=local_today(),
                     values=form, error=True), 400
    except Exception:  # noqa: BLE001 — never show a family a stack trace
        db.session.rollback()
        current_app.logger.exception("booking page: could not take request")
        return _page(state="form", tag=tag, doctor=doctor,
                     doctors=list_doctors(), today=local_today(),
                     values=form, error=True), 500
    db.session.commit()
    return redirect(url_for("booking_page.done", urgent=1 if urgent else None))


@booking_page_bp.route("/done", methods=["GET"])
def done():
    if not channels.page_open():
        abort(404)
    return _page(state="done", urgent=request.args.get("urgent") == "1")

