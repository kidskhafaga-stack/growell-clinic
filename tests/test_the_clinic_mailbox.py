"""صندوق إيميل العيادة قناة — IMAP للاستقبال وSMTP للرد.

* **رسالة واحدة مرة واحدة** بالـ ``Message-ID``، والجديد بيتعرف بالـ UID؛
* **مفيش دوّامة ردود**: الرد التلقائي والقوائم والإعلانات وإيميلنا إحنا
  ما بيتسجّلوش، والرد خارج المواعيد عليه ``Auto-Submitted``؛
* **الشخص بالعنوان**، والكلام الجديد بس من غير السلسلة المقتبسة، والـ PDF
  المرفق بيتحفظ؛
* **الرد في نفس السلسلة**: ``Re:`` و``In-Reply-To``.
"""
import os
import sys
from email.message import EmailMessage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _mail(frm="Mona Ahmed <mona@example.com>", subject="موعد د. أحمد",
          body="عايزة أحجز لابني السبت\n\nOn Mon, Clinic wrote:\n> old text",
          msg_id="<m1@example.com>", **headers):
    msg = EmailMessage()
    msg["From"] = frm
    msg["To"] = "clinic@clinic.example"
    msg["Subject"] = subject
    msg["Message-ID"] = msg_id
    for k, v in headers.items():
        msg[k.replace("_", "-")] = v
    msg.set_content(body)
    return msg


@pytest.fixture()
def mailbox(clinic, monkeypatch):
    from app.models import Setting
    from app.utils import channels, mail_channel

    with clinic["app"].app_context():
        for k, v in (("mail_imap_host", "imap.clinic.example"), ("mail_smtp_host", "smtp.clinic.example"),
                     ("mail_user", "clinic@clinic.example"), ("mail_password", "pw"),
                     ("mail_address", "clinic@clinic.example"), ("mail_smtp_port", "587")):
            Setting.set(k, v)
        channels.set_enabled(["whatsapp", "email"])
        clinic["db"].session.commit()
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host

        def starttls(self, context=None):
            assert context is not None, "TLS is verified"

        def login(self, user, password):
            pass

        def send_message(self, msg):
            sent.append(msg)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(mail_channel.smtplib, "SMTP", FakeSMTP)
    clinic["mail_sent"] = sent
    return clinic


def test_a_family_mail_is_filed_once_and_loops_are_not(mailbox):
    from app.models import Contact, MessageLog
    from app.utils import mail_channel

    with mailbox["app"].app_context():
        mail = _mail()
        pdf = b"%PDF-1.4 report"
        mail.add_attachment(pdf, maintype="application", subtype="pdf", filename="cbc.pdf")
        log = mail_channel.file_message(bytes(mail))
        mailbox["db"].session.commit()
        assert log is not None and log.channel == "email"
        assert "عايزة أحجز" in log.body and "old text" not in log.body
        assert log.image_url and log.image_url.endswith(".pdf")
        assert Contact.query.one().identity("email").value == "mona@example.com"
        assert mail_channel.file_message(bytes(_mail())) is None, "same Message-ID"
        for bad in (_mail(msg_id="<a1@x>", Auto_Submitted="auto-replied"),
                    _mail(msg_id="<a2@x>", Precedence="bulk"),
                    _mail(msg_id="<a3@x>", List_Id="<news.example.com>"),
                    _mail(msg_id="<a4@x>", frm="clinic@clinic.example")):
            assert mail_channel.file_message(bytes(bad)) is None
        assert MessageLog.query.count() == 1


def test_new_mail_is_found_by_uid_from_now_on(mailbox, monkeypatch):
    from app.models import MessageLog, Setting
    from app.utils import mail_channel

    store = {b"1": _mail(msg_id="<old@x>"), b"2": _mail(msg_id="<old2@x>")}

    class FakeBox:
        def select(self, name, readonly=False):
            assert readonly, "the clinic's own client still sees mail unread"
            return "OK", [b"2"]

        def response(self, code):
            return code, [b"77"]

        def uid(self, cmd, *args):
            if cmd == "SEARCH":
                return "OK", [b" ".join(sorted(store))]
            uid = args[0]
            return "OK", [(b"1 (BODY[] {n}", bytes(store[uid])), b")"]

        def logout(self):
            pass
    monkeypatch.setattr(mail_channel, "_connect_imap", lambda cfg: FakeBox())
    with mailbox["app"].app_context():
        assert mail_channel.poll() == (0, None), "a new box starts from now"
        assert Setting.get("mail_last_uid") == "2"
        store[b"3"] = _mail(msg_id="<new@x>", body="الكشف بكام؟")
        assert mail_channel.poll() == (1, None)
        assert mail_channel.poll() == (0, None)
        assert MessageLog.query.one().provider_msg_id == "mail:<new@x>"


def test_a_reply_stays_in_the_thread_and_the_away_note_says_it_is_automatic(mailbox, monkeypatch):
    from app.models import MessageLog, Setting
    from app.utils import mail_channel, service_desk

    with mailbox["app"].app_context():
        log = mail_channel.file_message(bytes(_mail()))
        mailbox["db"].session.commit()
        key = f"c{log.contact_id}"
    desk = mailbox["sign_in"]("desk")
    assert 'data-thread-channel="email"' in desk.get(f"/messages/inbox/{key}").get_data(as_text=True)
    desk.post(f"/messages/inbox/{key}/send", data={"body": "تمام، السبت ٥ م مناسب؟"})
    reply = mailbox["mail_sent"][-1]
    assert reply["To"] == "mona@example.com" and reply["Subject"] == "Re: موعد د. أحمد"
    assert reply["In-Reply-To"] == "<m1@example.com>" and reply["Auto-Submitted"] is None
    monkeypatch.setattr(service_desk, "is_open", lambda *a, **k: False)
    with mailbox["app"].app_context():
        Setting.set("wa_away_enabled", "1")
        mailbox["db"].session.commit()
        mail_channel.file_message(bytes(_mail(frm="Sara <sara@example.com>", msg_id="<s1@x>")))
        mailbox["db"].session.commit()
        assert MessageLog.query.filter_by(template_type="away", channel="email").count() == 1
    assert mailbox["mail_sent"][-1]["Auto-Submitted"] == "auto-replied"
