"""The assistant reads a reagent kit's insert — the laboratory's ranges, as
the manufacturer printed them — and a person saves what is right.

Asked as *«والمراجع بتاعتها … ولا بيبقى ازاي؟»*. A usual range is the
laboratory's own: its analyser, its kit, its population. Where most
laboratories start is the **kit insert** that came in the box — its
"Expected values" or "Reference ranges" table. Typing that table off a sheet
in six-point type is where a decimal goes missing; this only saves the
typing. It never supplies a figure of its own.

**What the assistant is asked for is narrow on purpose** (the same stance as
``lab_insert``, which reads a control's insert): each line of the expected-
values table **as printed** — the analyte, the age or group, the sex, the
low and high, the unit, and any note under it. No unit is converted, no
range calculated, nothing filled in from what ranges usually are. A line it
cannot read is left out. Critical limits are not on a kit insert and are not
asked for — they are the laboratory's.

**And nothing it says is saved.** :func:`read` returns proposals; the screen
shows them beside the test's own components. Only ticked lines are saved,
each checked by the same rules as a band typed by hand (``lab_hand._read``:
the age must be readable, low under high). They are written as a **new
reference from the laboratory** — the same as a new sheet — so they are
drafts: shown beside a result, never used to call it high or low, until the
director approves them; and approving them replaces that analyte's old
approved bands, because that is what a new kit's insert means.

Nothing on an insert belongs to a child, so it answers to the same switch as
the control insert, ``ai_lab_insert``.
"""
import json
import re

from app.extensions import db

MAX_ROWS = 80

SYSTEM = (
    "You read the package insert of a laboratory reagent kit. Find its table of "
    "expected values or reference ranges (also called reference intervals or "
    "normal values). Copy, do not interpret. Answer with one JSON object only: "
    "{\"kit\": the kit's name as printed, \"lot\": the lot number if printed, "
    "\"advice\": the insert's sentence telling laboratories to establish their "
    "own ranges, copied, if it has one, \"rows\": [{\"analyte\": name as "
    "printed, \"group\": the age or population as printed (e.g. Newborn, "
    "1-12 months, Children, Adults), \"sex\": male, female or all, \"low\": the "
    "printed lower limit as a number, \"high\": the printed upper limit as a "
    "number, \"unit\": the unit as printed, \"note\": any words printed with "
    "that line}]}. If the insert prints the same range in two units, give one "
    "row per unit. A one-sided limit (less than 5) has only low or only high. "
    "Leave out any row or key you cannot read clearly. Never convert units, "
    "never calculate, never add a range that is not printed on this insert."
)


class KitInsertError(ValueError):
    """A refusal with a key the screen can name (``lab_kit.err_<key>``)."""


def enabled():
    from app.utils import lab_insert

    return lab_insert.enabled()


def ready():
    from app.utils import lab_insert

    return lab_insert.ready()


def _sex(value):
    v = str(value or "").strip().lower()
    if v in ("male", "m", "men", "boys", "ذكر", "ذكور"):
        return "male"
    if v in ("female", "f", "women", "girls", "أنثى", "انثى", "إناث"):
        return "female"
    return "all"


def parse_reply(text):
    """``{kit, lot, advice, rows: [...]}`` — or None."""
    from app.utils.lab_insert import _number, _text

    m = re.search(r"\{.*\}", (text or "").strip(), re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    rows = []
    for r in data.get("rows") or []:
        if not isinstance(r, dict):
            continue
        name = _text(r.get("analyte"), 160)
        low, high = _number(r.get("low")), _number(r.get("high"))
        if not name or (low is None and high is None):
            continue
        rows.append({"analyte": name, "group": _text(r.get("group"), 60),
                     "sex": _sex(r.get("sex")), "low": low, "high": high,
                     "unit": _text(r.get("unit"), 30), "note": _text(r.get("note"), 255)})
        if len(rows) >= MAX_ROWS:
            break
    return {"kit": _text(data.get("kit"), 120), "lot": _text(data.get("lot"), 60),
            "advice": _text(data.get("advice"), 300), "rows": rows}


def _norm(unit):
    return (unit or "").replace(" ", "").replace("μ", "µ").casefold()


def match(test, rows):
    """Each row with the test's own component it seems to be — by any of
    its names, any case — and whether the printed unit is the component's.
    A suggestion the form shows, never a save."""
    from app.utils.lab_import import age_band, key

    own = [link.analyte for link in test.analyte_links]
    for r in rows:
        r["match"] = next((a for a in own
                           if key(r["analyte"]) in {key(n) for n in a.names()}), None)
        if r["match"] is None and len(own) == 1:
            r["match"] = own[0]
        r["unit_differs"] = bool(r["match"] and r["match"].unit and r["unit"]
                                 and _norm(r["match"].unit) != _norm(r["unit"]))
        r["age_ok"] = age_band(r["group"] or "") is not None
    return rows


def read(test, upload, instrument=None, config=None):
    """Ask. Returns the parsed reply with each row matched to the test's
    components. Raises :class:`KitInsertError`."""
    from app.utils import ai
    from app.utils.lab_insert import InsertError, _part

    if not enabled():
        raise KitInsertError("off")
    cfg = config or ai.get_config()
    try:
        part = _part(upload, cfg)
    except InsertError as err:
        raise KitInsertError(str(err)) from err
    ask = ("The laboratory's analyser or method: " + instrument.strip()[:120]
           if instrument and instrument.strip() else
           "The laboratory did not name its analyser.")
    ask += " The test is: " + (test.name_en or test.name_ar)[:160] + "."
    result = ai.chat([{"role": "user", "content": [part, {"type": "text", "text": ask}]}],
                     system=SYSTEM, config=cfg, feature="lab_kit_insert")
    if not result.get("ok"):
        raise KitInsertError("ai:" + str(result.get("error") or "unknown"))
    found = parse_reply(result.get("text"))
    if found is None or not found["rows"]:
        raise KitInsertError("nothing_found")
    match(test, found["rows"])
    return found


def from_form(test, form):
    """The proposals again, as the person left them — after a refusal."""
    rows = []
    for i in range(min(int(form.get("count") or 0), MAX_ROWS)):
        rows.append({"analyte": form.get(f"printed_{i}") or "",
                     "group": form.get(f"age_{i}") or "", "sex": form.get(f"sex_{i}") or "all",
                     "low": form.get(f"low_{i}") or "", "high": form.get(f"high_{i}") or "",
                     "unit": form.get(f"unit_{i}") or "", "note": form.get(f"note_{i}") or "",
                     "ticked": str(i) in form.getlist("take"),
                     "match_id": form.get(f"analyte_id_{i}", type=int)})
    own = {link.analyte_id: link.analyte for link in test.analyte_links}
    for r in rows:
        r["match"] = own.get(r.pop("match_id"))
        r["unit_differs"] = False
        r["age_ok"] = True
    return {"kit": form.get("kit_all"), "lot": form.get("lot_all"),
            "advice": form.get("advice_all"), "rows": rows}


def save_ticked(test, form, user):
    """Save the ticked lines as drafts from the laboratory. All or nothing: a
    line refused names its number. Returns the rows."""
    from werkzeug.datastructures import MultiDict

    from app.models import LabRange
    from app.utils import lab_hand

    own = {link.analyte_id: link.analyte for link in test.analyte_links}
    kit = (form.get("kit_all") or "").strip()
    lot = (form.get("lot_all") or "").strip()
    source = " · ".join(x for x in ("Kit insert", kit, f"lot {lot}" if lot else "") if x)[:160]
    saved = []
    for i in form.getlist("take"):
        if not str(i).isdigit():
            continue
        n = int(i) + 1
        analyte = own.get(form.get(f"analyte_id_{i}", type=int))
        if analyte is None:
            raise KitInsertError(f"line:{n}:need_analyte")
        line = MultiDict({"age": form.get(f"age_{i}", ""), "sex": form.get(f"sex_{i}", "all"),
                          "kind": "interval", "low": form.get(f"low_{i}", ""),
                          "high": form.get(f"high_{i}", ""), "note": form.get(f"note_{i}", ""),
                          "source": source})
        try:
            figures = lab_hand._read(line)
        except lab_hand.Refused as why:
            raise KitInsertError(f"line:{n}:{why.key}") from why
        printed = (form.get(f"unit_{i}") or "").strip()
        if printed and analyte.unit and _norm(printed) != _norm(analyte.unit):
            raise KitInsertError(f"line:{n}:unit")
        row = LabRange(analyte_id=analyte.id, manual=False,
                       entered_by=getattr(user, "id", None), **figures)
        db.session.add(row)
        saved.append(row)
    if not saved:
        raise KitInsertError("none_ticked")
    db.session.flush()
    return saved


__all__ = ["KitInsertError", "enabled", "from_form", "match", "parse_reply",
           "read", "ready", "save_ticked"]
