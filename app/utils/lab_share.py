"""The lab result to the family and to the referring doctor — م-٤.

LAB_GLAB360_PLAN.md م-٤, as the clinic's owner decided it:

* **after the doctor has seen it.** A released result goes on the doctor's
  list «نتايج مستنياك»; pressing «شُفتها» is what sends it;
* **a critical result or a sensitive test waits** until the doctor has
  spoken to the family and says so — the family must not read a potassium of
  7 or a positive serology on a phone before anybody has called them;
* **the referring doctor** can be sent the same link, with the same
  protection.

**What leaves**: where the clinic can be reached from outside (its public
address is set — :func:`online`), a link to the laboratory's report with
nothing added: no reading of it, no advice. It asks for the child's date of
birth, ends after :func:`days` days, and five wrong answers lock it
(`ResultShare`). Where it cannot, the same report as a file — the family's
choice of the owner — and, to the referring doctor, the numbers in the
message as well. Either way the report can be printed: «ده حق المريض».

**Off until the clinic turns it on** (the lab's settings), and from that day
only: switching it on does not put a year of old results on a doctor's list.
"""
import secrets
from datetime import date, datetime, timedelta

from app.extensions import db

SETTING = "lab_share"
SINCE = "lab_share_since"
DAYS = "lab_share_days"
DEFAULT_DAYS = 7


class ShareError(ValueError):
    """A refusal with a key the screen can name (``lab_share.err_<key>``)."""


# -------------------------------------------------------------- switches --
def on():
    from app.models import Setting
    from app.utils.facility import module_enabled

    return module_enabled("labs") and Setting.get(SETTING) == "1"


def days():
    from app.models import Setting

    raw = (Setting.get(DAYS) or "").strip()
    return int(raw) if raw.isdigit() and 0 < int(raw) <= 60 else DEFAULT_DAYS


def switch(turn_on, keep_days=None):
    """The clinic's choice. Turning it on starts the list from now."""
    from app.models import Setting

    was = Setting.get(SETTING) == "1"
    Setting.set(SETTING, "1" if turn_on else "0")
    if turn_on and not was:
        Setting.set(SINCE, datetime.utcnow().isoformat())
    if keep_days is not None:
        raw = str(keep_days).strip()
        if raw.isdigit() and 0 < int(raw) <= 60:
            Setting.set(DAYS, raw)


def _since():
    from app.models import Setting

    try:
        return datetime.fromisoformat(Setting.get(SINCE) or "")
    except ValueError:
        return datetime.utcnow()


# ------------------------------------------------------------ the states --
def released(order):
    """The laboratory has let this result go."""
    from app.utils import lab_release

    if order.kind != "lab" or order.status != "resulted":
        return False
    return order.verified_at is not None or not lab_release.required()


def hold_reason(order):
    """``critical`` / ``sensitive`` — why this result waits for a call."""
    if order.critical_at is not None:
        return "critical"
    if order.investigation is not None and order.investigation.sensitive:
        return "sensitive"
    return None


def held(order):
    return hold_reason(order) is not None and order.family_called_at is None


def _mine(query, doctor_id):
    from app.models import Visit, VisitInvestigation

    if not doctor_id:
        return query
    return (query.join(Visit, VisitInvestigation.visit_id == Visit.id)
            .filter(db.or_(VisitInvestigation.ordered_by == doctor_id,
                           Visit.doctor_id == doctor_id)))


def _released_since():
    from sqlalchemy.orm import selectinload

    from app.models import VisitInvestigation
    from app.utils import lab_release

    query = (VisitInvestigation.query
             .options(selectinload(VisitInvestigation.patient),
                      selectinload(VisitInvestigation.investigation))
             .filter(VisitInvestigation.kind == "lab",
                     VisitInvestigation.status == "resulted",
                     VisitInvestigation.resulted_at >= _since()))
    if lab_release.required():
        query = query.filter(VisitInvestigation.verified_at.isnot(None))
    return query


def to_see(doctor_id=None, limit=200):
    """Released results the doctor has not seen yet, oldest first."""
    from app.models import VisitInvestigation

    if not on():
        return []
    query = _mine(_released_since(), doctor_id).filter(
        VisitInvestigation.doctor_seen_at.is_(None))
    return query.order_by(VisitInvestigation.resulted_at).limit(limit).all()


def to_call(doctor_id=None, limit=200):
    """Seen, and held for a call to the family that has not been made."""
    from app.models import VisitInvestigation

    if not on():
        return []
    rows = (_mine(_released_since(), doctor_id)
            .filter(VisitInvestigation.doctor_seen_at.isnot(None),
                    VisitInvestigation.family_called_at.is_(None))
            .order_by(VisitInvestigation.resulted_at).limit(limit).all())
    return [r for r in rows if hold_reason(r)]


def to_see_count(doctor_id=None):
    return len(to_see(doctor_id)) + len(to_call(doctor_id))


def by_child(rows):
    """``[(patient, [orders])]`` in the order the rows came."""
    out = {}
    for row in rows:
        out.setdefault(row.patient_id, (row.patient, []))[1].append(row)
    return list(out.values())


# ------------------------------------------------------------- shares --
def _same_child(orders):
    ids = {o.patient_id for o in orders}
    if len(ids) != 1:
        raise ShareError("one_child")
    return orders[0].patient


def _already_with_family(orders):
    """The orders already sent to the family."""
    from app.models import ResultShare
    from app.models.result_share import FAMILY

    patient_id = orders[0].patient_id
    sent = set()
    for share in ResultShare.query.filter_by(patient_id=patient_id, audience=FAMILY):
        sent.update(share.order_ids or [])
    return {o.id for o in orders if o.id in sent}


def online():
    """Can a phone outside the clinic reach this program? Only when the
    clinic gave its public address (a domain or a tunnel — WhatsApp
    settings). Without it a link points into the clinic's own network."""
    from app.utils import whatsapp as wa

    return bool(wa.get_config().get("public_base"))


def _link(token):
    from flask import url_for

    from app.utils import whatsapp as wa

    base = wa.get_config().get("public_base")
    path = url_for("labs.result_link", token=token)
    return f"{base}{path}" if base else url_for("labs.result_link", token=token,
                                                  _external=True)


def _clinic_name():
    from app.models import Setting

    return Setting.get("clinic_name_ar") or Setting.get("clinic_name") or ""


def sheet(orders, patient, lang="ar", open_lang=None):
    """The report as one self-contained page — the link's page, the file,
    and what prints — **in Arabic and in English**, one shown and a button
    for the other («ممكن الأهل عربي أو إنجليزي»). ``open_lang`` is the one
    it opens in; the phone remembers a switch."""
    from flask import g, render_template

    from app.i18n import available_languages, get_direction
    from app.utils import lab_cards
    from app.utils.clock import local_now

    langs = [code for code in ("ar", "en") if code in available_languages()] or [lang]
    open_lang = open_lang if open_lang in langs else (lang if lang in langs else langs[0])
    printed = local_now()
    saved = (getattr(g, "lang", None), getattr(g, "direction", None))
    bodies = []
    try:
        for code in langs:
            g.lang, g.direction = code, get_direction(code)
            cards, summary = lab_cards.cards(orders, code)
            bodies.append((code, g.direction, render_template(
                "labs/_result_sheet_body.html", patient=patient, cards=cards,
                summary=summary, clinic_name=_clinic_name(), printed_at=printed)))
    finally:
        g.lang, g.direction = saved
    from app.i18n import translate

    # The doctype first, so a phone opening the file renders it as a page.
    return render_template("labs/result_sheet.html", bodies=bodies,
                           open_lang=open_lang,
                           title=f"{translate('lab_share.sheet_title')} — "
                                 f"{patient.display_name(open_lang)}").lstrip()


def opens_in(audience):
    """The family reads it first in Arabic, the referring doctor in English —
    the language reports between doctors are written in."""
    from app.models.result_share import DOCTOR

    return "en" if audience == DOCTOR else "ar"


def file_name(share):
    stamp = (share.created_at or datetime.utcnow()).strftime("%Y%m%d")
    number = "".join(ch for ch in (share.patient.patient_number or "") if ch.isalnum())
    return f"lab-result-{number or share.patient_id}-{stamp}.html"


def send(orders, user, audience="family", doctor=None, lang="ar"):
    """One link for these results of one child, sent on WhatsApp. Returns
    ``(share, message_log)``. The caller commits."""
    from app.models import ActivityLog, ResultShare, Setting
    from app.models.result_share import DOCTOR, FAMILY
    from app.utils import whatsapp as wa

    orders = [o for o in orders if o is not None]
    if not orders:
        raise ShareError("nothing")
    patient = _same_child(orders)
    if any(not released(o) for o in orders):
        raise ShareError("not_released")
    if any(held(o) for o in orders):
        raise ShareError("held")
    if audience == FAMILY:
        if any(o.doctor_seen_at is None for o in orders):
            raise ShareError("not_seen")
        fresh = _already_with_family(orders)
        orders = [o for o in orders if o.id not in fresh]
        if not orders:
            raise ShareError("already_sent")
        phone = patient.contact_phone
        template = "lab_result"
    elif audience == DOCTOR:
        if doctor is None or not (doctor.phone or "").strip():
            raise ShareError("no_doctor")
        phone = doctor.phone
        template = "lab_result_doctor"
    else:
        raise ShareError("nothing")
    if not phone:
        raise ShareError("no_phone")

    from app.models.result_share import FILE, LINK
    from app.utils import lab_cards

    mode = LINK if online() else FILE
    if mode == FILE:
        template += "_file"
    share = ResultShare(token=secrets.token_urlsafe(24), patient_id=patient.id,
                        order_ids=[o.id for o in orders], audience=audience,
                        mode=mode, external_doctor_id=getattr(doctor, "id", None),
                        to_phone=phone, created_by=getattr(user, "id", None),
                        expires_at=datetime.utcnow() + timedelta(days=days()))
    db.session.add(share)
    db.session.flush()
    body = wa.render(wa.template_body(template), {
        "patient": patient.display_name(lang),
        "first_name": (patient.display_name(lang) or "").split(" ")[0],
        "doctor": getattr(doctor, "name", "") or "",
        "clinic": _clinic_name(),
        "link": _link(share.token) if mode == LINK else "",
        "days": days(),
        "numbers": lab_cards.numbers_text(orders, lang) if audience == DOCTOR else "",
    })
    family_id = patient.id if audience == FAMILY else None
    if mode == LINK:
        log = wa.send(body, phone, patient_id=family_id,
                      user_id=getattr(user, "id", None), template_type=template,
                      ignore_window=True)
    else:
        log = wa.send_document(body, phone,
                               sheet(orders, patient, lang, opens_in(audience)).encode("utf-8"),
                               file_name(share), patient_id=family_id,
                               user_id=getattr(user, "id", None), template_type=template)
    db.session.flush()
    share.message_id = log.id
    ActivityLog.record("lab.result_sent", user_id=getattr(user, "id", None),
                       entity="lab_result_share", entity_id=share.id,
                       detail=f"{audience} {mode} orders={share.order_ids}")
    return share, log


def see(orders, user, at=None, lang="ar"):
    """The doctor has seen these results. Those not held for a call go to
    the family. Returns ``(share or None, log or None, held orders)``."""
    from app.utils.lab_results import reads_results

    if not reads_results(user):
        raise ShareError("not_a_doctor")
    orders = [o for o in orders if o is not None and released(o)]
    if not orders:
        raise ShareError("nothing")
    _same_child(orders)
    now = at or datetime.utcnow()
    for order in orders:
        if order.doctor_seen_at is None:
            order.doctor_seen_at = now
            order.doctor_seen_by = user.id
    waiting = [o for o in orders if held(o)]
    going = [o for o in orders if not held(o)]
    share = log = None
    if going:
        try:
            share, log = send(going, user, lang=lang)
        except ShareError as err:
            if str(err) not in ("no_phone", "already_sent"):
                raise
    return share, log, waiting


def called(order, user, note=None, at=None, lang="ar"):
    """The doctor spoke to the family about a held result; now it may go."""
    from app.utils.lab_results import reads_results

    if not reads_results(user):
        raise ShareError("not_a_doctor")
    if order is None or not hold_reason(order):
        raise ShareError("nothing")
    order.family_called_at = at or datetime.utcnow()
    order.family_called_by = user.id
    order.family_called_note = (note or "").strip()[:200] or None
    if order.doctor_seen_at is None:
        order.doctor_seen_at, order.doctor_seen_by = order.family_called_at, user.id
    try:
        return send([order], user, lang=lang)
    except ShareError as err:
        if str(err) in ("no_phone", "already_sent"):
            return None, None
        raise


def for_order(order):
    """Every link that carried this order, newest first."""
    from app.models import ResultShare

    return [s for s in (ResultShare.query.filter_by(patient_id=order.patient_id)
                        .order_by(ResultShare.created_at.desc()).all())
            if order.id in (s.order_ids or [])]


def referring_doctors():
    """The outside doctors on the clinic's list who have a phone."""
    from app.models import ExternalDoctor

    return [d for d in ExternalDoctor.query.filter_by(active=True)
            .order_by(ExternalDoctor.name).all() if (d.phone or "").strip()]


# ------------------------------------------------------- the open link --
def by_token(token):
    from app.models import ResultShare

    token = (token or "").strip()
    if not token or len(token) > 48:
        return None
    return ResultShare.query.filter_by(token=token).first()


def state(share):
    if share is None:
        return "gone"
    if share.expired:
        return "expired"
    if share.locked:
        return "locked"
    return "ok"


def _answer(patient):
    return patient.date_of_birth


def check(share, raw):
    """Is ``raw`` the child's date of birth? Counts the answer either way."""
    if state(share) != "ok":
        return False
    try:
        given = date.fromisoformat((raw or "").strip())
    except ValueError:
        given = None
    if given is not None and given == _answer(share.patient):
        share.opens = (share.opens or 0) + 1
        if share.opened_at is None:
            share.opened_at = datetime.utcnow()
        return True
    share.failures = (share.failures or 0) + 1
    return False


def orders_of(share):
    """The orders the link carries, still this child's and still released."""
    from app.models import VisitInvestigation

    ids = [i for i in (share.order_ids or []) if isinstance(i, int)]
    rows = (VisitInvestigation.query.filter(VisitInvestigation.id.in_(ids))
            .order_by(VisitInvestigation.created_at, VisitInvestigation.id).all()) if ids else []
    return [r for r in rows if r.patient_id == share.patient_id and released(r)]
