"""دمج نسختين من نفس التحليل — «اعمل أداة الدمج».

العيادات اللي خدت القايمة قبل ما تتنضّف عندها صورة الدم وCRP وغيرهم مرتين،
والطلبات متقسّمة بينهم. المتمسوك هنا:

* البرنامج **بيقترح** النسختين من الاسم — ومش بيدمج لوحده؛
* اللي يفضل بياخد كل حاجة: الطلبات، وسطور الروشتة، والمكوّنات، والمستهلكات،
  وأسعار المعمل المرجعي، والإجراءات — واللي عنده أصلاً بيكسب؛
* الخانات الفاضية بتتملي من التاني، والكود أولها؛ واسم التاني بيفضل يتلاقى؛
* ممنوع تدمج تحليل في نفسه أو في أشعة؛ وللمدير بس.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def twins(clinic):
    """«صورة دم كاملة» (ordered for months, no code) and «صورة دم كاملة
    (CBC)» (the panels' coded copy) — each with something of its own."""
    from app.models import (Investigation, LabAnalyte, LabConsumable,
                            LabTestAnalyte, PrescriptionInvestigation,
                            ReferralLab, ReferralLabPrice, Setting, StoreItem,
                            VisitInvestigation)
    from app.models.lab_quality import LabProcedure

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        old = Investigation(name_ar="صورة دم كاملة", name_en="CBC", kind="lab", is_active=True)
        new = Investigation(name_ar="صورة دم كاملة (CBC)", name_en="Complete Blood Count",
                            code="cbc", kind="lab", is_active=True, sample_type="دم", tube="EDTA")
        scan = Investigation(name_ar="أشعة صدر", kind="imaging", is_active=True)
        hb, wbc = LabAnalyte(name="Hemoglobin"), LabAnalyte(name="WBC")
        strip, ref = StoreItem(name="أنبوبة EDTA"), ReferralLab(name="المعمل المرجعي")
        db.session.add_all([old, new, scan, hb, wbc, strip, ref])
        db.session.flush()
        visit_id, child = clinic["ids"]["visit"], clinic["ids"]["child"]
        db.session.add_all([
            VisitInvestigation(visit_id=visit_id, patient_id=child, investigation_id=old.id,
                               kind="lab", name=old.name_ar),
            VisitInvestigation(visit_id=visit_id, patient_id=child, investigation_id=old.id,
                               kind="lab", name=old.name_ar),
            VisitInvestigation(visit_id=visit_id, patient_id=child, investigation_id=new.id,
                               kind="lab", name=new.name_ar),
            LabTestAnalyte(investigation_id=old.id, analyte_id=hb.id),
            LabTestAnalyte(investigation_id=new.id, analyte_id=hb.id),      # both have Hb
            LabTestAnalyte(investigation_id=new.id, analyte_id=wbc.id),     # only the new
            LabConsumable(investigation_id=new.id, store_item_id=strip.id, quantity=1),
            ReferralLabPrice(investigation_id=old.id, lab_id=ref.id, price=100),
            ReferralLabPrice(investigation_id=new.id, lab_id=ref.id, price=150),
            LabProcedure(investigation_id=new.id, version="1", location="الرف ٣",
                         effective_on=date(2026, 1, 1)),
        ])
        db.session.flush()
        from app.models import Prescription
        rx = Prescription(patient_id=child, visit_id=visit_id)
        db.session.add(rx)
        db.session.flush()
        db.session.add(PrescriptionInvestigation(prescription_id=rx.id, investigation_id=new.id,
                                                 name=new.name_ar))
        db.session.commit()
        clinic["ids"].update(old=old.id, new=new.id, scan=scan.id, hb=hb.id, wbc=wbc.id)
    return clinic


def test_the_pair_is_suggested_and_the_one_ordered_more_stays_by_default(twins):
    from app.models import Investigation
    from app.utils import investigation_merge as im

    with twins["app"].app_context():
        pairs = im.twins("lab")
        ids = {frozenset((a.id, b.id)) for a, b in pairs}
        assert frozenset((twins["ids"]["old"], twins["ids"]["new"])) in ids
        old = twins["db"].session.get(Investigation, twins["ids"]["old"])
        new = twins["db"].session.get(Investigation, twins["ids"]["new"])
        # 2 orders against 1 order + 1 prescription line: even — the coded
        # copy, the one the panels find, is offered to stay.
        assert im.suggested_keep(old, new).id == new.id
        from app.models import VisitInvestigation
        twins["db"].session.add(VisitInvestigation(
            visit_id=twins["ids"]["visit"], patient_id=twins["ids"]["child"],
            investigation_id=old.id, kind="lab", name=old.name_ar))
        twins["db"].session.commit()
        assert im.suggested_keep(old, new).id == old.id, "the copy ordered more"
        assert Investigation.query.count() == 3, "suggested, never merged on its own"


def test_everything_moves_to_the_one_that_stays(twins):
    from app.models import (ActivityLog, Investigation, LabConsumable,
                            LabTestAnalyte, PrescriptionInvestigation,
                            ReferralLabPrice, VisitInvestigation)
    from app.models.lab_quality import LabProcedure
    from app.utils import investigation_merge as im

    with twins["app"].app_context():
        db = twins["db"]
        keep = db.session.get(Investigation, twins["ids"]["old"])
        drop = db.session.get(Investigation, twins["ids"]["new"])
        moved = im.merge(keep, drop)
        db.session.commit()
        kid = twins["ids"]["old"]
        assert db.session.get(Investigation, twins["ids"]["new"]) is None
        assert moved["orders"] == 1
        assert VisitInvestigation.query.filter_by(investigation_id=kid).count() == 3
        assert PrescriptionInvestigation.query.filter_by(investigation_id=kid).count() == 1
        assert sorted(a.analyte_id for a in LabTestAnalyte.query.filter_by(investigation_id=kid)) \
            == sorted([twins["ids"]["hb"], twins["ids"]["wbc"]])
        assert LabConsumable.query.filter_by(investigation_id=kid).count() == 1
        price = ReferralLabPrice.query.filter_by(investigation_id=kid).one()
        assert price.price == 100, "the kept test's own price wins"
        assert LabProcedure.query.filter_by(investigation_id=kid).count() == 1
        keep = db.session.get(Investigation, kid)
        assert keep.code == "cbc" and keep.sample_type == "دم" and keep.tube == "EDTA"
        assert keep.name_en == "CBC", "what the kept test had stays"
        assert "صورة دم كاملة (CBC)" in keep.aliases and "Complete Blood Count" in keep.aliases
        assert Investigation.query.filter_by(code="cbc").one().id == kid, "the panels find it"
        assert ActivityLog.query.filter_by(action="lab.merge_tests").count() == 1


def test_a_test_is_not_merged_into_itself_or_into_a_scan(twins):
    from app.models import Investigation
    from app.utils import investigation_merge as im

    with twins["app"].app_context():
        db = twins["db"]
        old = db.session.get(Investigation, twins["ids"]["old"])
        scan = db.session.get(Investigation, twins["ids"]["scan"])
        for keep, drop, why in ((old, old, "same"), (old, scan, "kinds")):
            with pytest.raises(im.MergeError) as err:
                im.merge(keep, drop)
            assert str(err.value) == why


def test_the_list_shows_the_pair_and_only_an_administrator_merges(twins):
    from app.models import Investigation

    form = {"a_id": twins["ids"]["old"], "b_id": twins["ids"]["new"], "keep_id": twins["ids"]["new"]}
    assert twins["sign_in"]("doc").post("/labs/tests/merge", data=form).status_code in (302, 403)
    with twins["app"].app_context():
        assert Investigation.query.count() == 3
    boss = twins["sign_in"]()
    page = boss.get("/labs/tests").get_data(as_text=True)
    assert "data-twins" in page and f'data-twin="{twins["ids"]["old"]}-{twins["ids"]["new"]}"' in page
    boss.post("/labs/tests/merge", data=form)
    with twins["app"].app_context():
        assert twins["db"].session.get(Investigation, twins["ids"]["old"]) is None
        kept = twins["db"].session.get(Investigation, twins["ids"]["new"])
        assert "صورة دم كاملة" in (kept.aliases or "")
    assert "data-twins" not in boss.get("/labs/tests").get_data(as_text=True)
