"""Shared helpers for patient document uploads (lab/imaging reports, etc.).

Files are stored under ``static/uploads/patient_docs`` and served via the
static route. Used by both the visit screen and the patient documents tab.
"""
import os
import uuid

from flask import current_app
from werkzeug.utils import secure_filename

# Document kinds shown to users (lab tests / imaging / report / other).
ATTACHMENT_KINDS = ["lab", "imaging", "report", "other"]
ALLOWED_DOC_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "gif"}


def docs_dir():
    return os.path.join(current_app.static_folder, "uploads", "patient_docs")


def allowed_doc(filename):
    return (
        "." in (filename or "")
        and filename.rsplit(".", 1)[-1].lower() in ALLOWED_DOC_EXTENSIONS
    )


def save_document(file_storage):
    """Persist an uploaded document and return its stored filename, or None."""
    if not file_storage or not file_storage.filename or not allowed_doc(file_storage.filename):
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    stored = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(docs_dir(), exist_ok=True)
    file_storage.save(os.path.join(docs_dir(), secure_filename(stored)))
    return stored


def remove_document(filename):
    if not filename:
        return
    path = os.path.join(docs_dir(), filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
