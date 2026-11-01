"""PDF files made by the program itself — asked for as «ضيف مكتبة PDF».

Until now every paper the program sends out left as an HTML page that the
person printed to PDF from the browser, or that the payer opened in theirs.
This draws the page straight into a PDF instead, so a file sent by mail or
WhatsApp is the file the other side expects.

* **fpdf2** draws the page; **uharfbuzz** joins the Arabic letters and lays
  them right to left. Both install from ready-made wheels on 32- and 64-bit
  Windows — nothing else for a clinic to install (no GTK, no browser).
* **The font is Cairo**, the same face the screens use, shipped as TTF in
  ``static/vendor/cairo`` (SIL Open Font Licence, ``OFL.txt`` next to it;
  taken from the npm package ``@expo-google-fonts/cairo`` 0.4.2).
* **Numbers inside Arabic**: a date such as ``2026-11-01`` in an Arabic line
  came out as ``01-11-2026``. Each run of digits is wrapped in a
  left-to-right isolate (LRI … PDI), which is what a browser does for it.

If the library is missing (a computer that has not run ``update.bat`` since
it was added), :func:`available` is False and every caller keeps its old
way — the HTML page — rather than failing.
"""
import os
import re

#: Where the TTF files are.
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "static", "vendor", "cairo")
#: A point in millimetres, and the line height the printed page uses.
PT = 25.4 / 72
LINE = 1.15

_NUMBER = re.compile(r"\d[\d\-/.:,٫]*\d")
_ALIGN = {"right": "R", "center": "C", "left": "L"}


def available():
    """True when fpdf2 can be imported here."""
    try:
        import fpdf  # noqa: F401
    except ImportError:
        return False
    return True


def _shaping():
    try:
        import uharfbuzz  # noqa: F401
    except ImportError:
        return False
    return True


def isolate_numbers(text):
    """Each run of digits kept left to right inside a right-to-left line."""
    return _NUMBER.sub(lambda m: "⁦" + m.group(0) + "⁩", text or "")


def new(width_mm, height_mm):
    """A blank page of this size, Cairo loaded, no margins."""
    from fpdf import FPDF

    pdf = FPDF(unit="mm", format=(float(width_mm), float(height_mm)))
    pdf.set_auto_page_break(False)
    pdf.set_margin(0)
    pdf.add_font("cairo", "", os.path.join(FONT_DIR, "Cairo-Regular.ttf"))
    pdf.add_font("cairo", "B", os.path.join(FONT_DIR, "Cairo-Bold.ttf"))
    if _shaping():
        pdf.set_text_shaping(True)
    pdf.add_page()
    return pdf


def background(pdf, path):
    """A picture stretched over the whole page — a scanned form. Returns
    False when it cannot be drawn (a type Pillow does not read)."""
    if not path or not os.path.isfile(path):
        return False
    try:
        pdf.image(path, x=0, y=0, w=pdf.w, h=pdf.h)
    except Exception:  # noqa: BLE001 — a bad scan must not stop the page
        return False
    return True


def text_box(pdf, x, y, w, size, text, align="right", bold=True):
    """Text in a box ``w`` wide at ``(x, y)``, in millimetres, wrapping on
    its own and on new lines — the printed page's ``.f`` box."""
    text = isolate_numbers(str(text or "").strip())
    if not text:
        return
    pdf.set_font("cairo", "B" if bold else "", float(size))
    pdf.set_xy(float(x), float(y))
    pdf.multi_cell(float(w), float(size) * PT * LINE, text,
                   align=_ALIGN.get(align, "R"), new_x="LMARGIN", new_y="NEXT")


def output(pdf):
    """The finished file as bytes."""
    return bytes(pdf.output())
