"""Which port the clinic opens on, and where that decision lives.

Port 5000 collides more often than anyone expects — macOS AirPlay holds it,
and so do a few Windows tools. Changing it used to mean editing a batch file,
which on a clinic PC means nobody changes it. It now lives in one plain text
file next to the program, and the rules about who wins are the point of these
tests.
"""
import os
import socket
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.settings_file import (TEMPLATE, ensure_file, load_env,  # noqa: E402
                               parse, path)


# ------------------------------------------------------------ the file --
def test_the_settings_file_reads_like_something_a_person_can_edit():
    values = parse(TEMPLATE)
    assert values["PORT"] == "5000"
    assert values["DEFAULT_LANGUAGE"] == "ar"
    # Anything a clinic shouldn't casually change stays commented out.
    assert "SECRET_KEY" not in values
    assert "DATABASE_URL" not in values


def test_comments_and_junk_lines_are_ignored():
    values = parse("# a note\n\nPORT = 8080 \nnot-a-setting\nQ=\"quoted\"\n")
    assert values == {"PORT": "8080", "Q": "quoted"}


def test_the_file_is_created_once_and_then_belongs_to_the_clinic(tmp_path):
    assert ensure_file(str(tmp_path)) is True
    written = (tmp_path / "clinic.env")
    written.write_text("PORT=9999\n", encoding="utf-8")
    # A second run must not overwrite what they edited.
    assert ensure_file(str(tmp_path)) is False
    assert written.read_text(encoding="utf-8") == "PORT=9999\n"


def test_a_real_environment_variable_always_wins(tmp_path):
    """Someone who exported PORT meant it. A file that silently overrode them
    would be a trap."""
    (tmp_path / "clinic.env").write_text("PORT=8080\nLANG_X=ar\n",
                                         encoding="utf-8")
    env = {"PORT": "7777"}
    applied = load_env(str(tmp_path), env)
    assert env["PORT"] == "7777"          # untouched
    assert env["LANG_X"] == "ar"          # and the rest still loads
    assert applied == {"LANG_X": "ar"}


def test_a_missing_file_is_not_an_error(tmp_path):
    assert load_env(str(tmp_path), {}) == {}


def test_the_file_sits_next_to_the_program():
    assert os.path.basename(path()) == "clinic.env"
    assert os.path.isfile(os.path.join(os.path.dirname(path()), "run.py"))


# ------------------------------------------------------------- the port --
def test_the_command_line_beats_the_file():
    from run import chosen_port

    assert chosen_port(["8080"], {"PORT": "5050"}) == 8080


def test_the_file_is_used_when_nothing_was_typed():
    from run import chosen_port

    assert chosen_port([], {"PORT": "5050"}) == 5050


def test_it_falls_back_to_5000():
    from run import chosen_port

    assert chosen_port([], {}) == 5000


def test_nonsense_never_stops_the_clinic_starting():
    """A typo in a settings file must not be the reason a clinic can't open."""
    from run import chosen_port

    assert chosen_port(["abc"], {}) == 5000
    assert chosen_port([], {"PORT": ""}) == 5000
    assert chosen_port([], {"PORT": "99999"}) == 5000      # out of range
    assert chosen_port([""], {"PORT": "5050"}) == 5050     # empty argument


def test_a_busy_port_is_noticed_before_serving_not_after():
    """So the message can be "that port is taken", not a stack trace."""
    from run import port_is_free

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("0.0.0.0", 0))
        held.listen(1)
        taken = held.getsockname()[1]
        assert port_is_free(taken) is False
    assert port_is_free(taken) is True      # released again
