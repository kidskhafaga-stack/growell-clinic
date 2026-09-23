"""تبويب جوّه تبويب — **وعشرة تبويبات اختفت من ملف الطفل**.

*"4 تابات دي مبقتش ظاهرة فى الملف مع انها كانت ظاهرة قبل كده: النمو،
التطعيمات، المستندات والمرفقات، الروشتة."*

**الأزرار كانت موجودة والمحتوى فاضي.** والسبب إن لوحة «القساطر
والأنابيب» اتفتحت ومااتقفلتش: لما لوحة «الاستشارة والرأي التاني»
اتضافت (#384)، اتحطّت **بين `</table>` بتاع القساطر و`</div>` التانيين
اللي بيقفلوها** — فالاتنين دول بقوا بيقفلوا لوحة الاستشارة، والقساطر
فضلت مفتوحة. وكل لوحة بعدها بقت **جوّاها**: التغذية، والاستشارة،
والرفض، والطوارئ، والنمو، والتطعيمات، والأسنان، والمستندات،
والروشتات، والحسابات. وكلهم بيبانوا بس لما يكون التبويب المفتوح هو
«القساطر».

**وعدّى على ٧٦٠٠ اختبار** لأن كل اختبار بيدوّر على كلمة في الصفحة —
والكلمة موجودة فعلاً، بس جوّه لوحة `x-show` بتاعتها `false`. فالحارس
هنا مش بيدوّر على كلمة: **بيبني شجرة الصفحة ويسأل مين جوّه مين**.

واتنين، زي كل حارس هنا:

* **على الصفحة المترسومة** — اللي المتصفح بيشوفه بالظبط.
* **وعلى القالب نفسه** — لأن لوحة ورا `{% if %}` مقفول في الاختبار ما
  بتترسمش، والكسر فيها ما بيبانش في الصفحة. القالب بيتقاس لوحة لوحة.
"""
import os
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
PANEL = "gc-tab-panel"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "source", "track", "wbr"}


class _Nesting(HTMLParser):
    """بيمشي على الصفحة ويسجّل أي لوحة اتفتحت وفيه لوحة تانية مفتوحة."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []          # (tag, panel name or None)
        self.nested = []

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        attrs = dict(attrs)
        name = None
        if PANEL in (attrs.get("class") or "").split():
            found = re.search(r"tab===?'(\w+)'", attrs.get("x-show") or "")
            name = found.group(1) if found else "?"
            outer = [n for _t, n in self.stack if n]
            if outer:
                self.nested.append((name, outer[-1]))
        self.stack.append((tag, name))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        # يقفل أقرب واحد بنفس الاسم، زي المتصفح.
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def _nested(html):
    parser = _Nesting()
    parser.feed(html)
    return parser.nested


def test_the_parser_catches_the_break_it_was_written_for():
    """**الحارس بيعضّ** — على نفس شكل الكسر اللي حصل بالظبط."""
    broken = (
        '<div class="gc-tab-panel" x-show="tab===\'lines\'">'
        '<div><table></table>'
        '<div class="gc-tab-panel" x-show="tab===\'growth\'"></div>'
        '</div></div>')
    assert _nested(broken) == [("growth", "lines")]

    fine = (
        '<div class="gc-tab-panel" x-show="tab===\'lines\'">'
        '<div><table></table></div></div>'
        '<div class="gc-tab-panel" x-show="tab===\'growth\'"></div>')
    assert _nested(fine) == []


def test_no_tab_on_the_child_s_file_sits_inside_another(clinic):
    """**الصفحة زي ما المتصفح بيشوفها.**"""
    client = clinic["sign_in"]("boss")
    page = client.get(f"/patients/{clinic['ids']['child']}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)

    # الأربعة اللي اتبلّغ عنهم لازم يكونوا مترسومين أصلاً، وإلا الاختبار
    # بينجح وهو ما شافهمش.
    drawn = set(re.findall(r'class="gc-tab-panel" x-show="tab===\'(\w+)\'',
                           html))
    for tab in ("growth", "vaccinations", "documents", "prescriptions"):
        assert tab in drawn, tab

    assert _nested(html) == []


def _panels_in_source(source):
    """`[(اسم اللوحة, الـdivs اللي فتحتها ومقفلتهاش)]` لكل لوحة في القالب."""
    source = re.sub(r"\{#.*?#\}", "", source, flags=re.S)
    # كل لوحة بتبدأ من الـ`<div` اللي فيه الكلاس — **من الناحيتين**: لو
    # الحد بين لوحتين اتحسب من الكلاس، الـ`<div` بتاع اللي بعدها بيتعدّ
    # على اللي قبلها.
    starts = [(source.rfind("<div", 0, m.start()), m.group(1))
              for m in re.finditer(
                  r'class="gc-tab-panel"[^>]*x-show="tab===\'(\w+)\'',
                  source)]
    out = []
    for (a, name), (b, _next) in zip(starts, starts[1:] + [(len(source), None)]):
        chunk = source[a:b]
        out.append((name, len(re.findall(r"<div\b", chunk))
                    - len(re.findall(r"</div>", chunk))))
    return out


def test_every_panel_in_every_template_closes_before_the_next_opens():
    """**والقالب نفسه — حتى اللوحات اللي ورا `{% if %}`.**

    لوحة الأسنان مثلاً بتترسم بس لو العيادة فيها أسنان، فالاختبار اللي
    فوق ما بيشوفهاش. هنا كل لوحة بتتقاس: اللي بتفتحه لازم تقفله قبل ما
    اللي بعدها يبدأ. **والأخيرة بس** مسموح لها تقفل أكتر — دي بتقفل
    الغلاف اللي حوالين التبويبات كلها.
    """
    bad = []
    for root, _dirs, files in os.walk(TEMPLATES):
        for name in files:
            if not name.endswith(".html"):
                continue
            path = os.path.join(root, name)
            source = open(path, encoding="utf-8").read()
            if PANEL not in source:
                continue
            panels = _panels_in_source(source)
            for i, (panel, left_open) in enumerate(panels):
                last = i == len(panels) - 1
                if left_open > 0 or (left_open < 0 and not last):
                    bad.append((os.path.relpath(path, TEMPLATES), panel,
                                left_open))
    assert not bad, (
        "لوحة تبويب مش مقفولة قبل اللي بعدها — وكل اللي بعدها بيختفي "
        "جوّاها: " + ", ".join(f"{f}:{p} ({n:+d})" for f, p, n in bad))


def test_the_source_check_catches_the_break_too():
    broken = (
        '<div class="gc-tab-panel" x-show="tab===\'lines\'">\n'
        '  <div><table></table>\n'
        '<div class="gc-tab-panel" x-show="tab===\'food\'">\n'
        '</div></div></div>\n')
    assert ("lines", 2) in _panels_in_source(broken)
