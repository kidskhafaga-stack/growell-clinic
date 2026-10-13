"""The hospital and its community — GAHAR CAI. Models in
``app/models/community.py``.

**The rules the records keep:**

* a partner is not on the list without the channel the hospital reaches
  them by (CAI.02 ev. 2);
* a needs assessment answers all five needs (CAI.03 b i–v), names whom it
  was done with, and plans the services on it (c); the next is due two years
  after (CAI.06 ev. 2 — the standard's figure), and one not yet shared with
  the governing body or the partners shows (CAI.03 ev. 3);
* an activity names the need it answers (CAI.04 ev. 3); satisfaction is the
  satisfied out of those asked, never more than were asked (CAI.06 ev. 3);
* an advertisement is reviewed before it goes out; one that is not accurate
  or not within the codes is not published, and carries what was done
  (CAI.07 ev. 2, 4).
"""
from app.extensions import db
from app.models.community import (ACTIVITY_KINDS, ASSESS_EVERY_MONTHS, NEEDS, PARTNER_KINDS,
                                  Advertisement, CommunityActivity, CommunityPartner, NeedsAssessment)
from app.utils.facility_safety import FacilityError, _day, _int, _list, _text


def _today():
    from app.utils.clock import local_today

    return local_today()


def _partners(form, key="partners"):
    ids = {int(v) for v in _list(form, key) if str(v).isdigit()}
    return CommunityPartner.query.filter(CommunityPartner.id.in_(ids)).all() if ids else []


def save_partner(form):
    name, channel = _text(form.get("name"), 160), _text(form.get("channel"), 200)
    kind = form.get("kind")
    if not name or not channel or kind not in PARTNER_KINDS:
        raise FacilityError("need_partner")
    row = CommunityPartner(name=name, kind=kind, channel=channel, contact=_text(form.get("contact"), 160))
    db.session.add(row)
    db.session.flush()
    return row


def contacted(partner, form):
    partner.last_contact_on = _day(form.get("on"))
    db.session.flush()
    return partner


def save_assessment(user, form, file=None):
    population, sources = _text(form.get("population")), _text(form.get("sources"))
    plan = _text(form.get("services_plan"))
    if not population or not sources or not plan:
        raise FacilityError("need_assessment_text")
    findings = {n: _text(form.get(f"need_{n}")) for n in NEEDS}
    if not all(findings.values()):
        raise FacilityError("need_all_needs")
    partners = _partners(form)
    if not partners:
        raise FacilityError("need_partners")
    row = NeedsAssessment(done_on=_day(form.get("done_on")), population=population, sources=sources,
                          findings=findings, services_plan=plan, file=file,
                          shared_board_on=_day(form.get("shared_board_on"), need=False),
                          shared_partners_on=_day(form.get("shared_partners_on"), need=False),
                          recorded_by=getattr(user, "id", None))
    row.partners = partners
    db.session.add(row)
    db.session.flush()
    return row


def share(assessment, form):
    if form.get("shared_board_on"):
        assessment.shared_board_on = _day(form.get("shared_board_on"))
    if form.get("shared_partners_on"):
        assessment.shared_partners_on = _day(form.get("shared_partners_on"))
    db.session.flush()
    return assessment


def next_assessment(today=None):
    from app.utils.preparedness import add_months

    last = NeedsAssessment.query.order_by(NeedsAssessment.done_on.desc()).first()
    if last is None:
        return {"last": None, "due": None, "overdue": True}
    due = add_months(last.done_on, ASSESS_EVERY_MONTHS)
    return {"last": last, "due": due, "overdue": due < (today or _today())}


def save_activity(user, form):
    kind = form.get("kind")
    title = _text(form.get("title"), 200)
    if kind not in ACTIVITY_KINDS or not title:
        raise FacilityError("need_activity")
    need = _text(form.get("need"), 255)
    if kind != "peer_support" and not need:
        raise FacilityError("need_need")
    surveyed, satisfied = _int(form.get("surveyed")), _int(form.get("satisfied"))
    if satisfied is not None and (surveyed is None or satisfied > surveyed):
        raise FacilityError("bad_satisfaction")
    row = CommunityActivity(held_on=_day(form.get("held_on")), kind=kind, title=title, need=need,
                            initiative=_text(form.get("initiative"), 200),
                            attendance=_int(form.get("attendance")), surveyed=surveyed, satisfied=satisfied,
                            learnt=_text(form.get("learnt")), recorded_by=getattr(user, "id", None))
    row.partners = _partners(form)
    db.session.add(row)
    db.session.flush()
    return row


def activities_board(year=None, today=None):
    today = today or _today()
    year = year or today.year
    from datetime import date

    rows = (CommunityActivity.query.filter(CommunityActivity.held_on >= date(year, 1, 1),
                                           CommunityActivity.held_on <= date(year, 12, 31))
            .order_by(CommunityActivity.held_on.desc()).all())
    asked = sum(r.surveyed or 0 for r in rows if r.satisfied is not None)
    happy = sum(r.satisfied or 0 for r in rows if r.satisfied is not None)
    return {"year": year, "rows": rows, "asked": asked, "satisfied": happy,
            "rate": round(100 * happy / asked) if asked else None,
            "initiatives": [r for r in rows if r.initiative],
            "accreditation": [r for r in rows if r.kind in ("accreditation", "peer_support")]}


def review_ad(user, form):
    title, channel, content = (_text(form.get("title"), 200), _text(form.get("channel"), 120),
                               _text(form.get("content")))
    reviewer = _text(form.get("reviewed_by"), 160)
    compliant = form.get("compliant")
    if not title or not channel or not content or not reviewer or compliant not in ("yes", "no"):
        raise FacilityError("need_ad")
    action = _text(form.get("action"))
    published = _day(form.get("published_on"), need=False, future_ok=True)
    if compliant == "no":
        if not action:
            raise FacilityError("need_action")
        if published is not None:
            raise FacilityError("not_compliant")
    row = Advertisement(title=title, channel=channel, content=content, reviewed_on=_day(form.get("reviewed_on")),
                        reviewed_by=reviewer, compliant=compliant == "yes", published_on=published,
                        action=action, recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def board(today=None):
    today = today or _today()
    partners = CommunityPartner.query.filter_by(is_active=True).order_by(CommunityPartner.name).all()
    assessments = NeedsAssessment.query.order_by(NeedsAssessment.done_on.desc()).all()
    return {"partners": partners, "assessments": assessments, "next": next_assessment(today),
            "unshared": [a for a in assessments if not a.shared_board_on or not a.shared_partners_on],
            "ads": Advertisement.query.order_by(Advertisement.reviewed_on.desc()).limit(30).all()}


__all__ = ["activities_board", "board", "contacted", "next_assessment", "review_ad", "save_activity",
           "save_assessment", "save_partner", "share"]
