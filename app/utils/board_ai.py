"""The assistant reads a board — the medical one and the management one.

Asked as: *«عايز ادخل الذكاء الصناعي فى التحليل»*. Two things on each board:
**read the period** (what moved against the period before, and what wants a
look) and **ask the board** (one question about these figures).

**What leaves the clinic is the board, not the records.** The figures the
screen already shows — counts, diagnoses by code and by their words, units,
money by department — and nothing a child can be found by: no name, no file
number, no date of birth. Doctors go as ``[D1]``, ``[D2]``… and the reply
has their names put back on this side, so a doctor's figures are never sent
with the doctor's name on them.

**Its own switch** (``ai_boards``), off until somebody turns it on, beside
the assistant's other switches: reading the clinic's figures is a different
decision from reading a child's file, and neither should arrive with the
other.

**Nothing it says is saved, and it judges nothing on its own.** The reply is
shown under the board, marked as the assistant's, and gone on the next load.
It is told to use only the figures given, to name a possible reason as a
possibility, and to say when a number is too small to mean anything — the
same rule the boards keep: no invented outbreak line, no invented number.
"""
import re

from app.utils import ai

SETTING = "ai_boards"
MAX_QUESTION = 400
#: How many diagnoses of each kind go — the board's own long list is
#: paginated, and the assistant reads the head of it as a person would.
TOP_DX = 15

SYSTEM = (
    "You read a paediatric clinic's dashboard for its management. You are "
    "given the figures of one period and of the same-length period just "
    "before it. Use only these figures: never invent a number, a rate or a "
    "cause. When you suggest a reason, say it is a possibility to check. Say "
    "plainly when a number is too small to conclude anything from. Do not "
    "give advice about any individual patient. Doctors are written as codes "
    "like [D1]; refer to them by the same code. Be brief: short bullet "
    "points, the most important first. Answer in {language}."
)


def enabled():
    from app.models import Setting

    return Setting.get(SETTING) == "1"


def ready():
    return enabled() and ai.is_ready()


class _Codes:
    """Doctors as ``[D1]``… on the way out, names on the way back."""

    def __init__(self):
        self.names = {}

    def code(self, user):
        if user is None:
            return "—"
        for key, known in self.names.items():
            if known.id == user.id:
                return key
        key = f"[D{len(self.names) + 1}]"
        self.names[key] = user
        return key

    def restore(self, text, lang="ar"):
        for key, user in self.names.items():
            text = text.replace(key, user.display_name(lang))
        return text


def _pct(now, before):
    if now is None or not before:
        return ""
    return f" ({round((now - before) * 100 / before):+d}%)"


def _clean(words, limit=80):
    """A free-text diagnosis as typed — digits that could be a phone or a
    file number taken out, length capped."""
    words = re.sub(r"\d{5,}", "…", " ".join((words or "").split()))
    return words[:limit]


# ------------------------------------------------------------- the medical --
def medical_facts(w, on, now, before, dx, ages, wards, er, doctors):
    """The medical board as lines of text, and the codes for its doctors."""
    codes = _Codes()
    out = [f"Period: {w['from']} to {w['to']} ({w['days']} days); "
           f"previous: {w['prev_from']} to {w['prev_to']}.", "", "Headline (now / before):"]
    for key in ("visits", "new_patients", "doses", "admissions", "discharges",
                "deaths", "emergency", "operations"):
        if now.get(key) is None:
            continue
        out.append(f"- {key}: {now[key]} / {before.get(key)}"
                   f"{_pct(now[key], before.get(key))}")
    out += ["", f"Diagnoses (cases now / before), coded; "
                f"{dx.get('free_share') or 0}% of cases written without a code:"]
    for row in dx["coded"][:TOP_DX]:
        out.append(f"- ICD-{row['version']} {row['code']} {_clean(row['title'])}: "
                   f"{row['n']} / {row.get('p', 0)}")
    if dx["free"]:
        out.append("Written without a code (by their words):")
        for row in dx["free"][:TOP_DX]:
            out.append(f"- {_clean(row['title'])}: {row['n']} / {row.get('p', 0)}")
    if ages:
        out += ["", "Children seen by age band (band: boys, girls, sex not recorded):"]
        for row in ages:
            out.append(f"- {row[0]}: {', '.join(str(v) for v in row[1:])}")
    if wards:
        out += ["", "Inpatient units (admissions, mean stay days, occupancy %, "
                    "deaths, readmitted within 30 days %):"]
        for r in wards:
            name = r["unit"].name if r["unit"] is not None else "unplaced"
            out.append(f"- {name}: {r['admissions']}, {r['alos']}, "
                       f"{r['occupancy']}, {r['deaths']}, {r['readmit_pct']}")
    if er:
        out += ["", f"Emergency attendances: {er['total']}. Triage levels as "
                    "the hospital writes them:"]
        out += [f"- {lvl or 'not triaged'}: {n}" for lvl, n in er["levels"]]
        out.append("Where they went: " + ", ".join(
            f"{k or 'not recorded'} {n}" for k, n in er["dispositions"] if n))
    if doctors:
        out += ["", "Doctors (cases, patients, new patients, % came back, "
                    "% diagnoses without a code, admissions, mean stay):"]
        for r in doctors:
            out.append(f"- {codes.code(r['doctor'])}: {r['cases']}, {r['patients']}, "
                       f"{r['fresh']}, {r['back_pct']}, {r['nocode_pct']}, "
                       f"{r['admissions']}, {r['alos']}")
    return "\n".join(out), codes


# ---------------------------------------------------------- the management --
def management_facts(w, data):
    codes = _Codes()
    now, before = data["now"], data["before"]
    out = [f"Period: {w['from']} to {w['to']} ({w['days']} days); "
           f"previous: {w['prev_from']} to {w['prev_to']}.", "",
           "Headline (now / before):"]
    for key in ("revenue", "expenses", "net", "collected", "bills", "per_bill", "visits"):
        out.append(f"- {key}: {now.get(key)} / {before.get(key)}"
                   f"{_pct(now.get(key), before.get(key))}")
    owed = data["owed"]
    out.append(f"- owed today: {owed['total']} (overdue {owed['overdue']} "
               f"on {owed['overdue_count']} bills)")
    if data["departments"]:
        out += ["", "Departments (revenue now / before, direct costs, "
                    "contribution, margin %, doctors' share):"]
        for line in data["departments"]:
            name = line["centre"].display_name() if line["centre"] else "unplaced"
            out.append(f"- {name}: {line['revenue']} / {line['before']}, "
                       f"{line['direct']}, {line['contribution']}, "
                       f"{line['margin']}, {line['doctors']}")
    if data["methods"]:
        out.append("Collected by method: " + ", ".join(
            f"{m} {v}" for m, v in data["methods"]))
    if data["attention"]:
        out.append("Flagged on the board: " + ", ".join(
            f"{a['key']} {a['value']}" for a in data["attention"]))
    if data["doctors"]:
        out += ["", "Doctors (visits, bills, billed, doctor's share, per bill, "
                    "no-show %):"]
        for r in data["doctors"]:
            out.append(f"- {codes.code(r['doctor'])}: {r['visits']}, {r['bills']}, "
                       f"{r['billed']}, {r['share']}, {r['per_bill']}, "
                       f"{r['no_show_pct']}")
    return "\n".join(out), codes


# ---------------------------------------------------------------- the call --
def ask(facts, codes, question=None, lang="ar"):
    """``{"ok", "text"}`` or ``{"ok": False, "error"}``. Nothing is kept."""
    if not enabled():
        return {"ok": False, "error": "boards_disabled"}
    question = " ".join((question or "").split())[:MAX_QUESTION]
    task = (f"Question from the clinic about these figures: {question}"
            if question else
            "Read this period: what changed most against the period before, "
            "what deserves attention, and what is too small to conclude.")
    language = "Egyptian Arabic" if lang == "ar" else "English"
    reply = ai.chat([{"role": "user", "content": f"{facts}\n\n{task}"}],
                    system=SYSTEM.format(language=language),
                    feature="board_read")
    if not reply.get("ok"):
        return reply
    text = (reply.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "empty"}
    return {"ok": True, "text": codes.restore(text, lang), "question": question}
