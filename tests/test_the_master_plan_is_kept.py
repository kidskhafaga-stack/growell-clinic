"""الخطة المجمّعة بتفضل صح (MASTER_PLAN.md).

*«تحط تنبيه لما نخلص اجزاء من البلان المجمع تعلم انه خلص بعد الرفع والتجربة»* —
التنبيه هو الاختبار ده، لأنه بيوقّع الفحص الآلي:

* خطة فيها «PR الجاي» = بند اتعمل واترفع ولسه ما اتحطش رقم طلبه؛
* «✅ اتعمل» في الخطة المجمّعة من غير رقم PR؛
* ملف خطة (`*_PLAN.md`) مش مذكور في الخطة المجمّعة — خطة جديدة اتنست.
"""
import glob
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _plans():
    return sorted(glob.glob(os.path.join(ROOT, "*.md")) + glob.glob(os.path.join(ROOT, "docs", "*.md")))


def test_no_finished_part_is_left_without_its_pr_number():
    waiting = []
    for path in _plans():
        for n, line in enumerate(_read(path).splitlines(), 1):
            # «PR الجاي» between quotes is the rule being explained, not a part.
            if re.search(r"(?<!«)PR الجاي", line):
                waiting.append(f"{os.path.relpath(path, ROOT)}:{n}")
    assert not waiting, ("بند اتعمل ولسه مكتوب عليه «PR الجاي» — حط رقم الطلب: "
                         + ", ".join(waiting))


def test_every_done_line_in_the_master_plan_names_its_pr():
    bad = [line.strip() for line in _read(os.path.join(ROOT, "MASTER_PLAN.md")).splitlines()
           if re.search(r"(?<!«)✅ اتعمل", line) and not re.search(r"PR #\d+|قبل الخطة", line)
           and not line.lstrip().startswith(("1.", "2.", "3.", ">", "*"))]
    assert not bad, "«✅ اتعمل» من غير رقم PR: " + " | ".join(bad)


def test_every_plan_file_is_in_the_master_plan():
    master = _read(os.path.join(ROOT, "MASTER_PLAN.md"))
    names = [os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*_PLAN.md"))
             if os.path.basename(p) != "MASTER_PLAN.md"]
    names += ["ROADMAP.md", "IMPROVEMENTS_BACKLOG.md"]
    missing = [n for n in names if f"`{n}`" not in master]
    assert not missing, "خطط مش مذكورة في MASTER_PLAN.md: " + ", ".join(missing)


def test_the_rule_is_written_for_the_next_session():
    claude = _read(os.path.join(ROOT, "CLAUDE.md"))
    assert "MASTER_PLAN.md" in claude and "PR الجاي" in claude
