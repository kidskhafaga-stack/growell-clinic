"""Custom Flask CLI commands for database setup and seeding.

    flask --app run init-db         create all tables
    flask --app run seed            create demo users (one per role)
    flask --app run create-admin    interactively create an admin user
"""
import click

from app.extensions import db
from app.models import Setting, User


# Demo accounts created by ``seed`` — handy during Phase 1 development.
DEMO_USERS = [
    ("admin", "admin123", "مدير النظام", "System Administrator", "admin"),
    ("doctor", "doctor123", "د. سارة أحمد", "Dr. Sarah Ahmed", "doctor"),
    ("reception", "reception123", "موظف الاستقبال", "Reception Desk", "reception"),
    ("accountant", "accountant123", "المحاسب", "Accountant", "accountant"),
    ("pharmacy", "pharmacy123", "الصيدلية", "Pharmacy", "pharmacy"),
]

DEFAULT_SETTINGS = {
    "clinic_name": "GROWELL CLINIC",
    "clinic_name_ar": "جروويل كلينك",
    "default_language": "ar",
    "currency": "EGP",
    "default_growth_reference": "WHO",
}


def register_commands(app):
    @app.cli.command("init-db")
    def init_db():
        """Create all database tables."""
        db.create_all()
        _ensure_default_settings()
        db.session.commit()
        click.secho("Database initialised.", fg="green")

    @app.cli.command("seed")
    def seed():
        """Create demo users (one per role) and default settings."""
        db.create_all()
        _ensure_default_settings()

        created = 0
        for username, password, name_ar, name_en, role in DEMO_USERS:
            if User.query.filter_by(username=username).first():
                continue
            user = User(
                username=username,
                full_name=name_ar,
                full_name_en=name_en,
                role=role,
                is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            created += 1

        db.session.commit()
        click.secho(f"Seed complete. {created} user(s) created.", fg="green")
        if created:
            click.secho("Demo credentials (change in production!):", fg="yellow")
            for username, password, *_ in DEMO_USERS:
                click.echo(f"  {username} / {password}")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--name", prompt="Full name")
    @click.password_option()
    def create_admin(username, name, password):
        """Create a new administrator account."""
        db.create_all()
        if User.query.filter_by(username=username).first():
            click.secho("Username already exists.", fg="red")
            return
        user = User(username=username, full_name=name, role="admin", is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.secho(f"Administrator '{username}' created.", fg="green")


def _ensure_default_settings():
    for key, value in DEFAULT_SETTINGS.items():
        if Setting.query.filter_by(key=key).first() is None:
            db.session.add(Setting(key=key, value=value))
