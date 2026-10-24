"""«Ask the reports» — a question in words becomes a report-builder report
(REPORTS_PLAN.md ت-٣).

*«تكتب سؤالك بالعربي … الذكاء الاصطناعي بيحوّل السؤال لتقرير من منشئ
التقارير»*. What holds it together:

* **What leaves the clinic is the question and the builder's own words** —
  the sources, splits, measures and comparisons this person may use — and
  today's date. No record, no child, no figure. A doctor or a payer named in
  the question comes back as the words the question used, and is matched to
  the clinic's own list **here**, so not even the list of doctors is sent.
* **The answer is a builder report, shown with its settings**: the person sees
  what was understood, can change any of it, and saves it if it is right.
  Every value is checked by the builder itself (``report_builder.spec_from``),
  so a reply asking for a source this person may not use, or a field that
  does not exist, falls back to what they may — never further.
* **«Explain the result»** is optional and sends the table — the same totals
  the screen shows, doctors as ``[D1]``… — never a list of children.
* **Its own switch** (``ai_reports_ask``), off until somebody turns it on.
"""
import json
import re
from urllib.parse import urlencode

from werkzeug.datastructures import MultiDict

from app.utils import ai

SETTING = "ai_reports_ask"
MAX_QUESTION = 400

#: What each split and measure means, for the model — the builder's own keys.
DIM_HELP = {
    "month": "calendar month", "quarter": "quarter of the year", "year": "year",
    "day": "day", "weekday": "day of the week",
    "doctor": "the doctor", "appt_type": "booking type (new, followup, consultation, vaccination, procedure, urgent, none)",
    "gender": "the child's sex (male, female)",
    "age": "age group (newborn, infant, toddler, school, adolescent, over)",
    "diagnosis": "the diagnosis", "drug": "the medicine", "drug_class": "the drug class",
    "status": "status (bookings: scheduled, waiting, in_progress, completed, no_show, cancelled; bills: unpaid, partial, paid)",
    "payer_kind": "cash or contract (cash, contract)", "payer": "the payer (insurance company, club…)",
    "payer_type": "the kind of payer", "service": "the billed service",
    "category": "service group (consultation, procedure, vaccination_fee, booking, lab, radiology, other)",
}
MEASURE_HELP = {
    "count": "number of rows (visits, diagnoses, prescribed medicines, bookings, bills or billed lines)",
    "children": "number of different children", "age_m": "the child's age in months",
    "rx": "number of prescriptions", "billed": "bill value (family share + payer share)",
    "family": "the family's share", "payer_share": "the payer's share", "paid": "paid",
    "balance": "still owed", "qty": "quantity",
}
SOURCE_HELP = {
    "visits": "visits to the clinic", "diagnoses": "diagnoses recorded on visits",
    "drugs": "medicines written on prescriptions", "appointments": "bookings and whether they came",
    "bills": "bills (money)", "lines": "billed services, line by line (money)",
}
#: Filters the model may give as the clinic's own keys.
KEYED = {"gender", "age", "payer_kind", "status", "appt_type", "category"}
#: Filters the model gives as the words of the question, matched here.
NAMED = {"doctor", "payer"}

SYSTEM = (
    "You turn a paediatric clinic's question into the settings of its report "
    "builder. Answer with ONE JSON object and nothing else. Use only the "
    "sources, splits, measures and values listed; never invent one. Keys: "
    "src, preset (one of 7, 30, month, 90, year) OR from and to (YYYY-MM-DD), "
    "by, split (optional), m, agg (sum, avg, median, sd, min, max, stats; only "
    "for amounts and ages), vs (prev, year, custom; with from2 and to2 for "
    "custom), filters (an object: a split name to a list of values — for "
    "doctor and payer write the names exactly as the question says them), "
    "q (a word the diagnosis, medicine or service name must contain), and "
    "understood (one short sentence in {language} saying what report this is). "
    "If the question cannot be answered by these reports, return "
    '{{"understood": "<why, in {language}>", "src": null}}.'
)


def enabled():
    from app.models import Setting

    return Setting.get(SETTING) == "1"


def ready():
    return enabled() and ai.is_ready()


def schema(sources, today):
    """The builder, described for the model — only what this person may use."""
    from app.utils.report_builder import AGGS, SOURCES

    lines = [f"Today is {today.isoformat()}.", "Sources:"]
    for key in sources:
        s = SOURCES[key]
        dims = ", ".join(f"{d} ({DIM_HELP.get(d, d)})" for d in s.dims)
        measures = ", ".join(f"{m} ({MEASURE_HELP.get(m, m)})" for m in s.measures)
        lines.append(f"- {key}: {SOURCE_HELP.get(key, key)}. Splits: {dims}. Measures: {measures}. "
                     f"Filters: {', '.join(s.filters) or 'none'}."
                     + (f" Text search q on {s.text_dim}." if s.text_dim else ""))
    lines.append("Statistics (agg): " + ", ".join(AGGS) + ".")
    return "\n".join(lines)


def _json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no json")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


def _norm(text):
    from app.utils.report_builder import _norm as norm

    out = norm(text)
    for prefix in ("د.", "دكتور", "دكتوره", "dr.", "dr"):
        if out.startswith(prefix + " "):
            out = out[len(prefix) + 1:]
    return out.strip()


def _match(names, rows, label):
    """Names from the question → ids of the clinic's own rows; and what did
    not match, said rather than guessed."""
    found, missing = [], []
    for name in names or []:
        want = _norm(str(name))
        if not want:
            continue
        hits = [r.id for r in rows if want in _norm(label(r)) or _norm(label(r)) in want]
        if len(hits) == 1:
            found.append(str(hits[0]))
        else:
            missing.append(str(name))
    return found, missing


def to_args(data, lang="ar"):
    """The model's settings → the builder's own arguments, and the names
    that matched nothing."""
    from app.models import PayerEntity, User

    args = MultiDict()
    for key in ("src", "preset", "from", "to", "by", "split", "m", "agg", "vs", "from2", "to2", "q"):
        value = data.get(key)
        if value not in (None, ""):
            args.add(key, str(value)[:80])
    missing = []
    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    for dim, values in filters.items():
        values = values if isinstance(values, list) else [values]
        if dim in KEYED:
            for v in values:
                args.add("f_" + dim, str(v)[:40])
        elif dim == "doctor":
            ids, miss = _match(values, User.query.filter_by(is_active=True).all(),
                               lambda u: u.display_name(lang))
            for i in ids:
                args.add("f_doctor", i)
            missing += miss
        elif dim == "payer":
            ids, miss = _match(values, PayerEntity.query.all(),
                               lambda p: f"{p.name} {p.name_en or ''}")
            for i in ids:
                args.add("f_payer", i)
            missing += miss
    return args, missing


def ask(question, user, lang="ar", today=None):
    """``{"ok", "query", "understood", "missing"}`` or ``{"ok": False, "error"}``."""
    from app.utils import report_builder as rb
    from app.utils.clock import local_today

    if not enabled():
        return {"ok": False, "error": "ask_disabled"}
    question = " ".join((question or "").split())[:MAX_QUESTION]
    if not question:
        return {"ok": False, "error": "empty_question"}
    sources = rb.available(user)
    if not sources:
        return {"ok": False, "error": "no_sources"}
    today = today or local_today()
    language = "Egyptian Arabic" if lang == "ar" else "English"
    reply = ai.chat([{"role": "user", "content": f"{schema(sources, today)}\n\nQuestion: {question}"}],
                    system=SYSTEM.format(language=language), feature="reports_ask")
    if not reply.get("ok"):
        return reply
    try:
        data = _json(reply.get("text"))
    except (ValueError, TypeError):
        return {"ok": False, "error": "not_understood"}
    understood = " ".join(str(data.get("understood") or "").split())[:300]
    if not data.get("src"):
        return {"ok": False, "error": "cannot_answer", "understood": understood}
    args, missing = to_args(data, lang)
    spec = rb.spec_from(args, user, today=today)
    if spec is None:
        return {"ok": False, "error": "no_sources"}
    return {"ok": True, "query": urlencode(rb.query_args(spec)), "understood": understood,
            "missing": missing, "question": question}


EXPLAIN_SYSTEM = (
    "You read one table from a paediatric clinic's report builder. Use only "
    "these figures: never invent a number, a rate or a cause; when you suggest "
    "a reason, say it is a possibility to check; say plainly when a number is "
    "too small to conclude anything from. Doctors are written as codes like "
    "[D1]; use the same code. Be brief: short bullet points, the most "
    "important first. Answer in {language}."
)


def explain(spec, table, lang="ar"):
    """The table, explained — totals only, doctors as codes."""
    from app.utils.board_ai import _Codes
    from app.utils.report_builder import _t
    from app.models import User

    if not enabled():
        return {"ok": False, "error": "ask_disabled"}
    codes = _Codes()
    doctors = {u.display_name(lang): u for u in User.query.all()}
    coded = "doctor" in (spec["by"], spec["split"])

    def name(label):
        if coded and label in doctors:
            return codes.code(doctors[label])
        return label

    head = [_t("builder.d_" + spec["by"])] + [name(c) for c in table["cols"]]
    rows = [" | ".join([name(r["label"])] + ["" if c is None else str(c) for c in r["cells"]])
            for r in table["rows"][:60]]
    total = " | ".join([_t("builder.total")] + ["" if c is None else str(c) for c in table["total"]])
    facts = (f"Report: {_t('builder.src_' + spec['src'])} — {_t('builder.m_' + spec['m'])}, "
             f"{spec['from']} → {spec['to']}"
             + (f", compared with {spec['b_from']} → {spec['b_to']}" if spec["vs"] else "")
             + "\n" + " | ".join(head) + "\n" + "\n".join(rows) + "\n" + total)
    language = "Egyptian Arabic" if lang == "ar" else "English"
    reply = ai.chat([{"role": "user", "content": facts + "\n\nExplain this result."}],
                    system=EXPLAIN_SYSTEM.format(language=language), feature="reports_explain")
    if not reply.get("ok"):
        return reply
    text = (reply.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "empty"}
    return {"ok": True, "text": codes.restore(text, lang)}
