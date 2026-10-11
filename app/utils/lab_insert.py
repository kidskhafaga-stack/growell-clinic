"""The assistant reads a control's insert — and a person saves what is right.

A new lot of control material comes with a printed insert: for every
analyte, every level and every analyser, the manufacturer's assigned mean
and its spread. Typing thirty of those off a sheet in six-point type is how a
control ends up judged against somebody else's analyser. The laboratory's
own target is still the laboratory's (`utils/lab_quality`); this only saves
the typing.

**What the assistant is asked for is narrow on purpose**: the lot, its
expiry, and for the analyser the laboratory names, each analyte's level,
mean, SD and unit **as printed**. An SD is taken only where the insert
prints one — a printed range is not turned into an SD here, because whether
it is two SD or three is the manufacturer's statement and not a guess the
program should make. A line it cannot read is left out.

**Nothing on an insert belongs to a child**, so it answers to its own
switch, ``ai_lab_insert``, and not to the one for patients' papers.

**And nothing it says is saved.** :func:`read` returns proposals; the
screen shows them in a form beside the analyte each seems to be, and only
the lines a person ticks are saved — through ``lab_quality.save_material``,
the same door the hand-typed control goes through.
"""
import base64
import json
import re
from datetime import date

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 80

_MEDIA = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
          "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf"}

SYSTEM = (
    "You read the insert (package leaflet) of a laboratory quality-control "
    "material. Copy, do not interpret. You are told which analyser or method "
    "the laboratory uses; take only the values printed for it (if the insert "
    "has one table for all analysers, take that). Answer with one JSON object "
    "only: {\"lot\": the lot number as printed, \"expiry\": the expiry date as "
    "YYYY-MM-DD, \"rows\": [{\"analyte\": name as printed, \"level\": the level "
    "as printed (e.g. Level 1), \"mean\": the printed mean or target as a "
    "number, \"sd\": the printed SD as a number — only if an SD is printed, "
    "never derived from a range, \"unit\": the unit as printed}]}. Leave out "
    "any key or row you cannot read clearly. Never convert units, never "
    "calculate."
)


class InsertError(ValueError):
    """A refusal with a key the screen can name (``lab_insert.err_<key>``)."""


def enabled():
    from app.models import Setting

    return Setting.get("ai_lab_insert") == "1"


def ready():
    from app.utils import ai

    try:
        return enabled() and ai.is_ready()
    except Exception:          # noqa: BLE001 - a settings read never breaks the bench
        return False


def _part(upload, cfg):
    from app.utils import ai

    name = (getattr(upload, "filename", "") or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    media = _MEDIA.get(ext)
    if media is None:
        raise InsertError("not_readable")
    if media == "application/pdf" and not ai.reads_pdf(cfg):
        raise InsertError("pdf_provider")
    raw = upload.read(MAX_BYTES + 1)
    if not raw:
        raise InsertError("no_file")
    if len(raw) > MAX_BYTES:
        raise InsertError("too_big")
    data = base64.b64encode(raw).decode("ascii")
    return ({"type": "pdf", "data": data} if media == "application/pdf"
            else {"type": "image", "media_type": media, "data": data})


def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _text(v, limit):
    s = str(v or "").strip()
    return s[:limit] or None


def parse_reply(text):
    """``{lot, expiry, rows: [{analyte, level, mean, sd, unit}]}`` — or None."""
    m = re.search(r"\{.*\}", (text or "").strip(), re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    expiry = None
    try:
        expiry = date.fromisoformat(str(data.get("expiry") or "")[:10])
    except ValueError:
        expiry = None
    rows = []
    for r in data.get("rows") or []:
        if not isinstance(r, dict):
            continue
        name, mean = _text(r.get("analyte"), 160), _number(r.get("mean"))
        if not name or mean is None:
            continue
        sd = _number(r.get("sd"))
        rows.append({"analyte": name, "level": _text(r.get("level"), 40),
                     "mean": mean, "sd": sd if sd is not None and sd > 0 else None,
                     "unit": _text(r.get("unit"), 30)})
        if len(rows) >= MAX_ROWS:
            break
    return {"lot": _text(data.get("lot"), 60), "expiry": expiry, "rows": rows}


def match(rows):
    """Each row with the laboratory's analyte it seems to be — by name or an
    alias, any case — or None. A suggestion the form shows, never a save."""
    from app.models import LabAnalyte

    names = {}
    for a in LabAnalyte.query.all():
        for n in [a.name, a.name_ar] + (a.aliases or "").split(";"):
            n = (n or "").strip().casefold()
            if n:
                names.setdefault(n, a)
    for r in rows:
        r["match"] = names.get(r["analyte"].strip().casefold())
    return rows


def read(upload, instrument=None, config=None):
    """Ask. Returns the parsed reply with each row matched. Raises
    :class:`InsertError`."""
    from app.utils import ai

    if not enabled():
        raise InsertError("off")
    cfg = config or ai.get_config()
    part = _part(upload, cfg)
    ask = ("The laboratory's analyser or method: " + instrument.strip()[:120]
           if instrument and instrument.strip() else
           "The laboratory did not name its analyser; take the general table.")
    result = ai.chat([{"role": "user", "content": [part, {"type": "text", "text": ask}]}],
                     system=SYSTEM, config=cfg, feature="lab_insert")
    if not result.get("ok"):
        raise InsertError("ai:" + str(result.get("error") or "unknown"))
    found = parse_reply(result.get("text"))
    if found is None or not found["rows"]:
        raise InsertError("nothing_found")
    match(found["rows"])
    return found


def save_ticked(form):
    """Save the lines a person ticked, each through ``save_material``.
    All or nothing: a line refused names its number. Returns the rows."""
    from werkzeug.datastructures import MultiDict

    from app.utils import lab_quality

    saved = []
    for i in form.getlist("take"):
        if not str(i).isdigit():
            continue
        line = MultiDict({k: form.get(f"{k}_{i}", "") for k in
                          ("analyte_id", "level", "target_mean", "target_sd", "unit")})
        # The control's name: the material, then the line as printed.
        material = (form.get("name_all") or "").strip()
        printed = (form.get(f"printed_{i}") or "").strip()
        level = (line["level"] or "").strip()
        line["name"] = " — ".join(x for x in (material, " ".join(
            y for y in (printed, level) if y)) if x)[:160]
        line["lot_number"] = form.get("lot_all", "")
        line["expiry_date"] = form.get("expiry_all", "")
        try:
            saved.append(lab_quality.save_material(line))
        except lab_quality.QualityError as err:
            raise InsertError(f"line:{int(i) + 1}:{err}") from None
    if not saved:
        raise InsertError("none_ticked")
    return saved


def from_form(form):
    """The proposals back from a refused save, as the person left them."""
    from app.models import LabAnalyte
    from app.extensions import db

    rows, ticked = [], set(form.getlist("take"))
    for i in range(min(int(form.get("count") or 0), MAX_ROWS)):
        aid = form.get(f"analyte_id_{i}") or ""
        rows.append({"analyte": form.get(f"printed_{i}", ""),
                     "level": form.get(f"level_{i}"),
                     "mean": form.get(f"target_mean_{i}"),
                     "sd": form.get(f"target_sd_{i}"),
                     "unit": form.get(f"unit_{i}"),
                     "match": db.session.get(LabAnalyte, int(aid)) if aid.isdigit() else None,
                     "ticked": str(i) in ticked})
    return {"lot": form.get("lot_all"), "expiry": form.get("expiry_all"), "rows": rows}


__all__ = ["InsertError", "enabled", "from_form", "match", "parse_reply", "read",
           "ready", "save_ticked"]
