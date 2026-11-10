"""The clinic's files in one folder no update touches (UPGRADE_PLAN.md ٥ و٦).

The database, the backups, the licence, every uploaded file and clinic.env
live in ``data/`` beside the program. An older copy kept them inside the
program folder; they move once, by themselves, in one rename each — and not
while anything else has the database open.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app import data_home  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _db(path, rows=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS patients (id INTEGER)")
    conn.executemany("INSERT INTO patients VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    conn.close()


def _old_copy(root):
    """A clinic laid out the way every copy was before data/."""
    _db(os.path.join(root, "instance", "growell.db"), rows=3)
    os.makedirs(os.path.join(root, "instance", "backups"))
    with open(os.path.join(root, "instance", "backups", "backup-20261101-090000.zip"), "wb") as fh:
        fh.write(b"PK")
    with open(os.path.join(root, "instance", "licence.json"), "w") as fh:
        fh.write("{}")
    with open(os.path.join(root, "clinic.env"), "w") as fh:
        fh.write("PORT=8080\nSECRET_KEY=kept\n")
    docs = os.path.join(root, "app", "static", "uploads", "patient_docs")
    os.makedirs(docs)
    with open(os.path.join(docs, "cbc.png"), "wb") as fh:
        fh.write(b"scan")
    clinic = os.path.join(root, "app", "static", "uploads", "clinic")
    os.makedirs(clinic)
    open(os.path.join(clinic, ".gitkeep"), "w").close()


def _count(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    finally:
        conn.close()


def test_a_new_clinic_starts_in_data(tmp_path):
    root = str(tmp_path)
    assert data_home.data_dir(root) == os.path.join(root, "data")
    assert data_home.env_path(root) == os.path.join(root, "data", "clinic.env")
    assert data_home.settle(root) == {"moved": [], "waiting": []}
    assert not data_home.has_database(root)


def test_an_older_copy_moves_into_data_once_and_nothing_is_lost(tmp_path):
    root = str(tmp_path)
    _old_copy(root)
    assert data_home.data_dir(root) == os.path.join(root, "instance"), \
        "until it moves, the old folder is the clinic's — never an empty one"
    assert data_home.env_path(root) == os.path.join(root, "clinic.env")

    result = data_home.settle(root)

    data = os.path.join(root, "data")
    assert result["waiting"] == []
    assert set(result["moved"]) == {"instance", "clinic.env", "uploads/patient_docs"}
    assert data_home.data_dir(root) == data
    assert _count(os.path.join(data, "growell.db")) == 3
    assert os.path.isfile(os.path.join(data, "backups", "backup-20261101-090000.zip"))
    assert os.path.isfile(os.path.join(data, "licence.json"))
    assert open(os.path.join(data, "clinic.env")).read() == "PORT=8080\nSECRET_KEY=kept\n"
    with open(os.path.join(data, "uploads", "patient_docs", "cbc.png"), "rb") as fh:
        assert fh.read() == b"scan"
    assert not os.path.exists(os.path.join(root, "instance"))
    assert not os.path.exists(os.path.join(root, "clinic.env"))
    assert data_home.has_database(root)
    # The second start finds nothing to do.
    assert data_home.settle(root) == {"moved": [], "waiting": []}


def test_not_while_something_else_has_the_database_open(tmp_path):
    """The clinic running as a service while somebody opens the tools: the
    old folder keeps working, and the move waits for the next start."""
    root = str(tmp_path)
    _old_copy(root)
    live = sqlite3.connect(os.path.join(root, "instance", "growell.db"))
    live.execute("SELECT COUNT(*) FROM patients").fetchall()
    try:
        result = data_home.settle(root)
        assert ("instance", "in_use") in result["waiting"]
        assert data_home.data_dir(root) == os.path.join(root, "instance")
        assert os.path.isfile(os.path.join(root, "instance", "growell.db"))
        # What could move went into the clinic's folder as it stands now —
        # and travels with it later.
        assert os.path.isfile(os.path.join(root, "instance", "clinic.env"))
        assert os.path.isfile(os.path.join(root, "instance", "uploads", "patient_docs", "cbc.png"))
    finally:
        live.close()
    assert "instance" in data_home.settle(root)["moved"]
    assert os.path.isfile(os.path.join(root, "data", "uploads", "patient_docs", "cbc.png"))
    assert os.path.isfile(os.path.join(root, "data", "clinic.env"))


def test_a_database_url_pointed_into_the_old_folder_is_left_alone(tmp_path, monkeypatch):
    root = str(tmp_path)
    _old_copy(root)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///instance/growell.db")
    result = data_home.settle(root)
    assert ("instance", "database_url") in result["waiting"]
    assert os.path.isfile(os.path.join(root, "instance", "growell.db"))


def test_something_already_in_data_is_kept_beside_what_moves(tmp_path):
    root = str(tmp_path)
    _old_copy(root)
    stray = os.path.join(root, "data", "uploads", "users")
    os.makedirs(stray)
    with open(os.path.join(stray, "face.jpg"), "wb") as fh:
        fh.write(b"face")
    data_home.settle(root)
    assert _count(os.path.join(root, "data", "growell.db")) == 3
    assert os.path.isfile(os.path.join(stray, "face.jpg"))
    assert not [n for n in os.listdir(root) if n.startswith("data.before-move")]


def test_an_upload_is_read_where_it_really_is(tmp_path):
    root = str(tmp_path)
    old = os.path.join(root, "app", "static", "uploads", "patient_docs")
    os.makedirs(old)
    assert data_home.upload_dir("patient_docs", root) == os.path.join(
        root, "data", "uploads", "patient_docs"), "an empty old folder is not used"
    with open(os.path.join(old, "x.pdf"), "wb") as fh:
        fh.write(b"%PDF-")
    assert data_home.upload_dir("patient_docs", root) == old, "not moved yet"


def test_a_stored_address_finds_its_file_and_nothing_outside():
    assert data_home.stored_path("static/uploads/crm/a.png").endswith(
        os.path.join("uploads", "crm", "a.png"))
    assert data_home.stored_path("static/uploads/crm/../../run.py") is None
    assert data_home.stored_path("static/css/app.css") is None
    assert data_home.stored_path("static/uploads/.hidden/x") is None


@pytest.fixture
def served(tmp_path):
    from app import create_app

    app = create_app("testing")
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    folder = tmp_path / "uploads" / "patient_docs"
    folder.mkdir(parents=True)
    (folder / "scan.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
    return app


def test_the_same_address_is_answered_from_the_data_folder(served):
    client = served.test_client()
    reply = client.get("/static/uploads/patient_docs/scan.png")
    assert reply.status_code == 200 and reply.data.endswith(b"image")
    assert reply.headers.get("X-Content-Type-Options") == "nosniff"
    assert client.get("/static/uploads/patient_docs/missing.png").status_code == 404
    assert client.get("/static/uploads/../run.py").status_code == 404
    assert client.get("/static/uploads/patient_docs/../../../run.py").status_code == 404
    # The program's own static files are untouched.
    assert client.get("/static/js/app.js").status_code == 200


def test_the_database_and_instance_folder_are_the_data_folder(tmp_path, monkeypatch):
    from app import create_app

    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app("production")
    assert app.instance_path == data_home.data_dir()
    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///" + os.path.join(
        data_home.data_dir(), "growell.db")


def test_no_update_copies_over_data():
    with open(os.path.join(REPO, "update.bat"), encoding="utf-8") as fh:
        update = fh.read()
    assert "/XD data instance" in update
    with open(os.path.join(REPO, "start.bat"), encoding="utf-8") as fh:
        start = fh.read()
    assert "app.data_home settle" in start and "app.data_home has-db" in start
    assert 'instance\\growell.db' not in start
    with open(os.path.join(REPO, "start.sh"), encoding="utf-8") as fh:
        assert "app.data_home has-db" in fh.read()
    with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as fh:
        assert "/data/" in fh.read().split()
