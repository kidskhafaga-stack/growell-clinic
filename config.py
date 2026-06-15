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
    SESSION_COOKIE_SECURE = True


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
