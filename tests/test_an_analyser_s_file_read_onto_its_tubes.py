"""An analyser's result file, read onto its tubes (LAB_GLAB360_PLAN.md م-٢ أ).

* a line is written only when the tube finds one order, the analyser's code
  is linked here, and the analyte is on that order's test — then through the
  bench's own save (range, critical, delta), unreleased;
* anything else is held for a person with its reason — never placed on a
  child by a near match — and written once the link is made;
* a result already written is not overwritten without a person's press, and
  a released one never is;
* two shapes: a row per test, or a row per tube with a column per test code.
"""
import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_result_line_by_line import _fresh_cache, _order, bench  # noqa: E402,F401


def _tube(bench, test, code):
    from app.models import VisitInvestigation

    oid = _order(bench, test, collected_minutes_ago=20)
    with bench["app"].app_context():
        bench["db"].session.get(VisitInvestigation, oid).sample_code = code
        bench["db"].session.commit()
    return oid


def _device(bench, **links):
    from app.models import LabDevice

    boss = bench["sign_in"]("boss")
    boss.post("/labs/devices", data={"name": "Sysmex", "model": "XN-350"})
    with bench["app"].app_context():
        did = LabDevice.query.one().id
    for code, key in links.items():
        boss.post(f"/labs/devices/{did}", data={"action": "link", "code": code,
                                                "analyte_id": bench[key]})
    return did


def _read(bench, did, text, name="results.csv"):
    return bench["sign_in"]("boss").post(
        f"/labs/devices/{did}/import",
        data={"file": (io.BytesIO(text.encode("utf-8")), name)},
        content_type="multipart/form-data", follow_redirects=True).get_data(as_text=True)


def _states(bench):
    from app.models import LabImportLine

    with bench["app"].app_context():
        return {(ln.sample_code, ln.code): ln.state for ln in LabImportLine.query.all()}


def _value(bench, oid, key):
    from app.models import VisitInvestigation

    with bench["app"].app_context():
        row = bench["db"].session.get(VisitInvestigation, oid)
        v = next((v for v in row.analyte_values if v.analyte_id == bench[key]), None)
        return (v.value, v.flag, row.verified_at) if v else None


def test_known_lines_are_written_and_the_rest_are_held_with_their_reason(bench):
    cbc = _tube(bench, "cbc", "S1")
    crp = _tube(bench, "crp", "S2")
    did = _device(bench, HGB="hb", CRP="crp_a")
    page = _read(bench, did, "Sample ID,Test,Result,Unit,Flag\n"
                             "S1,HGB,12.1,g/dL,\nS1,PLT,250,,\nS2,CRP,3,,\nS9,HGB,10,,\n"
                             "S2,HGB,12,,\n")
    assert "data-import-lines" in page
    assert _states(bench) == {("S1", "HGB"): "applied", ("S1", "PLT"): "no_code",
                              ("S2", "CRP"): "applied", ("S9", "HGB"): "no_sample",
                              ("S2", "HGB"): "not_on_test"}
    value, flag, released = _value(bench, cbc, "hb")
    assert value == 12.1 and flag == "normal" and released is None, "the bench's own save"
    assert _value(bench, crp, "crp_a")[0] == 3
    assert "data-device-held" in bench["sign_in"]("boss").get("/labs/devices").get_data(as_text=True)


def test_linking_a_held_code_writes_it(bench):
    from app.models import LabImportLine, LabImportRun

    cbc = _tube(bench, "cbc", "S1")
    did = _device(bench, HGB="hb")
    _read(bench, did, "Sample ID,Test,Result\nS1,HGB,12\nS1,PLT,250\n")
    with bench["app"].app_context():
        run = LabImportRun.query.one().id
        line = LabImportLine.query.filter_by(code="PLT").one().id
    bench["sign_in"]("boss").post(f"/labs/import/{run}", data={
        "action": "link", "line_id": line, "analyte_id": bench["plt"]})
    assert _states(bench)[("S1", "PLT")] == "applied"
    assert _value(bench, cbc, "plt")[0] == 250


def test_a_row_per_tube_with_a_column_per_test(bench):
    cbc = _tube(bench, "cbc", "S3")
    did = _device(bench, HGB="hb", PLT="plt")
    _read(bench, did, "SampleID;HGB;PLT\nS3;11.5;300\n")
    assert _value(bench, cbc, "hb")[0] == 11.5 and _value(bench, cbc, "plt")[0] == 300


def test_a_written_result_waits_for_a_person_and_a_released_one_is_never_touched(bench):
    from datetime import datetime

    from app.models import LabImportLine, LabImportRun, VisitInvestigation

    cbc = _tube(bench, "cbc", "S1")
    bench["sign_in"]("boss").post(f"/labs/order/{cbc}/result", data={f"a_{bench['hb']}": "11"})
    did = _device(bench, HGB="hb")
    _read(bench, did, "Sample ID,Test,Result\nS1,HGB,12.5\n")
    assert _states(bench)[("S1", "HGB")] == "already" and _value(bench, cbc, "hb")[0] == 11
    with bench["app"].app_context():
        run = LabImportRun.query.one().id
        line = LabImportLine.query.one().id
    bench["sign_in"]("boss").post(f"/labs/import/{run}", data={"action": "write", "line_id": line})
    assert _value(bench, cbc, "hb")[0] == 12.5, "a person pressed «write over it»"
    with bench["app"].app_context():
        bench["db"].session.get(VisitInvestigation, cbc).verified_at = datetime.utcnow()
        bench["db"].session.commit()
    _read(bench, did, "Sample ID,Test,Result\nS1,HGB,9\n")
    assert _value(bench, cbc, "hb")[0] == 12.5, "a released result is never overwritten"


def test_a_file_without_a_sample_column_is_refused_and_nothing_is_written(bench):
    from app.models import LabImportRun

    did = _device(bench, HGB="hb")
    page = _read(bench, did, "Foo,Bar\n1,2\n")
    assert "عمود رقم العينة" in page
    with bench["app"].app_context():
        assert LabImportRun.query.count() == 0


# ------------------------------------------------ the analyser's folder --

def test_a_file_dropped_in_the_folder_is_read_once_and_moved_aside(bench, tmp_path):
    from datetime import datetime, timedelta

    from app.models import LabDevice, LabImportRun
    from app.utils import lab_device_import as imp

    cbc = _tube(bench, "cbc", "S1")
    did = _device(bench, HGB="hb")
    bench["sign_in"]("boss").post(f"/labs/devices/{did}", data={
        "name": "Sysmex", "folder": str(tmp_path)})
    (tmp_path / "run1.csv").write_text("Sample ID,Test,Result\nS1,HGB,12.3\n", encoding="utf-8")
    (tmp_path / "junk.csv").write_text("Foo,Bar\n1,2\n", encoding="utf-8")
    (tmp_path / "picture.png").write_bytes(b"not a result file")
    later = datetime.utcnow() + timedelta(minutes=1)
    with bench["app"].app_context():
        assert bench["db"].session.get(LabDevice, did).folder == str(tmp_path)
        imp.scan_folders(now=later)
        imp.scan_folders(now=later)          # a second look reads nothing again
        assert LabImportRun.query.count() == 1
    assert _value(bench, cbc, "hb")[0] == 12.3
    assert (tmp_path / "done" / "run1.csv").exists() and not (tmp_path / "run1.csv").exists()
    assert (tmp_path / "failed" / "junk.csv").exists(), "a file that cannot be read is put aside"
    assert (tmp_path / "picture.png").exists(), "anything else is left alone"


def test_a_file_still_being_written_waits_for_the_next_look(bench, tmp_path):
    from app.models import LabImportRun
    from app.utils import lab_device_import as imp

    _tube(bench, "cbc", "S1")
    did = _device(bench, HGB="hb")
    bench["sign_in"]("boss").post(f"/labs/devices/{did}", data={"name": "Sysmex", "folder": str(tmp_path)})
    (tmp_path / "run1.csv").write_text("Sample ID,Test,Result\nS1,HGB,12.3\n", encoding="utf-8")
    with bench["app"].app_context():
        imp.scan_folders()
        assert LabImportRun.query.count() == 0
    assert (tmp_path / "run1.csv").exists()
