"""A Python past its security support is named on the About page (SECURITY.md,
«نتأكد انها بتتحدث لوحدها علشان الامن»): the libraries are kept current, but
nothing patches the interpreter under them once its line has ended."""
from datetime import date

from app.utils import project


def test_the_dates_decide():
    assert project.python_past_security((3, 10), date(2026, 11, 1))
    assert not project.python_past_security((3, 10), date(2026, 10, 31))
    assert not project.python_past_security((3, 12), date(2026, 11, 1))
    # Older than the table: past. Newer than the table: not.
    assert project.python_past_security((3, 8), date(2020, 1, 1))
    assert not project.python_past_security((3, 99), date(2040, 1, 1))


def test_the_about_page_says_so(clinic, monkeypatch):
    boss = clinic["sign_in"]("boss")
    monkeypatch.setattr(project, "python_past_security", lambda *a, **k: True)
    page = boss.get("/about").get_data(as_text=True)
    assert "data-python-old" in page
    # The way out is the ordinary update: it finds the newer Python itself.
    assert "update.bat" in page

    monkeypatch.setattr(project, "python_past_security", lambda *a, **k: False)
    page = boss.get("/about").get_data(as_text=True)
    assert "data-python-old" not in page
