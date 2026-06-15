"""Development entry point for GROWELL CLINIC.

Usage:
    python run.py
    flask --app run run        (CLI commands available under `flask`)
"""
import os

from app import create_app

app = create_app(os.environ.get("FLASK_CONFIG", "default"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
