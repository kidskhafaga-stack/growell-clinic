"""Meta-approved templates: the only thing that goes out after 24 hours.

WhatsApp lets a business write freely for 24 hours after the customer's last
message. After that a free-text message is refused — the only thing Meta will
deliver is a *template you registered with them in advance and they approved*.

Until now the program knew about the rule and warned about it, which left the
receptionist reading "the window is closed" with nothing to do about it. An old
conversation was a dead end: the result is ready, the mother wrote two days
ago, and there is no way to tell her from inside the program.

So the clinic registers the names of its approved templates here, one per
line, and the thread offers them when the window has shut.

    appointment_reminder | ar | تذكير: معاد {{1}} يوم {{2}}

* the **name** is Meta's own template name — lowercase, digits, underscores;
* the **language** is the code the template was approved under (``ar``);
* the **body** is a copy of the approved text, kept for two reasons: so the
  person sending can see what the family will read, and so the program knows
  how many parameters to ask for.

The body is a *copy*, and it can drift from what Meta holds. That is a real
limitation and the honest one: Meta is the authority on the text, we are only
showing our note of it. What we never do is invent a parameter count — it is
read from the ``{{1}}`` markers in the copy, so a mismatch shows up as a
rejected send rather than as a message the family receives half-empty.

Templates are a Cloud API concept. WaPilot drives an ordinary WhatsApp session
and has no template endpoint, so this path is offered for ``cloud_api`` only.
"""
import re

from app.models import Setting

SETTING_KEY = "wa_approved_templates"
DEFAULT_LANG = "ar"

# Meta's own rule for template names. A name with a space or a capital in it
# will be rejected at send time with a message nobody can act on, so it is
# rejected here instead, where the clinic can see the line it typed.
_NAME = re.compile(r"^[a-z0-9_]+$")
_PARAM = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def parse(raw):
    """``name | lang | body`` lines → template dicts. Bad lines are dropped.

    Dropped rather than half-accepted: the settings screen shows what parsed,
    so a mistyped line visibly disappears instead of quietly becoming a
    template that fails on the one night somebody needs it.
    """
    out, seen = [], set()
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|", 2)]
        name = parts[0].lower()
        if not _NAME.match(name) or name in seen:
            continue
        seen.add(name)
        lang = (parts[1] if len(parts) > 1 and parts[1] else DEFAULT_LANG)
        body = parts[2] if len(parts) > 2 else ""
        out.append({"name": name, "lang": lang, "body": body,
                    "params": param_count(body)})
    return out


def param_count(body):
    """How many parameters the approved body takes.

    The highest marker wins, not the count of markers: a body using ``{{1}}``
    twice and ``{{3}}`` once still needs three parameters, and asking for two
    would produce a send Meta refuses.
    """
    numbers = [int(n) for n in _PARAM.findall(body or "")]
    return max(numbers) if numbers else 0


def approved():
    """The clinic's registered templates, as configured."""
    return parse(Setting.get(SETTING_KEY, ""))


def find(name):
    return next((tpl for tpl in approved() if tpl["name"] == name), None)


def fill(body, values):
    """Put the parameters into a copy of the approved body, for the log.

    What gets logged is what the family reads, so the thread shows the same
    sentence they saw. The wire format sends name + parameters; this is the
    human record of it.
    """
    def swap(match):
        idx = int(match.group(1)) - 1
        return values[idx] if 0 <= idx < len(values) else match.group(0)
    return _PARAM.sub(swap, body or "")


def available(provider=None):
    """Whether the approved-template path applies at all right now.

    Click-to-send has no window and needs no template; WaPilot has no template
    endpoint. Offering the button under either would be offering a button that
    cannot work.
    """
    from app.utils import whatsapp as wa

    provider = provider or wa.resolve_provider(wa.get_config())
    return provider == "cloud_api"
