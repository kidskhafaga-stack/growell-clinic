"""Questionnaires the parent, the teacher or the child fill themselves —
ASSESSMENTS_PLAN.md ت-٤.

The owner: *«الاستبيانات اللي الأهل والمدرس بيملوها بنفسهم … ياريت نعمل ده
برده»* — with Vanderbilt, M-CHAT and SDQ waiting on whether using them inside
a program is allowed.

**It is not, without the owner's permission.** Vanderbilt belongs to the AAP
and NICHQ; the M-CHAT's authors ask anybody putting it into software for
others to write to them; youthinmind does not allow an electronic SDQ without
its agreement. So the program follows the road the licensed visit tools
(c-ACT, ACT — ``utils/visit_scores``) already take:

* the program carries each questionnaire's **shape** only
  (``data/questionnaires.json``): how many items, each choice's points, which
  items are reversed, which items make which part and how the part is
  counted — from the tool's published scoring instructions, and checked by
  tests against the score boxes the assessment form already had;
* the **words** — every question and every choice — the clinic types from its
  own licensed copy, with whose permission it uses them and the copyright
  line the owner asks to be printed;
* a **doctor opens it**; until then it appears nowhere.

What happens then:

* the specialist hands it over from the assessment: on the clinic's tablet,
  as a WhatsApp link (when the clinic can be reached from outside), or on
  paper that is typed in afterwards;
* whoever fills it sees the questions only — never a score;
* the program adds up by the shape; a part with too few answers stays empty
  (the SDQ alone says how many may be missing);
* **the scores reach the assessment only when the specialist presses «put
  the scores in»**, still a draft for the doctor to approve.
"""
import json
import os
import secrets
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from app.extensions import db

_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "questionnaires.json")
INFORMANTS = ("parent", "teacher", "self")
MODES = ("tablet", "link", "paper")
RULES = ("sum", "mean", "count_at_least", "count_equal", "parts")
#: Hours a tablet questionnaire stays open — it is filled in the clinic.
TABLET_HOURS = 24
#: A typing guard on the clinic's own lines, not a clinical figure.
MAX_TEXT = 600


class QuestionnaireError(ValueError):
    """A refusal with a key the screen can name (``asm_q.err_<key>``)."""


# ------------------------------------------------------------ the shapes --
@lru_cache(maxsize=1)
def _catalogue():
    with open(_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def shapes():
    return _catalogue()["questionnaires"]


def shape(key):
    return shapes().get(key)


def items_of(sh):
    """``[{"n": 1, "scale": "freq"}, …]`` in order."""
    out = []
    for scale, first, last in sh["item_scales"]:
        out.extend({"n": n, "scale": scale} for n in range(first, last + 1))
    return out


def option_count(sh, scale):
    return len(sh["scales"][scale])


def ranges(numbers):
    """``[1, 2, 3, 7]`` → ``"1–3، 7"``-style runs, for saying which items."""
    nums = sorted(numbers)
    runs, start = [], None
    for i, n in enumerate(nums):
        if start is None:
            start = n
        if i + 1 == len(nums) or nums[i + 1] != n + 1:
            runs.append(str(start) if start == n else f"{start}–{n}")
            start = None
    return runs


def scale_items(sh, scale):
    return [it["n"] for it in items_of(sh) if it["scale"] == scale]


# ------------------------------------------------------- the clinic's words --
def text_for(key):
    from app.models import QuestionnaireText

    return QuestionnaireText.query.filter_by(key=key).first()


def ready_langs(sh, text):
    """The languages the clinic has typed every question and every choice in."""
    if text is None:
        return []
    items = text.items or []
    options = text.options or {}
    out = []
    for lang in ("ar", "en"):
        if len(items) != len(items_of(sh)) or not all((i.get(lang) or "").strip() for i in items):
            continue
        if all(len(options.get(s) or []) == option_count(sh, s)
               and all((o.get(lang) or "").strip() for o in options[s])
               for s in sh["scales"]):
            out.append(lang)
    return out


def blockers(key, text=None):
    """What still stands between this questionnaire and being sent."""
    sh = shape(key)
    text = text_for(key) if text is None else text
    out = []
    if not ready_langs(sh, text):
        out.append("wording")
    if not (getattr(text, "holder", None) or "").strip():
        out.append("holder")
    if not (getattr(text, "ref", None) or "").strip():
        out.append("ref")
    if sh.get("notice_required") and not (getattr(text, "notice", None) or "").strip():
        out.append("notice")
    return out


def is_open(key):
    text = text_for(key)
    return bool(text and text.status == "active" and not blockers(key, text))


def _lines(raw):
    return [line.strip() for line in (raw or "").replace("\r\n", "\n").split("\n") if line.strip()]


def save_text(key, data, user):
    """The clinic's words from the form. Returns the problems (``[]`` when
    saved). Changing an open questionnaire closes it until a doctor reopens it."""
    from app.models import ActivityLog, QuestionnaireText

    sh = shape(key)
    if sh is None:
        raise QuestionnaireError("no_kind")
    want = len(items_of(sh))
    problems = []
    lines = {lang: _lines(data.get(f"items_{lang}")) for lang in ("ar", "en")}
    for lang, got in lines.items():
        if got and len(got) != want:
            problems.append(f"count_{lang}")
        if any(len(line) > MAX_TEXT for line in got):
            problems.append(f"long_{lang}")
    if problems:
        return problems
    text = text_for(key)
    if text is None:
        text = QuestionnaireText(key=key, items=[], options={})
        db.session.add(text)
    before = (text.items, text.options, text.notice, text.intro_ar, text.intro_en)
    text.items = [{"ar": lines["ar"][i] if lines["ar"] else "",
                   "en": lines["en"][i] if lines["en"] else ""} for i in range(want)] \
        if (lines["ar"] or lines["en"]) else []
    text.options = {s: [{"ar": (data.get(f"opt_{s}_{i}_ar") or "").strip()[:120],
                         "en": (data.get(f"opt_{s}_{i}_en") or "").strip()[:120]}
                        for i in range(option_count(sh, s))] for s in sh["scales"]}
    text.holder = (data.get("holder") or "").strip()[:200] or None
    text.ref = (data.get("ref") or "").strip()[:300] or None
    text.notice = (data.get("notice") or "").strip()[:1000] or None
    text.intro_ar = (data.get("intro_ar") or "").strip()[:2000] or None
    text.intro_en = (data.get("intro_en") or "").strip()[:2000] or None
    text.updated_by = user.id
    changed = before != (text.items, text.options, text.notice, text.intro_ar, text.intro_en)
    if text.status == "active" and changed:
        text.status = "draft"
        text.approved_by = text.approved_at = text.approval_note = None
    ActivityLog.record("questionnaire.words", user_id=user.id, entity="questionnaire",
                       detail=key)
    return []


def activate(key, user, note=None):
    """A doctor opens it — only once nothing blocks it."""
    from app.models import ActivityLog
    from app.utils import assessments as asm

    if not asm.may_approve(user):
        raise QuestionnaireError("not_a_doctor")
    text = text_for(key)
    if text is None or blockers(key, text):
        raise QuestionnaireError("blocked")
    text.status = "active"
    text.approved_by, text.approved_at = user.id, datetime.utcnow()
    text.approval_note = (note or "").strip()[:255] or None
    ActivityLog.record("questionnaire.open", user_id=user.id, entity="questionnaire",
                       detail=key)
    return text


def switch_off(key, user):
    from app.models import ActivityLog

    text = text_for(key)
    if text is None:
        raise QuestionnaireError("no_kind")
    text.status = "off"
    ActivityLog.record("questionnaire.off", user_id=user.id, entity="questionnaire",
                       detail=key)
    return text


# ----------------------------------------------------- what is sent out --
def build_form(key):
    """The questionnaire as it is sent: the shape with the clinic's words in
    it, kept on the request so a later change of wording rewrites nothing."""
    sh = shape(key)
    text = text_for(key)
    langs = ready_langs(sh, text)
    return {
        "key": key, "tool": sh["tool"], "name_ar": sh["name_ar"], "name_en": sh["name_en"],
        "langs": langs, "intro_ar": text.intro_ar or "", "intro_en": text.intro_en or "",
        "notice": text.notice or "", "holder": text.holder or "",
        "scales": {s: [{"v": v, "ar": text.options[s][i]["ar"], "en": text.options[s][i]["en"]}
                       for i, v in enumerate(points)] for s, points in sh["scales"].items()},
        "items": [dict(it, ar=text.items[i]["ar"], en=text.items[i]["en"])
                  for i, it in enumerate(items_of(sh))],
        "reverse": list(sh.get("reverse") or []),
        "parts": [dict(p) for p in sh["parts"]],
    }


def offered(row):
    """The open questionnaires for the tools on this assessment's form:
    ``[(key, shape)]``."""
    tools = set((row.form.get("tool_defs") or {}).keys())
    return [(k, sh) for k, sh in shapes().items() if sh["tool"] in tools and is_open(k)]


def age_outside(sh, patient, on):
    """Whether the child's age that day is outside the ages the tool was
    built for — said on the screen, never a refusal."""
    from app.utils import assessments as asm

    months = asm.months_on(patient, on)
    low, high = sh.get("ages_months") or (None, None)
    return months is not None and low is not None and not (low <= months <= high)


# ---------------------------------------------------------- the scoring --
def _round_half_up(x, places=0):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))


def points(form, answers):
    """``{item number: points after reversing}`` for every answered item."""
    scales = {s: [o["v"] for o in opts] for s, opts in form["scales"].items()}
    reverse = set(form.get("reverse") or [])
    out = {}
    for it in form["items"]:
        raw = (answers or {}).get(str(it["n"]))
        if raw is None:
            continue
        pts = scales[it["scale"]]
        out[it["n"]] = (min(pts) + max(pts) - raw) if it["n"] in reverse else raw
    return out


def score(form, answers):
    """``{part: value}``: the arithmetic of the tool's scoring instructions on
    what was answered; ``None`` for a part with too few answers."""
    got = points(form, answers)
    out = {}
    for part in form["parts"]:
        rule = part["rule"]
        if rule == "parts":
            values = [out.get(k) for k in part["parts"]]
            out[part["key"]] = None if any(v is None for v in values) else sum(values)
            continue
        items = part["items"]
        have = [got[n] for n in items if n in got]
        complete = len(have) == len(items)
        if rule == "sum":
            if complete:
                out[part["key"]] = sum(have)
            elif part.get("prorate_min") and len(have) >= part["prorate_min"]:
                out[part["key"]] = int(_round_half_up(sum(have) / len(have) * len(items)))
            else:
                out[part["key"]] = None
        elif not complete:
            out[part["key"]] = None
        elif rule == "mean":
            out[part["key"]] = _round_half_up(sum(have) / len(have), 2)
        elif rule == "count_at_least":
            out[part["key"]] = sum(1 for v in have if v >= part["n"])
        elif rule == "count_equal":
            out[part["key"]] = sum(1 for v in have if v == part["n"])
    return out


def read_answers(form, data):
    """The posted choices, each checked against its item's own points."""
    scales = {s: {o["v"] for o in opts} for s, opts in form["scales"].items()}
    out = {}
    for it in form["items"]:
        raw = (data.get(f"i_{it['n']}") or "").strip()
        if raw == "":
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if value in scales[it["scale"]]:
            out[str(it["n"])] = value
    return out


# ------------------------------------------------------------ requests --
def _days(mode):
    from app.utils import lab_share

    if mode == "tablet":
        return timedelta(hours=TABLET_HOURS)
    return timedelta(days=lab_share.days())


def link_for(req):
    from flask import url_for

    from app.utils import whatsapp as wa

    base = wa.get_config().get("public_base")
    path = url_for("assessments.questionnaire_fill", token=req.token)
    return f"{base}{path}" if base else url_for("assessments.questionnaire_fill",
                                                 token=req.token, _external=True)


def create(row, key, user, informant="parent", mode="tablet", respondent=None,
           phone=None, lang="ar"):
    """Hand one questionnaire over for this assessment. A link goes out on
    WhatsApp at once; the caller commits."""
    from app.models import ActivityLog, QuestionnaireRequest
    from app.utils import assessments as asm
    from app.utils import lab_share

    if not asm.may_write(user):
        raise QuestionnaireError("not_allowed")
    if row.status == "approved":
        raise QuestionnaireError("approved")
    sh = shape(key)
    if sh is None or (key, sh) not in offered(row):
        raise QuestionnaireError("not_open")
    if informant not in sh["informants"]:
        raise QuestionnaireError("informant")
    if mode not in MODES:
        raise QuestionnaireError("mode")
    if mode == "link":
        if not lab_share.online():
            raise QuestionnaireError("offline")
        phone = (phone or "").strip() or (row.patient.contact_phone if row.patient else None)
        if not phone:
            raise QuestionnaireError("no_phone")
    form = build_form(key)
    lang = lang if lang in form["langs"] else form["langs"][0]
    req = QuestionnaireRequest(
        token=secrets.token_urlsafe(24), key=key, assessment_id=row.id,
        patient_id=row.patient_id, informant=informant, mode=mode,
        respondent=(respondent or "").strip()[:120] or None,
        to_phone=phone if mode == "link" else None, lang=lang, form=form,
        created_by=user.id, expires_at=datetime.utcnow() + _days(mode))
    db.session.add(req)
    db.session.flush()
    if mode == "link":
        _send(req, user)
    ActivityLog.record("questionnaire.request", user_id=user.id, entity="questionnaire_request",
                       entity_id=req.id, detail=f"{key} {informant} {mode} assessment={row.id}")
    return req


def _send(req, user):
    from app.utils import lab_share
    from app.utils import whatsapp as wa

    patient = req.patient
    lang = req.lang
    body = wa.render(wa.template_body("questionnaire_link"), {
        "patient": patient.display_name(lang),
        "first_name": (patient.display_name(lang) or "").split(" ")[0],
        "questionnaire": req.form.get(f"name_{lang}") or req.form["name_ar"],
        "clinic": lab_share._clinic_name(),
        "link": link_for(req),
        "days": lab_share.days(),
    })
    log = wa.send(body, req.to_phone, patient_id=patient.id, user_id=user.id,
                  template_type="questionnaire_link", ignore_window=True)
    db.session.flush()
    req.message_id = log.id
    return log


def by_token(token):
    from app.models import QuestionnaireRequest

    token = (token or "").strip()
    if not token or len(token) > 48:
        return None
    return QuestionnaireRequest.query.filter_by(token=token).first()


def for_assessment(row):
    from app.models import QuestionnaireRequest

    return (QuestionnaireRequest.query.filter_by(assessment_id=row.id)
            .order_by(QuestionnaireRequest.id.desc()).all())


def answer(req, data, user=None):
    """Keep what was answered and what it adds up to. ``user`` is the member
    of staff typing a paper in; nobody when the respondent filled it."""
    from app.models import ActivityLog

    if not req.answerable:
        raise QuestionnaireError("closed")
    req.answers = read_answers(req.form, data)
    req.scores = score(req.form, req.answers)
    req.status = "done"
    req.answered_at = datetime.utcnow()
    if user is not None:
        req.entered_by = user.id
    ActivityLog.record("questionnaire.answered", user_id=getattr(user, "id", None),
                       entity="questionnaire_request", entity_id=req.id,
                       detail=f"{req.key} {len(req.answers)}/{len(req.form['items'])}")
    return req


def use(req, user):
    """The specialist puts the scores into the assessment — still a draft."""
    from app.models import ActivityLog
    from app.utils import assessments as asm

    row = req.assessment
    if not asm.may_write(user):
        raise QuestionnaireError("not_allowed")
    if row.status == "approved":
        raise QuestionnaireError("approved")
    if req.status != "done":
        raise QuestionnaireError("not_answered")
    tool = req.form["tool"]
    answers = dict(row.answers or {})
    tools = dict(answers.get("tools") or {})
    values = dict(tools.get(tool) or {})
    fields = {f["key"] for f in (row.form.get("tool_defs") or {}).get(tool, {}).get("fields") or []}
    for part in req.form["parts"]:
        value = (req.scores or {}).get(part["key"])
        if part.get("field") in fields and value is not None:
            values[part["field"]] = value
    tools[tool] = values
    answers["tools"] = tools
    row.answers = answers
    req.status, req.used_by, req.used_at = "used", user.id, datetime.utcnow()
    ActivityLog.record("questionnaire.used", user_id=user.id, entity="questionnaire_request",
                       entity_id=req.id, detail=f"assessment={row.id}")
    return row


def cancel(req, user):
    from app.models import ActivityLog
    from app.utils import assessments as asm

    if not asm.may_write(user):
        raise QuestionnaireError("not_allowed")
    if req.status != "open":
        raise QuestionnaireError("closed")
    req.status = "cancelled"
    ActivityLog.record("questionnaire.cancel", user_id=user.id, entity="questionnaire_request",
                       entity_id=req.id)
    return req


def answered_count(req):
    return len(req.answers or {})
