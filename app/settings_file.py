"""``clinic.env`` — the handful of settings that live outside the database.

The port, the database location and the secret key have to be known *before*
the app is built, so they can't be clinic settings like everything else. They
were environment variables, which on a clinic's Windows PC means "edit a batch
file", which means nobody changes them.

So they live in one plain text file next to the program, with comments, and
this reads it. Real environment variables still win: a clinic that has set
PORT deliberately shouldn't have a file quietly override it.
"""
import os

FILENAME = "clinic.env"

TEMPLATE = """\
# ============================================================
#  GROWELL CLINIC — local settings
#  Edit with Notepad, then restart the program.
#  إعدادات محلية — عدّلها بالمفكرة وبعدين اقفل البرنامج وافتحه تاني.
# ============================================================

# The port the program opens on. Change it if 5000 is taken by
# something else on this computer (5050 and 8080 are common choices).
# المنفذ اللي البرنامج بيفتح عليه — غيّره لو ٥٠٠٠ محجوز لبرنامج تاني.
PORT=5000

# Interface language on first run: ar or en
# لغة الواجهة أول مرة
DEFAULT_LANGUAGE=ar

# Leave the rest alone unless you know what you are changing.
# سيب اللي تحت ده زي ما هو إلا لو إنت عارف بتغيّر إيه.

# A long random string. Changing it logs everybody out.
# SECRET_KEY=

# Where the database lives. The default is instance/growell.db
# DATABASE_URL=sqlite:///instance/growell.db
"""


def default_root():
    """The project folder — where the file sits next to start.bat."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def path(root=None):
    """Where the file is, or would be."""
    return os.path.join(root or default_root(), FILENAME)


def parse(text):
    """``KEY=value`` lines → dict. Comments and blank lines are ignored."""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            out[key] = value.strip().strip('"').strip("'")
    return out


def load_env(root=None, environ=None):
    """Read ``clinic.env`` into the environment. Returns what it set.

    A real environment variable always wins — someone who exported PORT meant
    it, and a file that silently overrode them would be a trap.
    """
    environ = environ if environ is not None else os.environ
    target = path(root or default_root())
    if not os.path.isfile(target):
        return {}
    try:
        with open(target, encoding="utf-8-sig") as fh:
            values = parse(fh.read())
    except OSError:
        return {}
    applied = {}
    for key, value in values.items():
        if key in environ or value == "":
            continue
        environ[key] = value
        applied[key] = value
    return applied


def ensure_file(root=None):
    """Create ``clinic.env`` on first run so there is something to edit.

    Never overwrites: the file is the clinic's once it exists.
    """
    target = path(root or default_root())
    if os.path.isfile(target):
        return False
    try:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(TEMPLATE)
        return True
    except OSError:
        return False
