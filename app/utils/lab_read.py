"""The assistant reads the paper a family brought — and a person decides.

Asked as: *«لو شغال في عيادة الـ AI يقدر يقرا التحليل ويضيفه»*. A clinic has
no laboratory writing results into the program; the result arrives as a photo
on WhatsApp or a PDF at the desk, attached to the order. Typing a CBC off it
line by line is the slow half of the visit.

**What the assistant is asked for is narrow on purpose.** Not "read this
report": the test's own lines, by name and unit, and for each the value as
printed — or nothing. It is sent the paper and the list of lines, nothing
else from the file; it is never asked to judge a value; and a line it cannot
find stays empty rather than filled with a guess.

**The paper carries the child's name**, so it goes to the provider only where
the clinic opted in to sharing patient data with the assistant
(``ai_patient_context``) — the same switch every other screen that sends a
child's record already answers to, off until somebody turns it on.

**And nothing it says is saved.** :func:`read` returns proposals; the screen
puts them into the same form the doctor types into, marked as read by the
assistant, beside the picture of the paper. The values reach the record only
when a person presses save — through ``lab_results.save``, so the approved
range, the flag and the critical check are the bench's, not the assistant's.
The same rule the program keeps everywhere it uses the assistant: it
suggests, a person confirms.
"""
import base64
import json
import os
import re

#: Larger than this, the paper is not sent — a phone photo is a few MB, and a
#: request the provider will refuse anyway is a wait for nothing.
MAX_BYTES = 8 * 1024 * 1024

_MEDIA = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
          "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf"}

SYSTEM = (
    "You read a photo or scan of a paediatric laboratory report. You are given "
    "the list of lines to look for, each with a key, its names and its unit. "
    "For each line you find on the report, copy the result value exactly as "
    "printed (a number with its decimal point, or the printed word such as "
    "Negative). Do not convert units, do not calculate, do not interpret, and "
    "never fill a line you cannot read clearly — leave it out. Answer with one "
    "JSON object only, mapping each key you found to its value as a string, "
    "and nothing else."
)


class ReadError(ValueError):
    """A refusal with a key the screen can name (``lab_read.err_<key>``)."""


def readable(attachment):
    """The media type of an attachment the assistant may be shown, or None."""
    name = (getattr(attachment, "filename", "") or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    return _MEDIA.get(ext)


def papers(order):
    """The files on this order the assistant could read, newest first."""
    rows = [f for f in (getattr(order, "files", None) or []) if readable(f)]
    return sorted(rows, key=lambda f: f.created_at, reverse=True)


def _lines_prompt(lines):
    rows = []
    for line in lines:
        a = line["analyte"]
        names = [n for n in a.names() if n]
        rows.append({"key": str(a.id), "names": names,
                     "unit": line.get("unit") or a.unit or ""})
    return json.dumps(rows, ensure_ascii=False)


def parse_reply(text, lines):
    """``{analyte_id: value}`` out of the assistant's answer — only keys that
    are lines of this test, only short strings. Anything else is dropped."""
    wanted = {str(line["analyte"].id): line["analyte"].id for line in lines}
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, value in data.items():
        aid = wanted.get(str(key).strip())
        if aid is None or value is None or isinstance(value, (dict, list)):
            continue
        value = str(value).strip()[:120]
        if value:
            out[aid] = value
    return out


def _paper_part(order, attachment, cfg):
    """The paper as a message part — after every check the assistant must pass
    before it may see a child's paper. Raises :class:`ReadError`."""
    from flask import current_app

    from app.utils import ai
    from app.utils.uploads import docs_dir

    if attachment is None or attachment.investigation_id != order.id:
        raise ReadError("no_paper")
    media = readable(attachment)
    if media is None:
        raise ReadError("not_readable")
    if not cfg.get("enabled"):
        raise ReadError("ai_off")
    if not ai.patient_context_enabled():
        raise ReadError("no_consent")
    if media == "application/pdf" and not ai.reads_pdf(cfg):
        raise ReadError("pdf_provider")
    path = os.path.join(docs_dir(), attachment.filename)
    try:
        size = os.path.getsize(path)
        if size > MAX_BYTES:
            raise ReadError("too_big")
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
    except OSError:
        current_app.logger.warning("lab_read: cannot open %s", attachment.filename)
        raise ReadError("no_paper") from None
    return ({"type": "pdf", "data": data} if media == "application/pdf"
            else {"type": "image", "media_type": media, "data": data})


def read(order, attachment, lines, config=None):
    """Ask the assistant for this order's lines off this paper.

    Returns ``{analyte_id: value}`` — proposals, never saved here. Raises
    :class:`ReadError` with a key the screen can say.
    """
    from app.utils import ai

    if not lines:
        raise ReadError("no_lines")
    cfg = config or ai.get_config()
    part = _paper_part(order, attachment, cfg)
    result = ai.chat(
        [{"role": "user", "content": [
            part,
            {"type": "text", "text": "Lines to look for:\n" + _lines_prompt(lines)},
        ]}],
        system=SYSTEM, config=cfg, feature="lab_read")
    if not result.get("ok"):
        raise ReadError("ai:" + str(result.get("error") or "unknown"))
    found = parse_reply(result.get("text"), lines)
    if not found:
        raise ReadError("nothing_found")
    return found


# ======================================== a report, or a test of one value ==
#
# «او تقرير اشعة» — a scan's report, or a test the laboratory has not broken
# into lines, has no list to fill. What the assistant is asked for is still
# narrow: the text **as printed**, and for a test of one value the value, its
# unit and the printed range — copied, never worked out, never judged.

REPORT_SYSTEM = (
    "You read a photo or scan of a paediatric medical report: a radiology "
    "report or a laboratory result. Copy, do not interpret. Answer with one "
    "JSON object only, with these keys and nothing else: \"text\" — the "
    "report's findings and conclusion copied exactly as printed (keep the "
    "printed language, line breaks allowed); for a laboratory result also "
    "\"value\" — the single numeric result as printed, \"unit\" — its unit "
    "as printed, \"low\" and \"high\" — the printed reference range limits. "
    "Leave out any key you cannot read clearly. Never add a diagnosis, an "
    "opinion, a calculation or a unit conversion."
)

REPORT_KEYS = ("text", "value", "unit", "low", "high")
_NUMERIC = ("value", "low", "high")


def parse_report(text, imaging=False):
    """``{key: string}`` out of the assistant's answer — only the known keys,
    numbers only where a number belongs, the text bounded. A scan has text
    and nothing else."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key in (("text",) if imaging else REPORT_KEYS):
        value = data.get(key)
        if value is None or isinstance(value, (dict, list)):
            continue
        value = str(value).strip()
        if not value:
            continue
        if key in _NUMERIC:
            # A plain number or nothing: «<5» is not 5, and a box that holds
            # a number would drop the sign that changes its meaning.
            value = value.replace(",", ".")
            if not re.fullmatch(r"-?\d+(\.\d+)?", value):
                continue
        out[key] = value[:4000] if key == "text" else value[:40]
    return out


def read_report(order, attachment, config=None):
    """Ask the assistant for the report off this paper — for a scan, or a
    test with no lines. Returns proposals, never saved here."""
    from app.utils import ai

    cfg = config or ai.get_config()
    part = _paper_part(order, attachment, cfg)
    imaging = order.kind == "imaging"
    ask = ("This is a radiology report: give \"text\" only."
           if imaging else "This is a laboratory result for: " + (order.name or ""))
    result = ai.chat(
        [{"role": "user", "content": [part, {"type": "text", "text": ask}]}],
        system=REPORT_SYSTEM, config=cfg, feature="lab_read")
    if not result.get("ok"):
        raise ReadError("ai:" + str(result.get("error") or "unknown"))
    found = parse_report(result.get("text"), imaging=imaging)
    if not found:
        raise ReadError("nothing_found_report")
    return found
