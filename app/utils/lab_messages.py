"""An analyser's own messages, read onto its tubes — ASTM E1394 (carried by
E1381) and HL7 v2 ORU^R01 (LAB_GLAB360_PLAN.md م-٢ ب).

The two published languages most laboratory analysers speak. A message is
turned into the same rows a result file gives — ``(row, sample, code, value,
unit, flag)`` — and goes through exactly the same road
(``lab_device_import.run``): the tube's number finds one order, the device's
code is linked to an analyte, the bench's own save checks range, critical and
delta, and **nothing is released by arriving**. A row that cannot be placed is
held for a person with its reason — never put on a child by a near match.

Only results are read: query and order records (``Q``, ``O`` without a
result, ``ORM``/``OML``) say nothing to write.

**ASTM** — records separated by CR: ``H`` (its first field gives the
delimiters), ``P`` patient, ``O`` order (the specimen id), ``R`` result
(``^^^code``, value, units, reference, flags), ``C`` comment, ``L`` end. The
E1381 frames around them (``<STX>`` frame number … ``<ETX>``/``<ETB>``
checksum CR LF) are taken off and a frame split by ``<ETB>`` is joined again.

**HL7 v2** — segments separated by CR: ``MSH`` (its fourth character and the
encoding characters), ``SPM``/``OBR`` (the specimen and order numbers), and
``OBX`` (code, value, units, flags). The MLLP envelope (``<VT>`` … ``<FS><CR>``)
is taken off.

Which field carries the tube's number differs between analysers, and the
interface manual says which. Every number the message gives for the specimen
is offered, in the standard's order, and the one that names exactly one order
here is taken — an exact match on the clinic's own printed number, so nothing
is guessed about a child.
"""
STX, ETX, ETB, EOT, ENQ, ACK, NAK = "\x02", "\x03", "\x17", "\x04", "\x05", "\x06", "\x15"
VT, FS = "\x0b", "\x1c"

PROTOCOLS = ("file", "astm", "hl7")
MAX_CHARS = 2 * 1024 * 1024


class MessageError(ValueError):
    """A refusal with a key (``lab_device.err_<key>``)."""


# ------------------------------------------------------------------ ASTM ---
def checksum(frame_body):
    """E1381's checksum: the sum of the characters from the frame number up
    to and including ETX/ETB, modulo 256, as two upper-case hex digits."""
    return f"{sum(frame_body.encode('latin-1', 'replace')) % 256:02X}"


def unframe(text):
    """The records an E1381 transmission carried, frames taken off and an
    ``<ETB>``-split record joined. Text with no frames is returned as is."""
    if STX not in text:
        return text.replace(ENQ, "").replace(EOT, "")
    out, i = [], 0
    while True:
        start = text.find(STX, i)
        if start < 0:
            break
        end = start + 1
        while end < len(text) and text[end] not in (ETX, ETB):
            end += 1
        if end >= len(text):
            raise MessageError("broken_frame")
        body = text[start + 1:end]
        # The frame number is one digit, 0–7.
        out.append(body[1:] if body[:1].isdigit() else body)
        i = end + 1
    return "".join(out)


def _records(text):
    text = unframe(text).replace("\r\n", "\r").replace("\n", "\r")
    return [r for r in (line.strip(" \t") for line in text.split("\r")) if r]


def _component(field, sep, index):
    parts = (field or "").split(sep)
    return parts[index].strip() if index < len(parts) else ""


def _last(field, sep):
    parts = [p.strip() for p in (field or "").split(sep) if p.strip()]
    return parts[-1] if parts else ""


def parse_astm(text):
    """``[(row, [sample candidates], code, value, unit, flag)]``."""
    records = _records(text)
    if not records or not records[0].startswith("H"):
        raise MessageError("no_header")
    head = records[0]
    field_sep = head[1] if len(head) > 1 else "|"
    comp_sep = head[3] if len(head) > 3 else "^"
    repeat_sep = head[2] if len(head) > 2 else "\\"
    rows, samples = [], []
    for n, rec in enumerate(records, start=1):
        kind = rec[:1].upper()
        fields = rec.split(field_sep)
        if kind == "O":
            # O-3 specimen id, O-4 the instrument's own specimen id.
            samples = [c for c in (_component(fields[2] if len(fields) > 2 else "", comp_sep, 0),
                                   _component(fields[3] if len(fields) > 3 else "", comp_sep, 0))
                       if c]
        elif kind == "R":
            test = fields[2] if len(fields) > 2 else ""
            code = _component(test, comp_sep, 3) or _last(test, comp_sep)
            value = fields[3] if len(fields) > 3 else ""
            # A value may come with repeats (e.g. a result and its dilution):
            # the first is the result.
            value = value.split(repeat_sep)[0].split(comp_sep)[0].strip()
            unit = _component(fields[4] if len(fields) > 4 else "", comp_sep, 0)
            flag = (fields[6] if len(fields) > 6 else "").strip()
            rows.append((n, list(samples), code, value, unit, flag))
    return rows


# ------------------------------------------------------------------ HL7 ---
def unwrap(text):
    """The HL7 message out of its MLLP envelope (if it has one)."""
    return text.replace(VT, "").replace(FS, "")


def parse_hl7(text):
    """``[(row, [sample candidates], code, value, unit, flag)]`` from ORU^R01."""
    text = unwrap(text).replace("\r\n", "\r").replace("\n", "\r")
    segments = [s for s in text.split("\r") if s.strip()]
    if not segments or not segments[0].startswith("MSH"):
        raise MessageError("no_header")
    msh = segments[0]
    field_sep = msh[3] if len(msh) > 3 else "|"
    enc = msh[4:8] if len(msh) >= 8 else "^~\\&"
    comp_sep = enc[0]
    rep_sep = enc[1] if len(enc) > 1 else "~"
    rows, spm, obr = [], [], []
    for n, seg in enumerate(segments, start=1):
        fields = seg.split(field_sep)
        name = fields[0].strip().upper()

        def field(i):
            return fields[i] if len(fields) > i else ""

        if name == "SPM":
            # SPM-2 specimen id: placer (component 1) then filler (component 2).
            spm = [c for c in (_component(field(2), comp_sep, 0),
                               _component(field(2), comp_sep, 1)) if c]
            spm = [x.split("&")[0] for x in spm]
        elif name == "OBR":
            # OBR-2 placer order number, OBR-3 filler order number.
            obr = [c for c in (_component(field(2), comp_sep, 0),
                               _component(field(3), comp_sep, 0)) if c]
            spm = []
        elif name == "OBX":
            code = _component(field(3), comp_sep, 0)
            value = field(5).split(rep_sep)[0]
            if field(2).strip().upper() in ("CE", "CWE"):
                value = _component(value, comp_sep, 1) or _component(value, comp_sep, 0)
            value = value.strip()
            unit = _component(field(6), comp_sep, 0)
            flag = field(8).split(rep_sep)[0].strip()
            rows.append((n, list(dict.fromkeys(spm + obr)), code, value, unit, flag))
    return rows


def ack_for(message, ok=True, text=""):
    """The HL7 ACK the analyser waits for (MSA AA or AE), echoing its control
    id — what the middleware sends back over MLLP."""
    from datetime import datetime

    text_in = unwrap(message).replace("\n", "\r")
    msh = next((s for s in text_in.split("\r") if s.startswith("MSH")), "MSH|^~\\&")
    sep = msh[3] if len(msh) > 3 else "|"
    f = msh.split(sep)

    def g(i):
        return f[i] if len(f) > i else ""

    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    control = g(9)
    version = g(11) or "2.5"
    head = sep.join(["MSH", g(1) or "^~\\&", g(4), g(5), g(2), g(3), stamp, "",
                     "ACK", control, "P", version])
    msa = sep.join(["MSA", "AA" if ok else "AE", control, text[:80]])
    return f"{VT}{head}\r{msa}\r{FS}\r"


# ------------------------------------------------------------------ both ---
def read(protocol, data):
    """``[(row, [sample candidates], code, value, unit, flag)]`` from a
    message's bytes, in the device's protocol."""
    if not data:
        raise MessageError("empty")
    if isinstance(data, bytes):
        if len(data) > MAX_CHARS:
            raise MessageError("too_big")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
    else:
        text = data
    if protocol == "astm":
        return parse_astm(text)
    if protocol == "hl7":
        return parse_hl7(text)
    raise MessageError("no_protocol")


__all__ = ["ACK", "ENQ", "EOT", "ETB", "ETX", "FS", "MessageError", "NAK", "PROTOCOLS",
           "STX", "VT", "ack_for", "checksum", "parse_astm", "parse_hl7", "read",
           "unframe", "unwrap"]
