"""Application configuration for GROWELL CLINIC.

Configuration is environment-driven so the same codebase can move from the
default SQLite database to PostgreSQL without code changes.
"""
import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration shared by all environments."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "growell-clinic-dev-secret-change-me")

    # SQLite by default; set DATABASE_URL to a PostgreSQL URI to upgrade.
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

    # Clinic defaults (overridable via the settings table later).
    CLINIC_NAME = os.environ.get("CLINIC_NAME", "GROWELL CLINIC")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    REMEMBER_COOKIE_HTTPONLY = True
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


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
