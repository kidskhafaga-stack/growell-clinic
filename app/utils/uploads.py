"""Shared helpers for patient document uploads (lab/imaging reports, etc.).

Files are stored under ``static/uploads/patient_docs`` and served via the
static route. Used by both the visit screen and the patient documents tab.

**The type comes from the bytes, not from the name.** These files land in a
folder the web server hands out, on the same origin as the whole program — so
whoever names the file must not get to decide what the browser treats it as.
The same rule the WhatsApp downloader already follows (``wa_media``), applied
to the uploads staff make from inside the screens.
"""
import os
import uuid

from flask import current_app
from werkzeug.utils import secure_filename

# Document kinds shown to users (lab tests / imaging / report / other).
ATTACHMENT_KINDS = ["lab", "imaging", "report", "other"]
ALLOWED_DOC_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "gif"}

# A phone photo is 2–6 MB and a scanned report can be larger; past this, one
# upload is filling the clinic's disk rather than recording a result.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# What each allowed type actually starts with. Nothing else is written: a file
# whose bytes we don't recognise is refused rather than stored under whatever
# extension its name claimed.
#
# The absent entries matter as much as the present ones. There is no SVG and
# no HTML here — both can carry script, and a script served from the clinic's
# own origin runs with the session of whoever opened it.
_MAGIC = (
    (b"%PDF-", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def docs_dir():
    return os.path.join(current_app.static_folder, "uploads", "patient_docs")


def allowed_doc(filename):
    return (
        "." in (filename or "")
        and filename.rsplit(".", 1)[-1].lower() in ALLOWED_DOC_EXTENSIONS
    )


def sniff_ext(head):
    """The extension these bytes really deserve, or None.

    None means "not one of the types this clinic stores", and the caller must
    refuse — never fall back to the name, which is the whole point.
    """
    if not head:
        return None
    for signature, ext in _MAGIC:
        if head.startswith(signature):
            return ext
    # WebP is a RIFF container; the format lives four bytes further in.
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _read_head(file_storage, size=32):
    """Peek at the start of an upload without consuming it."""
    head = file_storage.stream.read(size)
    file_storage.stream.seek(0)
    return head


def _too_big(file_storage):
    stream = file_storage.stream
    try:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
    except (OSError, ValueError):  # a stream that can't seek — let it through
        return False
    return size > MAX_UPLOAD_BYTES


def save_document(file_storage):
    """Persist an uploaded document and return its stored filename, or None.

    Returns None for anything refused, which every caller already treats as
    "no file" — so a rejected upload leaves the record without an attachment
    rather than with a broken one.
    """
    if not file_storage or not file_storage.filename:
        return None
    if _too_big(file_storage):
        return None
    # The name is checked first only to reject the obvious cheaply; the byte
    # signature is what actually decides the extension it is stored under.
    if not allowed_doc(file_storage.filename):
        return None
    ext = sniff_ext(_read_head(file_storage))
    if ext not in ALLOWED_DOC_EXTENSIONS:
        return None
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


# ---------------------------------------------------- drug media -----------
# Package photos and leaflets/SPC files for the drug reference. Kept apart from
# patient documents: these are catalogue content, shared by every patient, and
# they must survive a patient file being cleaned out.
ALLOWED_DRUG_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}


def drug_media_dir():
    return os.path.join(current_app.static_folder, "uploads", "drug_media")


def allowed_drug_file(filename):
    return ("." in (filename or "")
            and filename.rsplit(".", 1)[-1].lower() in ALLOWED_DRUG_EXTENSIONS)


def save_drug_media(file_storage):
    """Store a package photo / leaflet and return its filename, or None.

    Same rule as patient documents: this folder is served over the web too,
    and a leaflet is no safer a place to smuggle a script than an X-ray.
    """
    if not file_storage or not file_storage.filename \
            or not allowed_drug_file(file_storage.filename):
        return None
    if _too_big(file_storage):
        return None
    ext = sniff_ext(_read_head(file_storage))
    if ext not in ALLOWED_DRUG_EXTENSIONS:
        return None
    stored = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(drug_media_dir(), exist_ok=True)
    file_storage.save(os.path.join(drug_media_dir(), secure_filename(stored)))
    return stored


def remove_drug_media(filename):
    if not filename:
        return
    path = os.path.join(drug_media_dir(), filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
