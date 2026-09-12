"""Application configuration for PediaPro.

Configuration is environment-driven so the same codebase can move from the
default SQLite database to PostgreSQL without code changes.
"""
import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration shared by all environments."""

    # **Not renamed, deliberately.** This exact string is a *sentinel*:
    # `settings_file.ensure_secret` recognises it as "still the shared default
    # everybody can read" and replaces it with a generated key. Change the
    # wording and an install still carrying the old literal reads as having a
    # real key of its own, and never gets one — a security regression dressed
    # up as a rename. It has to keep matching `settings_file.DEFAULT_SECRET`.
    SECRET_KEY = os.environ.get("SECRET_KEY", "growell-clinic-dev-secret-change-me")

    # SQLite by default; set DATABASE_URL to a PostgreSQL URI to upgrade.
    #
    # The filename is not renamed either, for the plainest reason there is:
    # every clinic already running has its data in a file called this, and a
    # program looking for a different name would come up empty and offer to
    # set up a new clinic.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(basedir, "instance", "growell.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Internationalisation (bilingual from day one).
    LANGUAGES = ["ar", "en"]
    DEFAULT_LANGUAGE = os.environ.get("DEFAULT_LANGUAGE", "ar")

    # Session / security.
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12 hours
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # "Remember me" issues a *second* cookie that signs you in without the
    # session — it is the longer-lived of the two and the more valuable to
    # steal, so it gets the same protection, and it gets it in the base class.
    # These used to live in ProductionConfig alone, which meant a clinic
    # running on the default config had a remember-cookie readable by any
    # script on the page.
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    # A ceiling on how fast one caller can hit the login form, the webhooks
    # and the survey. See app/utils/rate_limit.py.
    RATELIMIT_ENABLED = True

    # Clinic defaults (overridable via the settings table later).
    #
    # **The program's name, not a customer's.** This shipped as «GROWELL
    # CLINIC» — one particular clinic — and it is the value that actually
    # wins: `app/__init__.py` reads `CLINIC_NAME` with a "PediaPro" fallback,
    # but this line is always set, so the fallback never ran and every fresh
    # copy came up wearing somebody else's sign.
    CLINIC_NAME = os.environ.get("CLINIC_NAME", "PediaPro")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    # Cookies marked "secure" are only ever sent over HTTPS — which is right
    # behind a certificate and a lock-out everywhere else. Most clinics run
    # this on the practice LAN over plain HTTP, where marking the session
    # cookie secure means the browser never sends it back and nobody can log
    # in at all. So it follows the truth: set HTTPS=1 in clinic.env when the
    # clinic really is behind TLS, and the cookies tighten with it.
    SESSION_COOKIE_SECURE = os.environ.get("HTTPS", "0") == "1"
    REMEMBER_COOKIE_SECURE = os.environ.get("HTTPS", "0") == "1"


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    # A suite that signs in forty times is not an attack. The tests that are
    # about the limiter switch it back on for themselves.
    RATELIMIT_ENABLED = False


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
