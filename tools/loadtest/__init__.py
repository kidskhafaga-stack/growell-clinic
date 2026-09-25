"""Load and stress testing — backlog item 15.

**Never pointed at a clinic's database.** ``fake_clinic`` builds a copy full of
made-up children in a file that must not exist yet, and ``drive`` refuses any
database that ``fake_clinic`` did not build. See ``tools/loadtest/README.md``.
"""
