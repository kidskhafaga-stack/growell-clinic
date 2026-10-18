"""الروشتة والشهادة بنفس الخط: Cairo اللي جوه البرنامج.

الخط متشال في ``static/vendor/cairo`` (رخصة OFL) عشان يطبع هو هو على أي جهاز
في العيادة، فيه إنترنت أو مفيش، ومتثبّت عليه الخط أو لأ. والورقة بتطلب الخط
مرة واحدة في ``_paper.html`` اللي شاشة الدكتور وصفحة الأهل والطباعة
التجريبية كلهم بيستعملوه.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_cairo_ships_with_the_program_and_its_licence():
    folder = os.path.join(ROOT, "app", "static", "vendor", "cairo")
    css = open(os.path.join(folder, "cairo.css"), encoding="utf-8").read()
    for name in ("cairo-arabic-wght-normal.woff2", "cairo-latin-wght-normal.woff2"):
        assert os.path.getsize(os.path.join(folder, name)) > 1000
        assert name in css
    assert "Open Font License" in open(os.path.join(folder, "OFL.txt"), encoding="utf-8").read()
    assert "http" not in css.replace("http://scripts.sil.org", "")   # nothing fetched from outside


def test_the_prescription_asks_for_it(clinic):
    from app.models import RxPrintTemplate

    with clinic["app"].app_context():
        tpl = RxPrintTemplate(name="تجربة")
        clinic["db"].session.add(tpl)
        clinic["db"].session.commit()
        tid = tpl.id
    page = clinic["sign_in"]("boss").get(f"/prescriptions/templates/{tid}/test-print").get_data(as_text=True)
    assert "vendor/cairo/cairo.css" in page and '"Cairo Local"' in page
    # The one-page fit measures again once the font has arrived.
    assert "document.fonts.ready" in open(
        os.path.join(ROOT, "app/templates/prescriptions/_paper.html"), encoding="utf-8").read()
