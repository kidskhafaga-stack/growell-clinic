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

# The key that signs everyone's login. The program writes a random one
# here by itself the first time — don't share it, and don't change it
# unless you mean to log the whole clinic out.
# مفتاح توقيع تسجيل الدخول — البرنامج بيكتبه لوحده أول مرة. ما تشاركهوش،
# وما تغيّرهوش إلا لو قاصد تخرّج كل الناس من البرنامج.

# HTTPS=1  only when the clinic really is behind a certificate.
# حطّها بـ 1 بس لو العيادة فعلاً ورا شهادة HTTPS.

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


# The value the code falls back to when nothing is configured. It is printed
# in the open source, so it is a password everybody already knows.
DEFAULT_SECRET = "growell-clinic-dev-secret-change-me"


def ensure_secret(root=None, environ=None):
    """Give this clinic its own session key, once.

    The key signs the session cookie: whoever knows it can mint a cookie for
    any user and walk in as the administrator. Falling back to a constant
    written in the source means every clinic that never set one shares a
    password the whole internet can read.

    So it is generated here — on first run, and on upgrade for the installs
    that never had one — and written into ``clinic.env`` next to the port.
    Written once and kept: regenerating it on every start would sign everyone
    out every time the clinic opened.

    Returns the key when it wrote one, otherwise None.
    """
    import secrets

    environ = environ if environ is not None else os.environ
    if (environ.get("SECRET_KEY") or "").strip() not in ("", DEFAULT_SECRET):
        return None                      # somebody set a real one; leave it
    target = path(root or default_root())
    existing = {}
    if os.path.isfile(target):
        try:
            with open(target, encoding="utf-8-sig") as fh:
                existing = parse(fh.read())
        except OSError:
            return None
        if (existing.get("SECRET_KEY") or "").strip():
            environ["SECRET_KEY"] = existing["SECRET_KEY"]
            return None

    key = secrets.token_urlsafe(48)
    line = f"\nSECRET_KEY={key}\n"
    try:
        # Append rather than rewrite: the file belongs to the clinic and may
        # carry their own edits and comments.
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        return None
    environ["SECRET_KEY"] = key
    return key
