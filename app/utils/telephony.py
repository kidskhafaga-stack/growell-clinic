"""The telephone, through whatever switchboard the clinic has.

``CONNECTHUB_PLAN.md`` stage 6. Clinics run Asterisk/FreePBX, 3CX, Yeastar,
Grandstream, or an old analogue exchange — the plan says it plainly: «حسب
السنترال اللي عند كل عميل». So the program speaks none of them. It opens
**one door of its own** and every switchboard that can call a web address on
a call event is wired to it (``docs/TELEPHONY.md``):

``POST /telephony/event`` — ``{"event": "ring" | "answer" | "hangup",
"call_id": …, "from": …, "to": …, "extension": …, "direction": "in" |
"out"}``, as JSON or as form fields (Asterisk's ``CURL()`` posts form
fields). The ring, the answer and the hang-up of one call share its
``call_id`` and land on one row; the same event twice changes nothing.

``GET /telephony/lookup?number=…`` — who this number is: the family's
children by name and file number, for a switchboard that shows a caller's
name on the handset (a «CRM lookup»).

Both need the clinic's key (``Authorization: Bearer …``), kept only as its
hash, and answer 404 while the telephone is off. **It starts off**, like
every other door onto the network here.

Inside the program:

* **who is calling** — the person on the ringing extension (or everybody
  who answers the phone, when no extension was sent) sees the caller: the
  children on that number, with the same panel the chat uses — the next
  booking, a result's state, the balance — by **that person's own
  permissions** (``utils/desk_actions.panel``);
* **the call log**, and **missed calls not yet returned**: a missed call is
  returned when somebody marks it so, or when the same number later gets
  through, either way;
* **no recording.** Recording needs the caller told and agreeing; it is a
  clinic's decision and not built here.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from app.extensions import db
from app.models import PhoneCall, Setting

ENABLED_KEY = "telephony_enabled"
KEY_HASH = "telephony_key_hash"
KEY_HINT = "telephony_key_hint"

EVENTS = ("ring", "answer", "hangup")
#: A ring older than this with nothing after it is not «ringing now» — the
#: hang-up may simply never have been sent.
RINGING_FOR = timedelta(seconds=90)
#: How far back the missed-calls list looks.
MISSED_WINDOW = timedelta(days=7)


class CallEventError(ValueError):
    """The event cannot be read; nothing is saved."""


# ----------------------------------------------------------- the door ---
def enabled():
    return Setting.get(ENABLED_KEY, "0") == "1"


def set_enabled(on):
    Setting.set(ENABLED_KEY, "1" if on else "0")


def new_key():
    """A new key for the switchboard; returned this once, kept as its hash.
    Making a new one retires the old. The caller commits."""
    key = "pptel_" + secrets.token_urlsafe(32)
    Setting.set(KEY_HASH, hashlib.sha256(key.encode("utf-8")).hexdigest())
    Setting.set(KEY_HINT, key[-4:])
    return key


def key_hint():
    return Setting.get(KEY_HINT, "") or None


def key_ok(header):
    """The ``Authorization: Bearer …`` header carries the clinic's key."""
    stored = Setting.get(KEY_HASH, "") or ""
    value = (header or "").strip()
    if not stored or not value.lower().startswith("bearer "):
        return False
    digest = hashlib.sha256(value[7:].strip().encode("utf-8")).hexdigest()
    return hmac.compare_digest(stored, digest)


# ------------------------------------------------------------- events ---
def _number(raw):
    from app.utils.whatsapp import normalize_phone

    return normalize_phone(raw) if raw else None


def _text(value, limit):
    return (str(value).strip()[:limit] or None) if value is not None else None


def receive(data, now=None):
    """Apply one switchboard event. Returns the call row.

    ``data`` is a mapping (the JSON body or the form). Raises
    :class:`CallEventError` when it cannot be read.
    """
    now = now or datetime.utcnow()
    event = (data.get("event") or "").strip().lower()
    if event not in EVENTS:
        raise CallEventError("event")
    ref = _text(data.get("call_id"), 120)
    if not ref:
        raise CallEventError("call_id")
    direction = (data.get("direction") or "in").strip().lower()
    if direction not in ("in", "out"):
        raise CallEventError("direction")
    # The other party is the caller on an incoming call and the one called
    # on an outgoing one.
    other = data.get("from") if direction == "in" else data.get("to")
    extension = _text(data.get("extension")
                      or (data.get("to") if direction == "in"
                          else data.get("from")), 20)

    call = PhoneCall.query.filter_by(call_ref=ref).first()
    if call is None:
        call = PhoneCall(call_ref=ref, direction=direction,
                         raw_number=_text(other, 64), number=_number(other),
                         extension=extension, status="ringing",
                         started_at=now)
        db.session.add(call)
    elif extension and not call.extension:
        call.extension = extension
    if event == "answer" and call.answered_at is None:
        call.answered_at = now
        if extension:
            # Answered at the extension that picked up, which on a ring
            # group is not the one the ring was sent to.
            call.extension = extension
    elif event == "hangup" and call.ended_at is None:
        call.ended_at = now
    # The status follows from the times, whatever order the events came in:
    # a retried «answer» that lands after the «hangup» is still a call that
    # was answered and has ended — not one still talking, and not missed.
    if call.ended_at is not None:
        call.status = "ended" if call.answered_at else (
            "missed" if call.direction == "in" else "ended")
    elif call.answered_at is not None:
        call.status = "answered"
    return call


# --------------------------------------------------------- who it is ---
def who(number):
    """The children on this number (guardians' phones and their own)."""
    from app.utils.inbox import known_patient_for_phone, match_patients

    if not number:
        return []
    found = match_patients(number)
    if found:
        return found
    known = known_patient_for_phone(_number(number))
    return [known] if known is not None else []


def who_many(numbers):
    """``{number: [children]}`` for many numbers at once — one pass over the
    phones on file, not one per number (the call log asks for hundreds)."""
    from app.models import Parent, Patient
    from app.utils.inbox import known_patient_for_phone

    wanted = {}
    for raw in numbers:
        norm = _number(raw) if raw else None
        if norm:
            wanted.setdefault(norm, []).append(raw)
    out = {raw: [] for raw in numbers if raw}
    if not wanted:
        return out
    families = {}
    for parent in Parent.query.filter(Parent.phone.isnot(None)).all():
        if not parent.family_id:
            continue
        for phone in (parent.phone, parent.phone_alt):
            norm = _number(phone) if phone else None
            if norm in wanted:
                families.setdefault(norm, set()).add(parent.family_id)
    found = {norm: {} for norm in wanted}
    fam_ids = set().union(*families.values()) if families else set()
    if fam_ids:
        by_family = {}
        for kid in Patient.query.filter(Patient.family_id.in_(fam_ids)).all():
            by_family.setdefault(kid.family_id, []).append(kid)
        for norm, fams in families.items():
            for fam in fams:
                for kid in by_family.get(fam, []):
                    found[norm][kid.id] = kid
    for kid in Patient.query.filter(Patient.own_phone.isnot(None)).all():
        norm = _number(kid.own_phone)
        if norm in found:
            found[norm][kid.id] = kid
    for norm, raws in wanted.items():
        kids = [found[norm][i] for i in sorted(found[norm])]
        if not kids:
            known = known_patient_for_phone(norm)
            kids = [known] if known is not None else []
        for raw in raws:
            out[raw] = kids
    return out


def lookup(number):
    """For the switchboard's handset display: names and file numbers only —
    nothing medical, nothing owed."""
    kids = who(number)
    return {"number": _number(number), "found": bool(kids),
            "name": " / ".join(k.full_name for k in kids[:3]) or None,
            "patients": [{"file": k.patient_number, "name": k.full_name}
                         for k in kids]}


def ringing_for(user, now=None):
    """Calls ringing now that this person should see.

    * A call to an extension somebody here answers on goes to that person.
    * Any other call — no extension sent, or one nobody here has (a
      switchboard that puts the clinic's own number in «to») — goes to the
      people with no extension of their own: the desk that answers the main
      line. If everyone has an extension, it goes to everyone, because a
      ringing phone nobody is shown is the one failure this exists to stop.
    """
    from app.models import User

    now = now or datetime.utcnow()
    rows = (PhoneCall.query
            .filter(PhoneCall.status == "ringing",
                    PhoneCall.direction == "in",
                    PhoneCall.started_at >= now - RINGING_FOR)
            .order_by(PhoneCall.started_at.desc()).all())
    if not rows:
        return []
    owned = {(u.phone_extension or "").strip()
             for u in User.query.filter(User.is_active.is_(True),
                                        User.phone_extension.isnot(None))}
    owned.discard("")
    mine = (getattr(user, "phone_extension", None) or "").strip()
    everyone_has_one = not User.query.filter(
        User.is_active.is_(True),
        (User.phone_extension.is_(None)) | (User.phone_extension == "")
    ).first()
    out = []
    for call in rows:
        if call.extension and call.extension in owned:
            if call.extension == mine:
                out.append(call)
        elif not mine or everyone_has_one:
            out.append(call)
    return out


def card(call, user):
    """What the person answering sees: the caller, and what they may act on
    — the chat's own panel, by this person's permissions."""
    from app.utils import desk_actions

    kids = who(call.raw_number or call.number)
    return {"call": call, "patients": kids,
            "panel": desk_actions.panel(user, kids, "") if kids else None}


# ------------------------------------------------------ missed calls ---
def missed(now=None):
    """Missed incoming calls not yet returned, newest first, one per number.

    Returned means somebody marked it so — or a later call with the same
    number got through, in either direction, which is the family reaching
    the clinic or the clinic reaching them."""
    now = now or datetime.utcnow()
    since = now - MISSED_WINDOW
    rows = (PhoneCall.query
            .filter(PhoneCall.direction == "in", PhoneCall.status == "missed",
                    PhoneCall.returned_at.is_(None),
                    PhoneCall.started_at >= since)
            .order_by(PhoneCall.started_at.desc()).all())
    reached = {}
    for call in (PhoneCall.query
                 .filter(PhoneCall.answered_at.isnot(None),
                         PhoneCall.started_at >= since).all()):
        if call.number:
            reached[call.number] = max(reached.get(call.number, call.started_at),
                                       call.started_at)
    out, seen = [], set()
    for call in rows:
        key = call.number or call.raw_number
        if key in seen:
            continue
        if call.number in reached and reached[call.number] > call.started_at:
            continue
        seen.add(key)
        out.append(call)
    return out


def mark_returned(call, user=None, note=None, now=None):
    """Somebody called them back (or decided not to — the note says)."""
    if call is None or call.status != "missed":
        raise CallEventError("not_missed")
    call.returned_by = getattr(user, "id", None)
    call.returned_at = now or datetime.utcnow()
    call.returned_note = _text(note, 255)
    return call
