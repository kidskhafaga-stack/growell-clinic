"""The survey as a path: which question comes next, given the answers so far.

The public page walks it one question at a time in the browser; the server
walks **the same rules again** when the answers arrive (:func:`save`), and
keeps only what lies on the path. So an answer to "what went wrong with the
bill?" from a family who gave the bill five stars is not kept — whether it
came from an old page, a page without JavaScript, or somebody typing a URL.

Rules, in one place (the page's script mirrors them):

* the survey starts at the first question that is not a branch question;
* after a question, a jump written for that answer's group wins, if it points
  forward to a question on this survey, or to the end;
* otherwise the next question in order that is not a branch question;
* a question not asked about this part of the clinic is not on the survey.
"""
import json

from app.extensions import db
from app.models.survey_question import BUILT_IN, END, KINDS, SurveyQuestion

BUILT_IN_ORDER = ("doctor", "service", "finance", "nps", "comment")
#: Answers kept per question, and in all.
MAX_TEXT = 2000


def ensure_seeded():
    """One row per built-in question, in the order the page always had.
    Returns how many were made."""
    have = {k for (k,) in db.session.query(SurveyQuestion.key)
            .filter(SurveyQuestion.builtin.is_(True)).all()}
    made = 0
    for order, key in enumerate(BUILT_IN_ORDER):
        if key in have:
            continue
        db.session.add(SurveyQuestion(key=key, builtin=True,
                                      kind=BUILT_IN[key][0],
                                      sort_order=(order + 1) * 10))
        made += 1
    if made:
        db.session.flush()
    return made


def rows(active_only=True):
    ensure_seeded()
    q = SurveyQuestion.query
    if active_only:
        q = q.filter(SurveyQuestion.is_active.is_(True))
    return q.order_by(SurveyQuestion.sort_order, SurveyQuestion.id).all()


def next_key():
    taken = [k for (k,) in db.session.query(SurveyQuestion.key)
             .filter(SurveyQuestion.key.like("q%")).all()]
    top = max((int(k[1:]) for k in taken if k[1:].isdigit()), default=0)
    return f"q{top + 1}"


# ------------------------------------------------------------ the steps ---
def centre_key_of(fb):
    """The part of the clinic a survey is about: its cost centre, or the
    outpatient clinics for a visit."""
    if fb is not None and getattr(fb, "cost_centre", None) is not None:
        return fb.cost_centre.key
    return "outpatient"


def steps(fb=None, lang="ar"):
    """The questions this survey asks, in order, as plain dicts the page
    and :func:`path` both read."""
    from app.utils.feedback import survey_config

    cfg = survey_config(lang)["questions"]
    here = centre_key_of(fb)
    out = []
    for row in rows():
        if row.builtin:
            meta = cfg.get(row.key)
            if meta is None or not meta["show"]:
                continue
            label, options = meta["label"], []
        else:
            label, options = row.text(lang), row.options(lang)
            if not label or row.kind not in KINDS:
                continue
            if row.kind in ("single", "multi") and not options:
                continue
        if row.centres() and here not in row.centres():
            continue
        out.append({"key": row.key, "kind": row.kind, "builtin": row.builtin,
                    "label": label, "options": options,
                    "branch_only": bool(row.branch_only) and not row.builtin,
                    "jumps": row.jump_map()})
    # A jump may only name a question still on this survey, further on.
    at = {s["key"]: i for i, s in enumerate(out)}
    for i, s in enumerate(out):
        s["jumps"] = {b: to for b, to in s["jumps"].items()
                      if to == END or at.get(to, -1) > i}
    return out


# ------------------------------------------------------------- the rules ---
def bucket(kind, value):
    """The answer group a value falls in, or None."""
    if value is None or value == "":
        return None
    try:
        if kind == "stars":
            n = int(value)
            return "low" if n <= 2 else ("mid" if n == 3 else "high")
        if kind == "nps":
            n = int(value)
            return "low" if n <= 6 else ("mid" if n <= 8 else "high")
    except (TypeError, ValueError):
        return None
    if kind == "yesno":
        return value if value in ("yes", "no") else None
    if kind == "single":
        return value if isinstance(value, str) and value.startswith("o") else None
    return None


def _default_next(all_steps, i):
    j = i + 1
    while j < len(all_steps) and all_steps[j]["branch_only"]:
        j += 1
    return j if j < len(all_steps) else None


def path(all_steps, answers):
    """The keys a family is asked, in order, given ``answers``
    (``{key: raw value}``). Unanswered questions take the default road."""
    at = {s["key"]: i for i, s in enumerate(all_steps)}
    i = _default_next(all_steps, -1)
    out = []
    while i is not None and len(out) <= len(all_steps):
        step = all_steps[i]
        out.append(step["key"])
        to = step["jumps"].get(bucket(step["kind"], answers.get(step["key"])))
        if to == END:
            break
        if to in at and at[to] > i:
            i = at[to]
        else:
            i = _default_next(all_steps, i)
    return out


# ------------------------------------------------------------ the saving ---
def _clamp(value, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _raw(step, form):
    """What the form says for a step, before the path is known."""
    key = step["key"]
    if step["builtin"]:
        field = BUILT_IN[key][1]
        return form.get(field)
    if step["kind"] == "multi":
        return form.getlist(f"a_{key}")
    return form.get(f"a_{key}")


def _clean(step, raw, lang="ar"):
    kind = step["kind"]
    if kind == "stars":
        return _clamp(raw, 1, 5)
    if kind == "nps":
        return _clamp(raw, 0, 10)
    if kind == "yesno":
        return raw if raw in ("yes", "no") else None
    if kind == "text":
        return (raw or "").strip()[:MAX_TEXT] or None
    options = step["options"]
    if kind == "single":
        if isinstance(raw, str) and raw.startswith("o") and raw[1:].isdigit():
            n = int(raw[1:])
            return options[n] if n < len(options) else None
        return None
    if kind == "multi":
        picked = []
        for value in raw or ():
            if isinstance(value, str) and value.startswith("o") and value[1:].isdigit():
                n = int(value[1:])
                if n < len(options) and options[n] not in picked:
                    picked.append(options[n])
        return picked or None
    return None


def save(fb, form, lang="ar"):
    """Write a submitted survey onto ``fb``: the built-in columns, the
    "what bothered you" taps, and the clinic's own questions — each only if
    it lies on the path the answers themselves draw."""
    from app.utils.feedback import clean_concerns

    all_steps = steps(fb, lang)
    raw = {s["key"]: _raw(s, form) for s in all_steps}
    walked = path(all_steps, raw)
    asked = set(walked)
    by_key = {s["key"]: s for s in all_steps}

    def built_in(key, lo, hi):
        return _clamp(raw.get(key), lo, hi) if key in asked else None

    fb.doctor_rating = built_in("doctor", 1, 5)
    fb.service_rating = built_in("service", 1, 5)
    fb.finance_rating = built_in("finance", 1, 5)
    fb.nps = built_in("nps", 0, 10)
    fb.comment = ((raw.get("comment") or "").strip()[:MAX_TEXT] or None
                  if "comment" in asked else None)
    sides = {"doctor": "doctor", "service": "service", "finance": "finance"}
    fb.concerns = clean_concerns(
        [c for c in form.getlist("concern")
         if sides.get(c.partition(":")[0]) in asked])
    answers = {}
    for key in walked:                      # in the order they were asked
        step = by_key[key]
        if step["builtin"]:
            continue
        value = _clean(step, raw.get(key), lang)
        if value is not None:
            # The question as it was asked: reworded later, the answer still
            # reads against the words the family saw.
            answers[key] = {"q": step["label"], "a": value}
    fb.answers = json.dumps(answers, ensure_ascii=False) if answers else None
    return answers


def answers_of(fb):
    try:
        data = json.loads(fb.answers or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


# ------------------------------------------------------------- the builder ---
def problems(lang="ar"):
    """What is wrong with the survey as built, for the builder to say:
    a branch question nothing leads to, and a jump to a question that is not
    further on."""
    out = []
    all_rows = rows()
    order = {r.key: i for i, r in enumerate(all_rows)}
    targets = {to for r in all_rows for to in r.jump_map().values()}
    for i, r in enumerate(all_rows):
        if r.branch_only and not r.builtin and r.key not in targets:
            out.append(("orphan", r.key))
        for to in r.jump_map().values():
            if to != END and order.get(to, -1) <= i:
                out.append(("backwards", r.key))
    return out


def plain_path_length(lang="ar"):
    """How many questions a family with nothing to complain of answers."""
    all_steps = steps(None, lang)
    happy = {}
    for s in all_steps:
        happy[s["key"]] = {"stars": 5, "nps": 10, "yesno": "yes"}.get(s["kind"])
    return len(path(all_steps, happy))


# ------------------------------------------------------------- the reading ---
def summary(feedback_rows, lang="ar"):
    """For each of the clinic's own questions, what families answered:
    counts for choices, the average for stars and scores, a count for text.
    ``feedback_rows`` are ``Feedback`` rows (submitted)."""
    from collections import Counter

    own = [r for r in rows(active_only=False) if not r.builtin]
    out = []
    for q in own:
        values = []
        for fb in feedback_rows:
            got = answers_of(fb).get(q.key)
            if got is not None:
                values.append(got.get("a"))
        if not values:
            continue
        item = {"question": q, "label": q.text(lang), "count": len(values),
                "kind": q.kind}
        if q.kind in ("stars", "nps"):
            nums = [v for v in values if isinstance(v, int)]
            item["avg"] = round(sum(nums) / len(nums), 1) if nums else None
        elif q.kind == "yesno":
            c = Counter(values)
            item["yes"], item["no"] = c.get("yes", 0), c.get("no", 0)
        elif q.kind in ("single", "multi"):
            c = Counter()
            for v in values:
                for one in (v if isinstance(v, list) else [v]):
                    c[one] += 1
            item["choices"] = c.most_common()
        out.append(item)
    return out
