"""Flask extension singletons.

Kept in a separate module to avoid circular imports between the application
factory and the models / blueprints.
"""
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
# The login message itself is translated in the auth blueprint.
login_manager.login_message = None
