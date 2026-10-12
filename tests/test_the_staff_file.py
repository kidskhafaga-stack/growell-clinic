"""ملف الموظف — GAHAR WFM.04–09، WFM.13، WFM.14.

* المؤهلات بالتحقق من المصدر الأصلي والصلاحية؛
* الوظيفة بالوصف الوظيفي، ومضيه؛
* التوجيه بمستوياته التلاتة، والتعليم المستمر؛
* التقييمات (سنوي، OPPE، أقران) برأي الموظف والإجراء، والسنوي مستحق بعد سنة؛
* للأدمن بس، والباب من صفحة المستخدمين.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401


def test_a_file_filled_in_order_and_its_gaps(clinic):
    from app.models import StaffCredential, User
    from app.utils import staff_file as sf

    boss = clinic["sign_in"]("boss")
    with clinic["app"].app_context():
        doc = User.query.filter_by(username="doc").first()
        uid = doc.id
        assert set(sf.gaps(doc)) >= {"no_credentials", "no_jd", "orientation", "evaluation_due"}
    base = f"/users/{uid}/file/"
    boss.post(base + "credential", data={"kind": "licence", "title": "ترخيص مزاولة طب", "number": "123",
                                         "expires_on": (date.today() + timedelta(days=200)).isoformat()})
    with clinic["app"].app_context():
        cid = StaffCredential.query.one().id
    boss.post(base + "verify", data={"credential_id": cid})
    with clinic["app"].app_context():
        assert StaffCredential.query.one().verified_at is None, "verification names its source"
    boss.post(base + "verify", data={"credential_id": cid, "source": "نقابة الأطباء"})
    boss.post(base + "job", data={"title": "أخصائي أطفال", "started_on": "2024-01-01", "job_description": "رعاية المرضى"})
    with clinic["app"].app_context():
        from app.models import StaffJob
        jid = StaffJob.query.one().id
    boss.post(base + "jd_signed", data={"job_id": jid})
    for level in ("general", "department", "job"):
        boss.post(base + "orientation", data={"level": level, "completed_on": "2024-01-05"})
    boss.post(base + "evaluation", data={"kind": "annual", "on": (date.today() - timedelta(days=30)).isoformat(),
                                         "evaluator": "رئيس القسم", "result": "ممتاز", "feedback": "موافق"})
    with clinic["app"].app_context():
        assert sf.gaps(User.query.get(uid)) == []
    page = boss.get("/users/files").get_data(as_text=True)
    assert f'data-staff="{uid}"' in page
    assert "data-to-staff-files" in boss.get("/users/").get_data(as_text=True)
    assert clinic["sign_in"]("doc").get(f"/users/{uid}/file").status_code in (302, 403, 404)
