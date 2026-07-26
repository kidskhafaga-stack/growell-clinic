"""The X-ray the parent sends, landing in the child's file.

The doctor asks for a chest film; the parent photographs the report at the lab
and sends it on WhatsApp. The webhook used to notice a file had arrived, write
``[media]`` in the conversation and throw the file away.

The rules held here are the ones about not trusting what arrives: the size is
capped before anything is written, the file type is decided from the declared
MIME rather than from a name the sender chose, and nothing is filed on a
patient's record unless we actually know whose number it was.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 200


@pytest.fixture()
def clinic(tmp_path):
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    static = tmp_path / "static"
    (static / "uploads").mkdir(parents=True)
    app.static_folder = str(static)
    with app.app_context():
        db.create_all()
        from app.models import Family, Parent, Patient

        fam = Family(family_name="عائلة")
        db.session.add(fam)
        db.session.flush()
        db.session.add(Parent(family_id=fam.id, full_name="الأم",
                              relation="mother", phone="01000000001"))
        child = Patient(patient_number="M1", full_name="طفل", gender="male",
                        date_of_birth=date(2019, 1, 1), family_id=fam.id)
        db.session.add(child)
        db.session.commit()
        yield {"app": app, "db": db, "child": child, "static": static}


def _fake_download(data=PNG, mime="image/png"):
    return lambda media, cfg=None: (data, mime)


def test_the_file_lands_on_the_patients_record(clinic, monkeypatch):
    from app.models import MessageLog, PatientAttachment
    from app.utils import wa_media
    from app.utils.inbound import handle_inbound

    with clinic["app"].app_context():
        monkeypatch.setattr(wa_media, "download", _fake_download())
        res = handle_inbound({"from_phone": "01000000001",
                              "text": "أشعة الصدر",
                              "media": {"id": "abc", "mime": "image/png",
                                        "kind": "image"}}, "test")
        clinic["db"].session.commit()
        assert res["attachment"] is True

        att = PatientAttachment.query.one()
        assert att.patient_id == clinic["child"].id
        assert att.kind == "imaging"           # from what the parent wrote
        assert att.label == "أشعة الصدر"
        # …and the file is really on disk, under the patient-documents folder.
        path = clinic["static"] / "uploads" / "patient_docs" / att.filename
        assert path.exists() and path.read_bytes() == PNG
        # The conversation can show it.
        log = MessageLog.query.filter_by(direction="in").one()
        assert log.image_url.endswith(att.filename)


def test_a_lab_result_is_filed_under_lab(clinic, monkeypatch):
    from app.models import PatientAttachment
    from app.utils import wa_media
    from app.utils.inbound import handle_inbound

    with clinic["app"].app_context():
        monkeypatch.setattr(wa_media, "download",
                            _fake_download(b"%PDF-1.4 report", "application/pdf"))
        handle_inbound({"from_phone": "01000000001", "text": "تحليل الدم",
                        "media": {"id": "x", "mime": "application/pdf",
                                  "kind": "document"}}, "test")
        clinic["db"].session.commit()
        att = PatientAttachment.query.one()
        assert att.kind == "lab"
        assert att.filename.endswith(".pdf")


def test_an_unknown_number_keeps_the_file_but_guesses_no_owner(clinic, monkeypatch):
    """A file from a number we can't place is kept with the message. Filing it
    on a record we guessed at would put someone else's X-ray in a child's
    file."""
    from app.models import MessageLog, PatientAttachment
    from app.utils import wa_media
    from app.utils.inbound import handle_inbound

    with clinic["app"].app_context():
        monkeypatch.setattr(wa_media, "download", _fake_download())
        res = handle_inbound({"from_phone": "01099999999", "text": "",
                              "media": {"id": "y", "mime": "image/png",
                                        "kind": "image"}}, "test")
        clinic["db"].session.commit()
        assert res["attachment"] is False
        assert PatientAttachment.query.count() == 0
        # But the file itself is still there, attached to the conversation.
        log = MessageLog.query.filter_by(direction="in").one()
        assert log.image_url


def test_a_type_nobody_asked_for_is_not_written_to_disk(clinic):
    """The documents folder is served over the web. What goes into it is
    decided by us from the declared type, never by the sender."""
    from app.utils.wa_media import store

    with clinic["app"].app_context():
        assert store(b"MZ...", "application/x-msdownload") is None
        assert store(b"<script>", "text/html") is None
        assert store(b"", "image/png") is None
        assert store(PNG, "image/png").endswith(".png")


def test_an_oversized_file_is_refused_rather_than_written(clinic):
    from app.utils import wa_media

    class Response:
        headers = {"Content-Type": "image/png"}
        status_code = 200

        def iter_content(self, size):
            # Two chunks that together exceed the cap.
            yield b"a" * wa_media.MAX_BYTES
            yield b"b" * 1024

    with clinic["app"].app_context():
        assert wa_media._read_capped(Response()) is None


def test_a_failed_download_costs_the_file_never_the_message(clinic, monkeypatch):
    from app.models import MessageLog, PatientAttachment
    from app.utils import wa_media
    from app.utils.inbound import handle_inbound

    with clinic["app"].app_context():
        monkeypatch.setattr(wa_media, "download",
                            lambda media, cfg=None: (None, "download_404"))
        res = handle_inbound({"from_phone": "01000000001", "text": "الأشعة",
                              "media": {"id": "z", "mime": "image/png",
                                        "kind": "image"}}, "test")
        clinic["db"].session.commit()
        assert res["attachment"] is False
        assert PatientAttachment.query.count() == 0
        log = MessageLog.query.filter_by(direction="in").one()
        assert log.body == "الأشعة"           # the message survived
        assert log.error == "download_404"    # and says why the file didn't


def test_the_kind_is_guessed_from_what_the_parent_wrote(clinic):
    from app.utils.wa_media import kind_for

    assert kind_for("أشعة على الصدر") == "imaging"
    assert kind_for("X-Ray chest") == "imaging"
    assert kind_for("تحليل صورة دم") == "lab"
    assert kind_for("", "application/pdf") == "report"
    assert kind_for("") == "imaging"
